/**
 * 等价检验（TOST）—— 重点是**两条不许出错的性质**
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件里最重要的是第二、第三个测试
 * ═══════════════════════════════════════════════════════════
 *
 *   · 差异**大**的时候绝不许说「等价」（那是把阴性结果刷成阳性）；
 *   · 差异**小而 n 大**的时候必须说「等价」（那是这个工具存在的理由）；
 *   · 两臂**逐格一致**时区间退化成一个点，delta=0 ⇒ 等价，且不许报成缺数据。
 *
 * @module JevLoop/equivalence.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { normalCdf, pairedDiff, pairedMde, tostPaired, zFor } from '../src/equivalence.ts'

// ═══════════════════════════════════════════════════════════
// ① 正态工具本身
// ═══════════════════════════════════════════════════════════

test('normalCdf：几个标准点对得上', () => {
  assert.ok(Math.abs(normalCdf(0) - 0.5) < 1e-6)
  assert.ok(Math.abs(normalCdf(1.96) - 0.975) < 2e-4)
  assert.ok(Math.abs(normalCdf(-1.96) - 0.025) < 2e-4)
  assert.ok(normalCdf(-6) < 1e-6)
  assert.ok(normalCdf(6) > 1 - 1e-6)
})

test('zFor 是 normalCdf 的反函数', () => {
  for (const p of [0.8, 0.9, 0.95, 0.975, 0.995]) {
    assert.ok(Math.abs(normalCdf(zFor(p)) - p) < 1e-4, `p=${p}`)
  }
})

// ═══════════════════════════════════════════════════════════
// ② 配对差
// ═══════════════════════════════════════════════════════════

test('配对差：δ = (b − c)/n，SE 用配对公式而不是两样本公式', () => {
  const d = pairedDiff(6, 1, 72)
  assert.ok(Math.abs(d.delta - 5 / 72) < 1e-12)
  // SE = sqrt(7 − 25/72)/72 = sqrt(6.6528)/72 ≈ 0.03582
  const expected = Math.sqrt(7 - 25 / 72) / 72
  assert.ok(Math.abs(d.se - expected) < 1e-12, `se=${d.se} 期望 ${expected}`)
})

test('两臂逐格一致 ⇒ δ=0 且 SE=0（点区间，不是缺数据）', () => {
  const d = pairedDiff(0, 0, 62)
  assert.equal(d.delta, 0)
  assert.equal(d.se, 0)
})

// ═══════════════════════════════════════════════════════════
// ③ ★ 防刷分：差异大的时候绝不许说等价
// ═══════════════════════════════════════════════════════════

test('★ 差异远大于边界 ⇒ 不许声称等价', () => {
  // 72 格里 20 格只甲接受、2 格只乙接受 ⇒ δ ≈ 25%，边界只有 5%
  const t = tostPaired(20, 2, 72, 0.05)
  assert.equal(t.equivalent, false)
  assert.ok(t.delta > 0.2)
  assert.equal(t.insideMargin, false)
})

test('★ 差异与边界同量级 ⇒ 边界拿不到那个结论', () => {
  // δ = 4/72 ≈ 5.6%，正压在 Δ=5% 上 ⇒ 必须不显著等价
  const t = tostPaired(4, 0, 72, 0.05)
  assert.equal(t.equivalent, false)
})

// ═══════════════════════════════════════════════════════════
// ④ ★ 该说等价的时候必须说
// ═══════════════════════════════════════════════════════════

test('★ 逐格一致 ⇒ 等价（最强的等价证据，不是「没数据」）', () => {
  const t = tostPaired(0, 0, 62, 0.05)
  assert.equal(t.equivalent, true)
  assert.equal(t.p, 0)
  assert.equal(t.delta, 0)
})

test('★ 小差异 + 足够 n ⇒ 等价（这个工具存在的理由）', () => {
  // 300 格里 3 格不一致、方向各半 ⇒ δ = 0%，区间远在 ±5% 内
  const t = tostPaired(2, 1, 300, 0.05)
  assert.equal(t.equivalent, true, `p=${t.p} 区间 [${t.lower}, ${t.upper}]`)
  assert.ok(t.lower > -0.05 && t.upper < 0.05)
})

test('同一个差异，n 小的时候说不出来 —— 阴性结果必须带 n', () => {
  const small = tostPaired(1, 0, 9, 0.05) // δ = 11%，SE 巨大
  const big = tostPaired(1, 0, 900, 0.05) // 同样的方向，n 大 100 倍
  assert.equal(small.equivalent, false)
  // n 大之后点估计小了、区间也窄了 ⇒ 才可能等价
  assert.ok(big.lower > -0.05 && big.upper < 0.05)
  assert.equal(big.equivalent, true)
})

// ═══════════════════════════════════════════════════════════
// ⑤ 一致性与最小可检测差异
// ═══════════════════════════════════════════════════════════

test('p 与区间两个判据结论一致', () => {
  for (const [b, c, n] of [
    [0, 0, 62],
    [2, 1, 300],
    [6, 1, 72],
    [20, 2, 72],
  ] as const) {
    const t = tostPaired(b, c, n, 0.05)
    assert.equal(t.equivalent, t.insideMargin, `b=${b} c=${c} n=${n}`)
  }
})

test('MDE：n 越大越小；不一致率越高越大', () => {
  const a = pairedMde(72, 0.1)
  const b = pairedMde(300, 0.1)
  assert.ok(b < a, `${b} 应小于 ${a}`)
  assert.ok(pairedMde(72, 0.3) > a)
  // 数量级：n=72、不一致率 10% ⇒ 约 0.16
  assert.ok(a > 0.1 && a < 0.25, `MDE=${a}`)
})

test('n=0 或没有不一致 ⇒ MDE 是 1（什么都排除不了）', () => {
  assert.equal(pairedMde(0, 0.1), 1)
  assert.equal(pairedMde(72, 0), 1)
})
