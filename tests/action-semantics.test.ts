/**
 * 动作语义（TODO §12 第一条）——**对着运行时**校验，不是自己对自己。
 *
 * ═══════════════════════════════════════════════════════════
 * 一张没人核对的语义表，就是又一份会撒谎的声明
 * ═══════════════════════════════════════════════════════════
 *
 * `ACTION_SEMANTICS` 声明了每个动作「之后会发生什么」。这些声明**很容易写成
 * 想当然的样子** —— 而外部实现者是照着它写 switch 的，写错了他不会知道，
 * 只会在某个分支上行为诡异。
 *
 * 所以这个文件做两件不同的事：
 *
 *   ① **完整性**（廉价）：`ACTIONS` 和语义表一一对应，每个位置用到的动作都有语义；
 *   ② **对账**（贵，但这是重点）：真的驱动一遍 loop，把每个动作**逼出来**，
 *      断言实际发生的和表里写的一致 —— 尤其是那两个反直觉的字段：
 *
 *         `stop`   结束工具循环，但**运行没结束**（后面还有一次生成）
 *         `deliver` 运行在这里结束，之后**没有**模型调用
 *
 * ② 用的是「按问题 id 配答案」的判定后端：动作是**策略**算出来的，所以要让
 * 某个动作出现，得让答案落在那条规则上（比如 `prob:ok >= 0.6 → continue`，
 * 答 0.05 就掉到 `stop`）。
 *
 * @module JevLoop/action-semantics.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { ACTION_SEMANTICS, type ActionSemantics } from '../src/action-semantics.ts'
import { ACTIONS } from '../src/vocab-decision.ts'
import { ANY_POSITION_ACTIONS, POSITIONS } from '../src/decision-shape.ts'
import { runAgent } from '../src/agent.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import type { Answer, AnswerSet } from '../src/vocab.ts'
import type { DecideRequest } from '../src/seam-provider.ts'

// ═══════════════════════════════════════════════════════════
// ① 完整性
// ═══════════════════════════════════════════════════════════

test('★ 语义表和动作表一一对应 —— 加一个动作而忘了写语义，这里就红', () => {
  assert.deepEqual(
    Object.keys(ACTION_SEMANTICS).sort(),
    [...ACTIONS].sort(),
    'ACTIONS 与 ACTION_SEMANTICS 的键必须完全相同',
  )
})

test('每个位置能产出的动作都有语义 —— 包括任何位置都合法的 escalate', () => {
  for (const [position, spec] of Object.entries(POSITIONS)) {
    for (const action of spec.actions) {
      assert.ok(
        action in ACTION_SEMANTICS,
        `位置 '${position}' 能产出 '${action}'，而语义表里没有它`,
      )
    }
  }
  for (const action of ANY_POSITION_ACTIONS) {
    assert.ok(action in ACTION_SEMANTICS, `'${action}' 在任何位置都合法，必须有语义`)
  }
})

test('★ 分类被钉住 —— 改一个布尔值必须是有意的', () => {
  /*
    这一条的格式刻意做成「一眼能读完的表」。它红了通常意味着有人真的改了
    `agent.ts` 的分支行为 —— 那**可能**是对的，但必须回来更新这里，
    而不是让表悄悄和代码脱节。
  */
  const shape = (s: ActionSemantics): string =>
    `${s.next}${s.endsLoop ? ' 停循环' : ''}${s.moreModelCalls ? ' 还有调用' : ' 到此为止'}`

  const actual = Object.fromEntries(ACTIONS.map((a) => [a, shape(ACTION_SEMANTICS[a])]))

  assert.deepEqual(actual, {
    // 还没走完：循环继续
    use_tool: 'pick_tool 还有调用',
    call: 'run_tool 还有调用',
    use: 'run_tool 还有调用',
    auto: 'run_tool 还有调用',
    auto_audit: 'run_tool 还有调用',
    continue: 'next_step 还有调用',
    keep_going: 'next_step 还有调用',
    // 停的是**工具循环**，后面仍然生成一份如实报告
    answer: 'generate 停循环 还有调用',
    stop: 'generate 停循环 还有调用',
    finish: 'generate 停循环 还有调用',
    escalate: 'end 停循环 还有调用',
    ask_human: 'human 停循环 还有调用',
    // 交付闸门：运行在这里结束
    deliver: 'end 停循环 到此为止',
    revise: 'regenerate 停循环 还有调用',
  })
})

