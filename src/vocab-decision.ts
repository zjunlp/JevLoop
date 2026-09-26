/**
 * JevLoop · L0 词汇 —— Decision 的形状
 *
 *     Decision = State 投影 + 类型化问题 + 策略（答案 → 动作）
 *
 * 这里只有**形状**和两个构造/判定助手，没有任何一个具体的判定节点 ——
 * 具体节点是产品主张，住在 L4（`decisions.ts`）。
 *
 * 分开的理由：这一层被 L1-L5 全都引用，而具体节点只该被循环层引用。
 * 合在一起时，`budget.ts`（L1）和 `decisions.ts`（L4）的 import 长得一模一样，
 * 分层就没法用依赖表达（见 DESIGN-layers-2026-09-21.md 的 D1）。
 *
 * @module JevLoop/vocab-decision
 */

import type { AnswerMap, AnswerSet, QuestionSet } from './vocab.ts'

// ═══════════════════════════════════════════════════════════
// Decision —— 唯一的原语
//   Decision = State 投影 + 类型化问题 + 策略（答案 → 动作）
// ═══════════════════════════════════════════════════════════

/**
 * 策略规则：概率 → 动作。
 *
 * 纯代码，不碰模型。所以调阈值不需要重跑任何东西 ——
 * 这是「决策便宜」的第二层含义：不只是调用便宜，改起来也便宜。
 */
export interface PolicyRule<A> {
  /** 省略 = 兜底规则（catch-all），必须放最后 */
  when?: (a: A) => boolean
  action: string
  /** 写清楚为什么。会进 trace，出问题时能一眼看出命中了哪条 */
  reason?: string
}

/**
 * loop 认得的 action 名 —— **封闭集合**。
 *
 * 为什么要有这张表：`resolvePolicy` 返回的 action 是拿给 loop 分派用的，
 * 而一个笔误（`ask_humam`）在运行时**没有任何东西会报错** —— 策略照样命中，
 * 只是得到一个没有消费方能处理的动作。界面那句「N 道授权闸门」也是靠
 * `action === 'ask_human'` 数出来的，写成别名那道闸门就不算数了。
 *
 * 这就是 `act.ts` 对工具名做过的事（`ToolNameOf` 从注册表推出），在 action 上重做一遍。
 *
 * ⚠️ **`PolicyRule.action` 仍然是 `string`，这是有意的。** policy 引擎是通用的
 * ——测试拿 `'a'` / `'ok'` 这种名字就能驱动它。封闭只该在**真实边界**上强制，
 * 也就是解析手写文件的地方（`decisiondoc.interpretBlock`）。
 *
 * `escalate` 是 `resolvePolicy` 在「一条都没命中且没有兜底」时自己产出的，
 * 不写在 `decisions.ts` 里 —— 所以下面的一致性测试只查一个方向
 * （`decisions.ts` 用到的名字必须都在这张表里）。
 */
export const ACTIONS = [
  'answer',
  'ask_human',
  'auto',
  'auto_audit',
  'call',
  'continue',
  'deliver',
  'escalate',
  'finish',
  'keep_going',
  'revise',
  'stop',
  'use',
  'use_tool',
] as const

export type Action = (typeof ACTIONS)[number]

/**
 * 帧制品的**最小词汇**。
 *
 * 完整形状在 `frame.ts`（L3：`FrameSpec` / `compileFrame` / 两种指纹）——
 * 这里只放**L2 的消费方**需要认得出的那几个键。理由和 `isDecision` 一样：
 * 形状声明在词汇层、实现住在更高的层，否则 L2 就得 import L3（§11 不许）。
 *
 * ★ 字段名与 `frame.ts` 的 `Frame` **逐字对应** —— 同名不同义是
 *   §8.16 记的那类最难发现的分歧，所以这里宁可少写几个键，也不改写名字。
 */
export interface FrameArtifact {
  /** 实际进帧的正文（与 `DecisionResult.state` 是同一个对象） */
  state: unknown
  /** 帧正文的指纹：回答「**它看到了什么**」 */
  digest: string
  /** 有界且**截了要报** */
  truncated: readonly { key: string; from: number; to: number }[]
  /** 声明要看，而 ctx 里没有 —— 可能忘了喂 */
  unfilled: readonly { key: string; from: string; why: string }[]
  /** 今天不适用（声明里说清了为什么）—— 与 `unfilled` **必须分开** */
  absent: readonly { key: string; why: string }[]
  /** **故意不看**的 ctx 栏，每条带理由。它随帧进日志 */
  excluded: readonly (readonly [string, string])[]
}

