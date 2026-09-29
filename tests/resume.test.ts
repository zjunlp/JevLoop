/**
 * 从最后一个可恢复的步骤接着跑（TODO §10）
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件要证的是**接着跑**，不是「折一个对象出来」
 * ═══════════════════════════════════════════════════════════
 *
 * 所以最后一条是端到端的：真的跑一轮、让它撞上 `max_steps` 停下、从它的日志
 * 折出恢复点、再跑一轮 —— 并断言第二轮**是从第 2 步开始的**，而不是从头再来。
 *
 * ★ 另外三条钉的是**拒绝**。恢复最危险的做法不是失败，是**猜**：
 *   猜一个空任务、猜那半步做过了、或者把一个已经做完的轮次再跑一遍。
 *
 * @module JevLoop/resume.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { resumePointFrom } from '../src/resume.ts'
import { runAgent } from '../src/agent.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import { mkdtemp, writeFile, rm } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
import type { AgentEvent } from '../src/events.ts'
import type { Answer, AnswerSet } from '../src/vocab.ts'
import type { AgentCtx } from '../src/frame.ts'

const start = (task: string, cwd: string) => ({ type: 'run:start', task, cwd, at: 0 })
const call = (step: number, tool: string, input: string) => ({ type: 'tool:call', step, tool, input })
const result = (step: number, tool: string, output: string) => ({ type: 'tool:result', step, tool, output, ms: 1 })

// ═══════════════════════════════════════════════════════════
// ① 折出状态
// ═══════════════════════════════════════════════════════════

test('★ 折出 history / files / readFiles，步号接在最后一步之后', () => {
  const out = resumePointFrom([
    start('读一下这些文件', '/w'),
    call(0, 'list_dir', '.'),
    result(0, 'list_dir', 'alpha.ts\nbeta.ts\nsub/'),
    call(1, 'read_file', 'alpha.ts'),
    result(1, 'read_file', 'export function totalOf() {}'),
  ])
  assert.equal(out.ok, true)
  if (!out.ok) return
  const s = out.state
  assert.equal(s.task, '读一下这些文件')
  assert.equal(s.cwd, '/w')
  assert.deepEqual(
    s.history.map((h) => h.step),
    [0, 1],
  )
  assert.equal(s.history[1]!.result, 'export function totalOf() {}')
  // ★ 口径与 loop 一致：目录不进 files
  assert.deepEqual(s.files, ['alpha.ts', 'beta.ts'])
  assert.deepEqual(s.readFiles, ['alpha.ts'])
  assert.equal(s.step, 2, '下一个该跑的是第 2 步')
  assert.equal(s.inFlight, undefined)
})

test('★ 只认**最后一轮**：会话文件可以装好几轮', () => {
  const out = resumePointFrom([
    start('第一轮', '/w'),
    call(0, 'list_dir', '.'),
    result(0, 'list_dir', 'old.ts'),
    { type: 'run:end', halt: 'agent_done', steps: 1, answer: 'ok', stats: {} },
    start('第二轮', '/w2'),
    call(0, 'list_dir', '.'),
    result(0, 'list_dir', 'new.ts'),
  ])
  assert.equal(out.ok, true)
  if (!out.ok) return
  assert.equal(out.state.task, '第二轮', '接着跑接着的永远是最后那一轮')
  assert.equal(out.state.cwd, '/w2')
  assert.deepEqual(out.state.files, ['new.ts'])
  assert.deepEqual(out.state.history.map((h) => h.tool), ['list_dir'])
})

// ═══════════════════════════════════════════════════════════
// ② 拒绝 —— 恢复最危险的失败方式是猜
// ═══════════════════════════════════════════════════════════

test('★★ 没有 `run:start` ⇒ 拒绝，不返回一个空任务的状态', () => {
  const out = resumePointFrom([call(0, 'list_dir', '.'), result(0, 'list_dir', 'a.ts')])
  assert.equal(out.ok, false)
  if (out.ok) return
  assert.match(out.why, /run:start/)
})

test('★★ 任务**做完了**（`agent_done`）⇒ 拒绝，不重跑一遍', () => {
  const out = resumePointFrom([
    start('t', '/w'),
    call(0, 'list_dir', '.'),
    result(0, 'list_dir', 'a.ts'),
    { type: 'run:end', halt: 'agent_done', steps: 1, answer: 'done', stats: {} },
  ])
  assert.equal(out.ok, false)
  if (out.ok) return
  assert.match(out.why, /agent_done/)
})

test('★★★ 因为 `max_steps` 停下的那一轮**可以**恢复 —— 它正是最该接着跑的', () => {
  const out = resumePointFrom([
    start('t', '/w'),
    call(0, 'list_dir', '.'),
    result(0, 'list_dir', 'a.ts'),
    { type: 'run:end', halt: 'max_steps', steps: 1, answer: '部分', stats: {} },
  ])
  assert.equal(out.ok, true, '撞上限而停不是「做完了」，不该拒绝恢复')
})

// ═══════════════════════════════════════════════════════════
// ③ ★ 死在半步中间：副作用**未知**，不许装作知道
// ═══════════════════════════════════════════════════════════

test('★★★ 最后一步只有 `tool:call` 没有 `tool:result` ⇒ 不进 history、步号停在它、并且**报出来**', () => {
  const out = resumePointFrom([
    start('t', '/w'),
    call(0, 'list_dir', '.'),
    result(0, 'list_dir', 'a.ts'),
    // 进程死在这一步执行中间：写没写下去，日志没说
    call(1, 'write_file', 'a.ts\n新内容'),
  ])
  assert.equal(out.ok, true)
  if (!out.ok) return
  assert.deepEqual(
    out.state.history.map((h) => h.step),
    [0],
    '★ 半步不许进 history —— 放进去等于宣称它成功了',
  )
  assert.equal(out.state.step, 1, '★ 恢复点停在它那一步，于是它会重跑')
  assert.deepEqual(out.state.inFlight, { step: 1, tool: 'write_file', input: 'a.ts\n新内容' })
})

test('★ 中间有一步缺结果时，**后面**的步骤也不再采信（那一轮已经乱了）', () => {
  const out = resumePointFrom([
    start('t', '/w'),
    call(0, 'read_file', 'a.ts'),
    call(1, 'read_file', 'b.ts'),
    result(1, 'read_file', 'B'),
  ])
  assert.equal(out.ok, true)
  if (!out.ok) return
  assert.deepEqual(out.state.history.map((h) => h.step), [], '第 0 步缺结果，整条链不采信')
  assert.equal(out.state.inFlight?.step, 0)
})

// ═══════════════════════════════════════════════════════════
// ④ 端到端：真的接着跑
// ═══════════════════════════════════════════════════════════

/**
 * 一个总选「第一个候选」、而且**不肯说做完**的判定后端。
 *
 * ★ `done` 必须压低：给 0.95 的话 `is_done` 第一步之后就判 finish，于是整轮
 *   一步就结束了 —— 第一版实测就是这样，撞不到 `maxSteps`，测试的前提不成立。
 *   `unsupported` 也要低，否则最后一轮会被交付闸门打回（halt 变成 `…+revise`）。
 */
