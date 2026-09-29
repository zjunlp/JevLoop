/**
 * JevLoop · **判定层的混淆矩阵** —— 把「有没有用」变成一个算得出来的数
 *
 * ══════════════════════════════════════════════════════════════
 *  为什么不能再看「两组的平均差」
 * ══════════════════════════════════════════════════════════════
 *
 * 实测里 81 个格子里只有 1 个事件。**平均值差在这种事件密度下估不出来**：
 * 零事件的臂只能排除「发生率 > 11%」（0/27 的 95% 上界）。而判定层真正要回答的
 * 问题本来就不是「平均差多少」，是**它拦对不对**：
 *
 *     它说「可以交付」的那些里，有多少其实不该交付？   ← 假确认（危险的那侧）
 *     它说「不行」的那些里，有多少其实是好的？         ← 假警报（把好活拦下）
 *
 * 这两个数**在事件很少时也估得出来**，而且直接决定判定层值不值。
 *
 * ── 三档判定，两档金标 ─────────────────────────────────────────
 *
 *     verdict: accept | reject | **abstain**   ← 弃权是**单独一档**，不进任何分子分母
 *     gold:    good | bad
 *
 *     ┌──────────┬────────────┬───────────────────────────┐
 *     │          │ gold good  │ gold bad                  │
 *     ├──────────┼────────────┼───────────────────────────┤
 *     │ accept   │ 正确确认   │ **假确认**（漏放）        │
 *     │ reject   │ 假警报     │ 正确拒绝（拦住了）        │
 *     │ abstain  │ ← 覆盖率损失：**不许折进任何一边** ──→ │
 *     └──────────┴────────────┴───────────────────────────┘
 *
 * ★ 弃权必须单列，否则「一律说不知道」的判定层会在所有率上拿满分。
 *   所以每个率都带**分母**，另有一个 `coverage` 一起报 —— 这是
 *   Propose-Judge-Commit 那条「分母永远打印」的纪律，落在代码里。
 *
 * ── 零事件：给上界，不给「0%」 ─────────────────────────────────
 *
 * 观测到 0 次不等于发生率是 0。`zeroBound` 给的是 **rule of three**（3/n）——
 * Leni 报 `0/357` 时用的就是它（⇒ 约 1%），而不是写一个 0%。
 * Wilson 区间同时给出（两者略有差别，都由这里报，不挑一个好看的）。
 *
 * ── 为什么不能再拆（§12：超过 300 行必须说清）──────────────────
 *
 * 一句话：**这个文件只做一件事 —— 把一批判定折成可报的数**。
 *
 * 里面五块（数表 / 比例与区间 / 四个率 / 复合可靠性 / 配对检验）不是五个话题，
 * 是同一条链上的五步：数表 → 比率 → 比率进不等式 → 两臂之间的差是否可分辨。
 * 它们的**消费者是同一个**（`bench/confusion.ts` 的报告），拆开只会让
 * 「一个率怎么来的」散到三个文件里，而这里最容易犯的错正是**分母接错**——
 * 那是必须一眼看完的东西。
 *
 * 真到了要拆的时候，第一条缝是 `mcnemar`（配对检验）：它是**唯一**消费
 * `Pair`（而不是 `Decision`）的那一块，有自己的输入形状，可以单独测。
 *
 * @module JevLoop/verifier-matrix
 */

/** 判定层对**一个候选步**给出的裁决 */
export type Verdict = 'accept' | 'reject' | 'abstain'

/** 外部金标（**确定性 oracle**，不是模型判的）对这一格的真值 */
export type Gold = 'good' | 'bad'

/** 一条判定记录。`id` 用于跨臂**配对**（同一个候选步在不同臂里 id 相同） */
export interface Decision {
  id: string
  verdict: Verdict
  gold: Gold
}

/** 2×2 的计数。`abstain` 在表外单独数 */
export interface Counts {
  /** accept ∧ good */
  acceptGood: number
  /** accept ∧ bad —— **假确认** */
  acceptBad: number
  /** reject ∧ good —— **假警报** */
  rejectGood: number
  /** reject ∧ bad */
  rejectBad: number
  /** 弃权（两边都不进） */
  abstain: number
  /** 全部判定数（含弃权），`coverage` 的分母 */
  total: number
}

/** 一个比例：**永远带着它的分子分母** */
export interface Proportion {
  /** 分子 */
  n: number
  /** 分母 */
  d: number
  /** n/d；分母为 0 时是 `null`（**不是 0**） */
  value: number | null
  /** Wilson 95% 下界 */
  lower: number
  /** Wilson 95% 上界 */
  upper: number
  /**
   * 分子为 0 时的 95% 上界（rule of three，≈ 3/d，**截到 1**）。
   * ★ 只在这种情况下非 `null` —— 有事件的时候不许拿它当区间用。
   * ★ 分母很小时 `3/d` 会超过 1（d=1 时是 300%），那不是区间，所以截断：
   *   小分母下这个上界**本来就没有信息量**，截到 100% 才是诚实的读法。
   */
  zeroBound: number | null
}

