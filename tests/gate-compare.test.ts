/**
 * 完成闸门对照实验 —— 把**读数**钉成断言
 *
 * ═══════════════════════════════════════════════════════════
 * 为什么这些结论必须是测试，不能只是报告里的一段话
 * ═══════════════════════════════════════════════════════════
 *
 * 这一轮的结论是**否定式**的：契约门在参考实现里的行为，与「没写守卫的手写门」
 * **逐格相同**。否定式结论最容易腐烂 —— 它不需要谁去反驳，只要有人改了
 * `frame.ts` 对缺格的处置（比如开始拒绝），报告就会**静静地变成假的**，
 * 而没有任何东西会响。
 *
 * 所以这里钉住四件事：
 *
 *   ① 基线：四条臂在无漂移时都与 oracle 一致（策略层可证等价的前提）
 *   ② 缺一个键：契约门**记下了** `unfilled` 却**不处置** —— 分类是「静默误判」
 *   ③ 值为空：**没有任何一臂**拒绝 —— `unfilled` 抓不住「键在值为空」
 *   ④ 反向对照：只改帧声明排除的格子，四条臂都与基线完全一致
 *
 * ★ ③ 是这一轮发现的**新洞**，不是设计出来的对照：`history: []` 与
 *   `history` 键不存在，在 `unfilled` 眼里是两回事，而前者不会被拦。
 *
 * @module JevLoop/gate-compare.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { SCENARIOS } from '../bench/gate-scenarios.ts'
import { PERTURBATIONS } from '../bench/gate-drift.ts'
import { ARMS, classify, contractArm, ifElseArm, runArm } from '../bench/gate-arms.ts'

const byId = (id: string) => PERTURBATIONS.find((p) => p.id === id)!
const armById = (id: string) => ARMS.find((a) => a.id === id)!

/** 某一臂在某一扰动下、所有场景的 outcome（用来做逐格比较） */
function outcomes(armId: string, pertId: string): string[] {
  const arm = armById(armId)
  return SCENARIOS.map((s) => runArm(arm, s, byId(pertId).apply(s.ctx)).outcome)
}

// ═══════════════════════════════════════════════════════════
// ① 基线：策略层等价 —— 四条臂都判对
// ═══════════════════════════════════════════════════════════

test('★ 基线（无漂移）：四条臂在全部 6 个场景上都与 oracle 一致', () => {
  for (const arm of ARMS) {
    for (const s of SCENARIOS) {
      const r = runArm(arm, s, s.ctx)
      assert.equal(
        classify(r, s.expected),
        'ok',
        `${arm.id} 在 ${s.id} 上应当是 ${s.expected}，实际 ${r.outcome}（${r.why}）`,
      )
    }
  }
})

test('★ 基线上「契约门」与「手写门」逐格相同 —— 策略层可证等价的那个前提', () => {
  assert.deepEqual(outcomes('contract', 'P0-none'), outcomes('ifelse-best', 'P0-none'))
  assert.deepEqual(outcomes('contract', 'P0-none'), outcomes('ifelse-naive', 'P0-none'))
})

// ═══════════════════════════════════════════════════════════
// ② 缺一个键：记下来 ≠ 处置它
// ═══════════════════════════════════════════════════════════

test('★★ 缺 `history` 键：契约门**记下** unfilled，却照常判定（参考实现不拒绝）', () => {
  const s = SCENARIOS[0]
  const ctx = byId('P1-history-absent').apply(s.ctx)

  const r = contractArm(s, ctx, false)
  assert.notEqual(r.outcome, 'refuse', '★ 参考实现的契约门**不会**因为缺格而拒绝 —— 拒绝住在适配器里')
  assert.ok(
    r.noticed.includes('unfilled:evidence'),
    `契约确实记下了这一格没喂，但没有任何人读它（实际 noticed=${JSON.stringify(r.noticed)}）`,
  )
})

test('★★ 缺 `history` 键：契约门与「没写守卫的手写门」逐格相同', () => {
  assert.deepEqual(
    outcomes('contract', 'P1-history-absent'),
    outcomes('ifelse-naive', 'P1-history-absent'),
    '★ 这是本实验最要紧的一条：把处置权交回默认行为时，契约门与最朴素的手写门不可区分',
  )
})

test('★★ 缺 `history` 键：契约门 + 适配器纪律 ≡ 最佳实践手写门（两者都拒绝）', () => {
  const strict = outcomes('contract-strict', 'P1-history-absent')
  const best = outcomes('ifelse-best', 'P1-history-absent')
  assert.deepEqual(strict, best)
  assert.ok(
    strict.every((o) => o === 'refuse'),
    '两边都应当在全部 6 个场景上拒绝',
  )
})

