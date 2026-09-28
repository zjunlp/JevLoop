/**
 * JevLoop · **动作语义** —— 每个 action 到底意味着什么
 *
 * ══════════════════════════════════════════════════════════════
 *  为什么需要它：这 14 个名字的含义，此前**只活在 `agent.ts` 的 if 分支里**
 * ══════════════════════════════════════════════════════════════
 *
 * `DECISION.md` 能声明「在哪个位置可以产出哪些动作」（`POSITIONS`），但**说不出
 * 产出之后要做什么**。于是第二个实现者只能去读我们的 loop —— 而「照抄我们的
 * 循环」正是可移植契约要消灭的东西。这是 TODO §12 的第一条。
 *
 * ── 为什么单独一个文件 ────────────────────────────────────────
 *
 * 从 `vocab-decision.ts` 拆出来：那个文件是「一问一答」的词汇表 + 决策规格的
 * 形状，而「一个动作被产出之后宿主该做什么」是**另一件事**。塞在一起之后它涨到
 * 397 行，`npm run check` 的 file-focus 当场报了出来。
 *
 * ── 两条约束 ──────────────────────────────────────────────────
 *
 * ★ **这张表是描述，不是执行器。** `agent.ts` 仍然用 if 分支实现这些语义，
 *   理由见 `POSITIONS` 那段说明：一个动作**在这个位置**意味着什么，只有那个
 *   位置的代码知道。
 *
 * ★ 所以表必须**被对着代码校验**，而不是让代码去读表。
 *   `tests/action-semantics.test.ts` 对每条动作真的驱动一遍 loop，断言实际
 *   发生的和这里声明的一致 —— 一张没人核对的语义表就是又一份会撒谎的声明。
 *
 * ★ 三个字段之所以分开，是因为它们**确实会分开**，混成一个 `terminal` 会撒谎：
 *
 *     `endsLoop`        工具循环在这里结束吗
 *     `moreModelCalls`  之后这次运行**还有模型调用**吗
 *
 *   实测反直觉的那一档：`stop`（这一步没成）**结束工具循环，但运行没有结束** ——
 *   后面仍然会生成一份如实报告。合成一个布尔值，外部实现者会以为「stop = 完事了」，
 *   然后漏掉那次生成。
 *
 * @module JevLoop/action-semantics
 */

import type { Action } from './vocab-decision.ts'

/**
 * 一个动作的语义。字段是**机器读的**；`about` 是给人读的。
 *
 * 外部宿主照 `next` 写一个 switch 就能把动作接上，不必知道我们的循环长什么样。
 */
export interface ActionSemantics {
  /**
   * 宿主接下来走哪个分支。**封闭集合**，一个取值对应一个分支。
   *
   *     pick_tool   接着问「用哪个工具」
   *     pick_input  接着问「用哪个参数」
   *     run_tool    去执行工具
   *     human       去问人（批准与否决定后续）
   *     next_step   开下一步
   *     generate    跳出工具循环，去生成
   *     regenerate  重新生成一次
   *     end         这次运行到此结束
   */
  next: 'pick_tool' | 'pick_input' | 'run_tool' | 'human' | 'next_step' | 'generate' | 'regenerate' | 'end'
  /** 工具循环是否在这里结束 */
  endsLoop: boolean
  /** 这之后这次运行**还有**模型调用吗（生成也是模型调用） */
  moreModelCalls: boolean
  /** 它成不成立**要靠证据**核对（交付闸门那一类） */
  needsEvidence: boolean
  /** 允许重试几次。`0` = 不许重试 */
  retries: number
  /** 一句话：这个动作意味着什么。给人读的 */
  about: string
}

/**
 * 每个动作的语义 —— 封闭表的另一半（另一半是 `ACTIONS` 本身）。
 *
 * ★ 键必须和 `ACTIONS` **一一对应**，由 `tests/action-semantics.test.ts` 钉住：
 *   加一个动作而忘了写语义，或者写了一个不存在的动作，都会红。
 */
export const ACTION_SEMANTICS: Record<Action, ActionSemantics> = {
  use_tool: {
    next: 'pick_tool',
    endsLoop: false,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '这一步需要动手 —— 接着问「用哪个工具」',
  },
  answer: {
    next: 'generate',
    endsLoop: true,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '不需要动手 —— 跳出工具循环，直接去生成。**运行没结束**',
  },
  call: {
    next: 'run_tool',
    endsLoop: false,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '调这个工具（已经过授权门）',
  },
  use: {
    next: 'run_tool',
    endsLoop: false,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '用这个输入去调 —— 参数是一次判定，不是写死的代码',
  },
  auto: {
    next: 'run_tool',
    endsLoop: false,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '风险可接受 —— 直接执行',
  },
  auto_audit: {
    next: 'run_tool',
    endsLoop: false,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '执行，并**留下一条审计**。说了留痕就必须真的留',
  },
  ask_human: {
    next: 'human',
    endsLoop: true,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '必须人来批。**拒绝（或没有授权钩子）就停**；批准之后按 `auto` 继续',
  },
  continue: {
    next: 'next_step',
    endsLoop: false,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '这一步成了 —— 接着问「整个任务完没完」',
  },
  stop: {
    next: 'generate',
    endsLoop: true,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '这一步没成 —— 停手。★ **运行没结束**：后面仍然生成一份如实报告',
  },
  finish: {
    next: 'generate',
    endsLoop: true,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '任务做完了 —— 跳出工具循环去生成。**运行没结束**',
  },
  keep_going: {
    next: 'next_step',
    endsLoop: false,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about: '还没完 —— 开下一步',
  },
  deliver: {
    next: 'end',
    endsLoop: true,
    moreModelCalls: false,
    needsEvidence: true,
    retries: 0,
    about: '这份回答可以交付 —— **运行在这里结束**，把它返回',
  },
  revise: {
    next: 'regenerate',
    endsLoop: true,
    moreModelCalls: true,
    needsEvidence: true,
    retries: 1,
    about: '回答不合格 —— **重新生成一次**（只有一次），再问一遍；再不合格就停',
  },
  escalate: {
    next: 'end',
    endsLoop: true,
    moreModelCalls: true,
    needsEvidence: false,
    retries: 0,
    about:
      '判不出来 —— 停，交回上层。**任何位置都合法**（`ANY_POSITION_ACTIONS`）。' +
      '★ 运行没结束：仍然生成一份如实报告',
  },
}
