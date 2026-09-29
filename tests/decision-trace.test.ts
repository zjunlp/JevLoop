/**
 * Decision Trace —— 人读的那一份**就是**可复核的那一份
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件测的不是「渲染得好不好看」，是**一条更强的话**：
 * ═══════════════════════════════════════════════════════════
 *
 * 指纹**印在文件里**和指纹**能被重算**是两件事。前者只是装饰，后者才叫可审计。
 * 所以关键是最后那两条：
 *
 *   · 只读 `.md` 本身 → 取回记录 → 重算指纹 → `verified`（往返成立）
 *   · 把嵌入块里改掉一个值 → 同一套重算 → `mismatch`（**它真的在查**）
 *
 * ★ 第二条不能省。没有它，第一条可能只是因为验证器压根没看那份文件。
 *
 * @module JevLoop/decision-trace.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  checkTrace,
  ordinalOf,
  parseTrace,
  recordFromTrace,
  renderTrace,
  traceAtOf,
  traceDate,
  traceFileName,
  traceNameMatches,
} from '../src/decision-trace.ts'
import { frameDigest, requestDigest } from '../src/frame-digest.ts'
import type { ReplayRecord } from '../src/replay-schema.ts'
import { verifyRecord } from '../src/replay-verify.ts'

const AT = Date.UTC(2026, 8, 29, 10, 23, 37)

/**
 * 一份**指纹自洽**的记录 —— 这是关键：用真指纹，往返才有意义。
 *
 * 第一版这里填的是编造的指纹，于是 `verifyRecord` 报 `mismatch`（它确实在查），
 * 而测试却断言 `unverifiable`。那会让「往返成立」这句话**因为错的原因**通过。
 */
function goodRecord(over: Partial<ReplayRecord> = {}): ReplayRecord {
  const base: ReplayRecord = {
    schema: 'decision-record/v1',
    step: 0,
    node: 'grade_risk',
    state: { tool: 'Bash', base_risk: 2, task: 'list the files' },
    batchIds: ['grade_risk'],
    questions: { risk: { type: 'score' } },
    sentQuestions: { risk: { type: 'score' } },
    answers: { risk: { type: 'score', score: 3, legend: {}, probabilities: {}, confidence: 0.9 } },
    action: 'ask_human',
    reason: 'score:risk >= 2 → ask_human',
    provider: 'stub',
  }
  const rec = { ...base, ...over }
  if (rec.frameDigest === undefined) {
    const d = frameDigest(rec.node, rec.state)
    rec.frameDigest = d
    rec.sentFrameDigest = d
  }
  // ★ 没有 requestDigest 时 `verifyRecord` 只能给 `partial`（那一项跳过）。
  //   夹具要的是**完整**的 verified，否则往返测试会因为「少一栏」而通不过 ——
  //   而那是夹具的问题，不是往返的问题。
  if (rec.requestDigest === undefined && rec.sentFrameDigest !== undefined) {
    rec.requestDigest = requestDigest(rec.sentFrameDigest, rec.sentQuestions)
  }
  return rec
}

/** 盘上的**真实形状**：`{kind:'event', run, at, e}` 包装行 */
function storedLine(rec: ReplayRecord, at = AT): unknown {
  return { kind: 'event', run: 0, at, e: { ...rec, type: 'decision', id: rec.node } }
}

/** 渲染一份记录。夹具本身先断言是可解析的，避免测试因为夹具坏掉而假通过 */
function render(rec: ReplayRecord, ordinal = 1, at = AT): string {
  return renderTrace(rec, storedLine(rec, at), verifyRecord(rec), at, ordinal)
}

// ═══════════════════════════════════════════════════════════
// ① 命名
// ═══════════════════════════════════════════════════════════

test('★ 一天一份序号，日期用 UTC —— 同一份日志在两台机器上要落到同一天', () => {
  const at = Date.UTC(2026, 8, 29, 23, 30)
  assert.equal(traceDate(at), '2026-09-29')
  assert.equal(traceFileName(at, 1), '2026-09-29-001.md')
  assert.equal(traceFileName(at, 12), '2026-09-29-012.md')
})

// ═══════════════════════════════════════════════════════════
// ② 渲染：该有的人话都在
// ═══════════════════════════════════════════════════════════

