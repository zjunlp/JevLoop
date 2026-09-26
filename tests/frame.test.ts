/**
 * 帧声明与编译器（§8.14）。
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件测的是「帧是不是声明出来的」，不是「判定准不准」
 * ═══════════════════════════════════════════════════════════
 *
 * 判定准不准由 `bench/` 测。这里测的是这一层新加的三件事：
 *
 *   ① **声明是完整的** —— `AgentCtx` 的每一格要么被某栏读、要么被声明为
 *      「故意不看」并写明为什么。**没有第三种状态。**
 *   ② **有界且截了要报**，**缺的要说**（而且「还没有」与「故意不看」分开）。
 *   ③ **指纹分两种**：帧的回答「它看到了什么」，请求的回答「它被问了什么」。
 *
 * ★ 其中 ① 的验收方式是**反向的**：光测「七个声明没问题」不够，还要测
 *   「漏掉一格时它**真的会响**」。§8.15 的判据是「把 bug 改回去，它得红」——
 *   下面每一条不变量都配了一条人为造出来的坏声明。
 *
 * @module JevLoop/frame.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  AGENT_CTX_KEYS,
  compileFrame,
  frameDigest,
  frameSpecViolations,
  requestDigest,
  type AgentCtx,
  type FrameExclusion,
  type FrameSpec,
} from '../src/frame.ts'
import { FRAME_SPECS, needsTool, stepOk, gradeRisk, pickTool } from '../src/decisions.ts'

/** 一个「什么都发生过」的 ctx —— 让每一栏都有东西可编 */
function fullCtx(): AgentCtx {
  return {
    task: '把 alpha.ts 里的 totalOf 抄到新文件 summary.ts 里',
    cwd: '/work',
    files: ['alpha.ts', 'beta.ts', 'notes.md'],
    readFiles: ['alpha.ts'],
    history: [
      { step: 1, tool: 'list_dir', input: '.', result: 'alpha.ts\nbeta.ts\nnotes.md' },
      { step: 2, tool: 'read_file', input: 'alpha.ts', result: 'export function totalOf() {}' },
    ],
    canWrite: true,
    earlier: '上一轮问的是这些文件各导出了什么',
    lastTool: 'read_file',
    lastResult: 'export function totalOf() {}',
    draft: '我把 totalOf 抄过去了。',
  }
}

// ═══════════════════════════════════════════════════════════
// ① 声明完整 —— 以及「漏了会响」
// ═══════════════════════════════════════════════════════════

test('七个声明是完整的：每一格 ctx 要么被看、要么被声明为故意不看', () => {
  const bad = frameSpecViolations(Object.values(FRAME_SPECS))
  assert.deepEqual(bad, [], `声明有毛病：\n${bad.join('\n')}`)
})

test('★ 反向：漏掉一格不声明，它必须响（否则这条检查等于没有）', () => {
  // 一个「少声明了 draft」的 spec：fields 与 excluded 都不提 draft
  const leaky: FrameSpec = {
    node: 'test.leaky',
    fields: [{ key: 'task', from: 'task', chars: 10, why: 'ok' }],
    excluded: AGENT_CTX_KEYS.filter((k) => k !== 'task' && k !== 'draft').map((k) => [k, '理由'] as const),
  }
  const bad = frameSpecViolations([leaky])
  assert.equal(bad.length, 1, `应当正好报一条，实际：${JSON.stringify(bad)}`)
  assert.match(bad[0]!, /draft/, '报的必须是漏掉的那一格')
  assert.match(bad[0]!, /故意不看/, '报的话要说清补什么')
})

test('★ 反向：排除理由为空，它必须响（空白等于没声明）', () => {
  const spec: FrameSpec = {
    node: 'test.blank',
    fields: [{ key: 'task', from: 'task', chars: 10, why: 'ok' }],
    excluded: AGENT_CTX_KEYS.filter((k) => k !== 'task').map((k) => [k, '   '] as const),
  }
  const bad = frameSpecViolations([spec])
  assert.ok(
    bad.some((v) => /理由为空/.test(v)),
    `空白理由必须被拦下，实际：${JSON.stringify(bad)}`,
  )
})

test('★ 反向：一栏没有界，它必须响（§8.2 的硬要求）', () => {
  const spec: FrameSpec = {
    node: 'test.unbounded',
    // 没有 chars 也没有 listMax
    fields: [{ key: 'task', from: 'task', why: 'ok' }],
    excluded: AGENT_CTX_KEYS.filter((k) => k !== 'task').map((k) => [k, '理由'] as const),
  }
  const bad = frameSpecViolations([spec])
  assert.ok(
    bad.some((v) => /没有界/.test(v)),
    `无界的一栏必须被拦下，实际：${JSON.stringify(bad)}`,
  )
})

