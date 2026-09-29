/**
 * JevLoop · 完成闸门对照实验：宿主漂移集
 *
 * ══════════════════════════════════════════════════════════════
 *  **扰动作用在原始 ctx 上，不作用在帧上。**
 * ══════════════════════════════════════════════════════════════
 *
 * 这一点是刻意的：帧由**真实投影**编出来（`src/frame.ts` + `frame-projections.ts`），
 * 所以「这一扰动让契约看到什么」是跑出来的，不是写出来的。手工把帧改成残缺的
 * 再喂进去，测的就成了「残缺帧会不会被拒绝」—— 那是个平凡问题，而且答案早写在
 * 缺失格的拒绝逻辑里。
 *
 * ── 扰动从哪来（★ 这一栏决定实验是不是自说自话）────────────────
 *
 * **每一条都有出处，没有一条是「为了弄坏 if/else 而造」的。** 前四条来自这个
 * 项目真实发生过的两次事故与一次已修 bug；第五条是**反向对照**。
 *
 * 一个实验如果先想好「契约赢」，再回头设计能让它赢的扰动，那它测的是作者的
 * 立场。所以这里的规矩是：**扰动只许从已记录的故障里取**，取不到就不编。
 *
 * @module JevLoop/gate-drift
 */

import type { StepRecord } from '../src/frame.ts'
import type { ScenarioCtx } from './gate-scenarios.ts'

/** 一个场景的原始 ctx —— 与 `gate-scenarios.ts` 里的 `ScenarioCtx` 是同一个类型 */
export type { ScenarioCtx }

/** 扰动**预期**造成哪种形状的漂移。★ 这是预测，不是断言 —— 跑出来要对账 */
export type DriftShape =
  | 'none'
  | 'cell-absent'
  | 'cell-empty'
  | 'cell-wrong-type'
  | 'cell-wrong-value'
  | 'irrelevant'

/** 一次扰动：把原始 ctx 换成一个「宿主没给全」的 ctx */
export interface Perturbation {
  id: string
  what: string
  /** 这条扰动的出处。**必须是真的发生过或已被写下的事** */
  from: string
  /** 预期形状 —— 跑完要和实测对账，对不上就是理解错了 */
  expect: DriftShape
  apply: (ctx: ScenarioCtx) => ScenarioCtx
}

/** 一个与本次任务无关的历史 —— 「格式对、内容错」用 */
const UNRELATED_HISTORY: StepRecord[] = [
  {
    step: 0,
    tool: 'list_dir',
    input: '.',
    result: 'notes.md\nREADME.md\npackage.json',
  },
]

/** 全部扰动。顺序即报告顺序：先基线，再真实漂移，最后反向对照 */
export const PERTURBATIONS: Perturbation[] = [
  {
    id: 'P0-none',
    what: '基线：宿主完全按约定提供',
    from: '对照组的起点。没有它，后面所有差异都无法归因',
    expect: 'none',
    apply: (ctx) => ctx,
  },
  {
    id: 'P1-history-absent',
    what: '`history` 这一格**整个不存在**（键被删掉）',
    from:
      '实测：codex 适配器首跑时 `base_risk` 就是这样消失的 —— 风险表按模型面名字建索引，hook 给的是 canonical 名，查表落空，那一栏**整个不进帧**（见 `frame-projections.ts` 的 `localToolRisk` 注释）',
    expect: 'cell-absent',
    apply: ({ history: _drop, ...rest }) => rest as ScenarioCtx,
  },
  {
    id: 'P2-history-empty',
    what: '`history` 存在但是**空数组**',
    from:
      '实测：codex 的 transcript 读不到时（读不到文件 / 找不到用户消息）就是这条路 —— 键在、值为空。★ 它与 P1 必须分开：`undefined` 和 `[]` 在 JS 里是两种东西，**而拒绝逻辑未必对两者一视同仁**',
    expect: 'cell-empty',
    apply: (ctx) => ({ ...ctx, history: [] }),
  },
  {
    id: 'P3a-result-array',
    what: '步骤的 `result` 是**数组**而不是字符串（原始 ctx 层面）',
    from:
      '真实 bug（已修）：`canDeliver` 的 `evidence` 投影返回的是**数组**，所以 `chars: 600` 那个界从来没生效过。codex 的 `FunctionCallOutputBody` 也是 untagged 的（字符串**或**内容项数组），所以这不是假想',
    expect: 'cell-wrong-type',
    apply: (ctx) => ({
      ...ctx,
      history: (ctx.history ?? []).map((s) => ({ ...s, result: [s.result] as unknown as string })),
    }),
  },
  {
    id: 'P3b-draft-array',
    what: '回答本身是**数组**（原始 ctx 层面）—— ★ 这一条才真的进到帧里',
    from:
      '实测（`frame.ts:390-396`）：数组按**元素个数**过 `listMax`，不报错、不拼成字符串，**原样进帧**。所以 `P3a` 被投影吸收了（实测两臂都没有任何变化），而这一条不会 —— 同一类漂移、两个注入点，结果完全不同，所以必须分开测',
    expect: 'cell-wrong-type',
    apply: (ctx) => ({ ...ctx, draft: [ctx.draft ?? ''] as unknown as string }),
  },
  {
    id: 'P4-unrelated-history',
    what: '历史**格式完全正常**，但内容与本次任务无关',
    from:
      '实测：codex 首跑时 `task` 读成了 `<environment_context>`（cwd / shell / 日期）—— 格式完美、内容完全错。这是契约**结构上拦不住**的那一类，必须留在实验里',
    expect: 'cell-wrong-value',
    apply: (ctx) => ({ ...ctx, history: UNRELATED_HISTORY }),
  },
  {
    id: 'P5-irrelevant-control',
    what: '★ 反向对照：只改动帧**明确排除**的格子',
    from:
      '★ 这一条是给实验本身当阴性对照的。它改的是 `can_deliver` 帧里 `- cwd` / `- files` / `- canWrite` / `- earlier` 排除掉的东西：**任何一臂在这里出现差异，都说明差异不是来自「契约的界」，而是别的东西漏进来了**。没有这条对照，后面测出的每一处不同都可以被怀疑是扰动本身把 if/else 弄坏了',
    expect: 'irrelevant',
    apply: (ctx) => ({
      ...ctx,
      files: ['alpha.ts', 'beta.ts', 'notes.md'],
      canWrite: true,
      earlier: '上一轮：这个仓库里有哪些文件？',
    }) as ScenarioCtx,
  },
]
