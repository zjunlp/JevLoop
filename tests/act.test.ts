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
 * ★ 这里还要测**第二刀**（TODO §1 第二个 checkbox）：工具表不只是「定义角立得住」，
 *   而是**能换掉实现**。`runAgent({ tools })` 现在收一张表，内核一行不改就能指向
 *   沙箱 / 远程 FS / 一个纯字符串的桩。
 *
 *   验收方式是下面那条 `★ 内核可以换掉整个工具表` —— 它给一个**根本不存在**的
 *   `cwd` 加一张不碰文件系统的表：内核但凡还在用 `LOCAL_TOOLS`，第一步就炸。
 *
 * ⚠️ 说清楚它**仍然不**证明什么：**名字换不了**，只有实现能换。内核只对这六个
 *   名字有输入解析规则；换一个名字它会响亮地拒绝（`assertNever`），而不是猜一个
 *   输入 —— 猜出来的输入会被真的执行。要换一套工具名，需要的是通用输入协议，
 *   那是另一刀（和加 shell / git 一起）。
 *
 * @module JevLoop/act.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'

import { callTool, isToolName, toolNames, type ToolRegistry } from '../src/act.ts'
import type { ToolTable } from '../src/act-local.ts'
import { runAgent } from '../src/agent.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import type { Answer, AnswerSet } from '../src/vocab.ts'
import type { DecideRequest } from '../src/seam-provider.ts'

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

/**
 * **换了实现的同一套工具名** —— 六个都在，但一个字节的文件系统都不碰。
 *
 * 为什么必须有全部六个名字：`ToolTable` 要求齐全（注入一半是编译错误），
 * 而且内核的 `resolveInput` 对每个名字都有规则，会真的调到它们。
 */
function fakeTable(log: string[]): ToolTable {
  const note = (name: string) => async (input: string): Promise<string> => {
    log.push(`${name}(${input})`)
    if (name === 'list_dir') return 'alpha.ts\nbeta.ts'
    if (name === 'read_file') return 'export function totalOf() {}'
    if (name === 'done') return '任务标记为完成'
    return `${name} 完成`
  }
  return {
    list_dir: { name: 'list_dir', description: '假装列目录', baseRisk: 0, run: note('list_dir') },
    read_file: { name: 'read_file', description: '假装读文件', baseRisk: 0, run: note('read_file') },
    write_file: { name: 'write_file', description: '假装写文件', baseRisk: 1, run: note('write_file') },
    move_file: { name: 'move_file', description: '假装移动', baseRisk: 2, run: note('move_file') },
    delete_file: { name: 'delete_file', description: '假装删除', baseRisk: 3, run: note('delete_file') },
    done: { name: 'done', description: '假装完成', baseRisk: 0, run: note('done') },
  }
}

test('★★★ 内核可以换掉整个工具表：给一个不存在的 cwd，用一张不碰文件系统的表跑完一轮', async () => {
  /*
    ★ 这条是「第二刀切开了没有」的验收，而且它**故意用不存在的 cwd**：

      `cwd` 是 `/definitely/not/a/real/path`。内核但凡还在走 `LOCAL_TOOLS`，
      `list_dir` 第一步就会 ENOENT。它跑得通，就说明表真的被换掉了 ——
      而不是「测试恰好没触发到那条路径」。
  */
  const log: string[] = []
  const tools = fakeTable(log)

  // 一个固定走「列目录 → 读文件 → 结束」的判定后端
  let step = 0
  const provider = {
    name: 'scripted',
    decide: async (req: DecideRequest) => {
      const answers: AnswerSet = {}
      for (const [id, q] of Object.entries(req.questions)) {
        if (q.type === 'noul') answers[id] = { type: 'noul', noul: id === 'needs_auth' ? 0.1 : 0.95 } as Answer
        else if (q.type === 'score') {
          answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.95 } as Answer
        } else {
          const options = Object.keys(q.criteria ?? {})
          const want = step === 0 ? 'list_dir' : step === 1 ? 'read_file' : 'done'
          const choice = options.includes(want) ? want : options[0]!
          answers[id] = {
            type: 'choice',
            choice,
            probabilities: Object.fromEntries(
              options.map((o) => [o, o === choice ? 0.95 : 0.05 / Math.max(1, options.length - 1)]),
            ),
            confidence: 0.95,
          } as Answer
        }
        if (id === 'tool') step++
      }
      return { answers, latencyMs: 0, provider: 'scripted' }
    },
  }

  const result = await runAgent({
    task: '目录里有什么？',
    cwd: '/definitely/not/a/real/path',
    tools, // ★ 就是这一行：内核不再认死 LOCAL_TOOLS
    decider: new Decider({ provider, meter: new Meter() }),
    generator: {
      name: 'noop',
      generate: async () => ({ text: '目录里有 alpha.ts 和 beta.ts', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'noop' }),
    },
    maxSteps: 6,
  })

  assert.ok(
    log.some((l) => l.startsWith('list_dir')),
    `★ 内核必须调到**这张表**的 list_dir，实际调用：${JSON.stringify(log)}`,
  )
  assert.ok(log.length > 0, '至少要真的用过这张表')
  assert.ok(result.answer.includes('alpha.ts'), '生成的结果要能出来')
})

