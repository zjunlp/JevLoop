/**
 * 决策记录与重放（TODO §12 最后一项）。
 *
 * ═══════════════════════════════════════════════════════════
 * 这一节的核心是**跑一次真 loop、抓真事件、验真记录**
 * ═══════════════════════════════════════════════════════════
 *
 * 手搓一条记录来验验证器，测的是「验证器能不能验我搓的那条」—— 而不是
 * 「真跑出来的记录能不能验」。所以下面用 `runAgent` + 一个脚本化判定后端真的
 * 跑一轮，把 `decision` 事件收下来，再逐条验。
 *
 * ★ 三种记录都要覆盖，因为它们的结论**本来就不同**：
 *
 *     单节点判定      三项检查全做 ⇒ `verified`
 *     合并判定        节点自己那份帧重不了 ⇒ `partial`（**不是失败**）
 *     旧日志（缺字段） 一条都做不了 ⇒ `unverifiable`（**不是通过**）
 *
 * ★ 还有一条是**诚实性**测试：验证器必须把「验证不了什么」写出来。少了它，
 *   「可重放」会被读成「可复现」「可判对错」—— 而这两件事它都给不了。
 *
 * @module JevLoop/replay-schema.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { REPLAY_NOTES, REPLAY_SCHEMA, recordOf, type ReplayRecord } from '../src/replay-schema.ts'
import { verifyRecord } from '../src/replay-verify.ts'
import { runAgent } from '../src/agent.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import { frameDigest, requestDigest } from '../src/frame-digest.ts'
import type { AgentEvent } from '../src/events.ts'
import type { Answer, AnswerSet } from '../src/vocab.ts'

/** 一个让 loop 正常往下走的判定后端 */
function scripted() {
  return {
    name: 'scripted',
    decide: async (req: { questions: Record<string, { type: string; criteria?: unknown }> }) => {
      const answers: AnswerSet = {}
      for (const [id, q] of Object.entries(req.questions)) {
        const no = ['needs_auth', 'unsupported', 'done'].includes(id)
        if (q.type === 'noul') answers[id] = { type: 'noul', noul: no ? 0.05 : 0.95 } as Answer
        else if (q.type === 'score') answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.9 } as Answer
        else {
          const options = Object.keys((q as { criteria: Record<string, string> }).criteria)
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
      return { answers, latencyMs: 0, provider: 'scripted' }
    },
  }
}

/** 真跑一轮，把事件收下来 */
async function realEvents(): Promise<AgentEvent[]> {
  const cwd = await mkdtemp(join(tmpdir(), 'jevloop-replay-'))
  try {
    for (const f of ['a.txt', 'b.txt']) await writeFile(join(cwd, f), 'x', 'utf8')
    const events: AgentEvent[] = []
    await runAgent({
      task: '看看这个目录里有什么',
      cwd,
      decider: new Decider({ provider: scripted(), meter: new Meter() }),
      generator: {
        name: 'noop',
        generate: async () => ({ text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'noop' }),
      },
      maxSteps: 3,
      onEvent: (e) => events.push(e),
    })
    return events
  } finally {
    await rm(cwd, { recursive: true, force: true })
  }
}

const records = (events: AgentEvent[]): ReplayRecord[] =>
  events.map((e) => recordOf(e)).filter((r): r is ReplayRecord => r !== null)

// ═══════════════════════════════════════════════════════════
// ① 真记录：每一类都得到它该得的结论
// ═══════════════════════════════════════════════════════════

test('★★ 真跑一轮：每条判定记录都自洽 —— 没有一条 mismatch', async () => {
  const recs = records(await realEvents())
  assert.ok(recs.length > 0, '应当收到判定记录')
  const bad = recs.map((r) => ({ r, v: verifyRecord(r) })).filter((x) => x.v.status === 'mismatch')
  assert.deepEqual(
    bad.map((x) => `${x.r.node}: ${x.v.checks.find((c) => c.outcome === 'fail')?.detail}`),
    [],
    '真跑出来的记录不该有不自洽的',
  )
})

test('★★ 合并判定得到 `partial`，而且**说清**哪项检查做不了 —— 不是假失败', async () => {
  const events = await realEvents()
  const recs = records(events)
  const merged = recs.filter((r) => r.batchIds.length > 1)
  assert.ok(merged.length > 0, '`needsTool + pickTool` 每步都合并，应当有合并记录')

  for (const r of merged) {
    const v = verifyRecord(r)
    assert.equal(v.status, 'partial', `合并判定 '${r.node}' 应当是 partial，实际 ${v.status}`)
    const frameCheck = v.checks.find((c) => c.what === 'frame-solo')!
    assert.equal(frameCheck.outcome, 'skipped')
    assert.match(frameCheck.detail, /合并/, '要说清是因为合并才做不了')
    // 请求指纹那一项**是**能验的 —— 这正是新加 sentFrameDigest 的意义
    assert.equal(v.checks.find((c) => c.what === 'request')!.outcome, 'pass')
  }
})

test('单节点判定得到 `verified`，三项检查全做', async () => {
  const recs = records(await realEvents())
  const solo = recs.filter((r) => r.batchIds.length === 1)
  assert.ok(solo.length > 0, '生成后那几个判定是单节点的')
  for (const r of solo) {
    const v = verifyRecord(r)
    assert.equal(v.status, 'verified', `'${r.node}' 应当是 verified，实际 ${v.status}：${JSON.stringify(v.checks)}`)
    assert.ok(v.checks.every((c) => c.outcome === 'pass'), '三项都该有结论')
  }
})

test('★ 单节点时 `sentFrameDigest` 等于该节点自己的帧指纹', async () => {
  const recs = records(await realEvents())
  for (const r of recs.filter((x) => x.batchIds.length === 1)) {
    assert.equal(r.sentFrameDigest, r.frameDigest, `'${r.node}' 单节点时两者必须相等`)
  }
})

test('★ 合并时 `sentFrameDigest` **不等于**任何单个节点的帧指纹 —— 这就是要单独记它的原因', async () => {
  const recs = records(await realEvents())
  const merged = recs.filter((r) => r.batchIds.length > 1)
  for (const r of merged) {
    assert.notEqual(
      r.sentFrameDigest,
      r.frameDigest,
      `'${r.node}' 合并时两者相等反而说明记录错了（合成帧 ≠ 该节点的帧）`,
    )
  }
})

// ═══════════════════════════════════════════════════════════
// ② 篡改：必须报 mismatch，而且指得出哪一项
// ═══════════════════════════════════════════════════════════

test('★★ 改掉 state ⇒ mismatch（手改过的日志不能当证据用）', async () => {
  const recs = records(await realEvents())
  const solo = recs.find((r) => r.batchIds.length === 1)!
  const tampered: ReplayRecord = { ...solo, state: { ...solo.state, task: '被改过的任务' } }
  const v = verifyRecord(tampered)
  assert.equal(v.status, 'mismatch')
  const fail = v.checks.find((c) => c.outcome === 'fail')!
  assert.equal(fail.what, 'frame-solo')
})

test('★★ 改掉**合并**记录的 state 也要被发现 —— 第一版这里漏了，CLI 实测才发现', async () => {
  /*
    ★ 这条测试是被一次**真跑**逼出来的：第一版对合并记录只报「合成帧指纹是多少」，
      不重算（我以为重算不了）。于是把一条合并记录的 `state` 改掉之后，
      `npm run replay` 照样报 0 mismatch、退出码 0 —— 而改 state 正是重放要抓的事。

      合并帧的指纹就是 `frameDigest(batchIds.join('+'), state)`，而两者记录里都有。
      所以这一项**必须**重算。
  */
  const recs = records(await realEvents())
  const merged = recs.find((r) => r.batchIds.length > 1)!
  const tampered: ReplayRecord = { ...merged, state: { ...merged.state, task: '被改过的任务' } }
  const v = verifyRecord(tampered)
  assert.equal(v.status, 'mismatch', '合并记录的 state 被改必须被发现')
  assert.equal(v.checks.find((c) => c.outcome === 'fail')!.what, 'sent-frame')
})

test('★★ 改掉**单节点**记录的 state 也要被发现', async () => {
  const recs = records(await realEvents())
  const solo = recs.find((r) => r.batchIds.length === 1)!
  const tampered: ReplayRecord = { ...solo, state: { ...solo.state, task: '被改过的任务' } }
  const v = verifyRecord(tampered)
  assert.equal(v.status, 'mismatch')
})

test('★★ 改掉**实际发出去的**问题集 ⇒ mismatch（换掉候选集必须被发现 —— §8.17 骗过我们一次的地方）', async () => {
  const recs = records(await realEvents())
  // 请求指纹覆盖的是 `sentQuestions` —— 换掉里面的候选集必须被发现
  const withChoice = recs.find((r) =>
    Object.values(r.sentQuestions).some((q) => (q as { type?: string }).type === 'choice'),
  )
  assert.ok(withChoice, '应当有带 choice 的判定')
  const qid = Object.keys(withChoice.sentQuestions).find(
    (k) => (withChoice.sentQuestions[k] as { type?: string }).type === 'choice',
  )!
  const q = withChoice.sentQuestions[qid] as { criteria: Record<string, string> }
  const tampered: ReplayRecord = {
    ...withChoice,
    sentQuestions: { ...withChoice.sentQuestions, [qid]: { ...q, criteria: { ...q.criteria, 伪造的候选: '假的' } } },
  }
  const v = verifyRecord(tampered)
  assert.equal(v.status, 'mismatch', '换掉候选集必须换请求指纹')
  assert.equal(v.checks.find((c) => c.outcome === 'fail')!.what, 'request')
})

test('★ 单节点记录里改掉 `questions`（节点自己那份）也会被发现', async () => {
  /*
    ★ 这一条补的是一个**真的洞**：`requestDigest` 覆盖的是 `sentQuestions`，
      所以单节点记录里被人改过的 `questions` 不会被请求指纹抓到。单节点时两者
      必须相等，这一项就是那个约束。
  */
  const recs = records(await realEvents())
  const solo = recs.find((r) => r.batchIds.length === 1)!
  const qid = Object.keys(solo.questions)[0]!
  const tampered: ReplayRecord = {
    ...solo,
    questions: { ...solo.questions, [qid]: { type: 'noul', instructions: '被改过的问题' } },
  }
  const v = verifyRecord(tampered)
  assert.equal(v.status, 'mismatch')
  assert.equal(v.checks.find((c) => c.outcome === 'fail')!.what, 'questions-solo')
})

test('改掉 requestDigest ⇒ mismatch', async () => {
  const recs = records(await realEvents())
  const r = recs[0]!
  const v = verifyRecord({ ...r, requestDigest: 'deadbeefdeadbeef' })
  assert.equal(v.status, 'mismatch')
})

test('单节点时 frameDigest 与 sentFrameDigest 不一致 ⇒ mismatch', async () => {
  const recs = records(await realEvents())
  const solo = recs.find((r) => r.batchIds.length === 1)!
  const v = verifyRecord({ ...solo, sentFrameDigest: 'deadbeefdeadbeef' })
  assert.equal(v.status, 'mismatch')
  assert.equal(v.checks.find((c) => c.outcome === 'fail')!.what, 'sent-frame')
})

// ═══════════════════════════════════════════════════════════
// ③ 旧日志 / 缺字段：`unverifiable`，**不是通过**
// ═══════════════════════════════════════════════════════════

test('★ 旧记录（没有 sentFrameDigest / batchIds）⇒ unverifiable，不崩也不当成通过', () => {
  // 模拟这次改动**之前**落盘的日志：那两个字段还不存在
  const legacy = {
    type: 'decision',
    step: 1,
    id: 'loop.stepOk',
    state: { output: '某次工具输出' },
    frame: { digest: frameDigest('loop.stepOk', { output: '某次工具输出' }) },
    requestDigest: requestDigest(frameDigest('loop.stepOk', { output: '某次工具输出' }), { ok: { type: 'noul', instructions: 'x' } }),
    questions: { ok: { type: 'noul', instructions: 'x' } },
    answers: { ok: { type: 'noul', noul: 0.9 } },
  }
  const rec = recordOf(legacy)
  assert.ok(rec, '旧事件仍然要能被读成记录 —— 缺字段不等于读不了')

  const v = verifyRecord(rec)
  assert.equal(v.status, 'partial', 'frame-solo 那一项还能做（无 batchIds ⇒ 按单节点算）')
  assert.equal(
    v.checks.find((c) => c.what === 'request')!.outcome,
    'skipped',
    '缺 sentFrameDigest ⇒ 请求指纹那一项做不了，要说清',
  )

  // 连 frame 都没有的旧记录 ⇒ 一条都做不了
  const bare = recordOf({ type: 'decision', step: 1, id: 'loop.stepOk', state: {}, questions: {} })!
  assert.equal(verifyRecord(bare).status, 'unverifiable')
})

test('recordOf 对非判定事件、坏形状一律返回 null（不抛）', () => {
  for (const bad of [
    null,
    undefined,
    42,
    'x',
    {},
    { type: 'run:start' },
    { type: 'decision' }, // 没有 state / questions
    { type: 'decision', state: {}, questions: {} }, // 没有 id / step
    { type: 'decision', step: 1, id: 'a', state: 'not-an-object', questions: {} },
  ]) {
    assert.equal(recordOf(bad), null, `${JSON.stringify(bad)} 应当被拒`)
  }
})

// ═══════════════════════════════════════════════════════════
// ④ 诚实性：必须说清验证不了什么
// ═══════════════════════════════════════════════════════════

test('★★ 每条结论都带上「验证不了什么」，而且那三条都在', async () => {
  const recs = records(await realEvents())
  const v = verifyRecord(recs[0]!)
  assert.deepEqual([...v.notes], [...REPLAY_NOTES], '结论里的注意事项就是格式级那一份')

  const text = REPLAY_NOTES.join('\n')
  assert.match(text, /原始 ctx/, '要说清：不验证帧是从原始状态编出来的')
  assert.match(text, /oracle/, '要说清：不验证判定对不对')
  assert.match(text, /answers/, '要说清：不核对答案')
})

test('格式有版本号 —— 读不懂的记录要能拒绝', () => {
  assert.equal(REPLAY_SCHEMA, 'decision-record/v1')
  assert.match(REPLAY_SCHEMA, /\/v\d+$/, '版本号长在格式名上，和 `DECISION.md` 的 schema 同一个理由')
})

test('记录里带齐了解释「为什么两次不同」所需要的字段', async () => {
  const recs = records(await realEvents())
  for (const r of recs) {
    assert.equal(typeof r.step, 'number')
    assert.ok(r.node)
    assert.ok(r.provider, '谁答的 —— 两次不同时第一件要看的就是它')
    assert.equal(typeof r.answers, 'object')
  }
})