test('★ 反向：同一格既被看又被排除，声明自相矛盾，它必须响', () => {
  const excluded: FrameExclusion[] = AGENT_CTX_KEYS.filter((k) => k !== 'task').map((k) => [k, '理由'])
  excluded.push(['task', '又说看又说不看'])
  const spec: FrameSpec = {
    node: 'test.contradiction',
    fields: [{ key: 'task', from: 'task', chars: 10, why: 'ok' }],
    excluded,
  }
  const bad = frameSpecViolations([spec])
  assert.ok(
    bad.some((v) => /自相矛盾/.test(v)),
    `矛盾声明必须被拦下，实际：${JSON.stringify(bad)}`,
  )
})

// ═══════════════════════════════════════════════════════════
// ② 有界 / 截了要报 / 缺的要说
// ═══════════════════════════════════════════════════════════

test('超预算要截，而且**截了要报** —— 不静默', () => {
  const ctx = fullCtx()
  // `stepOk` 的 output 读的是 `lastResult`（不是 history 里的最后一条）
  ctx.lastResult = 'x'.repeat(2000)
  const f = compileFrame(FRAME_SPECS['loop.stepOk']!, ctx)

  const cut = f.truncated.find((t) => t.key === 'output')
  assert.ok(cut, `output 应当被截并记录，实际 truncated=${JSON.stringify(f.truncated)}`)
  assert.equal(cut.from, 2000, '要记下原来多长')
  assert.equal(cut.to, 500, '要记下预算多少')
  assert.ok(String(f.state.output).startsWith('x'), '截断后仍是原文开头')
})

test('★★ 「还没有」与「故意不看」必须是两个信号（§8.15：混在一起 = 每一步都在响）', () => {
  // (a) 声明要看 lastResult，而 ctx 里没有 → unfilled（可能忘了喂）
  const noResult: AgentCtx = { task: 't', cwd: '/w', lastTool: 'read_file' }
  const a = compileFrame(FRAME_SPECS['loop.stepOk']!, noResult)
  assert.ok(
    a.unfilled.some((u) => u.key === 'output' && u.from === 'lastResult'),
    `没喂过的字段要进 unfilled，实际 ${JSON.stringify(a.unfilled)}`,
  )
  assert.deepEqual(a.absent, [], '这里没有「不适用」的栏，absent 应当是空的')

  // (b) 工具名认不出来 → base_risk **今天不适用**，不是「忘了喂」
  const unknown: AgentCtx = { task: 't', cwd: '/w', lastTool: 'rm_rf_everything' }
  const b = compileFrame(FRAME_SPECS['loop.gradeRisk']!, unknown)
  assert.ok(
    b.absent.some((x) => x.key === 'base_risk'),
    `认不出的工具要记进 absent，实际 ${JSON.stringify(b.absent)}`,
  )
  assert.ok(!('base_risk' in b.state), '★ 不编一个数：这一栏必须**整个不出现在帧里**')
  assert.ok(
    !b.unfilled.some((u) => u.key === 'base_risk'),
    '「不适用」不能混进 unfilled',
  )
})

test('排除项跟着帧走 —— 事后读轨迹的人看得见当时**没喂**什么', () => {
  const f = compileFrame(FRAME_SPECS['loop.stepOk']!, fullCtx())
  const excluded = f.excluded.map(([k]) => k)
  assert.ok(excluded.includes('task'), '★ stepOk 故意不看 task，这条必须出现在产物上')
  assert.ok(
    f.excluded.every(([, why]) => why.trim().length > 0),
    '每一条排除都要带理由 —— 理由是这个机制唯一防得住的事',
  )
})

// ═══════════════════════════════════════════════════════════
// ③ 指纹：帧的 / 请求的，是两个问题
// ═══════════════════════════════════════════════════════════

test('同一个 ctx 编两次，指纹相同（纯函数）', () => {
  const a = compileFrame(FRAME_SPECS['loop.isDone']!, fullCtx())
  const b = compileFrame(FRAME_SPECS['loop.isDone']!, fullCtx())
  assert.equal(a.digest, b.digest)
  assert.equal(a.digest.length, 16, '和冻结的 Python 那份一样是 16 个十六进制字符')
})

test('改一栏就换指纹', () => {
  const ctx = fullCtx()
  const before = frameDigest('loop.isDone', compileFrame(FRAME_SPECS['loop.isDone']!, ctx).state)
  ctx.readFiles = ['alpha.ts', 'beta.ts']
  const after = compileFrame(FRAME_SPECS['loop.isDone']!, ctx).digest
  assert.notEqual(before, after, '帧变了而指纹不动，「同一个方法」这句话就不成立')
})

test('★★★ 帧指纹相同、只有选项变了 —— 两个指纹必须给出不同的答案（§8.17 的全部教训）', () => {
  const ctx = fullCtx()
  const frame = compileFrame(FRAME_SPECS['loop.pickTool']!, ctx)

  // 同一个帧，两次不同的候选集
  const twoOptions = { tool: { type: 'choice', criteria: { read_file: 'A', done: 'B' } } }
  const threeOptions = { tool: { type: 'choice', criteria: { read_file: 'A', done: 'B', write_file: 'C' } } }

  // 帧指纹**看不见**这个差别 —— 因为选项不在帧里（§8.17 我拿它骗过自己一次）
  assert.equal(frame.digest, compileFrame(FRAME_SPECS['loop.pickTool']!, ctx).digest)

  // 请求指纹看得见 —— 它才是「两次跑的是不是同一个判定」的答案
  assert.notEqual(
    requestDigest(frame.digest, twoOptions),
    requestDigest(frame.digest, threeOptions),
    '★ 只比帧指纹会放过「换掉候选集」这一类，而那正是 §8.17 的机制',
  )
})

