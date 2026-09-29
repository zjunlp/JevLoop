/**
 * JevLoop · 「漂移检查是不是**可导出**的」—— 纯逻辑，无 IO、无 console
 *
 * ══════════════════════════════════════════════════════════════
 *  **这一轮测的不是「谁更准」，是「改动之后谁还盖得住」。**
 * ══════════════════════════════════════════════════════════════
 *
 * 上一轮（`bench/gate-compare.ts`）的结论是否定式的：契约门与等价的手写门在
 * unsupported completion 上**没有可测差异**。它唯一没能否证的是这句话：
 *
 *     声明式的帧让漂移检查**可导出** —— 契约里新增一格，检查自动跟上；
 *     手写门只覆盖作者记得的那几格。
 *
 * 所以这一轮把「可导出」拆成**可以跑出来的三件事**，而不是停在形容词上：
 *
 *     D1  **加一格声明**，`unfilled` 会不会自动带上它？（零行检查代码改动）
 *     D2  **改一个声明的界**，截断会不会跟着变？（零行检查代码改动）
 *     D3  这些信号**产出了**，有没有人消费？（参考实现：没有）
 *
 * ── ★ 先说清楚这一轮**不是**什么 ────────────────────────────────
 *
 * 它不产生「成功率」，因为这里没有失败率的样本 —— 帧从搬进 `DECISION.md` 起
 * 就没怎么长过（`git log` 可查：`can_deliver` 的正格子一直是 `task/answer/evidence`，
 * 唯一的变化是排除项多了 `canDelete`）。所以下面量的是**改动的代价**与
 * **漏检的可能**，不是「多久会漏一次」。把结构性质说成实测频率，是这类实验
 * 最容易犯的第二个谎（第一个是把人工 oracle 说成自动判定）。
 *
 * ── ★★ 还有一个公平性问题，必须写在实现里 ──────────────────────
 *
 * 手写门**只依赖它读的那几格**。拿「声明格数」去减「守卫格数」会**高估**它的
 * 缺口：一个不读 `task` 的门没有理由为 `task` 写守卫。上一轮的最佳实践手写门
 * 依赖 `draft` / `history` 两格，两格都守住了 —— 也就是说**勤快的作者是 100%**。
 *
 * 所以这里量的口径是**依赖覆盖率**：一个门读了几格、其中几格被漂移检查盖住。
 * 差距只可能出现在**依赖集变化**的时候，而那正是这一轮要量的东西。
 *
 * @module JevLoop/gate-derivable
 */

import { parseDecisionDoc } from '../src/contract.ts'
import { frameSpecFromBlock } from '../src/decisions.ts'
import { compileFrame, type AgentCtx, type Frame, type FrameSpec } from '../src/frame.ts'

/** 一次覆盖度测量的结果 */
export interface Coverage {
  /** 这一帧声明的全部格子（有顺序） */
  declared: string[]
  /** 其中「缺了会被 `unfilled` 记下」的格子 —— 存在性检查的可导出覆盖 */
  presenceCovered: string[]
  /** 其中「超预算会被 `truncated` 记下」的格子 —— 界的可导出覆盖 */
  boundCovered: string[]
}

/** 从一段 `DECISION.md` 文本里取某个节点的帧规格。注入失败会**抛**，不静默降级 */
export function specOf(mdText: string, blockId: string): FrameSpec {
  const block = parseDecisionDoc(mdText).blocks.find((b) => b.id === blockId)
  if (!block) throw new Error(`找不到节点 ${blockId}`)
  const spec = frameSpecFromBlock(block, blockId)
  if (!spec) throw new Error(`节点 ${blockId} 没有可编译的 frame`)
  return spec
}

/** 一个「什么都有、而且都很大」的 ctx —— 用来把能截断的格子都逼出来 */
function fatCtx(spec: FrameSpec): AgentCtx {
  const long = 'x'.repeat(4000)
  const steps = Array.from({ length: 40 }, (_, i) => ({
    step: i,
    tool: 'read_file',
    input: `file-${i}.ts`,
    result: long,
  }))
  // 先把声明里的每一个来源都填上，再逐个删 —— 这样「缺一格」是唯一变量
  const ctx: Record<string, unknown> = {
    task: long,
    cwd: '/work',
    draft: long,
    history: steps,
    files: ['a.ts', 'b.ts'],
    readFiles: ['a.ts'],
    lastTool: 'read_file',
    lastResult: long,
    lastInput: long,
    earlier: long,
    canWrite: true,
    canDelete: true,
  }
  for (const f of spec.fields) {
    if (ctx[f.from] === undefined) ctx[f.from] = long
  }
  return ctx as unknown as AgentCtx
}

/**
 * 量一帧的**可导出覆盖度**。
 *
 * 做法是逐个把声明的来源删掉、把每个格子撑爆，然后看**契约自己**报了什么 ——
 * 不看任何文档、任何注释。所以它顺带是一个回归测试：谁把 `unfilled`/`truncated`
 * 的产出改成硬编码的清单，这里立刻会变。
 */
