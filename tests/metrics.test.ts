/**
 * 指标导出（TODO §11）
 *
 * ═══════════════════════════════════════════════════════════
 * 它测的是**两个出口各自用对形状**，以及「数字是下界」不许被藏起来
 * ═══════════════════════════════════════════════════════════
 *
 *   ① 数据来自会话日志本身（`run:start` + `run:end.stats`），不另存一份计数
 *   ② Prometheus 那边**只有聚合** —— 任务名做成标签会让基数无界增长
 *   ③ JSON 那边有逐任务明细 —— 那才是「每任务多少」该待的地方
 *   ④ 漏报 usage 的批次数要**导出去**：token 总数是下界，监视器得看得见
 *   ⑤ 缺账目的轮次照样计入 `runs`，但不编数字出来
 *
 * @module JevLoop/metrics.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { metricsFrom, renderMetricsJson, renderPrometheus } from '../src/metrics.ts'

/** 一轮：run:start + run:end（带账目） */
function run(task: string, halt: string, stats: Record<string, number>) {
  return [
    { type: 'run:start', task, cwd: '/w', at: 0 },
    { type: 'run:end', halt, steps: 2, answer: 'ok', stats },
  ]
}

const FULL = {
  decisions: 7,
  modelCalls: 2,
  inputTokens: 1000,
  outputTokens: 200,
  decisionInputTokens: 400,
  decisionOutputTokens: 50,
  decisionBatchesWithoutUsage: 0,
}

test('★ 折两轮：总数是逐轮相加，明细留着任务名', () => {
  const snap = metricsFrom([...run('甲', 'agent_done', FULL), ...run('乙', 'max_steps', { ...FULL, decisions: 3 })])
  assert.equal(snap.runs, 2)
  assert.deepEqual(
    snap.tasks.map((t) => t.task),
    ['甲', '乙'],
  )
  assert.deepEqual(
    snap.tasks.map((t) => t.halt),
    ['agent_done', 'max_steps'],
  )
  assert.equal(snap.totals.decisions, 10, '7 + 3')
  assert.equal(snap.totals.inputTokens, 2000)
  assert.equal(snap.totals.decisionInputTokens, 800)
})

test('★★★ Prometheus 里**没有任务名** —— 基数无界是打垮监视器的经典方式', () => {
  const snap = metricsFrom([...run('把 alpha.ts 里的 totalOf 抄到 summary.ts', 'agent_done', FULL)])
  const prom = renderPrometheus(snap)
  assert.doesNotMatch(prom, /task=/, '不许把任务名做成标签')
  assert.doesNotMatch(prom, /totalOf/, '任务名连文本里都不该出现（那会误导成标签）')
  for (const name of [
    'jevloop_runs_total',
    'jevloop_decisions_total',
    'jevloop_model_calls_total',
    'jevloop_input_tokens_total',
    'jevloop_output_tokens_total',
  ]) {
    assert.match(prom, new RegExp(`^${name} \\d+$`, 'm'), `要有 ${name}`)
  }
})

test('★ Prometheus 是合法的最小暴露格式：每条都有 HELP 与 TYPE', () => {
  const prom = renderPrometheus(metricsFrom([...run('t', 'agent_done', FULL)]))
  const names = [...prom.matchAll(/^([a-z_]+) /gm)].map((m) => m[1]!)
  for (const n of names) {
    assert.ok(prom.includes(`# HELP ${n} `), `${n} 缺 HELP`)
    assert.ok(prom.includes(`# TYPE ${n} counter`), `${n} 缺 TYPE`)
  }
  assert.ok(prom.endsWith('\n'), '文本要以换行结束')
})

test('★★ JSON 快照里有逐任务明细 —— 「每任务多少」待在这里', () => {
  const snap = metricsFrom([...run('甲', 'agent_done', FULL), ...run('乙', 'budget_tokens:100', FULL)])
  const parsed = JSON.parse(renderMetricsJson(snap)) as typeof snap
  assert.equal(parsed.tasks.length, 2)
  assert.equal(parsed.tasks[1]!.halt, 'budget_tokens:100')
  assert.equal(parsed.tasks[0]!.decisions, 7)
  assert.equal(parsed.totals.decisions, 14)
})

test('★★★ 漏报 usage 的批次数要导出去 —— token 是下界，监视器得看得见', () => {
  const snap = metricsFrom([...run('t', 'agent_done', { ...FULL, decisionBatchesWithoutUsage: 3 })])
  assert.match(
    renderPrometheus(snap),
    /^jevloop_decision_batches_without_usage_total 3$/m,
    '★ 不导出去的话，一个漏报 token 的后端在面板上看起来是免费的',
  )
  assert.equal(snap.totals.decisionBatchesWithoutUsage, 3)
})

test('★★ 缺账目的轮次照样计入 runs，但**不编数字**', () => {
  const snap = metricsFrom([
    { type: 'run:start', task: '甲', cwd: '/w', at: 0 },
    { type: 'run:end', halt: 'crashed', steps: 0, answer: '' }, // 没有 stats
    ...run('乙', 'agent_done', FULL),
  ])
  assert.equal(snap.runs, 2, '★ 它是一轮，只是没有账目')
  assert.equal(snap.tasks[0]!.decisions, 0, '缺就按 0 计，不猜')
  assert.equal(snap.tasks[0]!.halt, 'crashed', '但结束原因要如实带上')
  assert.equal(snap.totals.decisions, 7, '有账目的那轮不受影响')
})

test('★ 没有 run:start 的孤立 run:end 也算一轮，任务名说「未记」而不是编一个', () => {
  const snap = metricsFrom([{ type: 'run:end', halt: 'agent_done', steps: 1, answer: '', stats: FULL }])
  assert.equal(snap.runs, 1)
  assert.equal(snap.tasks[0]!.task, '(未记任务)')
})

test('★ 坏行 / 认不出的形状不影响别的轮次', () => {
  const snap = metricsFrom([
    null,
    'not an object',
    42,
    { type: 'run:start', task: '甲', cwd: '/w' },
    { type: 'something:else' },
    ...run('乙', 'agent_done', FULL),
  ])
  assert.equal(snap.totals.decisions, 7, '只统计有账目的那一轮')
})

test('空输入 ⇒ 一份诚实的空快照，不是抛异常', () => {
  const snap = metricsFrom([])
  assert.equal(snap.runs, 0)
  assert.deepEqual(snap.tasks, [])
  assert.equal(snap.totals.decisions, 0)
  assert.match(renderPrometheus(snap), /^jevloop_runs_total 0$/m)
})
