/**
 * JevLoop · 完成闸门对照实验：四条臂（纯逻辑，无 IO、无 console）
 *
 * ══════════════════════════════════════════════════════════════
 *  **这个文件是「机制」，不是「报告」。**
 * ══════════════════════════════════════════════════════════════
 *
 * 拆出来的理由有两个，第二个更要紧：
 *
 *   ① `bench/gate-compare.ts` 是命令行入口，它在模块顶层 `await main()` ——
 *      于是**不能被 import**（一 import 就整轮跑起来）。测试要能直接调这些臂。
 *   ② 结论要能被**钉住**。这一轮的读数（契约门在参考实现里的行为与「没写守卫的
 *      手写门」逐格相同）如果只是打印出来，下次谁改了 `frame.ts` 的处置方式，
 *      报告会**静静地变成假的**。钉成测试之后，它变的是断言，不是文档。
 *
 * ── 四条臂 ──────────────────────────────────────────────────────
 *
 *     contract        契约门，照**参考实现真实的行为**：帧由 `frameArtifact` 编，
 *                     缺格记进 `unfilled`，然后**没人读它**，策略照跑
 *     contract-strict 同上 + `unfilled` 非空即拒绝（codex 适配器的纪律）
 *     ifelse-best     手写门，带「宿主没给证据」的守卫 —— **公平的那个对手**
 *     ifelse-naive    手写门，没写守卫
 *
 * ★ 策略层在四条臂里**逐字相同**（`unsupported >= 0.5 → revise`；
 *   `deliverable >= 0.6 → deliver`）。这是刻意的：策略层可以机械地翻译成
 *   if/else，所以任何「契约判得更准」的读数都只可能来自帧，不来自策略。
 *   如果这里让两臂的门限写得不一样，测出来的差异就没有意义了。
 *
 * @module JevLoop/gate-arms
 */

import { buildDecisions } from '../src/decisions.ts'
import { resolvePolicy } from '../src/policy.ts'
import type { AgentCtx } from '../src/frame.ts'
import type { AnswerSet, AnswerMap, NoulQuestion } from '../src/vocab.ts'
import type { FrameArtifact } from '../src/vocab-decision.ts'
import type { GateScenario } from './gate-scenarios.ts'
import type { ScenarioCtx } from './gate-drift.ts'

/** 一条臂一次运行给出的东西 */
export interface RunResult {
  outcome: 'deliver' | 'revise' | 'refuse' | 'error'
  why: string
  /** 这条臂**说出**了哪些格子的异常。空数组 = 它一个字都没说 */
  noticed: string[]
}

/** 相对 oracle 的记账。`refused` 单独计 —— 它不是「判错」，是「不判」 */
export type VerdictKind = 'ok' | 'false-accept' | 'false-reject' | 'refused' | 'error'

/** 全部记账类别，报告的顺序 */
export const KINDS: VerdictKind[] = ['ok', 'false-accept', 'false-reject', 'refused', 'error']

/**
 * 判据机 —— 读帧的确定性函数，四条臂共用。
 *
 * ★ **它只看得见传进来的那份 `evidence`。** 证据空了、成了数组、换成了别的东西，
 *   它就跟着给出不同的答案 —— 这正是「帧坏了，判定跟着坏」的真实路径。如果它
 *   绕开帧去读场景真值，这个实验就变成了在测脚本作者写对了没有。
 *
 * ★ `answer` / `evidence` 都收 `unknown` 并**对称地**做 `String()`。
 *   不对称会很隐蔽地替某一臂说话：一边崩、一边静默继续，读数就变成了
 *   「谁先把类型写对」，而不是「两种机制在漂移下各自做了什么」。
 *
 * ⚠️ 字面包含是**代理**，不是语义。真正的语义判据是第二臂（手写 LLM 门）。
 */
export function judge(
  claims: readonly { keyword: string }[],
  answer: unknown,
  evidence: unknown,
): AnswerSet {
  // 正常消费者会把它当字符串读（投影声明的 `returns` 就是 `string`）——
  // 类型漂移**不会抛**，它只会静默地改变结果。
  const hay = typeof evidence === 'string' ? evidence : String(evidence)
  const said = typeof answer === 'string' ? answer : String(answer)
  const missing = claims.filter((c) => !hay.includes(c.keyword))
  // 回答为空 = 没有可核对的主张。★ 单独一类，不该算作「有证据支持」
  const emptyAnswer = said.trim() === ''
  const unsupported = missing.length > 0 || emptyAnswer ? 0.9 : 0.1
  const deliverable = unsupported > 0.5 ? 0.1 : 0.9
  return {
    unsupported: { type: 'noul', noul: unsupported },
    deliverable: { type: 'noul', noul: deliverable },
  }
}

/** 帧里那些「宿主没喂 / 没投影出来 / 被截断」的格子 —— 契约**记下来了** */
export function frameSignals(frame: FrameArtifact): string[] {
  const out: string[] = []
  for (const u of frame.unfilled) out.push(`unfilled:${u.key}`)
  for (const a of frame.absent) out.push(`absent:${a.key}`)
  for (const t of frame.truncated) out.push(`truncated:${t.key}`)
  return out
}