/**
 * Wilson 区间。选它而不是正态近似：小样本 + 比例贴近 0 时正态近似会给出
 * 负的下界和过窄的区间，而我们**恰好**就活在这个区域里。
 */
export function wilson(n: number, d: number, z = 1.96): { lower: number; upper: number } {
  if (d <= 0) return { lower: 0, upper: 1 }
  const p = n / d
  const z2 = z * z
  const denom = 1 + z2 / d
  const center = (p + z2 / (2 * d)) / denom
  const half = (z * Math.sqrt((p * (1 - p)) / d + z2 / (4 * d * d))) / denom
  return { lower: Math.max(0, center - half), upper: Math.min(1, center + half) }
}

/** 把一个 `n/d` 包成带区间的比例。**分母为 0 时 value 是 `null`，不是 0** */
export function proportion(n: number, d: number): Proportion {
  if (d <= 0) return { n, d: 0, value: null, lower: 0, upper: 1, zeroBound: null }
  const { lower, upper } = wilson(n, d)
  return { n, d, value: n / d, lower, upper, zeroBound: n === 0 ? Math.min(1, 3 / d) : null }
}

/** 数出 2×2 */
export function confusion(decisions: readonly Decision[]): Counts {
  const c: Counts = { acceptGood: 0, acceptBad: 0, rejectGood: 0, rejectBad: 0, abstain: 0, total: 0 }
  for (const x of decisions) {
    c.total++
    if (x.verdict === 'abstain') c.abstain++
    else if (x.verdict === 'accept') x.gold === 'good' ? c.acceptGood++ : c.acceptBad++
    else x.gold === 'good' ? c.rejectGood++ : c.rejectBad++
  }
  return c
}

/** 合并多次重复/多个分片。**合并要显式写出来**，不许悄悄汇总 */
export function mergeCounts(list: readonly Counts[]): Counts {
  const out: Counts = { acceptGood: 0, acceptBad: 0, rejectGood: 0, rejectBad: 0, abstain: 0, total: 0 }
  for (const c of list) {
    out.acceptGood += c.acceptGood
    out.acceptBad += c.acceptBad
    out.rejectGood += c.rejectGood
    out.rejectBad += c.rejectBad
    out.abstain += c.abstain
    out.total += c.total
  }
  return out
}

/** 判定层的四个率 —— 缺任何一个都会让别的可以刷满 */
export interface Rates {
  /**
   * **捕获率 c** = 正确拒绝 ÷ 所有「本该拒绝」。判定层拦住了多少真的坏东西。
   * 对应用 Leni 那条复合公式里的 `c`。
   */
  catchRate: Proportion
  /**
   * **假警报率 f** = 假警报 ÷ 所有「本该接受」。判定层拦错了多少好东西。
   * 对应复合公式里的 `fb` —— ★ 它**不是免费的**：拦错会把好活改坏。
   */
  falseAlarmRate: Proportion
  /**
   * **假确认率** = 假确认 ÷ 所有「放行的」。
   * 这是 Propose-Judge-Commit 的 FFR 的同构物：**只看它批准了什么**。
   */
  falseConfirmRate: Proportion
  /** 覆盖率 = 给出明确裁决的比例（弃权为 1 − coverage） */
  coverage: Proportion
  /** 弃权率 */
  abstentionRate: Proportion
}

/** 从 2×2 算出四个率。弃权不进任何分子分母 */
export function rates(c: Counts): Rates {
  const decided = c.acceptGood + c.acceptBad + c.rejectGood + c.rejectBad
  return {
    // 坏的那一侧：拦住的 ÷ 所有该拦的
    catchRate: proportion(c.rejectBad, c.rejectBad + c.acceptBad),
    // 好的那一侧：拦错的 ÷ 所有该放的
    falseAlarmRate: proportion(c.rejectGood, c.rejectGood + c.acceptGood),
    // 只看批准：批错的 ÷ 所有批准的
    falseConfirmRate: proportion(c.acceptBad, c.acceptBad + c.acceptGood),
    coverage: proportion(decided, c.total),
    abstentionRate: proportion(c.abstain, c.total),
  }
}

/** 复合可靠性的输入 */
export interface ReliabilityInput {
  /** 单步本来做对的概率 p（**必须来自测量，不许拍**） */
  p: number
  /** 捕获率 c（`rates().catchRate.value`） */
  catchRate: number
  /** 假警报率 f（`rates().falseAlarmRate.value`） */
  falseAlarmRate: number
  /** 修复率 r：被拦住之后**真的修好**的比例 */
  fixRate: number
}