test('★★ 注入的工具表**替换**了 locals：默认那份一条都不该被调到', async () => {
  // 与上一条同源，但断言的是「没有本地实现漏进来」：用一张把每次调用都记下来的表，
  // 名字与本地表**完全相同** —— 于是「调到了谁」只能靠实现区分，靠不了名字。
  const log: string[] = []
  const tools = fakeTable(log)
  await runAgent({
    task: 't',
    cwd: '/definitely/not/a/real/path',
    tools,
    decider: new Decider({
      provider: {
        name: 'only-list',
        decide: async (req: DecideRequest) => {
          const answers: AnswerSet = {}
          for (const [id, q] of Object.entries(req.questions)) {
            if (q.type === 'noul') answers[id] = { type: 'noul', noul: id === 'needs_auth' ? 0.1 : 0.95 } as Answer
            else if (q.type === 'score') {
              answers[id] = { type: 'score', score: 0, legend: {}, probabilities: {}, confidence: 0.95 } as Answer
            } else {
              const options = Object.keys(q.criteria ?? {})
              const choice = options.includes('list_dir') ? 'list_dir' : options[0]!
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
          return { answers, latencyMs: 0, provider: 'only-list' }
        },
      },
      meter: new Meter(),
    }),
    generator: {
      name: 'noop',
      generate: async () => ({ text: 'ok', latencyMs: 0, inputTokens: 0, outputTokens: 0, model: 'noop' }),
    },
    maxSteps: 2,
  })
  assert.ok(log.some((l) => l.startsWith('list_dir')), '这张表必须被调到')
})

// ═══════════════════════════════════════════════════════════
// ⑥ TODO §8：需要隔离的工具，没有确认就**连跑都不跑**
// ═══════════════════════════════════════════════════════════

/**
 * 一个**声明了自己需要隔离**的工具。
 *
 * ★ 它在本仓库里还没有真实消费者（进程类工具是 TODO §1 的下一项），所以这里
 *   用一个测试夹具来验证**闸门本身**。闸门是 §8 那一项要的东西：
 *   「harness 封不住 CPU / 内存 / 磁盘 / 网络」这件事，从一句话变成一道检查。
 */
const NEEDS_ISOLATION = {
  process_spawner: {
    name: 'process_spawner',
    description: '起一个进程（夹具）',
    baseRisk: 3,
    requiresIsolation: true,
    timeoutMs: 1000,
    /** 记录它**真的跑过**。闸门必须在 `run()` 之前拦住，所以这个计数必须是 0 */
    async run(): Promise<string> {
      ran++
      return '起了个进程'
    },
  },
} satisfies ToolRegistry
let ran = 0

test('★★★ 需要隔离的工具：默认**拒绝**，而且拒绝发生在 `run()` 之前', async () => {
  ran = 0
  const out = await callTool(NEEDS_ISOLATION, 'process_spawner', '', '/w')
  assert.match(out, /^错误：/, `必须拒绝，实际：${out}`)
  assert.match(out, /隔离/, '要说清是因为没有确认隔离')
  assert.match(out, /SECURITY\.md/, '要把人指到那份文档')
  assert.equal(ran, 0, '★ `run()` 一次都不许被调到 —— 副作用发生在闸门之前才是最坏的')
})

test('★★ 明确确认隔离之后才放行', async () => {
  ran = 0
  const out = await callTool(NEEDS_ISOLATION, 'process_spawner', '', '/w', { isolated: true })
  assert.equal(out, '起了个进程', `确认隔离后应当执行，实际：${out}`)
  assert.equal(ran, 1, '确认之后才真的跑')
})

test('★ `isolated` 必须是**显式 true** —— `undefined` / `false` 都不算确认', async () => {
  for (const limits of [{}, { isolated: false }, { maxOutputChars: 100 }]) {
    ran = 0
    const out = await callTool(NEEDS_ISOLATION, 'process_spawner', '', '/w', limits)
    assert.match(out, /^错误：/, `${JSON.stringify(limits)} 不该算确认`)
    assert.equal(ran, 0, '不许因为「没传就是没限制」而放行')
  }
})

test('★ 不声明 `requiresIsolation` 的工具**不受影响** —— 闸门不是全局的', async () => {
  assert.equal(await callTool(FAKE, 'echo', 'hi', '/w'), 'hi', '普通工具照常')
  assert.equal(await callTool(FAKE, 'echo', 'hi', '/w', {}), 'hi')
})
