/**
 * Codex transcript 读取 —— 离线、确定性地验证它读出了什么、以及**读不出时怎么办**
 *
 * ═══════════════════════════════════════════════════════════
 * 这是读一个**内部格式**，所以测的重点是「防御」而不是「解析成功」
 * ═══════════════════════════════════════════════════════════
 *
 * codex 的 `RolloutLine` 自己写着「JSONL readers must use codex_rollout's canonical
 * parser」—— 也就是没有对外兼容承诺。所以这里的验收是：
 *
 *     · 读得出正常内容（task / history / lastResult / readFiles）
 *     · **坏行、认不出的形状、格式漂移** ⇒ 跳过并计数，不抛
 *     · **读不到 task** ⇒ `undefined` ⇒ 上层**拒绝**，不是拿空任务继续
 *     · 文件很大 ⇒ 只读头尾两段，而且**说出来**
 *
 * ★ 最后一条有两个测试，一个正一个反：正常文件必须**不**走窗口读（否则
 *   `windowedRead` 会变成一句永远为真的声明），大文件必须走且报出来。
 *
 * @module JevLoop/codex-transcript.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, writeFileSync, rmSync, openSync, writeSync, closeSync } from 'node:fs'
import { join } from 'node:path'
import { tmpdir } from 'node:os'

import { readTranscript } from '../adapters/codex/transcript.ts'
import { runDecision } from '../adapters/codex/core.ts'
import type { CodexHookEvent, HostState } from '../adapters/codex/types.ts'
import { readFileSync } from 'node:fs'
import type { AnswerSet } from '../src/contract.ts'

const MD = readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8')

/** 一行 rollout。形状按 `codex-rs/history/src/lib.rs` 的 `RolloutLine` */
const line = (type: string, payload: unknown) => JSON.stringify({ timestamp: '2025-01-01T00:00:00Z', type, payload })

const userMsg = (text: string) =>
  line('response_item', { type: 'message', role: 'user', content: [{ type: 'input_text', text }] })
const assistantMsg = (text: string) =>
  line('response_item', { type: 'message', role: 'assistant', content: [{ type: 'output_text', text }] })
const call = (id: string, name: string, args: Record<string, unknown>) =>
  line('response_item', { type: 'function_call', call_id: id, name, arguments: JSON.stringify(args) })
const output = (id: string, text: string) =>
  line('response_item', { type: 'function_call_output', call_id: id, output: { body: text } })
const meta = (cwd: string, id: string) =>
  line('session_meta', { id, cwd, model: 'gpt-x' })

