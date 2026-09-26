/**
 * JevLoop · Policy Engine
 *
 * 概率 → 动作。
 *
 * 这一层是**纯代码**，不碰模型。所以：
 *   · 调一个阈值不需要重跑任何判定
 *   · 同一次运行的答案可以拿去反复试不同的策略
 *   · 策略可以被单元测试覆盖（模型不能）
 *
 * ── 为什么不能再拆（§12：超过 300 行必须说清）────────────────────
 *
 * 一句话：**这个文件负责「答案 → 动作」**。
 *
 * 它有两半 —— 求值器（`resolvePolicy`）与谓词表（`gte` / `topGte` / …）——
 * 但谓词**只为被求值而存在**：它们没有第二个消费者，也没有独立的输入输出形状
 * （都是 `AnswerSet → boolean`）。§12 的两个判据在这里都不成立。
 *
 * ★ 2026-09-26 长出来的那部分（门限元数据 + `closestMargin`）也不构成新的缝：
 *   它是谓词表的**同一份定义的投影** —— `probe` 与谓词从同一处长出来，正是
 *   为了不让「margin 读的量」和「判定读的量」分叉（§8.16 的 `top` vs
 *   `prob_true` 就是这么错的）。把它拆走，那条「构造上成立」的保证就断了。
 *
 * @module JevLoop/policy
 */

import type { AnswerSet } from './vocab.ts'
import type { MarginReport, PolicyRule, ThresholdKind } from './vocab-decision.ts'
import { confidenceOf } from './vocab.ts'

// 再导出：门限这条链的消费方（标定台、界面）不用为了一个类型多认一个模块。
// 定义仍在 L0 —— `DecisionResult` 也带 `MarginReport`，而 L0 指不了 L1。
export type { MarginReport, ThresholdKind } from './vocab-decision.ts'

export interface PolicyOutcome {
  action: string
  reason: string
  /** 命中的规则下标，-1 = 没有规则命中 */
  ruleIndex: number
  /** 求值中发现的问题（策略函数抛异常、兜底规则位置不对） */
  warnings: PolicyWarning[]
}

export interface PolicyWarning {
  level: 'warn' | 'error'
  code: string
  message: string
}

/**
 * 按顺序求值，第一个 when 为真的规则胜出。
 * 没有 when 的规则 = 兜底，必须放最后。
 * 一条都没命中 → action = "escalate"（宁可交给上层，也不要瞎猜一个动作）。
 */
export function resolvePolicy<A extends AnswerSet>(
  rules: PolicyRule<A>[],
  answers: A,
  onWarn?: (w: PolicyWarning) => void,
): PolicyOutcome {
  const warnings: PolicyWarning[] = []
  const emit = (w: PolicyWarning) => {
    warnings.push(w)
    onWarn?.(w)
  }

  // 静态检查：「兜底必须放最后」如果不查，写错了是**静默**的
  const firstCatchAll = rules.findIndex((r) => !r.when)
  if (firstCatchAll >= 0 && firstCatchAll !== rules.length - 1) {
    emit({
      level: 'warn',
      code: 'catch_all_not_last',
      message: `第 ${firstCatchAll + 1} 条是无条件兜底，后面还有 ${rules.length - firstCatchAll - 1} 条规则 —— 那些永远不会被求值`,
    })
  }

  // ★ 静态检查：**兜底缺失同样是静默的**。
  //
  //   没有兜底时函数返回 escalate，但调用方从返回值上分不清
  //   「这组策略压根没打算兜底」和「兜底写了、条件没命中」——
  //   两者的排查方向完全相反。所以这里要主动报一句。
  //
  //   （这条在移植进 JevLoop 时掉过一次，见 REVIEWS 记录。）
  if (firstCatchAll < 0) {
    emit({
      level: 'warn',
      code: 'policy_no_catch_all',
      message: `这组策略（${rules.length} 条）没有无条件兜底规则。一条都没命中时会返回 escalate —— 没有调用方处理 escalate 的话，这一步就静默消失了`,
    })
  }

  for (let i = 0; i < rules.length; i++) {
    const r = rules[i]
    if (!r) continue
    if (!r.when) return { action: r.action, reason: r.reason ?? '兜底规则', ruleIndex: i, warnings }

    let hit = false
    try {
      hit = !!r.when(answers)
    } catch (err) {
      // 不静默：一个拼写错误（a.spamm.noul）和"模型判定不符合阈值"
      // 在日志上必须能区分开，否则排查是场灾难
      emit({
        level: 'warn',
        code: 'when_threw',
        message: `第 ${i + 1} 条（action=${r.action}）的 when 抛异常：${(err as Error)?.message ?? String(err)}。已按'条件不满足'处理`,
      })
    }
    if (hit) return { action: r.action, reason: r.reason ?? `命中第 ${i + 1} 条规则`, ruleIndex: i, warnings }
  }

  return {
    action: 'escalate',
    reason: '没有策略命中，且没有兜底规则 → 交回上层',
    ruleIndex: -1,
    warnings,
  }
}