test('渲染出节点 / 动作 / 理由 / 帧 / 问答 / 指纹，并给出结论', () => {
  const rec = goodRecord()
  const md = render(rec)
  for (const want of [
    'grade_risk',
    'ask_human',
    'score:risk >= 2',
    rec.frameDigest!,
    rec.requestDigest ?? 'requestDigest',
    'list the files',
  ]) {
    assert.ok(md.includes(want), `渲染结果里应当有 ${want}`)
  }
  assert.match(md, /结论：verified/, '结论要能一眼看到')
})

test('★ 帧表格明说**它自己会截断**，权威的是机器可读块 —— 不能让人以为表格就是全部', () => {
  const md = render(goodRecord())
  assert.match(md, /为了好读\*\*会截断\*\*/, '要写清表格不是权威')
  assert.ok(md.includes('权威的是文件末尾那个机器可读块'), '要指出权威在哪')
})

test('长的帧值在**表格里**被截断，但嵌入块里**一个字不少**', () => {
  const long = 'x'.repeat(5000)
  const rec = goodRecord({ state: { task: 't', blob: long } })
  const md = render(rec)
  assert.ok(md.includes('[+'), '表格里应当有截断标记')
  const embedded = parseTrace(md) as { e: { state: { blob: string } } }
  assert.equal(
    embedded.e.state.blob.length,
    5000,
    '★ 嵌入块里的值必须完整 —— 截断只许发生在给人看的表里，否则可复核性就是假的',
  )
})

// ═══════════════════════════════════════════════════════════
// ③ 合并判定：per-decision 形式**唯一真正会丢**的信息
// ═══════════════════════════════════════════════════════════

test('★★ 合并判定要**显式**写出来，并说清 sentFrameDigest ≠ frameDigest 是正常的', () => {
  const rec = goodRecord({
    node: 'can_deliver',
    batchIds: ['can_deliver', 'is_done'],
    frameDigest: frameDigest('can_deliver', { task: 't' }),
    sentFrameDigest: frameDigest('can_deliver+is_done', { task: 't' }),
  })
  const md = render(rec)
  assert.match(md, /合并判定/, '要写出这是一次合并')
  assert.match(md, /can_deliver \+ is_done/, '要写出合并了谁 —— 否则单看一份文件会以为它只判了一个节点')
  assert.match(md, /不同是正常的/, '要说明两个指纹不同是正常的，不然读的人会以为记录坏了')
})

// ═══════════════════════════════════════════════════════════
// ④ ★ 往返，以及它真的在查
// ═══════════════════════════════════════════════════════════

test('★★★ 往返：只读 `.md` 渲染结果 → 取回记录 → 重算指纹 → verified', () => {
  const md = render(goodRecord())
  const embedded = parseTrace(md)
  assert.ok(embedded, '要能把机器可读块取回来')
  const record = recordFromTrace(embedded)
  assert.ok(record, '取回来的东西要是可解析的记录')
  assert.equal(
    verifyRecord(record).status,
    'verified',
    '★ 从人看的那份文件本身重算，结论必须与原始记录一致',
  )
})

test('★★★ 反向：改掉嵌入块里的一个值 ⇒ 重算给出 `mismatch`（**它真的在查**）', () => {
  const rec = goodRecord({ state: { task: 't', answer: 'a', evidence: 'e' } })
  const md = render(rec)
  assert.equal(verifyRecord(recordFromTrace(parseTrace(md))!).status, 'verified', '前提：原样要 verified')

  const tampered = md.replace('"answer": "a"', '"answer": "b"')
  assert.notEqual(tampered, md, '篡改要真的落到文件内容里')
  const bad = recordFromTrace(parseTrace(tampered))
  assert.ok(bad, '篡改之后仍要能解析出来 —— 否则测的是「解析失败」而不是「指纹不符」')
  assert.equal(
    verifyRecord(bad).status,
    'mismatch',
    '★★★ 改了内容而指纹没变 ⇒ 必须 mismatch。若是 verified，说明这份 .md 根本不可审计',
  )
})

// ═══════════════════════════════════════════════════════════
// ⑤ 解析的纪律：宽容读、严格判
// ═══════════════════════════════════════════════════════════

test('没有标记 / 坏 JSON / 块没写完 ⇒ 取不回 `null`，不抛', () => {
  assert.equal(parseTrace('# 一份普通的 markdown\n'), null, '没有标记')
  assert.equal(parseTrace('<!-- jevloop:decision-record -->\n\n```json\n{ 坏\n```\n'), null, '坏 JSON')
  const md = render(goodRecord())
  assert.ok(parseTrace(md), '正常渲染的要取得到')
  assert.equal(parseTrace(md.slice(0, md.indexOf('```json') + 10)), null, '块没写完就该取不回')
})

