/**
 * capability report 的**门禁**（脚本在 `scripts/adapter-report.ts`）。
 *
 * ═══════════════════════════════════════════════════════════
 * 这份文件存在的唯一理由：**报告是手写的，代码不是**
 * ═══════════════════════════════════════════════════════════
 *
 * `examples/external-host.capabilities.json` 是给人看的能力声明。它写出来的
 * 当天是对的 —— 然后有人往宿主里加一个投影、改一个位置的动作，它不会跟着改。
 *
 * 在此之前，全仓库**只有 README 提到它**，没有任何代码读它：一份没有消费方的
 * 声明（§8.16）。`npm run adapter-report` 补上了消费方，但这个测试才是**门禁** ——
 * 脚本要有人记得跑才算检查，而 `npm test` 是每次都会跑的那一条。
 *
 * ★ 所以这里测的不只是「报告和代码一致」，还有**这个检查会不会红**：
 *   报告被改坏时必须报出来，而不是通过。一个不可能失败的检查和一个通过的
 *   检查无法区分 —— 所以下面拿真的报告做阴性/阳性两边。
 *
 * @module JevLoop/adapter-report.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { loadReport, reportDrift, contractProblems, type CapabilityReport } from '../scripts/adapter-report.ts'

const report = loadReport()

/** 复制一份报告并改一处 —— 用来证明检查真的会响 */
function withEdit(change: (r: CapabilityReport) => void): CapabilityReport {
  const copy = structuredClone(report) as CapabilityReport
  change(copy)
  return copy
}

test('报告与代码一致 —— 位置 / 动作 / 投影 / 动态提供者 / 图节点 / 终止态', () => {
  const drift = reportDrift(report)
  assert.deepEqual(drift, [], `报告和代码对不上：\n${drift.join('\n')}`)
})

test('声明出来的能力足以消费两份契约', () => {
  const problems = contractProblems(report)
  assert.deepEqual(problems, [], `能力不够用：\n${problems.join('\n')}`)
})

test('★ 报告多写一个位置会被挡下 —— 检查不是永远绿的', () => {
  const drift = reportDrift(withEdit((r) => { r.positions['host:made-up'] = ['call'] }))
  assert.ok(drift.some((m) => m.includes('host:made-up')), `应当报出多余的位置，实际：${JSON.stringify(drift)}`)
})

test('★ 位置的动作被改掉会被挡下', () => {
  const drift = reportDrift(withEdit((r) => { r.positions['after-tool'] = ['continue'] }))
  assert.ok(drift.some((m) => m.includes('\'after-tool\'')), `应当报出动作不一致，实际：${JSON.stringify(drift)}`)
})

test('★ 少写一个投影会被挡下', () => {
  const drift = reportDrift(withEdit((r) => { r.projections = r.projections.slice(1) }))
  assert.ok(drift.some((m) => m.includes('投影对不上')), JSON.stringify(drift))
})

test('★ 图节点写成图里不存在的名字会被挡下', () => {
  const drift = reportDrift(withEdit((r) => { r.customGraphNodes = [...r.customGraphNodes, 'does_not_exist'] }))
  assert.ok(drift.some((m) => m.includes('does_not_exist')), JSON.stringify(drift))
})

test('★ 终止态混进节点清单会被挡下 —— done 不是任何边的起点', () => {
  const drift = reportDrift(withEdit((r) => { r.customGraphNodes = [...r.customGraphNodes, 'done'] }))
  assert.ok(drift.some((m) => m.includes('\'done\'')), JSON.stringify(drift))
})

test('★ 声明一个演示不出来的图特征会被挡下', () => {
  const drift = reportDrift(withEdit((r) => { r.graphFeatures = [...r.graphFeatures, 'parallel-fanout'] }))
  assert.ok(drift.some((m) => m.includes('parallel-fanout')), JSON.stringify(drift))
})

test('★ 声称一个不存在的规范版本会被挡下', () => {
  const drift = reportDrift(withEdit((r) => { r.contractSchema = 'decision-contract/v99' }))
  assert.ok(drift.some((m) => m.includes('contractSchema')), JSON.stringify(drift))
})

test('★ 声称不需要先核对能力会被挡下', () => {
  const drift = reportDrift(withEdit((r) => { r.conformance.dispatchAfterCapabilityCheck = false }))
  assert.ok(drift.some((m) => m.includes('先核对能力')), JSON.stringify(drift))
})
