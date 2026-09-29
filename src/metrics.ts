/**
 * JevLoop · 把账目**导出给监视器**（TODO §11）
 *
 * ══════════════════════════════════════════════════════════════
 *  轨迹和账目一直是**给人看**的，这一份是给机器读的
 * ══════════════════════════════════════════════════════════════
 *
 * 数据来源是**会话日志本身**：每一轮的 `run:end` 里带着那一轮的 `stats`
 * （判定数、模型调用数、token），`run:start` 里带着任务。所以导出不需要新的
 * 记录格式，也不需要服务在跑 —— 离线折一份日志就能出数。
 *
 * ── ★ 一个刻意的取舍：任务名不进 Prometheus 标签 ────────────────
 *
 * 「每任务多少」这句话最直觉的写法是 `jevloop_decisions{task="…"}`。**不做**：
 * 任务名是自由文本，几乎每条都不一样，给指标加这种标签会让时间序列的基数
 * 无界增长 —— 那是把监视器打垮的经典方式，而且是在「加了个标签」这种看不出
 * 问题的小改动里发生的。
 *
 * 所以分成两个出口，各自用对形状：
 *
 *     Prometheus 文本   只有**聚合计数**（可加、基数固定），给监视器
 *     JSON 快照         有**逐任务明细**，给人 / 给事后分析
 *
 * @module JevLoop/metrics
 */

import type { MeterStats } from './vocab-records.ts'

/** 一轮任务跑完之后的账目 */
export interface TaskMetrics {
  task: string
  halt: string
  decisions: number
  modelCalls: number
  /** 生成 + 判定的总 token（§9） */
  inputTokens: number
  outputTokens: number
  /** 其中判定那部分 */
  decisionInputTokens: number
  decisionOutputTokens: number
  /** 后端一次 usage 都没报的判定批次 —— 于是 token 数是**下界** */
  decisionBatchesWithoutUsage: number
}

/** 一份可导出的快照 */
export interface MetricsSnapshot {
  /** 一共几轮 */
  runs: number
  /** 逐任务明细（Prometheus 那边**不放**这些） */
  tasks: TaskMetrics[]
  /** 聚合计数，可加 */
  totals: Omit<TaskMetrics, 'task' | 'halt'>
}

function isRecord(v: unknown): v is Record<string, unknown> {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

/** 从 `run:end.stats` 里取账目。取不到就按 0 计 —— 并**计数**，见 `unreadable` */
function statsOf(v: unknown): MeterStats | undefined {
  if (!isRecord(v)) return undefined
  const s = v as unknown as MeterStats
  return typeof s.decisions === 'number' ? s : undefined
}

/**
 * 一串事件（一个会话文件里的全部）→ 快照。
 *
 * 每一轮取**最后一次** `run:start` 的任务名与 `run:end` 的账目。缺账目的轮次
 * **照样计入 `runs`**，但它的各项按 0 计 —— 所以读了它的人要能看出「有几轮没数」。
 * 这里不编一个数字出来：一份看起来完整的导出比一份缺了东西的更危险。
 */
export function metricsFrom(events: readonly unknown[]): MetricsSnapshot {
  const tasks: TaskMetrics[] = []
  let current: string | undefined

  for (const e of events) {
    if (!isRecord(e)) continue
    if (e.type === 'run:start' && typeof e.task === 'string') {
      current = e.task
      continue
    }
    if (e.type !== 'run:end') continue
    const s = statsOf(e.stats)
    tasks.push({
      task: current ?? '(未记任务)',
      halt: typeof e.halt === 'string' ? e.halt : '(未记)',
      decisions: s?.decisions ?? 0,
      modelCalls: s?.modelCalls ?? 0,
      inputTokens: s?.inputTokens ?? 0,
      outputTokens: s?.outputTokens ?? 0,
      decisionInputTokens: s?.decisionInputTokens ?? 0,
      decisionOutputTokens: s?.decisionOutputTokens ?? 0,
      decisionBatchesWithoutUsage: s?.decisionBatchesWithoutUsage ?? 0,
    })
  }

  const sum = (f: (t: TaskMetrics) => number) => tasks.reduce((a, t) => a + f(t), 0)
  return {
    runs: tasks.length,
    tasks,
    totals: {
      decisions: sum((t) => t.decisions),
      modelCalls: sum((t) => t.modelCalls),
      inputTokens: sum((t) => t.inputTokens),
      outputTokens: sum((t) => t.outputTokens),
      decisionInputTokens: sum((t) => t.decisionInputTokens),
      decisionOutputTokens: sum((t) => t.decisionOutputTokens),
      decisionBatchesWithoutUsage: sum((t) => t.decisionBatchesWithoutUsage),
    },
  }
}

/**
 * Prometheus 文本格式。
 *
 * ★ 只有**聚合**，没有任务标签 —— 理由见模块头。任务名出现在 `# HELP` 里会成
 *   为误导（那是标签该干的事），所以这里连一个都不放。
 *
 * ★ `decision_batches_without_usage` 也导出去：token 总数是**下界**这件事
 *   必须能被监视器看见，否则一个漏报 token 的后端在面板上看起来是免费的。
 */
export function renderPrometheus(snap: MetricsSnapshot): string {
  const t = snap.totals
  const line = (name: string, help: string, value: number): string =>
    `# HELP ${name} ${help}\n# TYPE ${name} counter\n${name} ${value}\n`
  return (
    line('jevloop_runs_total', 'Runs recorded in the exported session log.', snap.runs) +
    line('jevloop_decisions_total', 'Decisions made across all runs.', t.decisions) +
    line('jevloop_model_calls_total', 'Generation calls across all runs.', t.modelCalls) +
    line('jevloop_input_tokens_total', 'Input tokens, generation and decision.', t.inputTokens) +
    line('jevloop_output_tokens_total', 'Output tokens, generation and decision.', t.outputTokens) +
    line('jevloop_decision_input_tokens_total', 'Input tokens spent on decisions.', t.decisionInputTokens) +
    line('jevloop_decision_output_tokens_total', 'Output tokens spent on decisions.', t.decisionOutputTokens) +
    line(
      'jevloop_decision_batches_without_usage_total',
      'Decision batches whose backend reported no token usage; token totals are a lower bound by this much.',
      t.decisionBatchesWithoutUsage,
    )
  )
}

/** 给人和事后分析用的 JSON。逐任务明细在这里。 */
export function renderMetricsJson(snap: MetricsSnapshot): string {
  return JSON.stringify(snap, null, 2)
}
