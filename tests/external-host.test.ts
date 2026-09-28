/**
 * `examples/external-host.ts` 的**运行方**。
 *
 * ═══════════════════════════════════════════════════════════
 * README 让人跑 `npm run external-host` —— 而在此之前没有任何东西跑它
 * ═══════════════════════════════════════════════════════════
 *
 * 这个仓库记过好几次同一件事（§8.16）：**声明了却没有消费方**。
 * `npm run external-host` 是 README 里推荐给别人看的第一条适配命令，
 * 而它既不在 CI 里、也没有任何测试调用过 —— 它坏掉不会有任何人知道，
 * 直到有人照着 README 敲下那一行。
 *
 * `runDemo()` 现在是**导出**的（不是一段打印脚本），所以这个文件能直接调它、
 * 断言它跑到哪、并证明它是确定性的。这样它进了 `npm test`，也就进了 CI。
 *
 * @module JevLoop/external-host.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { CAPABILITIES, GRAPH, HOST_POSITIONS, runDemo } from '../examples/external-host.ts'

const lines = runDemo()

test('外部宿主能跑完，并自己报出探针通过', () => {
  assert.ok(lines.length > 0, 'runDemo 不该什么都不返回')
  assert.match(lines[lines.length - 1]!, /adapter conformance probe passed/)
})

test('它真的走完了那张自定义图，而不是只解析了文件', () => {
  assert.ok(
    lines.some((l) => /custom graph reached done/.test(l)),
    `应当走到终止态 done，实际：${JSON.stringify(lines.slice(-4))}`,
  )
  assert.ok(lines.some((l) => /escalation graph reached done/.test(l)), '升级那条路也要走到终止态')
})

test('它消费的是参考契约里那四个节点', () => {
  for (const id of ['needs_tool', 'pick_tool', 'step_ok', 'is_done']) {
    assert.ok(lines.some((l) => l.startsWith(`  ${id}:`)), `少了 ${id} 那一行：${JSON.stringify(lines)}`)
  }
})

test('★ 确定性：同一个 fixture 跑两遍，逐字一样', () => {
  // 不确定的 fixture 会让上面每一条断言都变成「有时通过」—— 那种测试
  // 和一个不跑的测试一样危险，所以这里把确定性本身钉住。
  assert.deepEqual(runDemo(), lines)
})

test('导出的能力与图是**事实**，不是描述', () => {
  assert.ok(Object.keys(CAPABILITIES.positions).length > 0, '宿主得声明它处理哪些位置')
  assert.ok(CAPABILITIES.actions.length > 0, '宿主得声明它处理哪些动作')
  assert.ok(Object.keys(GRAPH).length > 0, '自定义图不能是空的')
  assert.ok(Object.keys(HOST_POSITIONS).length > 0, '自定义位置不能是空的')

  // 每一行能力的名字都要对得上形状 —— 少一个字段就会在下游变成 undefined
  for (const [position, actions] of Object.entries(CAPABILITIES.positions)) {
    assert.ok(Array.isArray(actions) && actions.length > 0, `位置 '${position}' 没有动作`)
  }
})
