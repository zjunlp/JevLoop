/**
 * 记账：**判定的 token 也要算进去**（TODO §9）
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件要钉住的是三个数，以及一个「不许装作知道」
 * ═══════════════════════════════════════════════════════════
 *
 * ① 判定花的 token 进总数 —— 在那之前只统计模型调用，于是一条判定占大头的
 *    运行（托管 Jev 就是）**没有被它真正花的 token 框住**。
 * ② ★ 求和**按批次去重**。一次 `askMany` 把若干节点合并成**一次前向**，
 *    那一批的每条记录都带同一份 `usage`；按记录求和会把它乘以路数 ——
 *    和 `decisionMs` 那个 3.31s 的事故是**同一个形状**，只是错在 token 上。
 * ③ 封顶看的是**总数**：判定token 单独把 `maxTokens` 撞线也要停机。
 * ④ 后端**没报** usage 时按 0 计，但要说出来（`decisionBatchesWithoutUsage`）。
 *    0 分的意思是「没花钱」，不能拿它冒充「不知道」——否则一个漏报的后端
 *    看起来是免费的，而封顶正好建在这个数上。
 *
 * @module JevLoop/meter-tokens.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { buildDecisions } from '../src/decisions.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import { runAgent } from '../src/agent.ts'
import type { AgentCtx } from '../src/frame.ts'
import type { Answer, AnswerSet } from '../src/vocab.ts'
import type { DecideRequest } from '../src/seam-provider.ts'

const CTX: AgentCtx = { task: 't', cwd: '/w', draft: 'a' }

/** 一个把 usage 如实报出来的后端 */
function usageProvider(input_tokens: number | undefined, output_tokens: number | undefined) {
  return {
    name: 'usage',
    decide: async (req: DecideRequest) => {
      const answers: AnswerSet = {}
      for (const [id, q] of Object.entries(req.questions)) {
        if (q.type === 'noul') answers[id] = { type: 'noul', noul: id === 'needs_auth' ? 0.1 : 0.9 } as Answer
        else if (q.type === 'score') {
          answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.9 } as Answer
        } else {
          // ★ 必须**挑一个真选项**：答空串会让 loop 停在 `input_unclear`，
          //   于是端到端那条根本走不到预算检查那一步（第一版实测就是这样）
          const options = Object.keys(q.criteria ?? {})
          const choice = options[0] ?? ''
          answers[id] = {
            type: 'choice',
            choice,
            probabilities: Object.fromEntries(options.map((o) => [o, o === choice ? 0.9 : 0.1 / Math.max(1, options.length - 1)])),
            confidence: 0.9,
          } as Answer
        }
      }
      return {
        answers,
        provider: 'usage',
        latencyMs: 1,
        ...(input_tokens !== undefined || output_tokens !== undefined
          ? {
              usage: {
                ...(input_tokens !== undefined ? { input_tokens } : {}),
                ...(output_tokens !== undefined ? { output_tokens } : {}),
              },
            }
          : {}),
      }
    },
  }
}

/** 用真实路径产出**一条** DecisionResult（单条口径的断言用它） */
async function oneDecision(provider: ReturnType<typeof usageProvider>, meter: Meter) {
  const specs = buildDecisions()
  const decider = new Decider({ provider, meter })
  return decider.decide(specs.stepOk, CTX)
}

/** 用真实路径产出两条 DecisionResult，用来喂记账 */
async function twoDecisions(provider: ReturnType<typeof usageProvider>, meter: Meter) {
  const specs = buildDecisions()
  const decider = new Decider({ provider, meter })
  return {
    a: await decider.decide(specs.stepOk, CTX),
    b: await decider.decide(specs.isDone, CTX),
  }
}

// ═══════════════════════════════════════════════════════════
// ① 判定 token 进总数
// ═══════════════════════════════════════════════════════════

test('★ 判定报的 token 进总数 —— 在那之前它只统计模型调用', async () => {
  const meter = new Meter()
  const a = await oneDecision(usageProvider(300, 40), meter)
  const s = meter.stats
  assert.equal(s.decisions, 1)
  assert.equal(s.decisionInputTokens, 300, '判定的输入 token 要被记下')
  assert.equal(s.decisionOutputTokens, 40)
  assert.equal(s.inputTokens, 300, '总数里要有它（这里没有模型调用）')
  assert.equal(s.outputTokens, 40)
  assert.equal(a.inputTokens, 300, '逐条记录上也留着，便于追溯')
})

test('★★ 生成 + 判定 = 总数，两边各自的数也单列', async () => {
  const meter = new Meter()
  meter.recordModelCall(0, { kind: 'gen', latencyMs: 5, inputTokens: 1000, outputTokens: 200 })
  await oneDecision(usageProvider(300, 40), meter)
  const s = meter.stats
  assert.equal(s.generationInputTokens, 1000)
  assert.equal(s.generationOutputTokens, 200)
  assert.equal(s.decisionInputTokens, 300)
  assert.equal(s.decisionOutputTokens, 40)
  assert.equal(s.inputTokens, 1300, '★ 总数 = 生成 + 判定')
  assert.equal(s.outputTokens, 240)
})

// ═══════════════════════════════════════════════════════════
// ② ★ 按批去重 —— 这个文件里最要紧的一条
// ═══════════════════════════════════════════════════════════