/**
 * 契约门。
 *
 * @param strict `true` 时 `unfilled` 非空即拒绝 —— 那是 **codex 适配器**的纪律
 *   （`adapters/codex/core.ts`），**不是**参考实现的行为。默认 `false` 才是
 *   「契约本身在漂移下会做什么」。
 */
export function contractArm(scenario: GateScenario, ctx: ScenarioCtx, strict: boolean): RunResult {
  const spec = buildDecisions().canDeliver
  const artifact = spec.frameArtifact
  if (!artifact) return { outcome: 'error', why: 'canDeliver 没有 frameArtifact', noticed: [] }

  let frame: FrameArtifact
  try {
    frame = artifact(ctx as AgentCtx)
  } catch (err) {
    return { outcome: 'error', why: `编帧抛了：${(err as Error).message}`, noticed: [] }
  }

  const noticed = frameSignals(frame)

  if (strict && frame.unfilled.length > 0) {
    return {
      outcome: 'refuse',
      why: `缺 state 格：${frame.unfilled.map((u) => u.key).join(', ')}`,
      noticed,
    }
  }

  const st = frame.state as { answer: string; evidence: string }
  const answers = judge(scenario.claims, st.answer, st.evidence)
  // `answers` 是本文件手工造的 AnswerSet，而策略是按 can_deliver 那两个问题编译出来的 ——
  // 形状对得上，类型对不上。这里显式收窄，而不是把策略放宽（放宽会让别的调用点失去检查）。
  const out = resolvePolicy(
    spec.policy,
    answers as AnswerMap<{ deliverable: NoulQuestion; unsupported: NoulQuestion }>,
  )
  return { outcome: out.action as RunResult['outcome'], why: out.reason, noticed }
}

/**
 * 手写门 —— **它自己**从原始 ctx 里取证据，不经过帧。
 *
 * ★ 这正是手写门与契约门真正的分界：契约的格子在 `DECISION.md` 里**声明**，
 *   手写门的格子在**代码里写死**。所以前者能自动多出一格，后者不会。
 *
 * @param guarded `true` = 最佳实践（含「宿主没给历史」的守卫），`false` = 没写守卫
 */
export function ifElseArm(scenario: GateScenario, ctx: ScenarioCtx, guarded: boolean): RunResult {
  const noticed: string[] = []

  const history = ctx.history
  if (history === undefined) noticed.push('unfilled:history')
  else if (history.length === 0) noticed.push('empty:history')

  if (guarded && ctx.draft === undefined) noticed.push('unfilled:draft')

  if (guarded && noticed.some((n) => n.startsWith('unfilled:'))) {
    // 最佳实践：知道自己要证据，而宿主没给 ⇒ 拒绝，别猜
    return { outcome: 'refuse', why: `手写守卫：${noticed.join(', ')}`, noticed }
  }

  const evidence = (history ?? []).map((s) => `${s.tool}(${s.input}) → ${s.result}`).join('\n')
  const answers = judge(scenario.claims, ctx.draft ?? '', evidence)
  const unsupported = (answers.unsupported as { noul: number }).noul
  const deliverable = (answers.deliverable as { noul: number }).noul
  // ── 策略：**逐字照抄** DECISION.md 的三条规则 ──
  const action = unsupported >= 0.5 ? 'revise' : deliverable >= 0.6 ? 'deliver' : 'revise'
  return { outcome: action, why: '手写 if/else（门限与契约一致）', noticed }
}

/** 一条臂：id + 说明 + 怎么跑 */
export interface Arm {
  id: string
  label: string
  run: (scenario: GateScenario, ctx: ScenarioCtx) => RunResult
}

/** 四条臂，顺序即报告顺序 */
export const ARMS: Arm[] = [
  {
    id: 'contract',
    label: '契约门（照参考实现的真实行为：记录缺格，但不处置）',
    run: (s, c) => contractArm(s, c, false),
  },
  {
    id: 'contract-strict',
    label: '契约门 + 缺格拒绝（codex 适配器的纪律）',
    run: (s, c) => contractArm(s, c, true),
  },
  { id: 'ifelse-best', label: '手写门（最佳实践：带守卫）', run: (s, c) => ifElseArm(s, c, true) },
  { id: 'ifelse-naive', label: '手写门（没写守卫）', run: (s, c) => ifElseArm(s, c, false) },
]

/** 把一次运行结果相对 oracle 分类 */
export function classify(result: RunResult, expected: GateScenario['expected']): VerdictKind {
  if (result.outcome === 'error') return 'error'
  if (result.outcome === 'refuse') return 'refused'
  if (result.outcome === expected) return 'ok'
  return expected === 'revise' ? 'false-accept' : 'false-reject'
}

/**
 * 跑一条臂，**不让它把整轮带走**。
 *
 * ★ 一条臂抛异常也是一种结果。不接住的话，「谁先在类型上崩掉」会表现为
 *   「那个台子跑不出来」，读数就丢了一格。
 */
export function runArm(arm: Arm, scenario: GateScenario, ctx: ScenarioCtx): RunResult {
  try {
    return arm.run(scenario, ctx)
  } catch (err) {
    return { outcome: 'error', why: (err as Error).message, noticed: [] }
  }
}
