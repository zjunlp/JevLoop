/**
 * `DECISION.md` 合规套件的**门禁**（脚本在 `scripts/conformance.ts`）。
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件存在的唯一理由：**一份没人跑的演示会烂掉，而且烂得没有声音**
 * ═══════════════════════════════════════════════════════════
 *
 * `scripts/conformance.ts` 里那十条锚点，是拿 `DECISION.md` 的**原文**钉的。
 * 文件里改一个词，锚点就失配 —— 那时演示会打印「已经过期」，但只要没人跑它，
 * 就没有人知道。§8.16 那条「声明了却没有消费方」在这里的形态是
 * **「检查写好了却没有运行方」**：和没有检查是同一件事。
 *
 * ★ 所以下面测的不只是「结果对不对」，还有**这套检查会不会红**：
 *
 *     · 期望写错       → 必须报「没报成预期的样子」，不是通过
 *     · 锚点不存在     → 必须报「已经过期」，不是通过
 *     · 对照被误伤     → 必须报「误报」
 *
 *   一个不可能失败的检查和一个通过的检查无法区分 —— 反过来，
 *   **一个永远红的检查和一个真的在检查的检查同样无法区分**。
 *   两边都要钉住，所以对照（`SHAM`）和反证（「期望写错」）都在这份文件里。
 *
 * @module JevLoop/conformance.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  CASES,
  FAMILIES,
  SHAM,
  inspect,
  runConformance,
  runOne,
  total,
  type Family,
  type Mutation,
} from '../scripts/conformance.ts'

const MD = readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8')

/** 取一条**突变**。对照不从这里取 —— 它们的断言在 `SHAM` 那一组 */
const byId = (id: string): Mutation => {
  const c = CASES.find((x) => x.id === id)
  assert.ok(c, `没有 '${id}' 这条突变`)
  return c
}

// ═══════════════════════════════════════════════════════════
// 基线
// ═══════════════════════════════════════════════════════════

test('真文件三层全干净 —— 基线红了，下面的突变结论都没有意义', () => {
  const p = inspect(MD)
  assert.deepEqual(p, { parse: [], policy: [], frame: [] })
  assert.equal(total(p), 0)
})

// ═══════════════════════════════════════════════════════════
// 十个突变 + 两个对照
// ═══════════════════════════════════════════════════════════

test('★ 每一个「会安静地判错」的改法都被它那一层挡下', () => {
  for (const o of runConformance(MD)) {
    assert.ok(o.ok, `${o.c.id} 没被挡下：${o.detail}`)
  }
})

test('阴性对照：改法变了、意思没变 —— 一行都不报', () => {
  for (const c of SHAM) {
    const o = runOne(MD, c)
    assert.ok(o.ok, `${c.id} 被误伤了：${o.detail}`)
    assert.deepEqual(o.firedIn, [], `${c.id} 本该一层都不响`)
  }
})

test('锚点必须**恰好命中一次** —— 命中 0 或多次都说明这段演示不可信', () => {
  for (const c of [...CASES, ...SHAM]) {
    const n = MD.split(c.find).length - 1
    assert.equal(n, 1, `'${c.id}' 的锚点在 DECISION.md 里命中 ${n} 次（必须恰好 1 次）`)
    assert.notEqual(c.to, c.find, `'${c.id}' 的改法是空操作 —— 它证明不了任何事`)
  }
})

test('三类静默失败都至少有一条演示 —— 分组不是装饰', () => {
  for (const fam of Object.keys(FAMILIES) as Family[]) {
    assert.ok(
      CASES.some((c) => c.family === fam),
      `'${fam}' 这一类一条演示都没有`,
    )
  }
})

// ═══════════════════════════════════════════════════════════
// ★★ 帧层是承重的
// ═══════════════════════════════════════════════════════════

test('★★ 删掉一条排除声明，**只有帧层**看得见 —— 这就是这一层存在的理由', () => {
  const o = runOne(MD, byId('exclusion-dropped'))
  assert.ok(o.ok)
  // ★ 写成 deepEqual 而不是 includes：这一条要钉的是「**另外两层看不见**」。
  //   在 `frameSpecsOf` 接上之前（2026-09-23 之前），解析器和谓词编译器
  //   对这一处删改**都没有话说**，而 `jevloop spec` 打印「✓ parses clean」。
  assert.deepEqual(
    o.firedIn,
    ['frame'],
    '解析层或谓词层也看见它了？那这一条就不该归在帧层 —— 但更要紧的是，' +
      '如果 firedIn 里**没有** frame，说明帧检查没有接上（§8.14 会原样复活）',
  )
})

test('★ 帧层也是**抛**的：格名认不出时当场抛，接住之后算「被挡下」', () => {
  const o = runOne(MD, byId('field-typo'))
  assert.ok(o.ok)
  assert.match(o.detail, /不是 ctx 的格名/)
})

// ═══════════════════════════════════════════════════════════
// ★★ 反证：这套检查会红
// ═══════════════════════════════════════════════════════════

test('★★ 期望写错时必须报「没报成预期的样子」，不能算过', () => {
  const o = runOne(MD, { ...byId('action-typo'), expect: /THIS-CANNOT-MATCH/ })
  assert.equal(o.ok, false, '把期望改成不可能命中的正则之后仍然通过 —— 断言根本没有在比')
  assert.match(o.detail, /没报成预期的样子/)
})

test('★★ 锚点不存在时必须报「已经过期」，不能静默算过', () => {
  const o = runOne(MD, { ...byId('exclusion-dropped'), find: '这一行在 DECISION.md 里不存在\n' })
  assert.equal(o.ok, false, '锚点找不到却算通过 —— 演示烂掉了也没有声音')
  assert.match(o.detail, /已经过期/)
})

test('★★ 喂一份缺了整块的文本，帧层必须当场抛而不是安静地少查一块', () => {
  const bad = MD.replace('## step_ok\n', '## step_ok_renamed\n')
  const p = inspect(bad)
  assert.ok(
    p.frame.some((m) => /没有 'step_ok' 这个块/.test(m)),
    '七个判定各对应一个块 —— 少一个就没有判定规格，不能静默跳过',
  )
})
