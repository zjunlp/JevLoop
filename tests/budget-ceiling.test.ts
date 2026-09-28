/**
 * 每轮硬上限（TODO §9）。
 *
 * ═══════════════════════════════════════════════════════════
 * 这一节测的是**刹车**，也是「刹车不保证什么」
 * ═══════════════════════════════════════════════════════════
 *
 * §9 记着：唯一的上限是 `maxSteps`，跑一轮花多少钱、多少时间都没有盖。
 * 现在有三个（墙钟 / 模型调用数 / token），越线**停机**。
 *
 * ★ 有一条测试专门钉住它的**边界**：检查发生在每步开始之前，所以它保证的
 *   是「越线之后不会再开新的一步」，**不是**「花费绝不超过上限」。一次请求
 *   发出去就收不回来，而越线往往正是那一次造成的。把这条写进测试，是为了
 *   不让「有上限了」这句话在某天被读成「不可能超支」。
 *
 * @module JevLoop/budget-ceiling.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { runAgent } from '../src/agent.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import type { Answer, AnswerSet } from '../src/vocab.ts'

async function withTmp<T>(fn: (cwd: string) => Promise<T>): Promise<T> {
  const cwd = await mkdtemp(join(tmpdir(), 'jevloop-budget-'))
  try {
    return await fn(cwd)
  } finally {
    await rm(cwd, { recursive: true, force: true })
  }
}

/** 一个永远想让 loop 继续动手的判定后端 —— 不设上限时它会一直跑到 maxSteps */
function keepsGoing(): { name: string; decide: (req: any) => Promise<any> } {
  return {
    name: 'keeps-going',
    decide: async (req: { questions: Record<string, { type: string; criteria?: unknown }> }) => {
      const answers: AnswerSet = {}
      for (const [id, q] of Object.entries(req.questions)) {
        if (q.type === 'noul') {
          /*
            按**问题 id** 答，不是一律 0.95。第一版一律 0.95，于是
            `grade_risk` 的第二个问题 `needs_auth` 也变成了「需要授权」⇒
            loop 去问人 ⇒ 默认拒绝 ⇒ `halt: 'denied'`，而且它是在
            **maxSteps 之前**停的 —— 那几条断言量的就不是上限，是授权。
          */
          const v = id === 'needs_auth' || id === 'done' ? 0.05 : 0.95
          answers[id] = { type: 'noul', noul: v } as Answer
        }
        else if (q.type === 'score') answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.9 } as Answer
        else {
          const options = Object.keys((q as { criteria: Record<string, string> }).criteria)
          /*
            优先 `read_file`：只要还有没读过的文件，它就一直在候选里，
            所以 loop 能真的跑到 maxSteps。第一版优先 `list_dir`，而它用过
            一次就不再是候选 ⇒ 第二/三步挑到 `read_file` 却没有未读文件
            ⇒ `halt: 'input_unclear'` —— 那几条断言量的就不是 maxSteps 了。
          */
          const choice = ['read_file', 'list_dir', 'done'].find((t) => options.includes(t)) ?? options[0]!
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
      return { answers, latencyMs: 0, provider: 'keeps-going' }
    },
  }
}

const noopGenerator = {
  name: 'noop',
  generate: async () => ({ text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'noop' }),
}

test('不给上限时行为和以前一样：跑到 maxSteps', async () => {
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const decider = new Decider({ provider: keepsGoing(), meter: new Meter() })
    const r = await runAgent({ task: 't', cwd, decider, generator: noopGenerator, maxSteps: 3 })
    // `max_steps` 后面可能跟一个 `+revise`（交付闸门那段的老约定），
    // 所以比前缀而不是全等
    assert.match(r.halt, /^max_steps/, '没设上限就应当撞 maxSteps —— 默认行为不变')
    assert.equal(r.steps, 3)
  })
})

test('★ 刹车在花钱之前踩：0 次模型调用的上限 ⇒ 一步都不开', async () => {
  /*
    用 `maxModelCalls: 0` 而不是 `maxWallMs: 0` 来测「一步都不开」，是为了
    **确定性**：墙钟为 0 时，第一步跑不跑取决于那一下有没有跨过一毫秒 ——
    写死 `steps === 0` 的断言会时绿时红，而时绿时红的测试和没有测试一样危险。
  */
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const decider = new Decider({ provider: keepsGoing(), meter: new Meter() })
    const r = await runAgent({ task: 't', cwd, decider, generator: noopGenerator, maxSteps: 5, maxModelCalls: 0 })
    assert.match(r.halt, /^budget_model_calls:0/, `halt 要说清是哪条上限、多少，实际：${r.halt}`)
    assert.equal(r.steps, 0, '越线之后一步都不该开')
  })
})

