#!/usr/bin/env node
/**
 * JevLoop · Codex hook 入口 —— codex 在生命周期事件上调用这个进程
 *
 * ══════════════════════════════════════════════════════════════
 *  stdin 一份事件 JSON → 判定 → stdout 一份裁决 JSON
 * ══════════════════════════════════════════════════════════════
 *
 * 这个文件只做**接线**：读 stdin、拼宿主状态、选后端、写记录、写 stdout。
 * 判定逻辑全在 `core.ts` 的纯函数里 —— 那部分能离线测，这部分不能，所以
 * 让它薄到不值得测。
 *
 * ── 用哪一份契约 ──────────────────────────────────────────────
 *
 *      $JEVLOOP_DECISION_MD   显式指定（默认：这个适配器所在仓库的 DECISION.md）
 *
 * ── 判定后端 ──────────────────────────────────────────────────
 *
 *      $JEVLOOP_JEV_URL + $TYPESAFE_API_KEY   走 HTTP 判定后端
 *      $JEVLOOP_STUB=1                        用确定性桩（**只用于自检**）
 *
 * ⚠️ 没配后端时**拒绝**（裁决为 deny），不是静默放行 —— 一个装不上后端的适配器
 *    如果默认放行，那它装上之后反而把闸门拆了。
 *
 * ── 记录 ──────────────────────────────────────────────────────
 *
 *      $JEVLOOP_RECORDS   记录写到这里（JSONL，一行一条 `decision-record/v1`）
 *
 *    写记录是**这个适配器的义务**：codex 不会写帧指纹，没有它们，
 *    `npm run replay` 会（正确地）报 `unverifiable`。
 *
 * @module JevLoop/adapters/codex/hook
 */

import { appendFileSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { checkCapabilities, runDecision, type Backend } from './core.ts'
import { readTranscript } from './transcript.ts'
import type { CodexHookEvent, HostState } from './types.ts'

const HERE = dirname(fileURLToPath(import.meta.url))
const REPO_ROOT = join(HERE, '..', '..')

/** 读 stdin 的全部内容。**codex 会给一份 JSON，也可能什么都不给** */
async function readStdin(): Promise<string> {
  const chunks: Buffer[] = []
  for await (const c of process.stdin) chunks.push(c as Buffer)
  return Buffer.concat(chunks).toString('utf8')
}

/**
 * 事件 → 宿主状态。
 *
 * ★ `task` 与 `history` 从 **transcript** 来（codex 只给一个路径，见
 *   `transcript.ts`），而它**读不到时留 `undefined`**，不留空串 ——
 *   空串会让帧看起来是完整的，而策略判定就基于一个空任务做出。
 *   留 `undefined` 的后果是上层**拒绝**，那才是安全的那一半。
 *
 * ★ `files` / `readFiles` 由适配器自己从 transcript 里认（**近似值**，
 *   已在那边的 notes 里声明）。这是「宿主不维护的状态」落到适配器头上的那一项。
 */
function stateOf(event: CodexHookEvent): { state: HostState; notes: string[] } {
  const toolInput = event.tool_input
  const notes: string[] = []
  let task: string | undefined
  let historyText: string | undefined
  let lastResult: string | undefined
  let files: string[] = []
  let readFiles: string[] = []
  let earlier = ''

  const path = event.transcript_path
  if (typeof path === 'string' && path) {
    const t = readTranscript(path)
    task = t.task
    historyText = t.historyText
    lastResult = t.lastResult
    files = t.files
    readFiles = t.readFiles
    notes.push(...t.notes)
  } else {
    // 没有 transcript 路径 ⇒ task 确定不了 ⇒ 上层拒绝
    notes.push('hook 事件里没有 transcript_path ⇒ task/history 无法确定（会拒绝，不是放行）')
  }

  return {
    state: {
      task: task as string,
      cwd: event.cwd ?? process.cwd(),
      tool: event.tool_name,
      input: typeof toolInput === 'string' ? toolInput : JSON.stringify(toolInput ?? ''),
      historyText,
      lastResult,
      files,
      readFiles,
      // 只在明确的只读模式下为 true —— 保守的一边（`permission_mode` 是最近的信号）
      canWrite: undefined,
      earlier,
    },
    notes,
  }
}

/** 按环境变量选后端。**没配就抛** —— 调用方会把它变成 deny */
function backendFromEnv(): Backend {
  if (process.env.JEVLOOP_STUB === '1') {
    /*
      ★ 自检用的确定性桩。它**不是判定**，而且它**故意保守**：

      第一版对一切都答「没问题」，于是它给 `shell(rm -rf /)` 判了 `risk=0 → auto`
      —— **放行**。那种桩如果被人留在环境变量里，就等于把闸门拆了还看起来在工作。

      所以这个桩只对「看起来只读」的工具放行，其余一律报高危 ⇒ 走到 `ask_human`
      ⇒ 本适配器 fail closed 成 deny。这样自检同时演示了放行与拒绝两条路，
      而且**它永远不能放行一个有破坏性的调用**。

      要真正的判定，配 `JEVLOOP_JEV_URL`。
    */
    const DESTRUCTIVE = new Set(['shell', 'bash', 'exec', 'delete_file', 'rm', 'apply_patch', 'write_file'])
    process.stderr.write('JevLoop codex adapter: ⚠ JEVLOOP_STUB=1 —— 这是自检桩，不是判定。破坏性工具一律报高危\n')
    return async (req) => {
      const tool = String((req.state as { tool?: unknown }).tool ?? '')
      const risky = DESTRUCTIVE.has(tool)
      const answers: Record<string, unknown> = {}
      for (const [id, q] of Object.entries(req.questions)) {
        const t = (q as { type: string }).type
        if (t === 'noul') {
          // `needs_auth` 跟着风险走：破坏性的答「需要授权」
          const no = id === 'needs_auth' ? !risky : ['unsupported'].includes(id)
          answers[id] = { type: 'noul', noul: no ? 0.05 : 0.95 }
        } else if (t === 'score') {
          answers[id] = { type: 'score', score: risky ? 3 : 0, legend: {}, probabilities: {}, confidence: 0.9 }
        } else {
          answers[id] = { type: 'choice', choice: '', probabilities: {}, confidence: 0.9 }
        }
      }
      return answers as never
    }
  }

  const baseUrl = process.env.JEVLOOP_JEV_URL
  if (!baseUrl) throw new Error('没有配判定后端：要么设 JEVLOOP_JEV_URL（+ TYPESAFE_API_KEY），要么设 JEVLOOP_STUB=1 自检')

  return async (req) => {
    const res = await fetch(new URL('/v1/systemone', baseUrl), {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        ...(process.env.TYPESAFE_API_KEY ? { authorization: `Bearer ${process.env.TYPESAFE_API_KEY}` } : {}),
      },
      body: JSON.stringify({ state: req.state, questions: req.questions }),
    })
    if (!res.ok) throw new Error(`判定后端 ${res.status}: ${(await res.text()).slice(0, 200)}`)
    const body = (await res.json()) as { answers?: Record<string, unknown> }
    if (!body.answers) throw new Error('判定后端没有返回 answers')
    return body.answers as never
  }
}

