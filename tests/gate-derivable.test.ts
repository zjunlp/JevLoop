/**
 * 「漂移检查是不是可导出的」—— 把三个探针钉成断言
 *
 * ═══════════════════════════════════════════════════════════
 * 为什么这些要钉
 * ═══════════════════════════════════════════════════════════
 *
 * 这一轮的结论是**弱肯定**：可导出是真的（D1/D2），但可导出的只是**信号**，
 * 处置仍然是策略（D3）。弱结论和否定结论一样容易腐烂 —— 尤其 D3 那三条
 * 现在成立只是因为**碰巧没人去读**：谁哪天在 `decide.ts` 里读一下 `unfilled`，
 * 报告就静静地过期了，而没有任何东西会响。
 *
 * @module JevLoop/gate-derivable.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  HAND_GATE_DILIGENT,
  SIGNALS,
  dependencyCoverage,
  measureCoverage,
  specOf,
  withBound,
  withExtraCell,
} from '../bench/gate-derivable.ts'
import { parseDecisionDoc } from '../src/contract.ts'
import { frameSpecFromBlock } from '../src/decisions.ts'
import { compileFrame, type AgentCtx } from '../src/frame.ts'

const MD = readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8')
const NODE = 'can_deliver'
const EXTRA = '+ files_known  200     filesMaybe  —— 测试用：模拟新增一栏'

// ═══════════════════════════════════════════════════════════
// D1 加一格声明 ⇒ 存在性检查自动跟上（零行检查代码）
// ═══════════════════════════════════════════════════════════

test('★ D1：每一格声明都被 unfilled 盖住 —— 现状是 3/3', () => {
  const c = measureCoverage(MD, NODE)
  assert.deepEqual(
    [...c.presenceCovered].sort(),
    [...c.declared].sort(),
    '声明了几格，就该有几格会被「没喂」记下来',
  )
})

test('★★ D1：**新加一格之后仍然是满覆盖** —— 证明检查是从声明算出来的，不是硬编码清单', () => {
  const grown = withExtraCell(MD, NODE, EXTRA)
  const c = measureCoverage(grown, NODE)
  assert.ok(c.declared.includes('files_known'), '新格要真的进了声明')
  assert.ok(
    c.presenceCovered.includes('files_known'),
    '★ 新格必须自动被盖住。这一条挂了，就说明 unfilled 不是从声明导出的 —— 那么本轮唯一没被证伪的声明也就倒了',
  )
  assert.deepEqual([...c.presenceCovered].sort(), [...c.declared].sort(), '加完之后仍是满覆盖')
})

test('★ D1 的边界：未注册的投影名在**编译期**就被拒绝（这是真的 load-time refusal）', () => {
  const bad = withExtraCell(MD, NODE, '+ cwd_len  20  cwdLength  —— 不存在的投影')
  const block = parseDecisionDoc(bad).blocks.find((b) => b.id === NODE)!
  assert.throws(
    () => frameSpecFromBlock(block, NODE),
    /不在注册表里/,
    '投影表是封闭的 —— 写错名字会让契约在加载时失败，而不是在判定时静默少一栏',
  )
})

// ═══════════════════════════════════════════════════════════
// D2 改一个声明的界 ⇒ 截断自动跟着变（零行截断代码）
// ═══════════════════════════════════════════════════════════

test('★★ D2：只改 `.md` 里的预算，实际截断就跟着变 —— chars 与 listMax 同源', () => {
  const spec = specOf(MD, NODE)
  const spec50 = specOf(withBound(MD, 'answer', 900, 50), NODE)
  assert.equal(spec.fields.find((f) => f.key === 'answer')?.chars, 900)
  assert.equal(spec50.fields.find((f) => f.key === 'answer')?.chars, 50)

  const lenAt = (s: ReturnType<typeof specOf>) => {
    const frame = compileFrame(s, { task: 't', cwd: '/w', draft: 'x'.repeat(4000) } as unknown as AgentCtx)
    return String(frame.state.answer).length
  }
  const big = lenAt(spec)
  const small = lenAt(spec50)
  assert.ok(big > small, `预算改小之后进帧的文本必须更短（${big} → ${small}）`)
  assert.ok(small < 50, '截断要真的按新预算生效')
})

// ═══════════════════════════════════════════════════════════
// D3 信号产出了 ⇒ 不等于有人管（★ 这一条最容易过期）
// ═══════════════════════════════════════════════════════════

test('★★★ D3：三个信号在参考运行时的循环里**一次都没被读过** —— 源码级断言', () => {
  /*
    ★ 这条断言的是「没人消费」，所以它挂掉的方式有两种，都是好消息要处理的那种：
      · 有人在 decide.ts / agent.ts 里开始读 unfilled/absent/truncated ⇒ 上面那句
        「处置仍然是策略，契约只管产出信号」就过期了，文档必须改
      · 有人把产出删了 ⇒ 那 D1/D2 也就假了
    两种都该让人停下来看一眼，而不是让报告静静地变成假的。
  */
  const files = ['decide.ts', 'agent.ts']
  for (const f of files) {
    const text = readFileSync(new URL(`../src/${f}`, import.meta.url), 'utf8')
    for (const sig of ['unfilled', 'absent', 'truncated']) {
      assert.doesNotMatch(
        text,
        new RegExp(`\\.${sig}\\b`),
        `src/${f} 开始引用 .${sig} 了 —— 「信号无人消费」这句话要重写，本文件与 MEASUREMENT 文档一起`,
      )
    }
  }
})

test('★ D3：SIGNALS 表里三条都标着「产出但运行时无人消费」，与源码断言保持一致', () => {
  assert.equal(SIGNALS.length, 3)
  for (const s of SIGNALS) {
    assert.equal(s.produced, true, `${s.signal} 应当是产出的`)
    assert.equal(s.consumedByRuntime, false, `${s.signal} 目前无人消费 —— 若已改，请连同文档一起更新`)
  }
})

// ═══════════════════════════════════════════════════════════
// 公平口径：差距是「改动代价」，不是「能力」
// ═══════════════════════════════════════════════════════════

test('★★ 勤快的手写门在原依赖集上是 100% —— 这一轮的差距**不是能力差距**', () => {
  const c = measureCoverage(MD, NODE)
  const d = dependencyCoverage(HAND_GATE_DILIGENT, c)
  assert.equal(d.uncovered.length, 0, '依赖什么就守什么的手写门没有缺口')
  assert.equal(d.ratio, '2/2')
})

test('★★ 依赖集变大、代码没改 ⇒ 手写门漏一格；补一行守卫即恢复 100%', () => {
  const after = measureCoverage(withExtraCell(MD, NODE, EXTRA), NODE)
  const stale = dependencyCoverage(
    { id: 'stale', dependsOn: [...HAND_GATE_DILIGENT.dependsOn, 'files_known'], guards: [...HAND_GATE_DILIGENT.guards] },
    after,
  )
  assert.deepEqual(stale.uncovered, ['files_known'], '漏的正是新加的那一格')

  const fixed = dependencyCoverage(
    { id: 'fixed', dependsOn: stale.covered.concat(stale.uncovered), guards: [...HAND_GATE_DILIGENT.guards, 'files_known'] },
    after,
  )
  assert.deepEqual(fixed.uncovered, [], '★ 一行守卫就能补回来 —— 所以契约的优势是「改动处数」，不是「能不能」')
})