function withFile<T>(content: string | Buffer, fn: (path: string) => T): T {
  const dir = mkdtempSync(join(tmpdir(), 'jevloop-transcript-'))
  try {
    const path = join(dir, 'rollout.jsonl')
    writeFileSync(path, content)
    return fn(path)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
}

// ═══════════════════════════════════════════════════════════
// ① 正常读取
// ═══════════════════════════════════════════════════════════

test('★ 读出 task / history / lastResult —— 配对靠 call_id', () => {
  const md = [
    meta('/work', 'sess-1'),
    userMsg('把 alpha.ts 里的 totalOf 抄到 summary.ts 里'),
    assistantMsg('好的'),
    call('c1', 'read_file', { path: 'alpha.ts' }),
    output('c1', 'export function totalOf() {}'),
    call('c2', 'read_file', { path: 'beta.ts' }),
    output('c2', 'export function otherFn() {}'),
  ].join('\n') + '\n'

  withFile(md, (path) => {
    const t = readTranscript(path)
    assert.match(t.task ?? '', /totalOf/, '第一次用户消息就是任务')
    assert.equal(t.sessionId, 'sess-1')
    assert.equal(t.cwd, '/work')
    assert.match(t.historyText ?? '', /read_file\(alpha\.ts\) → export function totalOf/, '历史要串起调用与结果')
    assert.match(t.lastResult ?? '', /otherFn/, 'lastResult 是**最后一次**有结果的调用')
    assert.deepEqual(t.readFiles.sort(), ['alpha.ts', 'beta.ts'], '读类工具的路径参数进 readFiles')
    assert.equal(t.windowedRead, false, '正常大小的文件**不该**走窗口读')
    assert.equal(t.skippedLines, 0)
  })
})

test('★ 认不出的工具名不进 readFiles —— 不猜', () => {
  const md = [
    userMsg('t'),
    call('c1', 'shell', { cmd: 'cat alpha.ts' }),
    output('c1', 'contents'),
    call('c2', 'apply_patch', { path: 'beta.ts' }),
    output('c2', 'ok'),
  ].join('\n')
  withFile(md, (path) => {
    const t = readTranscript(path)
    assert.deepEqual(t.readFiles, [], 'shell 的 cmd 里出现的文件名**不认**（那是猜）')
    assert.deepEqual(t.files.sort(), ['beta.ts'], '但见过的路径要记下来')
  })
})

test('输出体是内容项数组时也要读得出文本（codex 的 body 是 untagged）', () => {
  const md = [
    userMsg('t'),
    call('c1', 'read_file', { path: 'a.ts' }),
    line('response_item', {
      type: 'function_call_output',
      call_id: 'c1',
      output: { body: [{ type: 'output_text', text: '第一行' }, { type: 'output_text', text: '第二行' }] },
    }),
  ].join('\n')
  withFile(md, (path) => {
    const t = readTranscript(path)
    assert.match(t.lastResult ?? '', /第一行[\s\S]*第二行/, '内容项要拼成文本')
  })
})

test('工具参数是 JSON 字符串 —— 取路径类字段而不是整段 JSON', () => {
  const md = [userMsg('t'), call('c1', 'read_file', { path: 'a.ts', other: 'x'.repeat(500) }), output('c1', 'ok')].join('\n')
  withFile(md, (path) => {
    const t = readTranscript(path)
    assert.match(t.historyText ?? '', /read_file\(a\.ts\)/, '显示的是目标路径，不是整段参数')
    assert.ok((t.historyText ?? '').length < 400, '历史里不该塞进那一大段无关参数')
  })
})

// ═══════════════════════════════════════════════════════════
// ② 防御：坏行、漂移、读不到
// ═══════════════════════════════════════════════════════════

/*
  ★★ 这一组测的是一个**只有真跑才发现的** bug（0.158.0 实测，见
     `docs/ADAPTER-CODEX-SCOPE.md`）：codex 会在真正的用户消息**前面**塞一条自己
     生成的 `<environment_context>`，里面是 cwd / shell / 日期 / 沙箱档位。

     于是「取第一条 role=user」读到的不是任务 —— 而后果不是「读不到」，是
     **读到一个错的**。帧的每一栏都拿 task 当判据，所以那会变成一份看起来完整、
     实际答非所问的判定。安静的那种错，最难发现。

     所以这里要给**三**个方向：
       ① 合成块在前、真任务在后 ⇒ 取到真任务
       ② 只有合成块         ⇒ `undefined` ⇒ 上层**拒绝**（吵的那一半）
       ③ 只是**提到**这个标签 ⇒ **不能**被当成合成块（否则会吃掉真消息）
*/

/** 实测形状：整条就是一个 `<environment_context>` 包起来的块 */
const environmentContext = () =>
  userMsg(
    '<environment_context>\n  <cwd>/tmp/work</cwd>\n  <shell>bash</shell>\n' +
      '  <current_date>2026-09-29</current_date>\n  <timezone>Asia/Shanghai</timezone>\n' +
      '  <filesystem><workspace_roots><root>/tmp/work</root></workspace_roots></filesystem>\n' +
      '</environment_context>',
  )

test('★★ codex 的合成环境块不是任务 —— 取它后面的真用户消息', () => {
  const md = [meta('/tmp/work', 's1'), environmentContext(), userMsg('list the files in this directory')].join('\n')
  withFile(md, (path) => {
    const t = readTranscript(path)
    assert.equal(t.task, 'list the files in this directory', '★ 取的是真任务，不是环境块')
    assert.doesNotMatch(t.task ?? '', /cwd|environment_context/, '环境块一个字都不该进 task')
    assert.ok(
      t.notes.some((n) => /合成用户消息/.test(n)),
      '跳过要说出来 —— 静默跳过会让「为什么读到的不是第一条」变成一个谜',
    )
  })
})

test('★★ 只有合成块 ⇒ task 是 `undefined`，适配器**拒绝**（不是拿环境块去判定）', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'jevloop-transcript-envonly-'))
  try {
    const path = join(dir, 'r.jsonl')
    writeFileSync(path, `${meta('/tmp/work', 's1')}\n${environmentContext()}\n`)

    const t = readTranscript(path)
    assert.equal(t.task, undefined, '★ 合成块不能顶替任务')

    const state: HostState = {
      task: t.task as string, // undefined —— 正是这里要测的
      cwd: '/tmp/work',
      tool: 'shell',
      input: 'rm -rf /',
      historyText: t.historyText,
      files: t.files,
      readFiles: t.readFiles,
    }
    const backend = async (): Promise<AnswerSet> => ({}) // 不该被调用
    const r = await runDecision(
      { hook_event_name: 'PreToolUse', tool_name: 'shell', transcript_path: path },
      { md: MD, state, backend },
    )
    assert.equal(r.verdict.kind, 'deny', '★ 任务读不到就必须拒绝 —— 而这里正是它以前会「读到」的情形')
    assert.match(r.verdict.reason, /task/)
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('★ 只是**提到** `<environment_context>` 的消息不能被当成合成块吃掉', () => {
  const asked = '为什么我的 transcript 里会有 <environment_context> 这一段？'
  withFile([userMsg(asked)].join('\n'), (path) => {
    const t = readTranscript(path)
    assert.equal(t.task, asked, '★ 判据是「以标签开头」，不是「包含标签」')
  })
})

test('★★ 坏行跳过并计数 —— 追加式格式允许撕裂尾行', () => {
  const md = [
    userMsg('t'),
    '{"timestamp":"x","type":"response_item","payl', // 撕裂的半行
    call('c1', 'read_file', { path: 'a.ts' }),
    output('c1', 'ok'),
    'not json at all',
  ].join('\n')
  withFile(md, (path) => {
    const t = readTranscript(path)
    assert.equal(t.skippedLines, 2, '两行坏的要计数')
    assert.ok(t.notes.some((n) => /跳过/.test(n)), '要**说出来**，不能静默吞掉')
    assert.match(t.task ?? '', /t/, '坏行不影响它前后的正常行')
    assert.match(t.lastResult ?? '', /ok/)
  })
})

test('★★ 认不出的行类型静默跳过（格式加东西是正常的，不该算「跳过」）', () => {
  const md = [
    userMsg('t'),
    line('some_future_item_type', { hello: 'world' }),
    line('turn_context', { cwd: '/w' }),
    line('response_item', { type: 'reasoning', summary: [] }),
    call('c1', 'read_file', { path: 'a.ts' }),
    output('c1', 'ok'),
  ].join('\n')
  withFile(md, (path) => {
    const t = readTranscript(path)
    assert.equal(t.skippedLines, 0, '认不出的**行类型**不是坏行 —— 格式会加东西')
    assert.equal(t.lastResult, 'ok', '而且不影响后面的正常行')
  })
})

test('格式漂移：payload 形状变了 ⇒ 不抛，退化成读不到', () => {
  const md = [
    userMsg('t'),
    line('response_item', { type: 'function_call', name: 'read_file' }), // 少了 arguments
    line('response_item', 'not-an-object'),
  ].join('\n')
  withFile(md, (path) => {
    // 不抛就是重点
    const t = readTranscript(path)
    assert.equal(t.task, 't')
    assert.equal(t.lastResult, undefined, '拿不到结果就是拿不到')
  })
})

test('★★ 读不到 task ⇒ `undefined`，绝不填空串', () => {
  withFile([assistantMsg('只有助手消息，没有用户消息')].join('\n'), (path) => {
    const t = readTranscript(path)
    assert.equal(t.task, undefined, '★ 空串会让帧看起来完整，而策略基于一个空任务做判定')
    assert.ok(t.notes.some((n) => /找不到真正的用户消息/.test(n)), '要说清为什么')
  })
})

test('文件不存在 ⇒ 返回 notes，不抛', () => {
  const t = readTranscript('/definitely/not/here.jsonl')
  assert.equal(t.task, undefined)
  assert.ok(t.notes.some((n) => /读不到/.test(n)))
})

// ═══════════════════════════════════════════════════════════
// ③ 无界输入：窗口读
// ═══════════════════════════════════════════════════════════

test('★★ 大文件只读头尾两段，而且**说出来**', () => {
  const dir = mkdtempSync(join(tmpdir(), 'jevloop-transcript-big-'))
  try {
    const path = join(dir, 'big.jsonl')
    const fd = openSync(path, 'w')
    writeSync(fd, `${meta('/work', 's1')}\n${userMsg('真正要找的任务在这')}\n`)
    // 中间塞到远超 头+尾 窗口
    const filler = `${line('response_item', { type: 'reasoning', summary: [] })}\n`
    for (let i = 0; i < 40_000; i++) writeSync(fd, filler)
    writeSync(fd, `${call('c9', 'read_file', { path: 'last.ts' })}\n${output('c9', '最后一次结果')}\n`)
    closeSync(fd)

    const t = readTranscript(path)
    assert.equal(t.windowedRead, true, '大文件必须走窗口读 —— 它不是优化，是不让读取无界')
    assert.match(t.task ?? '', /真正要找的任务/, '任务在**头部**窗口里')
    assert.match(t.lastResult ?? '', /最后一次结果/, '最近一步在**尾部**窗口里')
    assert.ok(t.notes.some((n) => /只读了头/.test(n)), '★ 读了窗口就要说出来')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

// ═══════════════════════════════════════════════════════════
// ④ 端到端：读不到 task 时，适配器**拒绝**（不是放行）
// ═══════════════════════════════════════════════════════════

test('★★ transcript 里没有用户消息 ⇒ 适配器拒绝 —— 安全的那一半', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'jevloop-transcript-refuse-'))
  try {
    const path = join(dir, 'r.jsonl')
    writeFileSync(path, `${assistantMsg('只有助手消息')}\n`)

    const t = readTranscript(path)
    const event: CodexHookEvent = { hook_event_name: 'PreToolUse', tool_name: 'shell', transcript_path: path }
    const state: HostState = {
      task: t.task as string, // undefined —— 正是这里要测的
      cwd: '/work',
      tool: 'shell',
      input: 'rm -rf /',
      historyText: t.historyText,
      lastResult: t.lastResult,
      files: t.files,
      readFiles: t.readFiles,
      canWrite: undefined,
    }
    const backend = async (): Promise<AnswerSet> => ({}) // 不该被调用
    const r = await runDecision(event, { md: MD, state, backend })
    assert.equal(r.verdict.kind, 'deny', '★ 任务都读不到就必须拒绝')
    assert.equal(r.verdict.loss, 'missing state cells')
    assert.match(r.verdict.reason, /task/, '要说清缺哪一格')
    assert.equal(r.outcome.record, null, '没判定成功就不该留下记录')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})

test('★★ 缺格的拒绝必须带**这个 hook 的形状** —— PreToolUse 不是 Stop', async () => {
  /*
    ★ 这条测的是一个真 bug，而且只有**驱动真入口**才看得出来：
      第一版把几条早退路径的 JSON 写死成 `{ decision: 'block' }`（Stop 的形状），
      于是 `PreToolUse` 缺一格时 codex 收到的不是「拒绝这次调用」而是一份它在这个
      事件上不认得的裁决 ⇒ **工具照跑**。

    ⇒ 拒绝的形状由**事件**决定，不由调用点决定。
  */
  const noTask: HostState = { task: undefined as unknown as string, cwd: '/w', tool: 'shell', input: 'rm -rf /' }
  const backend = async (): Promise<AnswerSet> => ({})

  const pre = await runDecision({ hook_event_name: 'PreToolUse', tool_name: 'shell' }, { md: MD, state: noTask, backend })
  assert.deepEqual(
    pre.json,
    {
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: pre.verdict.reason,
      },
    },
    'PreToolUse 的拒绝必须是 permissionDecision:deny',
  )

  const stop = await runDecision({ hook_event_name: 'Stop' }, { md: MD, state: noTask, backend })
  assert.deepEqual(stop.json, { decision: 'block', reason: stop.verdict.reason }, 'Stop 的拒绝是顶层 decision:block')
})

test('★ 读到 task 之后同一个事件就放行了 —— 证明拒绝的原因是缺格，不是别的', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'jevloop-transcript-ok-'))
  try {
    const path = join(dir, 'r.jsonl')
    writeFileSync(path, `${userMsg('看看目录里有什么')}\n`)
    const t = readTranscript(path)
    assert.ok(t.task, '这次任务读得到')
    const state: HostState = {
      task: t.task as string,
      cwd: '/work',
      tool: 'read_file',
      input: 'a.ts',
      historyText: t.historyText,
      files: t.files,
      readFiles: t.readFiles,
    }
    const backend = async (req: { questions: Record<string, { type: string }> }): Promise<AnswerSet> => {
      const answers: AnswerSet = {}
      for (const [id, q] of Object.entries(req.questions)) {
        if (q.type === 'noul') answers[id] = { type: 'noul', noul: 0.05 } as AnswerSet[string]
        else if (q.type === 'score') answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.9 } as AnswerSet[string]
        else answers[id] = { type: 'choice', choice: '', probabilities: {}, confidence: 0.9 } as AnswerSet[string]
      }
      return answers
    }
    const r = await runDecision(
      { hook_event_name: 'PreToolUse', tool_name: 'read_file', transcript_path: path },
      { md: MD, state, backend },
    )
    assert.equal(r.verdict.kind, 'silence', '缺的那一格补上之后就放行了')
    assert.notEqual(r.outcome.record, null, '而且留下了可验证的记录')
  } finally {
    rmSync(dir, { recursive: true, force: true })
  }
})