test('★★ 越线时**不生成** —— 最贵的那一步不能漏在闸门外面', async () => {
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const decider = new Decider({ provider: keepsGoing(), meter: new Meter() })
    let generated = 0
    const r = await runAgent({
      task: 't',
      cwd,
      decider,
      generator: {
        name: 'counting',
        generate: async () => {
          generated++
          return { text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'counting' }
        },
      },
      maxSteps: 5,
      maxModelCalls: 0,
    })
    assert.equal(generated, 0, '★ 越线之后一次生成都不该发生 —— 它是整个 loop 里最贵的一步')
    assert.equal(r.answer, '', '没有生成就没有回答，halt 里说明为什么')
    assert.match(r.halt, /^budget_model_calls/)
  })
})

test('墙钟上限：halt 里写清是哪一条、多少', async () => {
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const decider = new Decider({ provider: keepsGoing(), meter: new Meter() })
    // 1ms：第一步多半跑得完，但下一步不会再开（这里只断言「停在哪条上」，
    // 不断言跑了几步 —— 那取决于机器有多快）
    const r = await runAgent({ task: 't', cwd, decider, generator: noopGenerator, maxSteps: 5, maxWallMs: 1 })
    assert.match(r.halt, /^budget_wall:1ms/, `实际：${r.halt}`)
    assert.ok(r.steps < 5, '它必须是**提前**停的，而不是跑满了 maxSteps')
  })
})

test('★ 模型调用数上限：达到就停', async () => {
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const meter = new Meter()
    // 先垫一次模型调用，让上限一开始就已经达到
    meter.recordModelCall(0, { kind: 'generate', latencyMs: 1, inputTokens: 0, outputTokens: 0 })
    const decider = new Decider({ provider: keepsGoing(), meter })
    const r = await runAgent({ task: 't', cwd, decider, generator: noopGenerator, maxSteps: 5, maxModelCalls: 1 })
    assert.match(r.halt, /^budget_model_calls:1/)
    assert.equal(r.steps, 0)
  })
})

test('★ token 上限：按 meter 记的输入+输出算', async () => {
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const meter = new Meter()
    meter.recordModelCall(0, { kind: 'generate', latencyMs: 1, inputTokens: 60, outputTokens: 60 })
    const decider = new Decider({ provider: keepsGoing(), meter })
    const r = await runAgent({ task: 't', cwd, decider, generator: noopGenerator, maxSteps: 5, maxTokens: 100 })
    assert.match(r.halt, /^budget_tokens:100/, '120 ≥ 100 ⇒ 停')
    assert.equal(r.steps, 0)
  })
})

test('上限被撞上时会留下一条轨迹 —— 不静默停住', async () => {
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const decider = new Decider({ provider: keepsGoing(), meter: new Meter() })
    const traces: string[] = []
    await runAgent({
      task: 't',
      cwd,
      decider,
      generator: noopGenerator,
      maxSteps: 3,
      maxWallMs: 0,
      onTrace: (l) => traces.push(l),
    })
    assert.ok(
      traces.some((l) => /budget reached/.test(l) && /budget_wall/.test(l)),
      `轨迹里要能看出停在哪条上限上，实际：${JSON.stringify(traces)}`,
    )
  })
})

test('★ 边界说清楚：上限是**刹车**，不是「绝不超支」', async () => {
  /*
    检查在每步开始前做，所以**已经开跑的那一步一定会跑完** —— 包括它那次
    判定请求。这条测试把这个边界钉死，而且用的是**确定性**的构造，不靠机器快慢：

      判定后端每次 `decide` 睡 20ms，上限设 5ms。
      ⇒ 第一步开始时还没越线（0ms < 5ms），于是它跑；
        跑完已经过了 20ms ⇒ 第二步不再开。

    `steps === 1` 是必然的，不是「多半」。把它写成断言，是为了不让
    「现在有花费上限了」在某天被读成「不可能超支」—— 请求发出去就收不回来。
  */
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const slow = keepsGoing()
    const slowProvider = {
      name: 'slow',
      decide: async (req: Parameters<typeof slow.decide>[0]) => {
        await new Promise((r) => setTimeout(r, 20))
        return slow.decide(req)
      },
    }
    const decider = new Decider({ provider: slowProvider, meter: new Meter() })
    const r = await runAgent({ task: 't', cwd, decider, generator: noopGenerator, maxSteps: 5, maxWallMs: 5 })
    assert.equal(r.steps, 1, '★ 第一步一定跑完（它开始时还没越线），第二步不再开')
    assert.match(r.halt, /^budget_wall:5ms/, '而 halt 里说清是撞了墙钟上限')
  })
})

test('上限的判定用的是 meter 的真实账，不是另算一份', async () => {
  await withTmp(async (cwd) => {
    for (const f of ['a.txt', 'b.txt', 'c.txt', 'd.txt', 'e.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const meter = new Meter()
    const decider = new Decider({ provider: keepsGoing(), meter })
    // 上限给得很宽 ⇒ 不该被撞上
    const r = await runAgent({
      task: 't',
      cwd,
      decider,
      generator: noopGenerator,
      maxSteps: 2,
      maxWallMs: 60_000,
      maxModelCalls: 99,
      maxTokens: 1_000_000,
    })
    assert.match(r.halt, /^max_steps/, '宽松的上限不该改变行为')
  })
})