// ── 策略里最常用的几个判断 ───────────────────────────────────

/**
 * 门限谓词的**可读回**的元数据。
 *
 * ★ 为什么要元数据：门限原来是**埋在闭包里**的（`topGte(id, t)` 返回一个
 *   捕获了 `t` 的匿名函数），于是「这次判定离翻掉有多近」这个问题**问不出来** ——
 *   而 TODO §2 说，**贴在门限边上的判定是一枚还没落地的硬币**，只报命中率
 *   而不报 margin 会高估我们知道的东西。
 *
 * ★★ `probe` 是这套东西的**全部要点**：它读的必须是**谓词读的同一个量**。
 *   §8.16 记着这个项目在 `top()`（`max(p, 1-p)`）与 `prob_true()`（`p`）上
 *   栽过一次 —— 两个名字看着是一件事，读的不是。所以下面的工厂里
 *   **谓词与 probe 从同一处定义长出来**，不是各写一遍：
 *
 *       const probe = (a) => …那个量…
 *       withThreshold((a) => probe(a) >= t, { …, probe })
 *
 *   这样「margin 和判定读的是同一个数」是**构造上成立**的，不靠人记。
 */
export interface ThresholdSpec {
  /** 谓词名，报出来让人对得上 DECISION.md 里的写法 */
  kind: ThresholdKind
  /** 问题 id */
  id: string
  threshold: number
  /** 被卡的那个量。**与谓词读的是同一个**；`undefined` = 这条规则对这类答案不适用 */
  probe: (a: AnswerSet) => number | undefined
  /** true = 「量 >= 门限」时成立（`probLt` / `topLt` 是 false） */
  gte: boolean
}

/**
 * 挂元数据用的键。用 `Symbol.for` 而不是字符串 —— 同 `defineDecision`
 * 的先例：别让它出现在 `JSON.stringify` 里，也别让外部伪造一个同名的键。
 */
const THRESHOLD = Symbol.for('JevLoop.threshold')

/** 给谓词挂上门限元数据。**不改变谓词本身的行为** */
function withThreshold<T extends (a: AnswerSet) => boolean>(fn: T, spec: ThresholdSpec): T {
  Object.defineProperty(fn, THRESHOLD, { value: spec, enumerable: false })
  return fn
}

/**
 * 读回一个谓词的门限。不是带门限的谓词就返回 `undefined`。
 *
 * 没有它，标定台只能自己抄一份门限表 —— 而抄的那份**会和策略漂开**，
 * 于是报告里的 margin 是拿一个已经不生效的门限算的（§8.16 的死配置）。
 */
export function thresholdOf(fn: unknown): ThresholdSpec | undefined {
  if (typeof fn !== 'function') return undefined
  const spec = (fn as unknown as Record<symbol, unknown>)[THRESHOLD]
  return spec && typeof spec === 'object' ? (spec as ThresholdSpec) : undefined
}

/**
 * 一次判定离「翻掉」有多近。
 *
 * `margin = |value - threshold|`，取**已求值过的规则里最小的那一条** ——
 * 也就是这颗硬币离哪条边最近。只算到**决定它的那条规则为止**：后面的规则
 * 根本没被问到，拿它们算 margin 是在报一个没发生过的比较。
 *
 * ★ 它**不需要标准答案**。margin 是「答案 + 策略」的性质，不是「对错」的性质 ——
 *   所以**每一个判定都报得出**，包括标定台判不了的那些（§2 要的正是这个）。
 */
export function closestMargin<A extends AnswerSet>(
  rules: readonly PolicyRule<A>[],
  answers: A,
  upto = rules.length - 1,
): MarginReport | undefined {
  let best: MarginReport | undefined
  for (let i = 0; i <= upto && i < rules.length; i++) {
    const spec = thresholdOf(rules[i]?.when)
    if (!spec) continue
    const value = spec.probe(answers)
    if (value === undefined) continue // 这条规则对这类答案不适用，没有边可贴
    const margin = Math.abs(value - spec.threshold)
    if (!best || margin < best.margin) {
      best = { id: spec.id, kind: spec.kind, threshold: spec.threshold, value, margin }
    }
  }
  return best
}

/**
 * 置信度门限：`when: gte("risky", 0.9)`
 *
 * ⚠️ **不要拿它卡 choice 问题。** Laya 的 `confidence` 是归一化熵
 * （`1 - H(p)/log(k)`，k = 选项个数），不是最大概率：
 *
 *     p = [0.80, 0.20]  →  confidence = 0.269
 *
 * 也就是说同一个阈值在 2 个选项和 20 个选项下含义完全不同 ——
 * 选项越少，要越过同一个门槛需要的概率就越极端。
 * choice 请用下面的 `topGte`。
 */
