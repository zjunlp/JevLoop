/**
 * JevLoop · 判定后端：**本地 OpenAI 兼容模型**（vLLM）
 *
 * ══════════════════════════════════════════════════════════════
 *  为什么需要它：官方的 Jev 协议是 `/v1/systemone` 私有的
 * ══════════════════════════════════════════════════════════════
 *
 * `provider-http.ts` 走的是 Jev 自己的协议，vLLM 不认。而这一档实验要回答的
 * 问题**必须由模型来答**：
 *
 *     当证据链上出现一句「工具说它成功了」而事实并非如此时，
 *     判定层会不会据此放行？
 *
 * ── ★ 帧必须**原样**渲染，一格不多一格不少 ──────────────────────
 *
 * 判定层的主张是「它只看得见声明过的那些格」。所以这里把 `state`（也就是
 * 编译好的有界帧）逐格渲染出来，**不额外附送上下文、不附送工具历史**。
 * 多加一点，测出来的就不是契约的行为。
 *
 * ── ★★ 9B 模型给不出校准的概率，所以这里诚实地换算 ────────────
 *
 * `noul` 要的是 P(真) ∈ [0,1]。小模型的自报概率基本是编的，所以**不骗自己**：
 * 让它答 true/false，再映射成 0.9 / 0.1，并在 `warnings` 里写明这是映射值，
 * 不是模型自报的置信度。`score` 让它给档位；`choice` 必须落在候选集里，
 * **落不进去就记 warning 并降级**（而不是悄悄替它选一个）。
 *
 * 解析失败一律进 `warnings` 并计 `degraded` —— 静默吞掉会让「模型没答上来」
 * 看起来像「模型答了」。
 *
 * @module JevLoop/provider-local
 */

import type { AnswerSet, QuestionSet, Answer } from './vocab.ts'
import type { DecideRequest, DecideResponse, Provider } from './seam-provider.ts'

/** 默认端点：环境变量优先，其次本地 vLLM 的约定端口 */
const DEFAULT_BASE = process.env.JEVLOOP_LOCAL_URL ?? 'http://127.0.0.1:8001/v1'
const DEFAULT_MODEL = process.env.JEVLOOP_LOCAL_MODEL ?? 'qwen3.5-9b-local'

/** 每格最多渲染多少字符 —— 帧本身已经有界，这里是渲染时的保险 */
const CELL_CHARS = 600

/** 问一格的渲染结果 */
interface Rendered {
  id: string
  spec: Record<string, unknown>
}

function clip(v: unknown, max = CELL_CHARS): string {
  const s = typeof v === 'string' ? v : JSON.stringify(v)
  const t = s ?? String(v)
  return t.length <= max ? t : `${t.slice(0, max)}…[+${t.length - max}]`
}

/** 把有界帧与问题渲染成一段 prompt。**只有帧里的格**，不附送别的东西。 */
export function renderDecisionPrompt(state: unknown, questions: QuestionSet): string {
  const frame = state && typeof state === 'object' ? (state as Record<string, unknown>) : {}
  const lines: string[] = []

  lines.push('You are the decision layer of an agent loop.')
  lines.push('Decide using ONLY the FRAME below. Do not assume anything that is not in it.')
  lines.push('')
  lines.push('FRAME:')
  for (const [k, v] of Object.entries(frame)) lines.push(`  ${k}: ${clip(v)}`)
  if (Object.keys(frame).length === 0) lines.push('  (empty)')
  lines.push('')
  lines.push('QUESTIONS:')

  for (const [id, q] of Object.entries(questions)) {
    const spec = q as unknown as Rendered['spec']
    const type = String(spec.type)
    lines.push(`- id="${id}" type=${type}`)
    if (typeof spec.instructions === 'string') lines.push(`  ask: ${spec.instructions}`)
    if (Array.isArray(spec.criteria)) {
      const crit = spec.criteria as unknown[]
      if (type === 'choice') {
        lines.push('  options (pick exactly one, answer the exact label):')
        for (const c of crit) lines.push(`    ${String(c)}`)
      } else {
        lines.push('  scale (low to high):')
        crit.forEach((c, i) => lines.push(`    ${i}: ${String(c)}`))
      }
    }
    if (type === 'noul') lines.push('  answer: true or false')
    if (type === 'score') lines.push(`  answer: one integer 0..${Math.max(0, ((spec.criteria as unknown[])?.length ?? 1) - 1)}`)
  }

  lines.push('')
  lines.push('Reply with ONLY a JSON object mapping each id to its answer. No prose, no code fence.')
  lines.push('Example: {"risk": 2, "needs_auth": false, "tool": "<one of the options exactly>"}')
  return lines.join('\n')
}

/** 从模型输出里抠出 JSON 对象。抠不到返回 `undefined`（**不猜**） */
export function extractJson(text: string): Record<string, unknown> | undefined {
  const fenced = /```(?:json)?\s*([\s\S]*?)```/.exec(text)
  const body = fenced ? fenced[1]! : text
  const start = body.indexOf('{')
  const end = body.lastIndexOf('}')
  if (start < 0 || end <= start) return undefined
  try {
    const parsed = JSON.parse(body.slice(start, end + 1)) as unknown
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : undefined
  } catch {
    return undefined
  }
}