/** 复合可靠性的结果 */
export interface Reliability {
  /** `p' = p(1−f) + (1−p)·c·r` —— 过了判定层之后单步做对的概率 */
  pPrime: number
  /** 判定层**净帮忙**吗：`(1−p)·c·r > p·f` */
  helps: boolean
  /** 净收益（可正可负）：`(1−p)·c·r − p·f` */
  net: number
  /**
   * **盈亏平衡的假警报率**：`f* = (1−p)·c·r / p`。
   * 假警报率一旦超过它，判定层就在帮倒忙 —— 这个数比 p 值好读得多。
   */
  breakEvenFalseAlarm: number
  /**
   * **净帮忙所要求的修复率**：`r* = p·f / ((1−p)·c)`。
   *
   * ★ 为什么需要它：`r` 要有一条「拦下之后重试并验证」的通道才测得到。
   * 通道还没有，就**不许编一个 r** —— 改成报「r 得大到什么程度才划算」，
   * 那是一个可以直接和现实对照的门槛（做不到 ⇒ 这个判定层不成立）。
   */
  requiredFixRate: number
  /** n 步之后整条链还对的概率：`(p')^n` */
  at: (n: number) => number
}

/**
 * 把判定层折进可靠性。
 *
 * ★ 这个式子是**判定层主张的算术形式**：它只在 `(1−p)cr > p·f` 时净帮忙。
 * 于是「独立判定层到底有没有用」不再是一个 p 值的问题，是一个不等式 ——
 * 而 c、f、r 三个数在事件很少时也估得出来（见模块头）。
 */
export function reliability({ p, catchRate, falseAlarmRate, fixRate }: ReliabilityInput): Reliability {
  const rescued = (1 - p) * catchRate * fixRate
  const damaged = p * falseAlarmRate
  const pPrime = p * (1 - falseAlarmRate) + rescued
  const ceiling = (1 - p) * catchRate
  return {
    pPrime,
    helps: rescued > damaged,
    net: rescued - damaged,
    breakEvenFalseAlarm: p === 0 ? Infinity : rescued / p,
    requiredFixRate: ceiling === 0 ? Infinity : (p * falseAlarmRate) / ceiling,
    at: (n: number) => Math.pow(pPrime, n),
  }
}

// ═══════════════════════════════════════════════════════════
//  配对比较：同**一批候选步**跨臂复用（五篇里只有一篇这么做）
// ═══════════════════════════════════════════════════════════

/** 一条配对记录：同一个候选步，两条臂各自的裁决 */
export interface Pair {
  id: string
  /** 金标：这一格该不该被接受（**与臂无关**，所以可配对） */
  gold: Gold
  /** 臂甲放行了吗 */
  a: boolean
  /** 臂乙放行了吗 */
  b: boolean
}

/** McNemar 的 2×2（只关心两条臂**意见不同**的那些格） */
export interface McNemar {
  bothAccept: number
  aOnly: number
  bOnly: number
  bothReject: number
  /** 精确二项检验的**双侧** p（不一致格数少时唯一能用的那个） */
  exactP: number
}

/** 组合数 —— 只用整数运算，避免浮点溢出的中间量 */
function binom(n: number, k: number): number {
  if (k < 0 || k > n) return 0
  let r = 1
  for (let i = 0; i < k; i++) r = (r * (n - i)) / (i + 1)
  return r
}

/**
 * 精确 McNemar（双侧）。用二项分布而不是卡方：不一致格常常只有个位数，
 * 卡方近似在这里是错的。
 *
 * ★ 之所以必须配对：两条臂跑的是**同一批候选步**，臂间差异才是判定位置的差异；
 * 各自独立 rollout 只能比两个分布，那就是我们现在测不出东西的那个设计。
 */
export function mcnemar(pairs: readonly Pair[]): McNemar {
  let bothAccept = 0
  let aOnly = 0
  let bOnly = 0
  let bothReject = 0
  for (const x of pairs) {
    if (x.a && x.b) bothAccept++
    else if (x.a) aOnly++
    else if (x.b) bOnly++
    else bothReject++
  }
  const n = aOnly + bOnly
  const k = Math.min(aOnly, bOnly)
  let tail = 0
  for (let i = 0; i <= k; i++) tail += binom(n, i)
  const exactP = n === 0 ? 1 : Math.min(1, 2 * tail * Math.pow(0.5, n))
  return { bothAccept, aOnly, bOnly, bothReject, exactP }
}

/**
 * 「0/n 只能排除什么」。rule of three 的 95% 上界 —— 报零事件时必须带上它，
 * 否则「没测到」会被读成「不存在」。
 */
export function minDetectable(n: number): number {
  return n <= 0 ? 1 : Math.min(1, 3 / n)
}
