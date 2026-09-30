/**
 * 「质疑前提」的探针 —— **TS 侧的那一半**
 *
 *   文件：`experiments/benchmark/bullshitbench/probe_samples.json`
 *
 * ══════════════════════════════════════════════════════════════
 *  这个测试存在的唯一理由：让一份"重复实现"不许漂
 * ══════════════════════════════════════════════════════════════
 *
 * 判据在两边各有一份：`src/claim-lexicon.ts`（正本，论文报数字用的）和
 * `experiments/benchmark/bullshitbench/premise.py`（镜子，因为评测管道是 Python，
 * 而它按约定不依赖 TS 内核）。
 *
 * `docs/CODE-STYLE.md` §3.1 反对同一件事两份实现，理由是**它们会分叉**。
 * 这里分叉不可避免（语言边界），所以给它加了一道防腐：
 *
 *     probe_samples.json   ← 两边各有一条测试读它
 *     tests/premise-probe.test.ts      （这条，TS）
 *     experiments/tests/test_bullshitbench.py  （Python）
 *
 * 任何一边的模式漂了，对应语言的测试就会红，并且直接指出是哪一条样本。
 *
 * ★ 探针里前 6 条是 Leni 公开运行记录里**逐字摘出来的原话**
 *   （`dataset/leni/data/eval_runs_bullshit.csv`，panel_score=2 的样本）。
 *   其中一条是写 Python 测试时才发现的缺口：`the premise is fabricated`
 *   原先抓不到 —— 因为表里只有形容词+名词的紧邻形式。
 *
 * @module JevLoop/premise-probe.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { claimOf } from '../src/claim-outcome.ts'

interface Probe {
  text: string
  challenges_premise: boolean
  why: string
}

const PROBES: Probe[] = (
  JSON.parse(
    readFileSync(
      resolve(import.meta.dirname, '..', 'experiments', 'benchmark', 'bullshitbench', 'probe_samples.json'),
      'utf8',
    ),
  ) as { samples: Probe[] }
).samples

test('探针文件不是空的 —— 空的话这条测试会"全过"而什么都没验', () => {
  assert.ok(PROBES.length >= 10, `只有 ${PROBES.length} 条探针`)
  assert.ok(
    PROBES.some((p) => p.challenges_premise) && PROBES.some((p) => !p.challenges_premise),
    '两侧都要有样本，否则测不出误报或漏报',
  )
})

test('★★ TS 判据在每一条探针上都要给出标注的答案', () => {
  for (const p of PROBES) {
    const got = claimOf(p.text).challengesPremise
    assert.equal(
      got,
      p.challenges_premise,
      `探针不符：${JSON.stringify(p.text.slice(0, 60))}\n  期望 ${p.challenges_premise}，实得 ${got}\n  理由：${p.why}`,
    )
  }
})

test('★ 两种言语行为不许混：「我做不到」≠「你的前提是假的」', () => {
  const own = claimOf('I cannot determine this from the corpus.')
  assert.equal(own.admitsFailure, true)
  assert.equal(own.challengesPremise, false, '说自己做不到不是质疑前提')

  const prem = claimOf('This question contains a false premise and fabricated terminology.')
  assert.equal(prem.challengesPremise, true)
  assert.equal(prem.claimsDone, false, '质疑前提不是声称完成')
})

test('质疑前提不会被读成"声称完成" —— 两类判定不能互相污染', () => {
  for (const p of PROBES.filter((x) => x.challenges_premise)) {
    assert.equal(claimOf(p.text).claimsDone, false, `被误读成声称完成：${p.text.slice(0, 50)}`)
  }
})