const firstOption = {
  name: 'first',
  decide: async (req: { questions: Record<string, { type: string; criteria?: Record<string, string> }> }) => {
    const answers: AnswerSet = {}
    for (const [id, q] of Object.entries(req.questions)) {
      if (q.type === 'noul') {
        const v = id === 'needs_auth' || id === 'done' || id === 'unsupported' ? 0.1 : 0.95
        answers[id] = { type: 'noul', noul: v } as Answer
      }
      else if (q.type === 'score') {
        answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.95 } as Answer
      } else {
        const options = Object.keys(q.criteria ?? {})
        const choice = options[0] ?? ''
        answers[id] = {
          type: 'choice',
          choice,
          probabilities: Object.fromEntries(
            options.map((o) => [o, o === choice ? 0.95 : 0.05 / Math.max(1, options.length - 1)]),
          ),
          confidence: 0.95,
        } as Answer
      }
    }
    return { answers, latencyMs: 0, provider: 'first' }
  },
}

const noopGenerator = {
  name: 'noop',
  generate: async () => ({ text: '答案', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'noop' }),
}

test('★★★ 端到端：撞上 maxSteps 停下 → 折日志 → 接着跑，而且**步号接着数**', async () => {
  const cwd = await mkdtemp(join(tmpdir(), 'jevloop-resume-'))
  try {
    await writeFile(join(cwd, 'alpha.ts'), 'export function totalOf() {}', 'utf8')

    const first: AgentEvent[] = []
    const r1 = await runAgent({
      task: '看一下 alpha.ts',
      cwd,
      decider: new Decider({ provider: firstOption, meter: new Meter() }),
      generator: noopGenerator,
      // ★ `null` = 明确不要写入（见 AgentOptions.provideWriteInput）。
      //   缺省会给一个「用生成器产出内容」的来源，而那会把测试的临时目录写花。
      provideWriteInput: null,
      maxSteps: 2,
      onEvent: (e) => first.push(e),
    })
    assert.match(String(r1.halt), /max_steps/, '前提：第一轮要因为撞上限而停')
    assert.ok(first.some((e) => e.type === 'tool:call'), '第一轮要真的做过一步')

    const folded = resumePointFrom(first)
    assert.equal(folded.ok, true, `折日志应当成功：${folded.ok ? '' : folded.why}`)
    if (!folded.ok) return
    const seen: AgentEvent[] = []

    const r2 = await runAgent({
      task: '看一下 alpha.ts',
      cwd,
      resume: folded.state,
      decider: new Decider({ provider: firstOption, meter: new Meter() }),
      generator: noopGenerator,
      provideWriteInput: null,
      maxSteps: 4,
      onEvent: (e) => seen.push(e),
    })

    assert.ok(folded.state.step > 0, '第一轮做过的步数要 > 0')
    const firstStep = seen.find((e) => e.type === 'tool:call' || e.type === 'decision')
    assert.ok(firstStep, '第二轮要有事件')
    assert.ok(
      (firstStep as { step: number }).step >= folded.state.step,
      `★ 第二轮必须从第 ${folded.state.step} 步接着数，实际从第 ${(firstStep as { step: number }).step} 步`,
    )
    assert.ok(r2.answer.length > 0, '第二轮要能产出答案')
  } finally {
    await rm(cwd, { recursive: true, force: true })
  }
})

