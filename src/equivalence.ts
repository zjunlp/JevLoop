/**
 * JevLoop · **等价检验**（TOST）—— 把「测不出差别」变成一句能写的结论
 *
 * ══════════════════════════════════════════════════════════════
 *  为什么必须有这个文件：我们的处境是「差异很小 + 事件很少」
 * ══════════════════════════════════════════════════════════════
 *
 * 零假设检验**在逻辑上无法证明「没有差别」**：p 大只说明「没测出来」，
 * 不说明「不存在」。而我们手上最常出现的结果恰恰是前者 ——
 * 判定臂之间 / 契约与 if/else 之间，逐格相同、事件稀少。
 *
 * 想把这种结果**正面**写成一句话，只有等价检验能做到：
 *
 *     先声明一个**可以接受的最大差异** Δ（业务决定，不是统计决定），
 *     再检验「差异是否落在 ±Δ 之内」。
 *
 * 做法是两次单侧检验：
 *
 *     H0₁: δ ≤ −Δ     对  H1₁: δ > −Δ
 *     H0₂: δ ≥ +Δ     对  H1₂: δ < +Δ
 *
 * 两个都拒掉 ⇒ 在 1−2α 水平上可以声称**等价**。等价区间同时给出
 * （1−2α 的置信区间落在 ±Δ 之内，是同一个判定的直观读法）。
 *
 * ── ★ 为什么是**配对**版本 ─────────────────────────────────────
 *
 * 我们的实验里，两条臂判的是**同一个候选**（见 `docs/MEASUREMENT-gate-equivalence.md`
 * Round 4），所以差异只该由**意见不一致的那些格**决定：
 *
 *     b = 只有甲接受、乙拒绝的格数
 *     c = 只有乙接受、甲拒绝的格数
 *     δ̂ = (b − c) / n
 *
 * 用独立两样本的公式会**高估方差**（把配对本身消掉的个体差异又算回去），
 * 于是等价检验变得过度保守 —— 明明等效却说测不出来。
 *
 * ── ★★ 这个模块**不猜** Δ ────────────────────────────────────────
 *
 * Δ 是「假确认率差多少算可接受」，那是**产品/风险判断**，不是统计能给的。
 * 所以 Δ 一律由调用方传进来，报告里必须把用的那个数印出来 ——
 * 一个不写 Δ 的等价结论是没有内容的。
 *
 * @module JevLoop/equivalence
 */

/** 标准正态分布函数。用 Abramowitz–Stegun 7.1.26 的 erf 近似（绝对误差 < 1.5e-7） */
export function normalCdf(z: number): number {
  const sign = z < 0 ? -1 : 1
  const x = Math.abs(z) / Math.SQRT2
  const t = 1 / (1 + 0.3275911 * x)
  const y =
    1 -
    ((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) *
      t *
      Math.exp(-x * x)
  return 0.5 * (1 + sign * y)
}

/** 单侧 z 分位（够用的近似，用于算最小可检测差异） */
export function zFor(p: number): number {
  // 二分：`normalCdf` 单调，区间取得足够宽
  let lo = -8
  let hi = 8
  for (let i = 0; i < 80; i++) {
    const mid = (lo + hi) / 2
    if (normalCdf(mid) < p) lo = mid
    else hi = mid
  }
  return (lo + hi) / 2
}

/** 配对比例差的估计与标准误。`b`/`c` 是**不一致**的两格，`n` 是总格数 */
export interface PairedDiff {
  /** δ̂ = (b − c) / n */
  delta: number
  /** Wald 标准误：sqrt((b + c) − (b − c)²/n) / n */
  se: number
  b: number
  c: number
  n: number
}

/**
 * 配对比例差（McNemar 的连续化版本）。
 *
 * ★ `se = 0`（两臂逐格一致）时 δ̂ 也是 0 —— 那不是「n 不够」，是**没有任何
 *   可归因的差异**。调用方要把它读成「点估计恰好为 0、区间为 0 宽」，
 *   而不是当成缺数据：62 格里两臂一格都没不一致，本身就是最强的等价证据。
 */
export function pairedDiff(b: number, c: number, n: number): PairedDiff {
  if (n <= 0) return { delta: 0, se: 0, b, c, n: 0 }
  const delta = (b - c) / n
  // SE(δ̂) = sqrt( (b + c) − (b − c)²/n ) / n
  //   ← Var = [ (b+c)/n − ((b−c)/n)² ] / n，两边同乘 n² 即得这个写法
  const variance = b + c - ((b - c) * (b - c)) / n
  return { delta, se: Math.sqrt(Math.max(0, variance)) / n, b, c, n }
}

/** 等价检验的结果 */
export interface Tost {
  /** 观测到的差异 δ̂ */
  delta: number
  /** 用进来的等价边界（**必须由调用方给**） */
  margin: number
  /** 单侧 p 值里较大的那个（> α 就不能声称等价） */
  p: number
  /** 在 1−2α 水平上能不能声称等价 */
  equivalent: boolean
  /** 1−2α 的置信区间 */
  lower: number
  upper: number
  /** 区间是否整个落在 ±Δ 之内（和 `equivalent` 应当一致，两个都给是为了让人核对） */
  insideMargin: boolean
}

/**
 * 配对比例的等价检验（TOST）。
 *
 * `alpha` 是**每一个单侧**检验的显著性水平，所以等价结论的置信水平是 `1 − 2α`。
 * 默认 `alpha = 0.05` ⇒ 90% 区间 —— 这一点常被写错，所以写进签名默认值里。
 */
export function tostPaired(b: number, c: number, n: number, margin: number, alpha = 0.05): Tost {
  const { delta, se } = pairedDiff(b, c, n)
  if (se === 0) {
    // 逐格一致：区间退化成一个点。点落在 ±Δ 内 ⇒ 等价。
    const inside = Math.abs(delta) < margin
    return { delta, margin, p: inside ? 0 : 1, equivalent: inside, lower: delta, upper: delta, insideMargin: inside }
  }
  const zLo = (delta + margin) / se // H0₁: δ ≤ −Δ
  const zHi = (margin - delta) / se // H0₂: δ ≥ +Δ
  const pLo = 1 - normalCdf(zLo)
  const pHi = 1 - normalCdf(zHi)
  const p = Math.max(pLo, pHi)
  const z = zFor(1 - alpha) // 单侧分位
  const lower = delta - z * se
  const upper = delta + z * se
  const inside = lower > -margin && upper < margin
  return { delta, margin, p, equivalent: p < alpha, lower, upper, insideMargin: inside }
}

/**
 * **最小可检测差异**（MDE）：在给定的不一致率和 n 下，这套设计能分辨多小的差。
 *
 * ★ 为什么报它：阴性结果必须带上「这套设计本来能看见多大的差异」，否则
 *   「没测出来」会被读成「不存在」。近似式 `MDE ≈ (z_{1−α/2} + z_{1−β})·sqrt(ψ/n)`，
 *   `ψ = (b+c)/n` 是不一致率。δ 很小时这个近似足够用，而它给出的量级正是
 *   报告里需要的那一句「本次设计只能排除大于 X 的差异」。
 */
export function pairedMde(n: number, discordance: number, alpha = 0.05, power = 0.8): number {
  if (n <= 0 || discordance <= 0) return 1
  const z = zFor(1 - alpha / 2) + zFor(power)
  return Math.min(1, z * Math.sqrt(discordance / n))
}
