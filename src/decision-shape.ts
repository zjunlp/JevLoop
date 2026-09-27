/**
 * JevLoop · DECISION.md 的**形状**
 *
 * 从 `decisiondoc.ts` 切出来 —— 那个文件当时还剩「形状 + 解析」，而**形状可以独立**：
 * 它只描述 `DocBlock` 这一族类型，不认识 Markdown、也不认识策略。
 * 独立之后解析段更纯，而且形状成了 L0 的公共词汇，谁都能引用。
 *
 * **与 `decision-compile.ts` 的区别**：那边不能靠 re-export 兼容，
 * 因为它是 L2、`decisiondoc.ts` 是 L0（L0 不能 import L2）；这里两边都是 L0，
 * 所以 `decisiondoc.ts` **可以** re-export 本文件，消费方一行都不用改。
 *
 * @module JevLoop/decision-shape
 */

// ═══════════════════════════════════════════════════════════
// 形状
// ═══════════════════════════════════════════════════════════

/**
 * `choice` / `noul` / `score` 是单问题的判定，`mixed` 是一个判定问
 * 多件事（实测 `gradeRisk` 同时问危险度和是否需要授权），`rule` 是
 * 代码答的。
 */
export const KINDS = ['choice', 'noul', 'score', 'mixed', 'rule'] as const
export type BlockKind = (typeof KINDS)[number]

/** 问题的原语类型。由选项**写法**推出来，不靠声明 */
export type Primitive = 'choice' | 'noul' | 'score'

export interface DocOption {
  /** 选项 id。会原样进 `criteria` 的键，所以它就是对模型说的话 */
  name: string
  /** 什么情况下选它。这一栏决定判定质量 —— 帧里没有的，模型判不出来 */
  criteria: string
}

export interface DocQuestion {
  /** 问题 id。`prob:<id>` / `score:<id>` / `picked:<id>=..` 指的就是它 */
  id: string
  type: Primitive
  ask: string
  options: DocOption[]
  /** 起始行号（1-based），用于报错定位 */
  line: number
}

export interface DocPolicyRule {
  /** 谓词原文，如 `top >= 0.6`；兜底规则是 `else` */
  when: string
  action: string
}

/**
 * `frame:` 里的一行 —— **这个判定看这一格**。
 *
 * ★ `project` 是一张**代码里注册的封闭表**里的名字（`frame-fields`）。文件里
 *   写不出函数，所以派生值（把 `history` 压成一句话这种）只能点名。
 *   好处是**它读哪一格由代码说了算** —— 文件没法声称自己读的是别处。
 */
/**
 * **判定住在循环的哪一步** —— 一个**封闭集合**，而 `when:` 现在必须点名其中一个。
 *
 * ★★ 它把「加一个判定只改文件」这句话的**边界**变成了可检查的东西。
 *
 * 循环在每个位置的分支是硬编码的（`need.action === 'answer'`、`risk.action === 'ask_human'`…）——
 * 因为一个动作**在这个位置意味着什么，只有那个位置的代码知道**。所以：
 *
 *     **一个新判定，如果它产出的动作是那个位置已经在处理的，就只改文件；**
 *     **否则你必须给那个位置加一个分支 —— 而解析器会在你写文件的时候就告诉你。**
 *
 * ⇒ 这句话从前是一个**承诺**，现在是一条**解析期检查**。没有它，加进去的判定会
 *   被问到、会被记进轨迹、策略也会命中 —— 而**没有任何东西按它的动作做事**。
 *   那正是 §8.16 记的「`auto_audit` 以前和 `auto` 完全一样，只多打一行 trace」。
 *
 * `escalate` 不列在里面：它在每个位置都合法（交回上层是通用的兜底出口）。
 */
