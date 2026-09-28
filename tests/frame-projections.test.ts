/**
 * 帧投影的能力声明（TODO §12 第二条）。
 *
 * ═══════════════════════════════════════════════════════════
 * 「声明和实现对不上」这件事，在这一层要变成**不可能**
 * ═══════════════════════════════════════════════════════════
 *
 * `DECISION.md` 的 `frame:` 行点名的每一个投影，外部宿主都必须自己实现。
 * 而在这份声明之前，他们能拿到的只有**名字** —— 「`lastOrNone` 和 `resultMaybe`
 * 差在哪」得去读我们的实现才知道，可那个差别**是判据的一部分**。
 *
 * 这里核对三类事实，每一类都会独立地错：
 *
 *   ① **键一一对应**（编译期已经强制，这里再钉一次运行时形状）；
 *   ② **`from` 真的是 `AgentCtx` 的格名** —— 声明里是 `string`，
 *      `decisions.ts` 有一次类型断言，这一条就是那次断言的凭据；
 *   ③ **`returns` 和实现真的返回那个形状** —— 标错会让那一栏的预算**静默失效**
 *      （字符串标成 list ⇒ `chars` 不再生效，而 `chars` 是逐栏硬要求）。
 *
 * ★ 还有一条是**对外**的：`examples/external-host.ts` 声明的能力清单必须和
 *   这份声明**完全相同**。它以前多了一个 `lastResult` —— 一个在注册表里、
 *   在 `DECISION.md` 里都**不存在**的投影，却出现在发布出去的能力报告里。
 *   一份列着不存在能力的报告，比没有报告更糟。
 *
 * @module JevLoop/frame-projections.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  PROJECTIONS,
  PROJECTION_NAMES,
  isProjectionName,
  type ProjectionReturns,
} from '../src/frame-projections.ts'
import { AGENT_CTX_KEYS, type AgentCtx } from '../src/frame.ts'
import { frameSpecFromBlock } from '../src/decisions.ts'
import { parseDecisionDoc } from '../src/decisiondoc.ts'
import { CAPABILITIES } from '../examples/external-host.ts'

/** 一个「什么都发生过」的 ctx —— 让每个投影都有真值可算 */
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

// ① 键与名字
test('★ 声明里的每个名字都真的是 `AgentCtx` 的格名 —— 那次类型断言的凭据', () => {
  for (const name of PROJECTION_NAMES) {
    const from = PROJECTIONS[name].from
    assert.ok(
      (AGENT_CTX_KEYS as string[]).includes(from),
      `投影 '${name}' 声明读 '${from}'，而 ctx 只有 ${AGENT_CTX_KEYS.join(' / ')}`,
    )
  }
})

test('名字清单被钉住 —— 加一个投影必须是有意的', () => {
  assert.deepEqual([...PROJECTION_NAMES].sort(), [
    'describeDone',
    'draftMaybe',
    'earlierMaybe',
    'filesMaybe',
    'lastInput',
    'lastOrNone',
    'localToolRisk',
    'readCount',
    'readMaybe',
    'recentSteps',
    'resultMaybe',
    'toolOrEmpty',
    'toolOrUnknown',
    'writeEvidence',
  ])
})

test('闭集查表：认得的认得，继承来的键骗不过去', () => {
  assert.equal(isProjectionName('resultMaybe'), true)
  assert.equal(isProjectionName('resultMaybeTypo'), false)
  // 走 Object.hasOwn 而不是 `in` —— 这几个是继承来的键
  for (const sneaky of ['toString', 'constructor', '__proto__', 'hasOwnProperty']) {
    assert.equal(isProjectionName(sneaky), false, `'${sneaky}' 不该被当成投影名`)
  }
})

// ② `returns` 和实现对得上
test('★★ 声明的返回形状必须和实现真返回的一致 —— 标错会让那一栏的预算静默失效', () => {
  const ctx = fullCtx()
  for (const name of PROJECTION_NAMES) {
    // 空 ctx 也要过一遍：缺省分支返回的形状可能与有值时不同（那正是兜底投影的全部意义）
    for (const [label, c] of [['满 ctx', ctx], ['空 ctx', { task: 't', cwd: '/w' } as AgentCtx]] as const) {
      // 投影函数住在 decisions.ts 里，通过一个**真的用了它**的 frame 字段取到 ——
      // 用运行时同一条路径，而不是在这里再抄一份名单
      const fn = projectionFnOf(name)
      const out = fn(c)
      if (out === undefined) continue // `localToolRisk` 认不出工具时就是这样（记进 absent）
      const declared: ProjectionReturns = PROJECTIONS[name].returns
      const actual: ProjectionReturns = Array.isArray(out)
        ? 'list'
        : typeof out === 'number'
          ? 'count'
          : 'string'
      assert.equal(actual, declared, `${label} 下投影 '${name}' 声明为 ${declared}，实际返回 ${actual}`)
    }
  }
})

/**
 * 拿到某个投影的实现函数。
 *
 * 从 `DECISION.md` 的真实 frame 行里找一栏用了它的字段，再取那份 spec 的
 * `project` —— 这样测试用的是**运行时同一条路径**，不是另抄一份名单。
 */
function projectionFnOf(name: string): (ctx: AgentCtx) => unknown {
  const doc = parseDecisionDoc(readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8'))
  for (const block of doc.blocks) {
    for (const field of block.frame?.fields ?? []) {
      if (field.project !== name) continue
      const spec = frameSpecFromBlock(block, `loop.${block.id}`)
      const f = spec?.fields.find((x) => x.key === field.key)
      assert.ok(f?.project, `投影 '${name}' 在块 '${block.id}' 里没有编出实现`)
      return f.project
    }
  }
  throw new Error(`没有任何 frame 行用到投影 '${name}' —— 那它就是死声明`)
}

// ③ 每个声明的投影都要真的被用到
test('★ 没有死声明：每个投影都被 `DECISION.md` 的某一行真的用到', () => {
  const doc = parseDecisionDoc(readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8'))
  const used = new Set<string>()
  for (const block of doc.blocks) {
    for (const field of block.frame?.fields ?? []) if (field.project) used.add(field.project)
  }
  const unused = PROJECTION_NAMES.filter((n) => !used.has(n))
  assert.deepEqual(unused, [], `这些投影声明了却没人用：${unused.join(', ')}`)
})

// ④ 对外的清单
test('★★ 外部宿主 fixture 的能力清单必须和声明**完全相同**', () => {
  assert.deepEqual(
    [...CAPABILITIES.projections].sort(),
    [...PROJECTION_NAMES].sort(),
    '差异说明有人在某一边加了名字 —— 发布出去的能力报告不能列不存在的能力',
  )
})