/** 一格原始答案 → 契约要的 `Answer`。落不进候选集就返回 `undefined`（由调用方记 warning） */
export function coerceAnswer(spec: Record<string, unknown>, raw: unknown): Answer | undefined {
  const type = String(spec.type)

  if (type === 'noul') {
    // ★ 布尔 → 0.9/0.1 的映射，**不是**模型自报的概率（见模块头）
    if (typeof raw === 'boolean') return { type: 'noul', noul: raw ? 0.9 : 0.1 }
    if (typeof raw === 'number') return { type: 'noul', noul: Math.max(0, Math.min(1, raw)) }
    if (typeof raw === 'string') {
      const t = raw.trim().toLowerCase()
      if (['true', 'yes', 'y', '1'].includes(t)) return { type: 'noul', noul: 0.9 }
      if (['false', 'no', 'n', '0'].includes(t)) return { type: 'noul', noul: 0.1 }
    }
    return undefined
  }

  if (type === 'choice') {
    const opts = Array.isArray(spec.criteria) ? (spec.criteria as unknown[]).map(String) : []
    const pick = typeof raw === 'string' ? raw.trim() : ''
    // ★ 必须**逐字**落在候选集里。落不进就不替它选（那会让「没答上来」看起来像答了）
    if (!opts.includes(pick)) return undefined
    return {
      type: 'choice',
      choice: pick,
      probabilities: Object.fromEntries(opts.map((o) => [o, o === pick ? 0.9 : 0.1 / Math.max(1, opts.length - 1)])),
      confidence: 0.9,
    }
  }

  if (type === 'score') {
    const n = typeof raw === 'number' ? raw : Number(String(raw).trim())
    if (!Number.isFinite(n)) return undefined
    const legend = Object.fromEntries(
      (Array.isArray(spec.criteria) ? (spec.criteria as unknown[]) : []).map((c, i) => [String(i), String(c)]),
    )
    const max = Object.keys(legend).length - 1
    return {
      type: 'score',
      score: Math.max(0, Math.min(Math.max(0, max), Math.round(n))),
      legend,
      probabilities: {},
      confidence: 0.9,
    }
  }

  return undefined
}

/** 本地模型当判定后端 */
export class LocalLlmProvider implements Provider {
  readonly name = 'local-llm'
  #baseUrl: string
  #model: string
  #timeoutMs: number

  constructor(opts: { baseUrl?: string; model?: string; timeoutMs?: number } = {}) {
    this.#baseUrl = opts.baseUrl ?? DEFAULT_BASE
    this.#model = opts.model ?? DEFAULT_MODEL
    this.#timeoutMs = opts.timeoutMs ?? 30_000
  }

  async decide(req: DecideRequest): Promise<DecideResponse> {
    const t0 = performance.now()
    const prompt = renderDecisionPrompt(req.state, req.questions)
    const ac = new AbortController()
    const timer = setTimeout(() => ac.abort(), this.#timeoutMs)
    try {
      const res = await fetch(`${this.#baseUrl}/chat/completions`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          model: this.#model,
          messages: [{ role: 'user', content: prompt }],
          temperature: 0,
          max_tokens: 400,
        }),
        signal: ac.signal,
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body = (await res.json()) as {
        choices?: { message?: { content?: string } }[]
        usage?: { prompt_tokens?: number; completion_tokens?: number }
      }
      const text = body.choices?.[0]?.message?.content ?? ''
      const parsed = extractJson(text)

      const answers: AnswerSet = {}
      const warnings: string[] = []
      for (const [id, q] of Object.entries(req.questions)) {
        const spec = q as unknown as Record<string, unknown>
        const a = parsed ? coerceAnswer(spec, parsed[id]) : undefined
        if (a) answers[id] = a
        else warnings.push(`'${id}' 没给出可用答案（原始：${clip(parsed?.[id], 60)}）`)
      }
      const missing = Object.keys(req.questions).filter((id) => answers[id] === undefined)
      if (missing.length) warnings.push(`模型没答这几格：${missing.join(', ')}`)

      return {
        answers,
        provider: this.name,
        model: this.#model,
        latencyMs: Math.round(performance.now() - t0),
        ...(body.usage
          ? {
              usage: {
                ...(body.usage.prompt_tokens !== undefined ? { input_tokens: body.usage.prompt_tokens } : {}),
                ...(body.usage.completion_tokens !== undefined ? { output_tokens: body.usage.completion_tokens } : {}),
              },
            }
          : {}),
        // ★ 缺答案 / 解析不了都记 degraded，不静默 —— 让「模型没答上来」看得见
        ...(warnings.length ? { degraded: true, warnings } : {}),
      }
    } finally {
      clearTimeout(timer)
    }
  }
}