async function main(): Promise<void> {
  let event: CodexHookEvent = { hook_event_name: '' }
  try {
    const raw = await readStdin()
    event = raw.trim() ? (JSON.parse(raw) as CodexHookEvent) : { hook_event_name: '' }
  } catch (err) {
    // 读不懂事件 ⇒ 什么都不说（沉默 = 放行）。**这是有意的**：hook 读不懂输入时
    // 拒绝一切会让 codex 完全不可用，而这一层不是安全边界（见 SECURITY.md）
    process.stderr.write(`JevLoop codex adapter: 读不懂 hook 事件（${(err as Error).message}）\n`)
    process.stdout.write('{}\n')
    return
  }

  const mdPath = process.env.JEVLOOP_DECISION_MD ?? join(REPO_ROOT, 'DECISION.md')
  let md: string
  try {
    md = readFileSync(mdPath, 'utf8')
  } catch (err) {
    process.stderr.write(`JevLoop codex adapter: 读不到契约 ${mdPath}（${(err as Error).message}）\n`)
    process.stdout.write('{}\n')
    return
  }

  // 启动时对账：我声称支持的位置上不该有契约问题
  const caps = checkCapabilities(md)
  if (caps.fatal.length > 0) {
    process.stderr.write(`JevLoop codex adapter: 能力对账失败（${caps.fatal.length} 处）\n`)
    for (const f of caps.fatal) process.stderr.write(`  · ${f}\n`)
    process.stdout.write('{}\n') // 拒绝启动⇒沉默；下面的 runDecision 仍会因缺后端而 deny
    return
  }

  let backend: Backend
  try {
    backend = backendFromEnv()
  } catch (err) {
    // ★ 没后端时**拒绝**，不是放行。装不上后端却默认放行 = 装上之后把闸门拆了
    process.stderr.write(`JevLoop codex adapter: ${(err as Error).message}\n`)
    const deny =
      event.hook_event_name === 'PreToolUse'
        ? { hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'deny', permissionDecisionReason: (err as Error).message } }
        : { decision: 'block', reason: (err as Error).message }
    process.stdout.write(`${JSON.stringify(deny)}\n`)
    return
  }

  const { state, notes: stateNotes } = stateOf(event)
  const result = await runDecision(event, { md, state, backend })
  for (const n of stateNotes) process.stderr.write(`  · ${n}\n`)

  for (const n of result.outcome.notes) process.stderr.write(`  · ${n}\n`)

  const records = process.env.JEVLOOP_RECORDS
  if (records && result.outcome.record) {
    try {
      appendFileSync(records, `${JSON.stringify({ kind: 'event', run: 0, at: Date.now(), e: { type: 'decision', step: 1, id: result.outcome.record.node, ...result.outcome.record } })}\n`)
    } catch (err) {
      // 记录写不下就**说出来**：一份没有记录的运行不能被当成「审计过了」
      process.stderr.write(`JevLoop codex adapter: 记录写盘失败：${(err as Error).message}\n`)
    }
  }

  process.stdout.write(`${JSON.stringify(result.json)}\n`)
}

main().catch((err: unknown) => {
  process.stderr.write(`JevLoop codex adapter: ${(err as Error)?.message ?? String(err)}\n`)
  process.stdout.write('{}\n')
})
