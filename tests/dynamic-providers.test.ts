/**
 * 动态提供者的**输入声明**（TODO §12 第三条）。
 *
 * ═══════════════════════════════════════════════════════════
 * 「声明你的输入」这句话，要用**行为**核对，不是再抄一份表
 * ═══════════════════════════════════════════════════════════
 *
 * `DECISION.md` 现在写着 `toolsFor(ctx: history, files, …)`。那是对实现的声明 ——
 * 而一份没人核对的声明会过期。核对方式有两种，这里选贵的那个：
 *
 *     声明的每一格：改它 → 候选**必须**变（实现真的读了它）
 *     没声明的格：  改它 → 候选**必须不变**（实现没有偷偷读别的）
 *
 * ★ **第二条才是重点。** 一个读了 `lastResult` 却没声明的提供者，会让宿主在缺
 *   那一格的时候拿到一份**说不清来路**的候选 —— 而候选可能因此多一类或少一类，
 *   谁都不会知道。只查第一条的话，这一半永远是盲区。
 *
 * 这两个方向都是**纯函数**上的实验，不需要模型、不需要网络。
 *
 * @module JevLoop/dynamic-providers.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  DYNAMIC_PROVIDERS,
  DYNAMIC_PROVIDER_NAMES,
  isDynamicProviderName,
  type DynamicProviderName,
} from '../src/dynamic-providers.ts'
import { DYNAMIC_OUTPUTS, parseDynamic } from '../src/decision-syntax.ts'
import { AGENT_CTX_KEYS, fileOptions, toolsFor, type AgentCtx } from '../src/frame.ts'
import { parseDecisionDoc } from '../src/decisiondoc.ts'

/** 名字 → 真实实现。加一个提供者而这里没写 → 下面的完整性测试会红 */
const IMPL: Record<DynamicProviderName, (ctx: AgentCtx) => unknown> = {
  toolsFor: (ctx) => toolsFor(ctx),
  fileOptions: (ctx) => fileOptions(ctx),
}

/**
 * 一份「每一格都有值且都**算数**」的 ctx。
 *
 * ★ 必须让每个声明的格都真的影响输出，否则「改它 → 候选必须变」这条会误报。
 *   `history` 里放一次 list_dir，于是 `list_dir` 已经用过（影响候选）；
 *   `files` 里有未读文件（影响 read_file 候选）；`canWrite` / `canDelete` 开着
 *   （让 write_file / delete_file 进候选）。
 */
function richCtx(): AgentCtx {
  return {
    task: '整理一下工作目录',
    cwd: '/work',
    files: ['a.ts', 'b.ts'],
    readFiles: ['a.ts'],
    history: [{ step: 1, tool: 'list_dir', input: '.', result: 'a.ts\nb.ts' }],
    canWrite: true,
    canDelete: true,
    earlier: '上文',
    lastTool: 'list_dir',
    lastResult: 'a.ts\nb.ts',
    draft: '草稿',
  }
}

/** 每一格换成一个「明显不同」的值 —— 用来测那一格会不会影响输出 */
const OTHER: Record<string, unknown> = {
  task: '换一个完全不同的任务描述',
  cwd: '/somewhere/else',
  // ★ 多一个文件 ⇒ 未读从 1 变 2 ⇒ 判据从「一个文件」变成列出名字。
  //   只把名字换掉（['z.ts']）时数量没变，文案一模一样 —— 第一版就是这么红的
  files: ['a.ts', 'b.ts', 'c.ts', 'd.ts'],
  readFiles: [],
  history: [{ step: 9, tool: 'read_file', input: 'z.ts', result: '别的结果' }],
  canWrite: false,
  canDelete: false,
  earlier: '别的上文',
  lastTool: 'read_file',
  lastResult: '别的结果',
  draft: '别的草稿',
}

const show = (v: unknown): string => JSON.stringify(v)

// ═══════════════════════════════════════════════════════════
// ① 完整性
// ═══════════════════════════════════════════════════════════

test('每个声明的提供者都有实现，每个实现都有声明', () => {
  assert.deepEqual(Object.keys(IMPL).sort(), [...DYNAMIC_PROVIDER_NAMES].sort())
})

test('提供者名清单被钉住 —— 加一个必须是有意的', () => {
  assert.deepEqual([...DYNAMIC_PROVIDER_NAMES].sort(), ['fileOptions', 'toolsFor'])
})

test('闭集查表：认得的认得，继承来的键骗不过去', () => {
  assert.equal(isDynamicProviderName('toolsFor'), true)
  assert.equal(isDynamicProviderName('toolsForX'), false)
  for (const sneaky of ['toString', 'constructor', '__proto__', 'hasOwnProperty']) {
    assert.equal(isDynamicProviderName(sneaky), false, `'${sneaky}' 不该被当成提供者名`)
  }
})