test('★★ 缺 `history` 键时那个「判对」是巧合，不是变准 —— 假拒绝是它的破绽', () => {
  // 证据一空 ⇒ 每一条主张都不被支持 ⇒ 该交付的三种场景全被打回。
  // 单看「假接受 = 0」会把它读成安全；假拒绝率才是揭穿它的那根针。
  const arm = armById('contract')
  const verdicts = SCENARIOS.map((s) => classify(runArm(arm, s, byId('P1-history-absent').apply(s.ctx)), s.expected))
  assert.equal(verdicts.filter((v) => v === 'false-accept').length, 0, '假接受确实是 0')
  assert.equal(verdicts.filter((v) => v === 'false-reject').length, 3, '★ 而假拒绝是 3 —— 闸门停摆了，不是变准了')
})

// ═══════════════════════════════════════════════════════════
// ③ 值为空：没有任何一臂拒绝 —— 这一轮发现的洞
// ═══════════════════════════════════════════════════════════

test('★★★ `history: []`（键在、值为空）**没有任何一臂**拒绝 —— 包括接了适配器纪律的那条', () => {
  const refused = ARMS.filter((arm) =>
    SCENARIOS.some((s) => runArm(arm, s, byId('P2-history-empty').apply(s.ctx)).outcome === 'refuse'),
  )
  assert.deepEqual(
    refused.map((a) => a.id),
    [],
    '★ unfilled 抓的是「键不存在」，抓不住「键在、值为空」—— 而后者正是读不到 transcript 时的形状',
  )
})

// ═══════════════════════════════════════════════════════════
// ④ 两个失败的扰动：必须**照样钉住**，否则它们会被误读成「没问题」
// ═══════════════════════════════════════════════════════════

test('★ P3a/P3b（类型漂移）没能改变任何一臂的判定 —— 这是**失败的扰动**，不是「类型安全」', () => {
  for (const pert of ['P3a-result-array', 'P3b-draft-array']) {
    assert.deepEqual(
      outcomes('contract', pert),
      outcomes('contract', 'P0-none'),
      `${pert} 本意是制造类型漂移，实测判定一格没变 —— 它被投影/类型强制吸收了`,
    )
  }
  /*
    ★ 这两条留着而不是删掉，是因为「没测出差异」和「扰动没生效」是两件事。
      把它们删了，报告里就只剩「所有扰动下两臂都一致」，那会把一个**没做成的
      实验**记成一条**成立的结论**。
  */
})

// ═══════════════════════════════════════════════════════════
// ⑤ 反向对照：差异必须来自被扰动的那一格
// ═══════════════════════════════════════════════════════════

test('★★ 反向对照：只改帧声明**排除**的格子，四条臂都与基线逐格相同', () => {
  for (const arm of ARMS) {
    assert.deepEqual(
      outcomes(arm.id, 'P5-irrelevant-control'),
      outcomes(arm.id, 'P0-none'),
      `${arm.id} 在无关扰动下变了 —— 那么 P1 上测到的差异就不能归因于缺格`,
    )
  }
})

test('★ 无关扰动确实改到了 ctx（否则上一条是空转的）', () => {
  const ctx = byId('P5-irrelevant-control').apply(SCENARIOS[0].ctx)
  assert.ok(ctx.files && ctx.files.length > 0, 'files 要真的被改了')
  assert.ok(ctx.canWrite === true, 'canWrite 要真的被改了')
  assert.ok(ctx.earlier, 'earlier 要真的被改了')
})

// ═══════════════════════════════════════════════════════════
// ⑥ 手写门这一侧的自检：它不是因为写坏了才和契约门一致的
// ═══════════════════════════════════════════════════════════

test('★ 手写门「带守卫」与「不带守卫」在基线上相同、在缺格时不同 —— 证明守卫是真的在起作用', () => {
  const s = SCENARIOS[0]
  assert.equal(
    ifElseArm(s, s.ctx, true).outcome,
    ifElseArm(s, s.ctx, false).outcome,
    '基线：有没有守卫都该给出同一个判定',
  )
  const ctx = byId('P1-history-absent').apply(s.ctx)
  assert.equal(ifElseArm(s, ctx, true).outcome, 'refuse', '带守卫的要拒绝')
  assert.notEqual(ifElseArm(s, ctx, false).outcome, 'refuse', '不带守卫的不会拒绝')
})