test('★ 只有交付闸门那两个动作要求证据 —— 那是它们被单列出来的理由', () => {
  const needsEvidence = ACTIONS.filter((a) => ACTION_SEMANTICS[a].needsEvidence).sort()
  assert.deepEqual(needsEvidence, ['deliver', 'revise'])
})

test('★ 只有 revise 允许重试，而且只允许一次', () => {
  const retrying = ACTIONS.filter((a) => ACTION_SEMANTICS[a].retries > 0)
  assert.deepEqual(retrying, ['revise'], '别的动作都不重试 —— 重试是花钱的事，要显式')
  assert.equal(ACTION_SEMANTICS.revise.retries, 1, '只能重来一次')
})

test('只有 deliver 声明「之后没有模型调用」', () => {
  const done = ACTIONS.filter((a) => !ACTION_SEMANTICS[a].moreModelCalls)
  assert.deepEqual(done, ['deliver'], '别的动作之后运行都还没结束')
})

// ═══════════════════════════════════════════════════════════
// ② 对账：真的驱动一遍 loop
// ═══════════════════════════════════════════════════════════

/** 按**问题 id** 配答案的判定后端。没配的用默认值（默认让 loop 正常往下走） */
function scripted(over: Record<string, number | string> = {}) {
  return {
    name: 'scripted',
    decide: async (req: DecideRequest) => {
      const pick = (id: string): number | string | undefined => over[id]
      const answers: AnswerSet = {}
      for (const [id, q] of Object.entries(req.questions)) {
        const v = pick(id)
        if (q.type === 'noul') {
          // needs_auth / unsupported / done 默认「否」，其余默认「是」
          const fallback = ['needs_auth', 'unsupported', 'done'].includes(id) ? 0.05 : 0.95
          answers[id] = { type: 'noul', noul: typeof v === 'number' ? v : fallback } as Answer
        } else if (q.type === 'score') {
          answers[id] = { type: 'score', score: typeof v === 'number' ? v : 0, legend: {}, probabilities: {}, confidence: 0.9 } as Answer
        } else {
          const options = Object.keys((q as { criteria: Record<string, string> }).criteria)
          const choice = typeof v === 'string' && options.includes(v)
            ? v
            : (['read_file', 'list_dir', 'done'].find((t) => options.includes(t)) ?? options[0]!)
          answers[id] = {
            type: 'choice',
            choice,
            probabilities: Object.fromEntries(
              options.map((o) => [o, o === choice ? 0.95 : 0.05 / Math.max(1, options.length - 1)]),
            ),
            confidence: 0.9,
          } as Answer
        }
      }
      return { answers, latencyMs: 0, provider: 'scripted' }
    },
  }
}

interface Observed {
  halt: string
  steps: number
  generates: number
  audits: number
}

