/**
 * JevLoop · 从**最后一个可恢复的步骤**接着跑（TODO §10）
 *
 * ══════════════════════════════════════════════════════════════
 *  会话日志本来就有全部原料，缺的是「把它折回一个状态」
 * ══════════════════════════════════════════════════════════════
 *
 * 事件流里每一步都有 `tool:call` + `tool:result`，所以 `history` 是可以**重建**
 * 的，不必把 ctx 另存一份。这条比「再加一个快照文件」好：快照会与事件流分叉，
 * 而分叉的那一天没人知道该信哪个。
 *
 * ── ★ 恢复不了的，说恢复不了 ──────────────────────────────────
 *
 * 三条**明确的拒绝**，而不是猜一个状态出来：
 *
 *     · 没有 `run:start`        → 不知道要跑什么、在哪儿跑
 *     · `run:end` 说**做完了** → 没有可恢复的步骤（见下）
 *     · 最后一步**没有结果**    → 见下
 *
 * ── ★★ 最要紧的一条：那一步的副作用**不知道发没发生** ──────────
 *
 * 日志里 `tool:call` 有、`tool:result` 没有，意味着进程死在**工具执行中间**。
 * 那一步**做过没有是未知的** —— 对 `read_file` 无所谓，对 `write_file` /
 * `move_file` / `delete_file` 则完全不同：重跑一次可能覆盖、也可能因为来源
 * 已经没了而失败。
 *
 * 这里**不假装知道**：不把它放进 `history`（放进去等于宣称它成功了），
 * 把 `step` 停在**它**那一步（于是会重跑），并且把这条不确定性**报出来**
 * （`inFlight`），由调用方决定要不要继续。**静默跳过它**和**静默重跑它**
 * 都是在替别人猜一个涉及副作用的决定。
 *
 * @module JevLoop/resume
 */

import type { StepRecord } from './frame.ts'

/** 一个可以接着跑的状态 */
export interface ResumeState {
  task: string
  cwd: string
  /** 下一个该跑的步号 */
  step: number
  /** 已经做完的动作（`tool:call` 与 `tool:result` 配对的结果） */
  history: StepRecord[]
  /** 已知文件（从 `list_dir` 的结果里认出来，口径与 loop 一致） */
  files: string[]
  /** 读过哪些文件 */
  readFiles: string[]
  /**
   * 死在半路、**副作用未知**的那一步。有它就意味着上面那个 `step` 会被重跑。
   */
  inFlight?: { step: number; tool: string; input: string }
}

/** 折日志的结果。**恢复不了就是恢复不了**，不返回一个半成品 */
export type ResumeOutcome = { ok: true; state: ResumeState } | { ok: false; why: string }

/** 一条事件是不是某种形状。日志是可以手改的，所以逐字段验，不硬转 */
function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

/**
 * 把一串事件折成一个恢复点。
 *
 * 只看**最后一次** `run:start` 之后的事件 —— 一个会话文件可以装好几轮，
 * 而「接着跑」接着的永远是最后那一轮。
 *
 * @param events 会话日志里这一轮的事件（顺序即发生顺序）
 */
export function resumePointFrom(events: readonly unknown[]): ResumeOutcome {
  let task: string | undefined
  let cwd: string | undefined
  let startAt = -1
  /**
   * 结束原因。★ **不是「有 run:end 就不能恢复」** —— 一轮撞上 `max_steps` 或
   * 预算封顶也会正常结束（`run:end` 照写），而那一轮**恰恰是最该接着跑的**。
   * 只有「任务做完了」才叫没有可恢复的步骤。
   */
  let halt: string | undefined

  for (let i = 0; i < events.length; i++) {
    const e = events[i]
    if (!isRecord(e)) continue
    if (e.type === 'run:start') {
      task = typeof e.task === 'string' ? e.task : undefined
      cwd = typeof e.cwd === 'string' ? e.cwd : undefined
      startAt = i
      halt = undefined // 又开了一轮，之前那轮的 run:end 不算数
      continue
    }
    if (e.type === 'run:end' && startAt >= 0) halt = typeof e.halt === 'string' ? e.halt : '?'
  }

  if (startAt < 0 || task === undefined || cwd === undefined) {
    return { ok: false, why: '日志里没有可用的 run:start —— 不知道要跑什么、在哪个目录跑' }
  }
  if (halt === 'agent_done') {
    return { ok: false, why: '这一轮是 agent_done 结束的 —— 任务已经做完了，没有可恢复的步骤' }
  }

  // ── 按步号把 call 与 result 配对 ──
  const calls = new Map<number, { tool: string; input: string }>()
  const results = new Map<number, string>()
  for (const e of events.slice(startAt + 1)) {
    if (!isRecord(e) || typeof e.step !== 'number') continue
    if (e.type === 'tool:call' && typeof e.tool === 'string' && typeof e.input === 'string') {
      calls.set(e.step, { tool: e.tool, input: e.input })
    }
    if (e.type === 'tool:result' && typeof e.tool === 'string' && typeof e.output === 'string') {
      results.set(e.step, e.output)
    }
  }

  const steps = [...calls.keys()].sort((a, b) => a - b)
  const history: StepRecord[] = []
  const files: string[] = []
  const readFiles: string[] = []
  let inFlight: ResumeState['inFlight']

  for (const s of steps) {
    const call = calls.get(s)!
    const out = results.get(s)
    if (out === undefined) {
      /*
        ★ 最后一个只有 call 没有 result 的步骤 = 死在执行中间。
          不放进 history（那等于宣称它成功了），把恢复点停在它这里，并报出来。
      */
      inFlight = { step: s, tool: call.tool, input: call.input }
      break
    }
    history.push({ step: s, tool: call.tool, input: call.input, result: out })
    // 口径与 loop 里那两处一致：`list_dir` 的结果是文件列表，读类工具记进 readFiles
    if (call.tool === 'list_dir') {
      for (const line of out.split('\n')) {
        const name = line.trim()
        if (name && !name.endsWith('/') && !files.includes(name)) files.push(name)
      }
    }
    if (call.tool === 'read_file' && call.input.trim() && !readFiles.includes(call.input.trim())) {
      readFiles.push(call.input.trim())
    }
  }

  // 重跑那一步 → 恢复点就是它的步号；否则接在最后一个做成的步骤之后
  const next = inFlight ? inFlight.step : steps.length > 0 ? steps[steps.length - 1]! + 1 : 0

  return {
    ok: true,
    state: {
      task,
      cwd,
      step: next,
      history,
      files,
      readFiles,
      ...(inFlight ? { inFlight } : {}),
    },
  }
}