test('声明的 `from` 都是真的格名，且声明的输出是合法输出', () => {
  for (const [name, spec] of Object.entries(DYNAMIC_PROVIDERS)) {
    for (const cell of spec.reads) {
      assert.ok(
        (AGENT_CTX_KEYS as string[]).includes(cell),
        `提供者 '${name}' 声明读 '${cell}'，而 ctx 只有 ${AGENT_CTX_KEYS.join(' / ')}`,
      )
    }
    assert.ok(DYNAMIC_OUTPUTS.includes(spec.output), `提供者 '${name}' 的输出 '${spec.output}' 不在 ${DYNAMIC_OUTPUTS.join(' / ')} 里`)
  }
})

// ═══════════════════════════════════════════════════════════
// ② 行为核对：声明了的真的读，没声明的一格都不读
// ═══════════════════════════════════════════════════════════

test('★★ 声明的每一格都真的影响输出 —— 少喂一格候选就会变', () => {
  for (const name of DYNAMIC_PROVIDER_NAMES) {
    const base = IMPL[name](richCtx())
    for (const cell of DYNAMIC_PROVIDERS[name].reads) {
      const mutated: AgentCtx = { ...richCtx(), [cell]: OTHER[cell] }
      assert.notEqual(
        show(IMPL[name](mutated)),
        show(base),
        `提供者 '${name}' 声明读 '${cell}'，可改了它输出没变 —— 声明和实现至少有一个错了`,
      )
    }
  }
})

test('★★ 没声明的格，改了一格都不许影响输出 —— 不许偷偷读别的', () => {
  for (const name of DYNAMIC_PROVIDER_NAMES) {
    const declared = new Set<string>(DYNAMIC_PROVIDERS[name].reads)
    const base = IMPL[name](richCtx())
    for (const cell of AGENT_CTX_KEYS as string[]) {
      if (declared.has(cell)) continue
      const mutated: AgentCtx = { ...richCtx(), [cell]: OTHER[cell] }
      assert.equal(
        show(IMPL[name](mutated)),
        show(base),
        `提供者 '${name}' **没有**声明读 '${cell}'，可改了它输出变了 —— 候选会因为没写出来的格而变`,
      )
    }
  }
})

test('缺省状态下也不许读没声明的格（空 ctx 那一档）', () => {
  // 上面那条用的是「什么都发生过的」ctx；这里用最空的 ctx 再走一遍，
  // 因为兜底分支里偷偷读一格是最容易发生、也最难发现的情况
  const empty: AgentCtx = { task: 't', cwd: '/w' }
  for (const name of DYNAMIC_PROVIDER_NAMES) {
    const declared = new Set<string>(DYNAMIC_PROVIDERS[name].reads)
    for (const cell of AGENT_CTX_KEYS as string[]) {
      if (declared.has(cell)) continue
      const mutated: AgentCtx = { ...empty, [cell]: OTHER[cell] }
      assert.equal(
        show(IMPL[name](mutated)),
        show(IMPL[name](empty)),
        `空 ctx 下，'${name}' 因为没声明的 '${cell}' 变了输出`,
      )
    }
  }
})

test('声明的输出形状是候选集（不是字符串、不是计数）', () => {
  for (const name of DYNAMIC_PROVIDER_NAMES) {
    const out = IMPL[name](richCtx())
    assert.equal(typeof out, 'object', `'${name}' 应当返回候选集对象，实际 ${typeof out}`)
    assert.ok(!Array.isArray(out), `'${name}' 应当返回 {候选: 判据} 的形状`)
  }
})

// ═══════════════════════════════════════════════════════════
// ③ 文件与声明必须一致
// ═══════════════════════════════════════════════════════════

test('★★ `DECISION.md` 里声明的输入格，和这份声明**逐字一致**', () => {
  /*
    文件是**契约**，这里是**实现的能力**。两边各写一遍是有意的（一个给宿主读、
    一个给校验用），但它们必须是同一个东西 —— 否则文件说的和实现做的就分叉了，
    而分叉的表现是候选静默地多一类或少一类。
  */
  const doc = parseDecisionDoc(readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8'))
  let checked = 0
  for (const block of doc.blocks) {
    if (!block.dynamic) continue
    checked++
    const { provider, reads } = block.dynamic
    const declared = DYNAMIC_PROVIDERS[provider as DynamicProviderName]
    assert.ok(declared, `块 '${block.id}' 点名了提供者 '${provider}'，而声明表里没有它`)
    assert.deepEqual(
      [...reads],
      [...declared.reads],
      `块 '${block.id}' 的 '${provider}' 输入格和声明表对不上`,
    )
    assert.equal(block.dynamic.output, declared.output, `块 '${block.id}' 的 '${provider}' 输出形状和声明表对不上`)
  }
  assert.equal(checked, 2, '`DECISION.md` 里应当正好有两个 `dynamic:` 声明')
})

test('解析期就要求写出输入格 —— 光写 `(ctx)` 会被拒', () => {
  const bare = parseDynamic('toolsFor(ctx) → candidates —— 理由')
  assert.ok(
    bare.problems.some((m) => /没有写它读哪几格/.test(m)),
    `裸 (ctx) 必须被拒并说清怎么改，实际：${JSON.stringify(bare.problems)}`,
  )
  const good = parseDynamic('toolsFor(ctx: files, history) → candidates —— 理由')
  assert.deepEqual(good.problems, [])
  assert.deepEqual([...good.reads], ['files', 'history'])
})
