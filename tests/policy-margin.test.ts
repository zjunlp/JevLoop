/**
 * 门限元数据与 margin（TODO §2）。
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件测的是「margin 算在**同一条边**上」，不是「判定准不准」
 * ═══════════════════════════════════════════════════════════
 *
 * §2 的原始观察：`pickTool` 回来 0.71 对 0.6 门限，margin 只有 0.11，
 * 而**换掉候选集就翻了**。所以每个节点除了命中率还要报 margin。
 *
 * ★ 而 margin 要成立，`probe` 必须读**谓词读的那个量**。§8.16 记着这个项目
 *   正是在这里栽过：`top()` 用的是 `max(p, 1-p)`，`prob_true()` 用的是 `p` ——
 *   两个名字看着是一件事，读的不是，于是同一个答案被读反。
 *
 *   所以下面第一条测的就是那件事：**`topGte` 的 probe 必须是选中项的概率，
 *   不是 `confidence`**（后者是归一化熵，选项个数一变含义就变，§8.3）。
 *
 * @module JevLoop/policy-margin.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  closestMargin,
  probGte,
  scoreGte,
  thresholdOf,
  topGte,
  topLt,
} from '../src/policy.ts'
import type { AnswerSet } from '../src/vocab.ts'
import type { PolicyRule } from '../src/vocab-decision.ts'

/** 一个 choice 答案：选中 `a`，概率 0.71 —— §8.17 那个实测值 */
function choiceSet(probs: Record<string, number>, choice: string): AnswerSet {
  return { tool: { type: 'choice', choice, probabilities: probs, confidence: 0.269 } }
}

test('门限能被读回来 —— 它以前埋在闭包里，问不出来', () => {
  const spec = thresholdOf(topGte('tool', 0.6))
  assert.ok(spec, '带门限的谓词必须能读回元数据')
  assert.equal(spec.kind, 'topGte')
  assert.equal(spec.id, 'tool')
  assert.equal(spec.threshold, 0.6)
  assert.equal(thresholdOf(() => true), undefined, '不带的要老实返回 undefined')
  assert.equal(thresholdOf(undefined), undefined)
})

test('★★ probe 读的是**选中项的概率**，不是 confidence（§8.16 那条的老位置）', () => {
  const spec = thresholdOf(topGte('tool', 0.6))!
  // confidence 是 0.269（归一化熵），选中项概率是 0.71 —— 两者差得远
  const a = choiceSet({ a: 0.71, b: 0.29 }, 'a')
  assert.equal(spec.probe(a), 0.71, '★ 读的必须是 probabilities[choice]')
  assert.notEqual(spec.probe(a), 0.269, '不是 confidence —— 同名不同义正是 §8.16 的坑')
})

test('边界从构造上成立：量 == 门限 时谓词为真，margin 正好 0', () => {
  const at = choiceSet({ a: 0.6, b: 0.4 }, 'a')
  const below = choiceSet({ a: 0.59, b: 0.41 }, 'a')

  const rules: PolicyRule<AnswerSet>[] = [{ when: topGte('tool', 0.6), action: 'call' }]
  const m0 = closestMargin(rules, at)!
  const m1 = closestMargin(rules, below)!

  assert.equal(m0.value, 0.6)
  assert.equal(m0.margin, 0, '压线 = margin 0')
  assert.equal(m1.value, 0.59)
  assert.ok(Math.abs(m1.margin - 0.01) < 1e-9, `差一点就是差一点，实际 ${m1.margin}`)
})

test('★ 补集与本体读同一条边（topLt 复用 topGte 的 probe）', () => {
  const positive = thresholdOf(topGte('tool', 0.6))!
  const negative = thresholdOf(topLt('tool', 0.6))!
  assert.equal(negative.threshold, positive.threshold)
  assert.equal(negative.gte, false, '方向标了出来')
  const a = choiceSet({ a: 0.71, b: 0.29 }, 'a')
  assert.equal(negative.probe(a), positive.probe(a), '★ 同一条边，不是另算一个数')
})

test('不适用这类答案的规则**不贡献 margin** —— 不算一条没生效的边', () => {
  const a = choiceSet({ a: 0.71, b: 0.29 }, 'a')
  // `prob:` 只认 noul（§policy 的注释：对 choice 它恒假）
  const rules: PolicyRule<AnswerSet>[] = [{ when: probGte('tool', 0.7), action: 'x' }]
  assert.equal(closestMargin(rules, a), undefined, 'probe 报 undefined 就该跳过')
})

test('取**最近**的那条边，而且只算到决定它的规则为止', () => {
  const a = choiceSet({ a: 0.71, b: 0.29 }, 'a')
  const noul: AnswerSet = { ...a, auth: { type: 'noul', noul: 0.95 } }

  const rules: PolicyRule<AnswerSet>[] = [
    { when: topGte('tool', 0.6), action: 'call' }, // margin 0.11
    { when: probGte('auth', 0.5), action: 'ask' }, // margin 0.45
  ]
  const nearest = closestMargin(rules, noul, 1)!
  assert.equal(nearest.kind, 'topGte', '最近的那条是 0.11，不是 0.45')
  assert.ok(Math.abs(nearest.margin - 0.11) < 1e-9)

  // `upto` 之后那条规则**根本没被问到** —— 拿它算 margin 是报一个没发生过的比较
  const onlyFirst = closestMargin(rules, noul, 0)!
  assert.equal(onlyFirst.kind, 'topGte')
  assert.equal(closestMargin([rules[1]!], noul, -1), undefined, 'upto=-1 = 一条都没求值过')
})

test('score 门限按**档位**算，不是按概率', () => {
  const a: AnswerSet = {
    risk: {
      type: 'score',
      score: 2,
      confidence: 0.9,
      legend: { '0': 'read-only', '1': 'reversible write', '2': 'irreversible', '3': 'destructive' },
      probabilities: { '0': 0.02, '1': 0.08, '2': 0.9 },
    },
  }
  const spec = thresholdOf(scoreGte('risk', 2))!
  assert.equal(spec.probe(a), 2, '读的是档位')
  assert.equal(closestMargin([{ when: scoreGte('risk', 3), action: 'ask' }], a)!.margin, 1)
})

test('没有带门限的规则时**返回 undefined**，不用 0 冒充「贴着门限」', () => {
  const a = choiceSet({ a: 0.71, b: 0.29 }, 'a')
  const rules: PolicyRule<AnswerSet>[] = [{ when: (s) => 'tool' in s, action: 'x' }]
  assert.equal(closestMargin(rules, a), undefined)
})