test('★★★ 合并判定：一次前向的 token **只算一次**，不按记录数乘', async () => {
  /*
    ★ 一次 `askMany` 把若干节点合并成一次请求，`decide.ts` 于是把**同一份**
      `usage` 写在那一批的**每条**记录上（逐条记是对的：每条都要能单独追溯）。

      但**求和必须按 `batch` 去重**。按记录求和会把它乘以合并的路数 ——
      这正是 `decisionMs` 上发生过的那个事故（3.31s > 整轮墙钟 3.29s），
      只是这次错在 token 上。所以这条断言是「两条记录、一次请求、一份 token」。
  */
  const meter = new Meter()
  const { a, b } = await twoDecisions(usageProvider(500, 50), meter)
  // 重记到一个干净的记账本上，并**强制同一个批次号** —— 模拟一次合并前向
  const merged = new Meter()
  const batch = merged.nextBatch()
  merged.recordDecision(0, a, batch)
  merged.recordDecision(0, b, batch)

  const s = merged.stats
  assert.equal(s.decisions, 2, '两条记录（两个节点）')
  assert.equal(s.decisionInputTokens, 500, `★ 只能是 500，按记录求和会得到 1000`)
  assert.equal(s.decisionOutputTokens, 50, '★ 只能是 50，不是 100')
})

test('★★ 反向：不同批次的 token **要**累加 —— 去重不是「只看第一条」', async () => {
  const meter = new Meter()
  const { a, b } = await twoDecisions(usageProvider(500, 50), meter)
  const two = new Meter()
  two.recordDecision(0, a, two.nextBatch())
  two.recordDecision(0, b, two.nextBatch())
  const s = two.stats
  assert.equal(s.decisions, 2)
  assert.equal(s.decisionInputTokens, 1000, '两次请求就是两份 token')
  assert.equal(s.decisionOutputTokens, 100)
})

// ═══════════════════════════════════════════════════════════
// ③ 漏报：按 0 计，但要说出来
// ═══════════════════════════════════════════════════════════

test('★★ 后端没报 usage ⇒ 按 0 计，但**批次数**要报出来（它是下界）', async () => {
  const meter = new Meter()
  // 只报一个空的 usage：两个字段都没有 ⇒ 等于没报
  const provider = {
    name: 'silent',
    decide: async (req: DecideRequest) => {
      const answers: AnswerSet = {}
      for (const [id, q] of Object.entries(req.questions)) {
        if (q.type === 'noul') answers[id] = { type: 'noul', noul: 0.9 } as Answer
        else if (q.type === 'score') {
          answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.9 } as Answer
        } else answers[id] = { type: 'choice', choice: '', probabilities: {}, confidence: 0.9 } as Answer
      }
      return { answers, provider: 'silent', latencyMs: 1, usage: {} }
    },
  }
  await oneDecision(provider as ReturnType<typeof usageProvider>, meter)
  const s = meter.stats
  assert.equal(s.decisionInputTokens, 0)
  assert.equal(
    s.decisionBatchesWithoutUsage,
    1,
    '★ 一个批次没报 usage —— 不说出来的话，这个后端看起来是免费的',
  )
})

test('★ 报了 usage 就不该记进「漏报」（否则那个计数是噪音）', async () => {
  const meter = new Meter()
  await oneDecision(usageProvider(1, 1), meter)
  assert.equal(meter.stats.decisionBatchesWithoutUsage, 0)
})

// ═══════════════════════════════════════════════════════════
// ④ 封顶覆盖判定 token
// ═══════════════════════════════════════════════════════════

test('★★★ 端到端：光靠**判定**的 token 就能把 maxTokens 撞线', async () => {
  /*
    ★ 这就是 §9 那句话的验收：一条判定占大头的运行，必须被它真正花的 token
      框住，而不是只被墙钟和调用次数框住。

      生成器报 0 token，判定后端每次报 1000 —— 于是撞线的只能是判定那部分。
  */
  const provider = usageProvider(1000, 0)
  let genCalls = 0
  const result = await runAgent({
    task: 't',
    cwd: '/w',
    decider: new Decider({ provider: provider as ReturnType<typeof usageProvider>, meter: new Meter() }),
    generator: {
      name: 'free',
      generate: async () => {
        genCalls++
        return { text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'free' }
      },
    },
    // 一次判定就 1000 ⇒ 第二步开始前必然越线
    maxTokens: 1500,
    maxSteps: 5,
  })
  assert.match(
    String(result.halt),
    /^budget_tokens/,
    `★ 判定 token 必须能撞线，实际 halt=${result.halt}`,
  )
  assert.ok(genCalls <= 2, `生成器不该被反复调用到上限，实际 ${genCalls} 次`)
})

test('★ 封顶把生成与判定的 token 加在一起看（两边各一半也能撞线）', async () => {
  const meter = new Meter()
  meter.recordModelCall(0, { kind: 'gen', latencyMs: 1, inputTokens: 400, outputTokens: 0 })
  await oneDecision(usageProvider(400, 0), meter)
  const s = meter.stats
  assert.equal(s.inputTokens, 800, '两边加起来才是总数')
  assert.ok(s.inputTokens > 700, '封顶比较的就是这个数')
})