export const POSITIONS: Record<string, { actions: string[]; about: string }> = {
  'step-start': {
    actions: ['use_tool', 'answer'],
    about: '每个 step 的开头 —— 判「还要不要动手」，判否就直接跳到生成、省掉整个工具循环',
  },
  'tool-choice': { actions: ['call'], about: '决定动手之后 —— 判「调哪个工具」' },
  'input-choice': { actions: ['use'], about: '选定的工具需要参数时 —— 判「调哪个文件」' },
  'before-call': {
    actions: ['auto', 'auto_audit', 'ask_human'],
    about: '真正调用工具之前 —— 分级审批，**硬闸门在这一格**',
  },
  'after-tool': {
    actions: ['continue', 'stop', 'finish', 'keep_going'],
    about: '工具执行之后 —— 判「这一步成没成」与「整个任务完没完」',
  },
  'after-generate': {
    actions: ['deliver', 'revise'],
    about: '生成之后、交出去之前 —— 交付闸门，判的对象是刚生成的那份草稿',
  },
}

/** `escalate` 在任何位置都合法：那是交回上层的通用出口 */
export const ANY_POSITION_ACTIONS = ['escalate']

export interface DocFrameField {
  /** 帧里这一栏叫什么 */
  key: string
  /** 这一栏的界：字符串按字符、列表按项数。**必须写** */
  bound: number
  /** 派生投影的名字。不给就是 `ctx[from]` 原样 */
  project?: string
  /** 为什么这一栏在这个判定里。**必填** */
  why: string
  line: number
}

/** `frame:` 里的一行 —— **这个判定故意不看这一格**。理由必填 */
export interface DocFrameExclusion {
  field: string
  why: string
  line: number
}

export interface DocFrame {
  fields: DocFrameField[]
  excluded: DocFrameExclusion[]
}

export interface DocBlock {
  id: string
  kind: BlockKind
  /** 什么时候问。散文，只给人读 */
  when: string
  /**
   * 候选是每步算出来的，不是这份文件里列的。
   *
   * 选项必须每步重建（docs/CODE-STYLE.md §8.4）—— 固定的候选会让模型去选一个已经
   * 不适用的动作。有这一项时，文件里列的选项只是**默认全集或示例**，
   * 校验也不再要求至少两个。
   */
  dynamic: string
  /**
   * **这个判定看什么、故意不看什么。**
   *
   * ★ 它以前只住在 `src/decisions.ts` 的 `FrameSpec` 里，于是「把判定声明在
   *   文件里」这句话只对**问题**成立，对**帧**不成立 —— 而四次事故全在帧上。
   *   搬进来之后，问什么和看什么住在同一处了。
   *
   * `null` = 这个块没写 `frame:`，消费方回退到代码里的那份（迁移可以逐个做）。
   */
  frame: DocFrame | null
  questions: DocQuestion[]
  policy: DocPolicyRule[]
  /** 为什么这么设计。最该写的一段，也是这个文件作为文档的价值所在 */
  rationale: string
  /** 起始行号（1-based），用于报错定位 */
  line: number
}

export interface DocProblem {
  line: number
  message: string
}

export interface DecisionDoc {
  title: string
  /** 第一个 `##` 之前的散文 */
  intro: string
  blocks: DocBlock[]
  /** `## generator` 那一段，原样进 system prompt */
  generatorSection: string
  problems: DocProblem[]
  source: string
}

/** 它是不是一道授权闸门 —— 从策略里推，不要人声明 */
export function isGate(block: DocBlock): boolean {
  return block.policy.some((r) => r.action === 'ask_human')
}

/** 头条数字：这个 agent 有几个判定点、几个问题，其中几个要模型 */
export interface DocSummary {
  blocks: number
  byKind: Record<BlockKind, number>
  questions: number
  byPrimitive: Record<Primitive, number>
  /** 要过判定模型的判定点（非 rule） */
  modelDecisions: number
  /** 纯代码的判定点（rule） */
  codeDecisions: number
  /** 授权闸门 —— 从 policy 推出来的 */
  gates: number
  options: number
}
