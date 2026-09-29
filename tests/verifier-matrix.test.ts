/**
 * 判定层混淆矩阵 —— 每个率都要**带着分母**，零事件要给上界，弃权不许刷分
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件的重点是三条**防刷分**的性质，不是算得对不对
 * ═══════════════════════════════════════════════════════════
 *
 *   · 一律弃权 ⇒ 所有率的分母都是 0，`value` 是 `null`（**不是 0**），覆盖率塌到 0；
 *   · 一律拒绝 ⇒ `catchRate` 满分，但 `falseAlarmRate` 同时满分 —— 两个数必须一起看；
 *   · 一律放行 ⇒ `falseAlarmRate` 是 0，但 `falseConfirmRate` 会暴露它。
 *
 * @module JevLoop/verifier-matrix.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  confusion,
  mcnemar,
  mergeCounts,
  minDetectable,
  proportion,
  rates,
  reliability,
  wilson,
  type Decision,
} from '../src/verifier-matrix.ts'

const d = (verdict: Decision['verdict'], gold: Decision['gold'], id = 'x'): Decision => ({ id, verdict, gold })

// ═══════════════════════════════════════════════════════════
// ① 数表
// ═══════════════════════════════════════════════════════════

test('数表：四格 + 弃权分得清', () => {
  const c = confusion([
    d('accept', 'good'),
    d('accept', 'bad'),
    d('reject', 'good'),
    d('reject', 'bad'),
    d('abstain', 'good'),
    d('abstain', 'bad'),
  ])
  assert.deepEqual(c, { acceptGood: 1, acceptBad: 1, rejectGood: 1, rejectBad: 1, abstain: 2, total: 6 })
})

test('合并是显式的：分片求和，不做平均', () => {
  const a = confusion([d('accept', 'bad'), d('reject', 'good')])
  const b = confusion([d('accept', 'bad')])
  const m = mergeCounts([a, b])
  assert.equal(m.acceptBad, 2)
  assert.equal(m.rejectGood, 1)
  assert.equal(m.total, 3)
})

// ═══════════════════════════════════════════════════════════
// ② 四个率：防刷分的三条性质
// ═══════════════════════════════════════════════════════════

test('防刷分：一律弃权 ⇒ 分母为 0，value 是 null 而不是 0', () => {
  const r = rates(confusion([d('abstain', 'good'), d('abstain', 'bad')]))
  assert.equal(r.catchRate.value, null)
  assert.equal(r.falseAlarmRate.value, null)
  assert.equal(r.falseConfirmRate.value, null)
  assert.equal(r.coverage.value, 0)
  assert.equal(r.abstentionRate.value, 1)
})

test('防刷分：一律拒绝 ⇒ 捕获率满分，但假警报率同时满分', () => {
  const r = rates(confusion([d('reject', 'bad'), d('reject', 'bad'), d('reject', 'good'), d('reject', 'good')]))
  assert.equal(r.catchRate.value, 1)
  assert.equal(r.falseAlarmRate.value, 1)
})

test('防刷分：一律放行 ⇒ 假警报率为 0，假确认率把它暴露出来', () => {
  const r = rates(confusion([d('accept', 'good'), d('accept', 'bad')]))
  assert.equal(r.falseAlarmRate.value, 0)
  assert.equal(r.falseConfirmRate.value, 0.5)
})

test('假确认率只看批准过的那些格（FFR 的分母纪律）', () => {
  // 批准的 9 格里 1 格是坏的 ⇒ 1/9，而不是 ÷ 全部 20
  const r = rates(confusion([...Array(8).fill(d('accept', 'good')), d('accept', 'bad'), ...Array(11).fill(d('reject', 'bad'))]))
  assert.equal(r.falseConfirmRate.n, 1)
  assert.equal(r.falseConfirmRate.d, 9)
  assert.equal(r.falseConfirmRate.value, 1 / 9)
})

// ═══════════════════════════════════════════════════════════
// ③ 零事件：给上界，不给「0%」
// ═══════════════════════════════════════════════════════════

test('0/n 必须带 95% 上界：rule of three 与 Wilson 都给', () => {
  const z = proportion(0, 27)
  assert.equal(z.value, 0)
  assert.equal(z.zeroBound, 3 / 27) // 11.1% —— 这正是「0/27 只能排除 > 11%」
  assert.ok(z.upper > 0.1 && z.upper < 0.15, `Wilson 上界应落在 10%~15%，实得 ${z.upper}`)
})

test('有事件的时候不给 zeroBound —— 不许拿它冒充区间', () => {
  assert.equal(proportion(1, 27).zeroBound, null)
})

test('小分母的 rule of three 会超过 1 —— 截到 100%，不许印 300%', () => {
  assert.equal(proportion(0, 1).zeroBound, 1) // 3/1 = 300% ⇒ 截成 1
  assert.equal(proportion(0, 2).zeroBound, 1)
  assert.equal(proportion(0, 4).zeroBound, 0.75)
})

test('minDetectable：0/300 才排到 1%', () => {
  assert.ok(Math.abs(minDetectable(300) - 0.01) < 1e-9)
  assert.equal(minDetectable(0), 1)
})

test('Wilson 在极端比例上不给负下界', () => {
  const w = wilson(0, 5)
  assert.ok(w.lower >= 0 && w.upper <= 1)
  const w2 = wilson(5, 5)
  assert.ok(w2.lower > 0 && w2.upper === 1)
})

// ═══════════════════════════════════════════════════════════
// ④ 复合可靠性：不等式，不是 p 值
// ═══════════════════════════════════════════════════════════

test('净帮忙 ⟺ (1−p)·c·r > p·f', () => {
  const r = reliability({ p: 0.5, catchRate: 0.8, falseAlarmRate: 0.1, fixRate: 0.5 })
  // 救回 0.5*0.8*0.5 = 0.2；弄坏 0.5*0.1 = 0.05 ⇒ 净赚 0.15
  assert.ok(Math.abs(r.net - 0.15) < 1e-12)
  assert.ok(Math.abs(r.pPrime - 0.65) < 1e-12)
  assert.equal(r.helps, true)
  assert.ok(Math.abs(r.breakEvenFalseAlarm - 0.4) < 1e-12)
})

test('假警报太贵的时候判定层在帮倒忙 —— 而且公式自己会说', () => {
  const r = reliability({ p: 0.9, catchRate: 0.5, falseAlarmRate: 0.2, fixRate: 0.2 })
  // 救回 0.1*0.5*0.2 = 0.01；弄坏 0.9*0.2 = 0.18 ⇒ 净亏
  assert.equal(r.helps, false)
  assert.ok(r.pPrime < 0.9)
})

test('r = 0（拦下但修不好）时判定层纯粹是成本', () => {
  const r = reliability({ p: 0.5, catchRate: 1, falseAlarmRate: 0, fixRate: 0 })
  assert.equal(r.pPrime, 0.5)
  assert.equal(r.helps, false) // 净收益恰好是 0，不算「帮忙」
})

test('不发明 r：报「要求多大的修复率」', () => {
  // p=0.5, f=0.1, c=0.8 ⇒ r* = 0.5·0.1 / (0.5·0.8) = 0.125
  const r = reliability({ p: 0.5, catchRate: 0.8, falseAlarmRate: 0.1, fixRate: 0 })
  assert.ok(Math.abs(r.requiredFixRate - 0.125) < 1e-12)
  // 恰好达到门槛时，净收益正好是 0
  const at = reliability({ p: 0.5, catchRate: 0.8, falseAlarmRate: 0.1, fixRate: r.requiredFixRate })
  assert.ok(Math.abs(at.net) < 1e-12)
  assert.equal(at.helps, false) // 相等不算「净帮忙」
})

// ═══════════════════════════════════════════════════════════
// ⑤ 配对比较：精确 McNemar
// ═══════════════════════════════════════════════════════════

const pair = (a: boolean, b: boolean, id = 'x'): Parameters<typeof mcnemar>[0][number] => ({ id, gold: 'bad', a, b })

test('McNemar 只看不一致的格', () => {
  const m = mcnemar([pair(true, true), pair(false, false), pair(true, false), pair(true, false)])
  assert.equal(m.bothAccept, 1)
  assert.equal(m.bothReject, 1)
  assert.equal(m.aOnly, 2)
  assert.equal(m.bOnly, 0)
  assert.equal(m.exactP, 0.5) // 2 · C(2,0) · 0.5² = 0.5
})

test('McNemar 精确 p：5:0 不显著，6:0 显著 —— 小样本只有精确检验能用', () => {
  assert.ok(Math.abs(mcnemar(Array(5).fill(pair(true, false))).exactP - 0.0625) < 1e-12)
  assert.ok(Math.abs(mcnemar(Array(6).fill(pair(true, false))).exactP - 0.03125) < 1e-12)
})

test('两臂完全一致 ⇒ p = 1（没有可归因的差异）', () => {
  assert.equal(mcnemar([pair(true, true), pair(false, false)]).exactP, 1)
})

test('零配对 ⇒ p = 1，不抛异常', () => {
  assert.equal(mcnemar([]).exactP, 1)
})