test('★★ 恢复点与本次调用对不上 ⇒ **抛**，不是悄悄挑一个', async () => {
  const resume = {
    task: '甲任务',
    cwd: '/w',
    step: 1,
    history: [],
    files: [],
    readFiles: [],
  }
  await assert.rejects(
    () =>
      runAgent({
        task: '乙任务', // ★ 与恢复点不一致
        cwd: '/w',
        resume,
        decider: new Decider({ provider: firstOption, meter: new Meter() }),
        generator: noopGenerator,
        maxSteps: 1,
      }),
    /对不上/,
    '两个任务对不上时必须停下来问，而不是挑一个跑',
  )
})

test('★ 恢复点里的 history / files 真的进了 ctx（不是只传了个步号）', () => {
  const s = resumePointFrom([
    start('t', '/w'),
    call(0, 'list_dir', '.'),
    result(0, 'list_dir', 'seen.ts'),
    call(1, 'read_file', 'seen.ts'),
    result(1, 'read_file', 'content'),
  ])
  assert.equal(s.ok, true)
  if (!s.ok) return
  // 折出来的状态就是 AgentCtx 的子集，形状必须对得上
  const ctx: Pick<AgentCtx, 'task' | 'cwd' | 'files' | 'readFiles' | 'history'> = s.state
  assert.deepEqual(ctx.files, ['seen.ts'])
  assert.deepEqual(ctx.readFiles, ['seen.ts'])
  assert.equal(ctx.history?.length, 2)
})