/** 跑一次，记下「实际发生了什么」 */
async function drive(over: Record<string, number | string>, opts: { askHuman?: boolean } = {}): Promise<Observed> {
  const cwd = await mkdtemp(join(tmpdir(), 'jevloop-semantics-'))
  try {
    for (const f of ['a.txt', 'b.txt', 'c.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const meter = new Meter()
    const decider = new Decider({ provider: scripted(over), meter })
    let generates = 0
    const r = await runAgent({
      task: 'clean up the workspace',
      cwd,
      decider,
      ...(opts.askHuman ? { onAskHuman: async () => true } : {}),
      generator: {
        name: 'counting',
        generate: async () => {
          generates++
          return { text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'counting' }
        },
      },
      maxSteps: 6,
    })
    return { halt: r.halt, steps: r.steps, generates, audits: meter.stats.audits }
  } finally {
    await rm(cwd, { recursive: true, force: true })
  }
}

test('★ answer：不需要动手 —— 停工具循环，但**仍然生成**（表里说运行没结束）', async () => {
  const o = await drive({ needs_tool: 0.05 })
  assert.equal(o.halt, 'answered_directly')
  assert.equal(o.steps, 1, '第一步就决定了直接回答')
  assert.equal(o.generates, 1, '★ 工具循环停了，运行没停 —— 生成照做')
})

test('★ stop：这一步没成 —— 停工具循环，但**仍然生成一份如实报告**', async () => {
  const o = await drive({ ok: 0.05 })
  assert.equal(o.halt, 'step_failed')
  assert.ok(o.generates >= 1, '★ 这是最反直觉的一档：stop 之后运行还没结束，生成照做')
})

test('★ finish：任务完成 —— 跳出工具循环去生成，运行没结束', async () => {
  const o = await drive({ done: 0.95 })
  assert.equal(o.halt, 'task_done')
  assert.equal(o.generates, 1, 'finish 之后是一次生成，不是一个「运行结束」')
})

test('keep_going + continue：循环真的往下走（不是停）', async () => {
  const o = await drive({ done: 0.05 }, {})
  assert.ok(o.steps > 1, `还没完就应当开下一步，实际只走了 ${o.steps} 步`)
  assert.ok(!o.halt.startsWith('task_done'), `不该判成完成，实际 halt=${o.halt}`)
})

test('★ deliver：运行在这里结束 —— 之后**没有**模型调用', async () => {
  const o = await drive({ deliverable: 0.95, unsupported: 0.05 })
  assert.equal(o.generates, 1, '只生成了那一次，交付之后没有第二次')
  assert.ok(!o.halt.includes('revise'), `交付了就不该有 revise，实际 halt=${o.halt}`)
})

test('★ revise：重新生成**一次**，再不合格就停 —— retries 声明为 1', async () => {
  // unsupported 一直 0.95 ⇒ 每次都判 revise
  const o = await drive({ unsupported: 0.95 })
  assert.equal(o.generates, 2, '★ 一次原始生成 + 一次重来 = 2；声明的 retries 就是 1')
  assert.match(o.halt, /revise/, `停在 revise 上，实际 halt=${o.halt}`)
})

test('★ escalate：判不出来就停 —— 而且停的是工具循环，生成照做', async () => {
  // pick_tool 的门限是 top >= 0.6，这里把选中项压到 0.2 ⇒ escalate
  const cwd = await mkdtemp(join(tmpdir(), 'jevloop-semantics-'))
  try {
    await writeFile(join(cwd, 'a.txt'), 'x', 'utf8')
    const decider = new Decider({
      provider: {
        name: 'low-confidence',
        decide: async (req: DecideRequest) => {
          const answers: AnswerSet = {}
          for (const [id, q] of Object.entries(req.questions)) {
            if (q.type === 'noul') {
              /*
                按 id 配：`done` 与 `unsupported` 给「否」，否则会给一遍
                `unsupported=0.95` ⇒ 交付闸门要求 revise ⇒ 多一次生成，
                而这条测试要量的就不是 escalate 了（实测第一版就是这么红的）。
              */
              const no = id === 'done' || id === 'unsupported'
              answers[id] = { type: 'noul', noul: no ? 0.05 : 0.95 } as Answer
            }
            else {
              const options = Object.keys((q as { criteria: Record<string, string> }).criteria)
              // 所有选项平分 ⇒ top 远低于 0.6
              answers[id] = {
                type: 'choice',
                choice: options[0]!,
                probabilities: Object.fromEntries(options.map((o) => [o, 1 / options.length])),
                confidence: 0.5,
              } as Answer
            }
          }
          return { answers, latencyMs: 0, provider: 'low-confidence' }
        },
      },
      meter: new Meter(),
    })
    let generates = 0
    const r = await runAgent({
      task: 't',
      cwd,
      decider,
      generator: {
        name: 'counting',
        generate: async () => {
          generates++
          return { text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'counting' }
        },
      },
      maxSteps: 4,
    })
    assert.match(r.halt, /unclear|escalate/, `应当停在「判不出来」上，实际 ${r.halt}`)
    assert.equal(generates, 1, '★ 表里说 escalate 之后运行没结束 —— 生成照做')
  } finally {
    await rm(cwd, { recursive: true, force: true })
  }
})

test('★ ask_human：拒绝就停（表里说 endsLoop）', async () => {
  // risk=3 ⇒ score:risk >= 2 → ask_human；不传 onAskHuman ⇒ 默认拒绝
  const o = await drive({ risk: 3 })
  assert.equal(o.halt, 'denied', `默认拒绝应当停机，实际 ${o.halt}`)
})

test('★ ask_human：批准之后就按 auto 继续（表里那句「批准之后按 auto 继续」）', async () => {
  const o = await drive({ risk: 3 }, { askHuman: true })
  assert.notEqual(o.halt, 'denied', '批准了就不该停在 denied 上')
  assert.ok(o.steps >= 1, '而且真的往下走了')
})

test('auto_audit：说了留痕就真的留 —— audits 字段不是空头支票', async () => {
  // risk=1 ⇒ score:risk >= 1 → auto_audit
  const o = await drive({ risk: 1 })
  assert.ok(o.audits >= 1, `auto_audit 必须留下审计条目，实际 ${o.audits} 条`)
})