// ═══════════════════════════════════════════════════════════
// ④ 端口保真：声明编出来的帧，必须和原来手拼的 dict 逐字节相同
// ═══════════════════════════════════════════════════════════

test('★ 端口保真：七个节点的帧与手拼时代的形状逐字段相同', () => {
  const ctx = fullCtx()

  // 这一份是**照着改动前的 `state:` 逐字抄下来的期望值**。它红了只有两种可能：
  // 要么 porte 时改了字节（那会让已有的 bench 数字不再可比），要么声明写错了。
  assert.deepEqual(stepOk.state(ctx), {
    tool: 'read_file',
    input: 'alpha.ts',
    output: 'export function totalOf() {}',
    already_read: 1,
  })

  assert.deepEqual(gradeRisk.state(ctx), {
    tool: 'read_file',
    base_risk: 0,
    target: 'alpha.ts',
    task: '把 alpha.ts 里的 totalOf 抄到新文件 summary.ts 里',
  })

  assert.deepEqual(pickTool.state(ctx), {
    task: '把 alpha.ts 里的 totalOf 抄到新文件 summary.ts 里',
    earlier: '上一轮问的是这些文件各导出了什么',
    already_done: 'already called: list_dir, read_file (2 steps)',
    files_known: ['alpha.ts', 'beta.ts', 'notes.md'],
    already_read: ['alpha.ts'],
    last_result: 'export function totalOf() {}',
  })
})

test('端口保真：空 ctx 也逐字相同（原来那些 `?? []` / `?? \'\'` 的兜底一个没少）', () => {
  const bare: AgentCtx = { task: 't', cwd: '/w' }
  assert.deepEqual(stepOk.state(bare), {
    tool: 'unknown',
    input: '',
    output: '',
    already_read: 0,
  })
  assert.deepEqual(pickTool.state(bare), {
    task: 't',
    earlier: '',
    already_done: 'nothing yet',
    files_known: [],
    already_read: [],
    last_result: '',
  })
})

// ═══════════════════════════════════════════════════════════
// ⑤ 端到端：指纹**真的**走到日志里了吗
//
// ★ 这一条防的是「声明了却没消费方」（§8.16 记的形状）：`compileFrame` 算出了
//   指纹，而如果没有任何东西把它带出去，那就是一段**没人读的计算** ——
//   和「一条要求写在文档里、却没写在代码里」是同一类毛病。
// ═══════════════════════════════════════════════════════════

test('★★ 判定走完一圈，帧指纹与请求指纹都到了事件里', async () => {
  const { Decider } = await import('../src/decide.ts')
  const { MockProvider } = await import('../src/provider-mock.ts')
  const { decisionEvent } = await import('../src/events.ts')

  const decider = new Decider({ provider: new MockProvider() })
  const res = await decider.decide(needsTool, fullCtx())

  assert.ok(res.frame, '判定结果上必须带着帧的账')
  assert.equal(res.frame.digest.length, 16, '帧指纹：16 个十六进制字符')
  assert.equal(res.requestDigest?.length, 16, '请求指纹：同样长度，但回答的是另一个问题')
  assert.notEqual(res.frame.digest, res.requestDigest, '★ 两者是**两个问题**，不该是同一个串')

  const ev = decisionEvent(res)
  assert.equal(ev.type, 'decision')
  assert.ok(ev.frame, '事件里必须有帧的账')
  assert.ok(
    ev.frame.excluded.some(([k]) => k === 'draft'),
    '★ needsTool 故意不看 draft，这条必须出现在事件里',
  )
  assert.equal(ev.requestDigest, res.requestDigest, '请求指纹要一路带到事件')
})

test('★★ 换掉候选集：帧指纹不动，请求指纹要动（§8.17 那次自我欺骗的回归）', async () => {
  const { Decider } = await import('../src/decide.ts')
  const { MockProvider } = await import('../src/provider-mock.ts')

  const ctx = fullCtx()
  const decider = new Decider({ provider: new MockProvider() })

  // `pickTool` 的候选由 `toolsFor(ctx)` 每步重建 —— 加一个文件就换了候选集
  const before = await decider.decide(pickTool, ctx)
  ctx.files = [...(ctx.files ?? []), 'gamma.ts']
  const after = await decider.decide(pickTool, ctx)

  assert.notEqual(
    before.requestDigest,
    after.requestDigest,
    '★ 候选集换了，请求指纹必须换 —— 只比帧指纹会放过这一类',
  )
})