export function measureCoverage(mdText: string, blockId: string): Coverage {
  const spec = specOf(mdText, blockId)
  const fat = fatCtx(spec)

  const presenceCovered: string[] = []
  for (const f of spec.fields) {
    // ★ 只删这一个来源；其余保持「什么都有」
    const without: Record<string, unknown> = { ...(fat as unknown as Record<string, unknown>) }
    delete without[f.from]
    const frame: Frame = compileFrame(spec, without as unknown as AgentCtx)
    if (frame.unfilled.some((u) => u.key === f.key)) presenceCovered.push(f.key)
  }

  const boundFrame = compileFrame(spec, fat)
  const boundCovered = [...new Set(boundFrame.truncated.map((t) => t.key))]

  return {
    declared: spec.fields.map((f) => f.key),
    presenceCovered,
    boundCovered,
  }
}

/**
 * 手写门的**守卫清单** —— 这是它和契约门真正不同的地方。
 *
 * 契约的检查从 `frame:` 声明**算出来**；手写门的检查是**代码里的一行行**。
 * 所以这里要显式地把它建模成一份清单：一个门守了哪几格，是它作者写下的，
 * 不是它声明出来的。
 */
export interface HandGate {
  id: string
  /** 这个门**读**哪几格 —— 它的依赖集。门的作者知道这个 */
  dependsOn: string[]
  /** 这个门**为哪几格写了守卫**。★ 这才是会漏的地方 */
  guards: string[]
}

/**
 * 一个写得很好的手写门：依赖什么就守什么。
 *
 * ★ 这是**公平的那个对手**，也是这一轮的关键。如果拿一个漏守的手写门来比，
 *   测出来的只是「我故意写坏了一个对手」，那不是实验，是演示。
 */
export const HAND_GATE_DILIGENT: HandGate = {
  id: 'hand-diligent',
  dependsOn: ['answer', 'evidence'],
  guards: ['answer', 'evidence'],
}

/**
 * 依赖覆盖度：这个门读的格子里，有几格被漂移检查盖住了。
 *
 * ★ 口径是 `dependsOn ∩ guards`，不是 `declared ∩ guards` —— 见模块注释里那段
 *   公平性说明。用后者会让一个不读 `task` 的门凭空欠一格。
 */
export function dependencyCoverage(
  gate: HandGate,
  _coverage: Coverage,
): { covered: string[]; uncovered: string[]; ratio: string } {
  const covered = gate.dependsOn.filter((c) => gate.guards.includes(c))
  const uncovered = gate.dependsOn.filter((c) => !gate.guards.includes(c))
  return {
    covered,
    uncovered,
    ratio: `${covered.length}/${gate.dependsOn.length}`,
  }
}

/**
 * 在 `DECISION.md` 文本里给某个节点的 `frame:` **加一格**。
 *
 * 用**已注册**的投影名 —— 投影表是封闭的，未注册的名字会在解析时就抛
 * （实测：`frameSpecFromBlock` 报「投影 'cwdLength' 不在注册表里」）。这条本身
 * 也是「load-time refusal 是真的」的一个实例，只是它是**编译期**的，不是漂移期的。
 */
export function withExtraCell(mdText: string, blockId: string, line: string): string {
  const marker = new RegExp(`(## ${blockId}\\n[\\s\\S]*?frame:\\n)`)
  if (!marker.test(mdText)) throw new Error(`找不到 ${blockId} 的 frame: 段`)
  return mdText.replace(marker, `$1${line}\n`)
}

/** 在 `DECISION.md` 文本里改某个节点的某一格**预算**（只动声明，不动代码） */
export function withBound(mdText: string, cellKey: string, oldBound: number, newBound: number): string {
  const from = new RegExp(`(\\+ ${cellKey}\\s+)${oldBound}(\\s)`)
  if (!from.test(mdText)) throw new Error(`找不到 ${cellKey} 的 ${oldBound} 预算`)
  return mdText.replace(from, `$1${newBound}$2`)
}

/** 三个信号里，参考实现**消费**了哪几个 —— 用来把「产出了」与「有人管」分开 */
export interface SignalConsumption {
  signal: string
  /** 契约里有没有产出它 */
  produced: boolean
  /** 参考运行时的循环里有没有人读它 */
  consumedByRuntime: boolean
  /** 住在哪 */
  where: string
}

/**
 * ★ D3：信号产出了，不等于有人管。
 *
 * 这三条是从**代码**里核出来的（`frame.ts` 产出、`decide.ts`/`agent.ts` 不读），
 * 不是从文档里抄的。它们的用处是给「可导出」划一条诚实的边：可导出的是
 * **信号**，不是**处置** —— 处置仍然是策略，仍然要有人写。
 */
export const SIGNALS: SignalConsumption[] = [
  { signal: 'unfilled（声明过的来源没有被喂）', produced: true, consumedByRuntime: false, where: 'frame.ts 产出；codex 适配器读，参考运行时循环不读' },
  { signal: 'absent（投影说「今天不适用」）', produced: true, consumedByRuntime: false, where: 'frame.ts 产出；无人读' },
  { signal: 'truncated（超了声明预算）', produced: true, consumedByRuntime: false, where: 'frame.ts 产出；无人读' },
]
