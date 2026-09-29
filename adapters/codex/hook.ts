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
 * ★ 这里体现了外部宿主的四项额外义务（见 `docs/ADAPTER-CODEX-SCOPE.md`）：
 *
 *    1. `task` / `history`：codex 不给你，只给一个 `transcript_path`。
 *       这里**不读那个文件** —— 读它就要处理无界输入和裁剪策略，而这个入口
 *       故意保持薄。缺的部分如实留空，`compileHostFrame` 会把它当 unfilled
 *       并**拒绝**，而不是编一个空串。
 *    2. `files` / `readFiles`：codex 不维护。真要用得持久化到自己的状态文件。
 *    3. `canWrite`：`permission_mode` 是最近的信号；这里只认最保守的那一种。
 *    4. 审计与指纹：由 `core.ts` 与下面的记录负责。
 *
 * ⚠️ 所以这个入口**今天只在一件事上是完整的**：把 codex 的裁决点接到契约上。
 *    要让它有完整的帧，需要补 transcript 读取（并裁剪）—— 见 README 的 Roadmap。
 *    **未完成的部分会变成 deny，不会变成放行。**
 */
function stateOf(event: CodexHookEvent): HostState {
  const toolInput = event.tool_input
  return {
    // 任务与历史来自 transcript，这个入口暂不读它（见上）
    task: '',
    cwd: event.cwd ?? process.cwd(),
    tool: event.tool_name,
    input: typeof toolInput === 'string' ? toolInput : JSON.stringify(toolInput ?? ''),
    historyText: undefined,
    lastResult: undefined,
    files: [],
    readFiles: [],
    // 只在明确的只读模式下为 true —— 保守的一边
    canWrite: undefined,
    earlier: '',
  }
}

/** 按环境变量选后端。**没配就抛** —— 调用方会把它变成 deny */
function backendFromEnv(): Backend {
  if (process.env.JEVLOOP_STUB === '1') {
    // 确定性桩：risk=0 / done=0.95 ⇒ 放行。**只用于自检**，不要拿它当判定
    return async (req) => {
      const answers: Record<string, unknown> = {}
      for (const [id, q] of Object.entries(req.questions)) {
        const t = (q as { type: string }).type
        if (t === 'noul') {
          // `needs_auth` / `unsupported` 答「否」，其余答「是」⇒ 一切正常、放行
          const no = ['needs_auth', 'unsupported'].includes(id)
          answers[id] = { type: 'noul', noul: no ? 0.05 : 0.95 }
        }
        else if (t === 'score') answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.9 }
        else answers[id] = { type: 'choice', choice: '', probabilities: {}, confidence: 0.9 }
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

  const result = await runDecision(event, { md, state: stateOf(event), backend })

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
