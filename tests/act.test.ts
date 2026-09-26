/**
 * 工具缝的**定义角**（`src/act.ts`）必须真的和实现分开。
 *
 * ═══════════════════════════════════════════════════════════
 * 这个文件测的是「缝切开了没有」，不是「工具好不好用」
 * ═══════════════════════════════════════════════════════════
 *
 * 工具好不好用由 `core.test.ts` 测（它拿 `LOCAL_TOOLS` 跑真实文件系统）。
 * 这里测的是另一件事，也是拆缝**唯一**能诚实验收的那条：
 *
 *     一张**完全不碰文件系统**的工具表，能不能只对着 `act.ts` 立起来？
 *
 * ★ 它是一道**编译期**检查，不只是运行期断言。若 `act.ts` 里还藏着本地实现
 *   （import 了 `node:fs`、或者 `callTool` 写死了 `LOCAL_TOOLS`），下面这个
 *   只用字符串的假注册表就**编译不过** —— 那正是「缝没切开」的定义。
 *
 * ⚠️ 说清楚它**不**证明什么：它**不**证明内核可以换掉工具表。今天不行 ——
 *   `agent.ts` / `decisions.ts` 仍然直接 import `LOCAL_TOOLS`（模块级注册表，
 *   不是注入的）。把工具表变成 `runAgent` 的参数是**下一刀**（TODO §1 第二个
 *   checkbox，和加 shell / git 一起做），那时才谈得上「换一个提供者」。
 *   在这里假装测了那件事，就是 §8.15 那条「测试通过 ≠ 测试抓得住」。
 *
 * @module JevLoop/act.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { callTool, isToolName, toolNames, type ToolRegistry } from '../src/act.ts'

/**
 * 一张**不碰文件系统**的表：只有纯字符串运算。
 *
 * `satisfies ToolRegistry` 就是验收条件 —— 它只依赖 `act.ts` 导出的契约，
 * 拿不到任何本地实现，也不需要 `cwd`。
 */
const FAKE = {
  echo: {
    name: 'echo',
    description: '原样返回输入',
    baseRisk: 0,
    async run(input: string): Promise<string> {
      return input
    },
  },
  boom: {
    name: 'boom',
    description: '永远抛错',
    baseRisk: 2,
    async run(): Promise<string> {
      throw new Error('炸了')
    },
  },
} satisfies ToolRegistry

test('定义角立得住：一个只有两个工具、不碰文件系统的表就能当注册表', async () => {
  assert.deepEqual(toolNames(FAKE), ['echo', 'boom'], '名字按声明顺序，从表本身推出')
  assert.equal(await callTool(FAKE, 'echo', 'hi', '/nowhere'), 'hi', 'cwd 只是契约参数')
  assert.equal(await callTool(FAKE, 'boom', '', '/nowhere'), '错误：炸了', '执行结果永远回传')
})

test('工具名是不可信输入：继承来的键不算工具', () => {
  assert.equal(isToolName(FAKE, 'echo'), true)
  assert.equal(isToolName(FAKE, 'nope'), false)
  // ★ `in` 会在这三个上返回 true —— `Object.hasOwn` 不会。
  //   模型给的名字走到这里时，`toString` / `__proto__` 是它最容易撞中的形状。
  assert.equal(isToolName(FAKE, 'toString'), false)
  assert.equal(isToolName(FAKE, '__proto__'), false)
  assert.equal(isToolName(FAKE, 'constructor'), false)
})

test('判定收窄到具体表的键 —— 写错就是编译错', () => {
  const raw = 'echo'
  if (isToolName(FAKE, raw)) {
    // 若 `isToolName` 返回 `v is string`（也就是没和表绑定），这一行编译不过。
    const narrowed: 'echo' | 'boom' = raw
    assert.equal(narrowed, 'echo')
  } else {
    assert.fail('echo 应当是这张表里的键')
  }
})
