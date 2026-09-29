/**
 * JevLoop · 完成闸门对照实验：报告
 *
 *   node --experimental-strip-types bench/gate-compare.ts
 *
 * ══════════════════════════════════════════════════════════════
 *  **它回答哪一句话，以及它不能回答哪一句话。**
 * ══════════════════════════════════════════════════════════════
 *
 * 定位文档（`docs/POSITIONING-spec-vs-hook.md`）把 falsification 条件写成了：
 *
 *     拿一个用 if/else 写成的完成闸门，和一个由决策契约驱动的同一道闸门比。
 *     如果 **unsupported completion** 上两者没有可测的差异，契约的价值就塌缩成
 *     「一种更好看的写法」。
 *
 * 这个台子就去测它。结论与两个**失败的扰动**写在
 * `docs/MEASUREMENT-gate-equivalence.md`；机制与四条臂在 `bench/gate-arms.ts`，
 * 用例与 oracle 在 `bench/gate-scenarios.ts`，漂移在 `bench/gate-drift.ts`。
 *
 * ── 它测不了什么 ────────────────────────────────────────────────
 *
 * 判据机是**字面包含**（见 `gate-scenarios.ts` 的 `Claim`），所以这里的
 * 「unsupported」是代理，不是语义。真正的语义判据是第二臂（手写 LLM 门），
 * 那需要真判定后端，不在这一轮。**不要把这份报告读成「闸门准不准」** ——
 * 它读的是「同一份判据下，两种机制在宿主漂移时各自做了什么」。
 *
 * @module JevLoop/gate-compare
 */

import { buildDecisions } from '../src/decisions.ts'
import type { AgentCtx } from '../src/frame.ts'
import { SCENARIOS } from './gate-scenarios.ts'
import { PERTURBATIONS, type ScenarioCtx } from './gate-drift.ts'
import { ARMS, KINDS, classify, runArm, type VerdictKind } from './gate-arms.ts'

/** 扰动**实际**把 ctx 弄成了什么样 —— 与 `expect` 对账，不靠猜 */
function observedShape(ctx: ScenarioCtx): string {
  const parts: string[] = []
  if (ctx.history === undefined) parts.push('history 键不存在')
  else if (ctx.history.length === 0) parts.push('history 为空数组')
  else if (ctx.history.some((s) => typeof s.result !== 'string')) parts.push('history.result 不是字符串')
  else parts.push('history 正常')
  if (typeof ctx.draft !== 'string') parts.push(`draft 是 ${typeof ctx.draft}`)
  return parts.join(' / ')
}

/**
 * ★ 目击证词：契约门**实际编出来的那一格**是什么类型，以及它**说了什么**。
 *
 * 这一栏是为 P3 那两条加的：它们**没能改变任何一条臂的判定**，所以单看判定矩阵
 * 会读成「这个扰动什么都没发生」。事实上帧里那一格已经不是它声明的 `string`，
 * 而 `unfilled` / `absent` / `truncated` **没有一个会说这件事**。
 * 判定没变不代表帧没坏，这两件事必须分开报。
 */
function frameWitness(ctx: ScenarioCtx): string {
  const artifact = buildDecisions().canDeliver.frameArtifact
  if (!artifact) return '(没有 frameArtifact)'
  try {
    const f = artifact(ctx as AgentCtx)
    const t = (v: unknown) => (Array.isArray(v) ? `数组(${v.length})` : typeof v)
    return `answer=${t(f.state.answer)} evidence=${t(f.state.evidence)} unfilled=[${f.unfilled.map((u) => u.key).join(',')}] absent=[${f.absent.map((a) => a.key).join(',')}]`
  } catch (err) {
    return `编帧抛了：${(err as Error).message}`
  }
}