export interface DecisionSpec<Ctx, Q extends QuestionSet = QuestionSet> {
  /** 唯一标识。用「域.动作」的写法 */
  id: string
  describe?: string
  /**
   * State 投影：把 agent 状态压成一段**有界**的决策帧。
   *
   * 这一步决定了判定的上限 —— **帧里没有的东西，模型判不出来**。
   * 而且上下文很短（512/1024 token），所以不能把原始对话塞进去。
   */
  state: (ctx: Ctx) => unknown
  /**
   * 这一份 state 是**怎么编出来的**（§8.14）。
   *
   * 声明了它的节点，帧由 `FrameSpec` 编译，并带上指纹 / 截断记录 / 缺失记录 /
   * 「故意不看什么」。不声明就是手拼的 dict —— 那种帧**没有任何办法被复查**，
   * 而这个项目出过的四次事故全部在帧上。
   *
   * ★ 给了它的时候，`state(ctx)` 必须与 `artifact.state` **逐字相同**：
   *   `decide.ts` 优先用 artifact，别的调用方用 `state`，两者分叉就等于
   *   发出去的帧和记下来的帧不是一份（§8.16 的「同名不同义」）。
   */
  frameArtifact?: (ctx: Ctx) => FrameArtifact
  /** 问题。可以是 ctx 的函数（选项随状态变化时必须这样写） */
  questions: Q | ((ctx: Ctx) => Q)
  policy: PolicyRule<AnswerMap<Q>>[]
  model?: string
}

const DECISION = Symbol.for('JevLoop.decision')

/**
 * 定义一个判定节点。**它只做一件事：盖一个不可枚举的标记。**
 *
 * 标记的作用是让 `isDecision()` 在运行时认得出「这是一个判定」——
 * 因为 `questions` 允许写成 `ctx => Q` 的函数，光看类型分不出来。
 * 标记用 `Symbol.for` 而不是字符串键：别让它在 `JSON.stringify` 里出现，
 * 也别让外部能伪造一个同名的普通对象混进来。
 */
export function defineDecision<Ctx, Q extends QuestionSet>(
  spec: DecisionSpec<Ctx, Q>,
): DecisionSpec<Ctx, Q> {
  Object.defineProperty(spec, DECISION, { value: true, enumerable: false })
  return spec
}

/**
 * 用 Symbol 标记而不是鸭子类型判断（"看起来像决策节点就是"）——
 * 后者太脆：一个恰好有 id/questions 的对象会被误收。
 */
export function isDecision(v: unknown): boolean {
  return !!v && typeof v === 'object' && (v as Record<symbol, unknown>)[DECISION] === true
}

/** 一次判定的完整结果 */
export interface DecisionResult<A = AnswerSet> {
  id: string
  step: number
  /** 实际发给模型的 state 帧（投影后） */
  state: unknown
  questions: QuestionSet
  answers: A
  action: string
  reason: string
  latencyMs: number
  provider: string
  model?: string
  degraded: boolean
  /**
   * 后端自己报的问题：缺了哪几个答案、丢了哪几个、它那边的警告。
   *
   * ★ **`degraded: true` 必须能查到为什么。** 这份清单本来被算了、也被
   *   收进了一个局部变量，然后**没有任何消费者** —— 实测某个会话的每一次
   *   判定都是 `degraded: true`，而轨迹、日志、事件里都没说缺了什么，
   *   排查只能靠手工再发一次请求（§8.10）。
   */
  warnings?: string[]
  /**
   * 这一帧是怎么编出来的（§8.14）。**声明了帧的节点才有。**
   *
   * ★ 它回答「它看到了什么」；「它被问了什么」要看 `requestDigest`。
   *   两个问题以前共用一个串，而差别正好骗过这个项目一次（§8.17）。
   */
  frame?: FrameArtifact
  /**
   * **请求**的指纹：帧 + 问题 + 选项（§8.17 更正的那一条）。
   *
   * 只比 `frame.digest` 会漏掉「换掉候选集」那一类 —— 帧一动不动、答案却翻了。
   */
  requestDigest?: string
  /** true = 无人接住，该走兜底路径了 */
  escalate: boolean
}