export const gte = (id: string, threshold: number) => {
  const probe = (a: AnswerSet) => confidenceOf(a[id])
  return withThreshold((a: AnswerSet) => probe(a) >= threshold, {
    kind: 'gte',
    id,
    threshold,
    probe,
    gte: true,
  })
}

/**
 * 选中项的概率门限：`when: topGte("tool", 0.6)`
 *
 * **choice 问题应该用这个。** 它直接可解释（"选中的那个拿到多少概率质量"），
 * 而且和选项个数无关 —— 加一个选项不会改变门槛的含义。
 */
export const topGte = (id: string, threshold: number) => {
  const probe = (a: AnswerSet): number | undefined => {
    const ans = a[id]
    if (!ans) return undefined
    if (ans.type === 'choice') return ans.probabilities?.[ans.choice] ?? 0
    if (ans.type === 'noul') return Math.max(ans.noul, 1 - ans.noul)
    return ans.confidence ?? 0
  }
  return withThreshold((a: AnswerSet) => probe(a) !== undefined && probe(a)! >= threshold, {
    kind: 'topGte',
    id,
    threshold,
    probe,
    gte: true,
  })
}

/** 布尔概率门限：`when: probGte("risky", 0.7)` */
export const probGte = (id: string, threshold: number) => {
  // 只认 noul：对别的答案类型这条规则**永远不成立**，probe 也如实报 undefined，
  // 好让 margin 不去算一条没生效的边
  const probe = (a: AnswerSet): number | undefined => {
    const ans = a[id]
    return ans?.type === 'noul' ? ans.noul : undefined
  }
  return withThreshold((a: AnswerSet) => {
    const v = probe(a)
    return v !== undefined && v >= threshold
  }, { kind: 'probGte', id, threshold, probe, gte: true })
}

/**
 * 布尔概率的「小于」门限。
 *
 * 用在「只有当它**不**成立时才怎样」的规则上，比写 `!probGte(...)` 可读：
 * `when: probLt("ok", 0.5)` 直接读成「不太可能成功」。
 *
 * ⚠️ **它不是 `probGte` 的补集，只在 `noul` 上成立。** 两者对非 `noul` 答案
 * 都返回 `false`（偏保守），所以对 `choice` / `score` 问题，`prob:x < v` 是一条
 * **永远不触发**的规则。这正是 `top < v` 不能用它的原因 —— 见 `topLt`。
 * （`decisiondoc` 侧还应该拒绝把 `prob:` 用在非 noul 问题上，见 REVIEWS-round5。）
 */
export const probLt = (id: string, threshold: number) => {
  const probe = (a: AnswerSet): number | undefined => {
    const ans = a[id]
    return ans?.type === 'noul' ? ans.noul : undefined
  }
  return withThreshold((a: AnswerSet) => {
    const v = probe(a)
    return v !== undefined && v < threshold
  }, { kind: 'probLt', id, threshold, probe, gte: false })
}

/**
 * `topGte` 的**真补集**，对每种答案类型都成立。
 *
 * 为什么需要它：`top < v` 曾经被编译成 `probLt`，而后者只认 `noul`，且对 `noul`
 * 判的是 `p` 而不是 `max(p, 1-p)` —— 于是 `top >= v` 与 `top < v` 在 `p` 偏离 0.5 时
 * **同时为真**（实测 `p=0.05` 两条都真），在 `choice` / `score` 上 `top < v` **恒假**
 * （作者以为写了一道闸门，它一次都不会响）。
 *
 * 定义成 `!topGte(...)` 而不是另写一遍阈值比较：**补集必须从构造上成立**，
 * 靠两处代码各自正确是迟早会分叉的。
 */
export const topLt = (id: string, threshold: number) => {
  const positive = topGte(id, threshold)
  const spec = thresholdOf(positive)!
  // 复用同一个 probe：补集与它读的必须是同一个量，否则 margin 会算在另一条边上
  return withThreshold((a: AnswerSet) => !positive(a), { ...spec, kind: 'topLt', gte: false })
}

/** 分数门限：`when: scoreGte("risk", 2)` */
export const scoreGte = (id: string, threshold: number) => {
  const probe = (a: AnswerSet): number | undefined => {
    const ans = a[id]
    return ans?.type === 'score' ? ans.score : undefined
  }
  return withThreshold((a: AnswerSet) => {
    const v = probe(a)
    return v !== undefined && v >= threshold
  }, { kind: 'scoreGte', id, threshold, probe, gte: true })
}

/** 选了某个选项：`when: picked("tool", "read_file")` */
export const picked =
  (id: string, option: string) =>
  (a: AnswerSet): boolean => {
    const ans = a[id]
    return ans?.type === 'choice' ? ans.choice === option : false
  }

/** 取某个选项的概率（做分级审批时用） */
export function probabilityOf(a: AnswerSet, id: string, option?: string): number {
  const ans = a[id]
  if (!ans) return 0
  if (ans.type === 'noul') return ans.noul
  return option ? (ans.probabilities?.[option] ?? 0) : (ans.confidence ?? 0)
}