async function main(): Promise<void> {
  const rows: {
    scenario: string
    perturbation: string
    arm: string
    observed: string
    kind: VerdictKind
    outcome: string
  }[] = []

  for (const pert of PERTURBATIONS) {
    for (const scenario of SCENARIOS) {
      const ctx = pert.apply(scenario.ctx)
      for (const arm of ARMS) {
        const result = runArm(arm, scenario, ctx)
        rows.push({
          scenario: scenario.id,
          perturbation: pert.id,
          arm: arm.id,
          observed: observedShape(ctx),
          kind: classify(result, scenario.expected),
          outcome: result.outcome,
        })
      }
    }
  }

  // ── 表一：每个扰动一张 场景 × 臂 的矩阵 ──
  //
  // ★ 为什么要有明细而不是只给汇总：汇总里的「假接受 0」很容易被读成「很安全」。
  //   明细才看得出**它是怎么得到 0 的** —— P1 下契约门那 0 其实是「证据一空，
  //   所有主张都不被支持，于是把每一份回答都打回」，那不是变准了，是闸门停摆了。
  //   只报汇总等于把「全部拒绝」装成满分。
  const SYM: Record<VerdictKind, string> = {
    ok: '✓',
    'false-accept': '假受',
    'false-reject': '假拒',
    refused: '拒绝',
    error: '崩',
  }
  console.log('\n每个扰动一张明细（行 = 场景，列 = 臂；✓ 表示与 oracle 一致）\n')
  for (const pert of PERTURBATIONS) {
    console.log(`── ${pert.id}　${pert.what}`)
    console.log(`   ${'场景'.padEnd(26)}${ARMS.map((a) => a.id.padEnd(16)).join('')}oracle`)
    for (const s of SCENARIOS) {
      const cells = ARMS.map((a) => {
        const r = rows.find((x) => x.scenario === s.id && x.perturbation === pert.id && x.arm === a.id)
        return (r ? SYM[r.kind] : '?').padEnd(16)
      }).join('')
      console.log(`   ${s.id.padEnd(26)}${cells}${s.expected}`)
    }
    const obs = [...new Set(rows.filter((r) => r.perturbation === pert.id).map((r) => r.observed))]
    console.log(`   ↳ 实测形状：${obs.join(' / ')}　（预期 ${pert.expect}）`)
    console.log(`   ↳ 帧实际内容（S1）：${frameWitness(pert.apply(SCENARIOS[0].ctx))}\n`)
  }

  // ── 表二：汇总 ──
  console.log('\n汇总（每臂 6 场景 × 6 扰动 = 36 次）\n')
  const header = `${'臂'.padEnd(16)}` + KINDS.map((k) => k.padEnd(14)).join('')
  console.log(header)
  console.log('─'.repeat(header.length + 6))
  for (const arm of ARMS) {
    const cell = rows.filter((r) => r.arm === arm.id)
    const counts = KINDS.map((k) => String(cell.filter((r) => r.kind === k).length).padEnd(14)).join('')
    console.log(`${arm.id.padEnd(16)}${counts}`)
  }

  // ── 表三：逐格比较两臂是否给出同一结果 ──
  console.log('\n两臂在同一 (场景, 扰动) 上是否给出同一结果：\n')
  const pairs = [
    ['contract', 'ifelse-naive'],
    ['contract-strict', 'ifelse-best'],
    ['contract', 'ifelse-best'],
  ] as const
  for (const pert of PERTURBATIONS) {
    for (const [a, b] of pairs) {
      const diff = SCENARIOS.filter((s) => {
        const ra = rows.find((r) => r.scenario === s.id && r.perturbation === pert.id && r.arm === a)
        const rb = rows.find((r) => r.scenario === s.id && r.perturbation === pert.id && r.arm === b)
        return ra?.outcome !== rb?.outcome
      })
      console.log(
        `  ${`${pert.id} · ${a} vs ${b}`.padEnd(50)} ${diff.length === 0 ? '逐格一致' : `不同：${diff.map((s) => s.id).join(', ')}`}`,
      )
    }
  }

  // ── 表四：★ 反向对照必须无差异 ──
  console.log('\n★ 反向对照（P5）—— 只改帧声明**排除**的格子：\n')
  const p0 = rows.filter((r) => r.perturbation === 'P0-none')
  const p5 = rows.filter((r) => r.perturbation === 'P5-irrelevant-control')
  for (const arm of ARMS) {
    const a = p0.filter((r) => r.arm === arm.id).map((r) => `${r.scenario}:${r.outcome}`).join('|')
    const b = p5.filter((r) => r.arm === arm.id).map((r) => `${r.scenario}:${r.outcome}`).join('|')
    console.log(
      `  ${arm.id.padEnd(16)} ${a === b ? '与基线一致 ✓' : '★ 与基线不同 ✗（对照失败，差异另有来源）'}`,
    )
  }
  console.log('')
}

await main()