test('★ 文件名的日期与记录时间对得上 —— 名字**不是装饰**，它可以被核对', () => {
  const embedded = parseTrace(render(goodRecord()))
  assert.equal(traceNameMatches('2026-09-29-001.md', traceAtOf(embedded)), true)
  assert.equal(traceNameMatches('2026-09-30-001.md', traceAtOf(embedded)), false, '换了一天就该报不一致')
  assert.equal(traceNameMatches('2026-09-29-001.md', undefined), false, '没有时间戳就不能声称对得上')
})

test('裸的 decision 事件（没有包装行）也认 —— 把「格式对不上」误报成「不可验证」是最贵的错', () => {
  const rec = goodRecord()
  const bare = { ...rec, type: 'decision', id: rec.node }
  const back = recordFromTrace(bare)
  assert.ok(back, '没有 {kind:"event"} 包装也要能读')
  assert.equal(back.node, rec.node)
  assert.equal(traceAtOf(bare), undefined, '裸事件没有时间戳 —— 那就说没有，不编一个')
})

// ═══════════════════════════════════════════════════════════
// ⑥ ★ 端到端跑出来的那个洞：只改**正文**也要报出来
// ═══════════════════════════════════════════════════════════

test('★★★ `checkTrace`：干净的一份 ⇒ 没问题', () => {
  const md = render(goodRecord())
  const c = checkTrace(md, '2026-09-29-001.md')
  assert.equal(c.ok, true, `不该有问题，实际：${c.problems.join(' / ')}`)
  assert.deepEqual(c.problems, [])
  assert.equal(c.verdict?.status, 'verified')
})

test('★★★ `checkTrace`：只改**正文表格**（机器可读块不动）⇒ 必须报「正文不一致」', () => {
  /*
    ★ 这一条是**端到端跑出来的**，不是想出来的。

    第一版只查「块取不取得到 / 记录自不自洽」，于是把渲染出来的表格里的命令
    从 `ls -la` 改成 `rm -rf /` 之后，`--verify` 依然报 `verified` —— 因为改的
    不是那个块。而人读的恰恰是表格。一份能被人读出错误结论却报 verified 的
    文件，不算可审计 —— 那样这个功能就只是把指纹当装饰印上去。

    单元测试当时也没抓住，因为它改的是块。所以这两条必须都在。
  */
  const md = render(goodRecord())
  const tampered = md.replace('list the files', '把整个仓库删掉')
  assert.notEqual(tampered, md, '正文要真的被改到')
  // 机器可读块必须还是原样 —— 否则测的就成了上一条
  // （★ 用 deepEqual：`assert.equal` 对对象比的是引用，这里要比内容）
  assert.deepEqual(parseTrace(tampered), parseTrace(md), '这一条只许动正文')

  const c = checkTrace(tampered, '2026-09-29-001.md')
  assert.equal(c.ok, false, '★ 正文被改了却报没问题，等于这个 .md 不可审计')
  assert.ok(
    c.problems.some((p) => p.includes('正文与机器可读块不一致')),
    `要找得到「正文不一致」，实际：${c.problems.join(' / ')}`,
  )
})

test('★★ `checkTrace`：文件名与记录时间对不上 ⇒ 报出来', () => {
  const md = render(goodRecord())
  const c = checkTrace(md, '2026-01-01-001.md')
  assert.equal(c.ok, false)
  assert.ok(c.problems.some((p) => p.includes('日期与记录的时间不一致')), c.problems.join(' / '))
})

test('★★ `checkTrace`：块取不回 / 块里不是记录 ⇒ 各自说清是哪一种', () => {
  const noBlock = checkTrace('# 普通 markdown\n', '2026-09-29-001.md')
  assert.equal(noBlock.ok, false)
  assert.match(noBlock.problems.join(' '), /取不回机器可读块/)

  const notRecord = checkTrace(`<!-- jevloop:decision-record -->\n\n\`\`\`json\n{"hello":1}\n\`\`\`\n`, 'x.md')
  assert.equal(notRecord.ok, false)
  assert.match(notRecord.problems.join(' '), /不是一条判定记录/)
})

test('`ordinalOf` 认形状，不猜', () => {
  assert.equal(ordinalOf('2026-09-29-001.md'), 1)
  assert.equal(ordinalOf('2026-09-29-042.md'), 42)
  assert.equal(ordinalOf('2026-09-29.md'), undefined)
  assert.equal(ordinalOf('随便什么.md'), undefined)
})
