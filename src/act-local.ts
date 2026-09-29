/**
 * JevLoop · L2 接缝 —— 工具的**本地文件系统提供者**
 *
 * 缝的另一角（定义在 `act.ts`）：
 *
 *     定义     `Tool` 接口 + 注册表契约   （act.ts）
 *     提供者   五个工具的真实副作用        ← 这里
 *     消费     gradeRisk / pickTool       （decisions.ts / agent.ts）
 *
 * 这里住着全仓库**唯一**产生真实副作用的地方：五个工具的实现、以及那道
 * 「路径锁死在工作目录内」的检查。**换后端就是换这个文件** —— 指向沙箱、
 * 远程 FS 或一个测试桩，内核（`agent.ts` / `decisions.ts`）一行都不用动。
 *
 * ★ 这个文件只 import 定义角（`act.ts`），别的什么都不 import。
 *   那不是巧合：`scripts/check.ts` 的 layers 规则规定 L2 内部只允许
 *   「提供者 → 定义角」这一个方向（docs/CODE-STYLE.md §11）。
 *
 * 两道契约（不可信的工具名、执行结果永远回传）**不在**这里，在 `act.ts` ——
 * 它们属于契约而非某个实现，否则换后端时会被漏掉。
 *
 * @module JevLoop/act-local
 */

import { readFile, writeFile, readdir, mkdir, stat, unlink, rmdir, rename } from 'node:fs/promises'
import { resolve, relative, dirname, sep } from 'node:path'

import type { ToolRegistry } from './act.ts'

/** 把用户给的路径解析到 cwd 内，逃逸就抛 */
function safePath(cwd: string, p: string): string {
  const full = resolve(cwd, p)
  const rel = relative(cwd, full)
  if (rel.startsWith('..') || (rel !== '' && rel.startsWith(sep))) {
    throw new Error(`路径逃出工作目录：${p}`)
  }
  return full
}

/**
 * 本地文件系统这一份工具表。**注册表住在这里，不在定义角里** ——
 * 定义角不认识任何一个具体工具。
 *
 * `satisfies` 而不是 `: ToolRegistry` —— 后者会把键擦成 `string`，于是
 * `ToolName` 只能是 `string`，`defaultInput` 的 switch 就永远需要一个
 * 什么都接的 `default` 分支。
 */
export const LOCAL_TOOLS = {
  list_dir: {
    name: 'list_dir',
    description: '列出工作目录里的文件（不含子目录内容）',
    baseRisk: 0,
    // 只读 ⇒ 迟到的结果丢掉就行，超时可以放心声明（见 Tool.timeoutMs）
    timeoutMs: 5000,
    async run(_input: string, cwd: string): Promise<string> {
      const entries = await readdir(cwd, { withFileTypes: true })
      const out = entries
        .filter((e) => !e.name.startsWith('.'))
        .map((e) => (e.isDirectory() ? `${e.name}/` : e.name))
        .sort()
      // ★ 空目录返回**空串**，不是「(目录为空)」这种给人看的文案。
      //
      //   这个函数的返回值不只是给人读的：`agent.ts` 会把它
      //   `split('\n').filter(l => l && !l.endsWith('/'))` 当成**文件列表**解析
      //   （写进 `ctx.files`，再进 `pickInput` 的候选）。
      //   返回文案时那句文案本身就成了"文件名"：实测空目录下 `ctx.files = ['(目录为空)']`、
      //   `hasFileOptions` 为 true、`read_file` 去读它得到 ENOENT；
      //   更糟的是**写路径** —— `write_file` 会在用户目录里创建一个真名叫
      //   `(目录为空)` 的文件并报告「已写入」。
      //
      //   代价：界面上看不到「目录为空」这句话了。那是**显示层**该说的话，
      //   等 `Tool.run()` 有了结构化返回（见 REVIEWS-round6 的移交）再挪过去 ——
      //   在返回值还是散文的情况下，任何非空文案都会被解析成一个文件。
      return out.join('\n')
    },
  },

  read_file: {
    name: 'read_file',
    description: '读取一个文件的内容。输入是相对工作目录的路径',
    baseRisk: 0,
    // 只读 ⇒ 同上。而**不**声明 maxInputChars：它只收一个路径
    timeoutMs: 5000,
    async run(input: string, cwd: string): Promise<string> {
      const path = safePath(cwd, input.trim())
      const info = await stat(path)
      if (info.isDirectory()) return `(这是一个目录，请用 list_dir)`
      const text = await readFile(path, 'utf8')
      return text.length > 4000 ? text.slice(0, 4000) + `\n…[+${text.length - 4000} chars]` : text
    },
  },

  write_file: {
    name: 'write_file',
    description: '写入或覆盖一个文件。输入格式：`路径\n内容`（第一行是路径，其余是内容）',
    baseRisk: 1,
    /*
      「这个工具被允许写多少」的落点：输入就是 `路径\n内容`，所以给输入封顶
      等于给能写下去的字节封顶，而且 `callTool` 在 `run()` **之前**就查 ——
      超限时文件一个字节都不会被改。

      64KB：远高于任何一次该写的内容（生成预算本身在 KB 级），
      挡的是「生成跑飞了，一次写下去 50MB」。

      ⚠️ 它**不**声明 timeoutMs，这是有意的：写操作取消不掉，报超时而其实
         写成功了，会让 loop 基于一件没发生的事往下走（见 Tool.timeoutMs）。
    */
    maxInputChars: 64_000,
    async run(input: string, cwd: string): Promise<string> {
      const nl = input.indexOf('\n')
      if (nl < 0) throw new Error('write_file 需要两行输入：第一行路径，其余内容')
      const path = safePath(cwd, input.slice(0, nl).trim())
      const content = input.slice(nl + 1)
      await mkdir(dirname(path), { recursive: true })
      await writeFile(path, content, 'utf8')
      return `已写入 ${relative(cwd, path)}（${content.length} 字符）`
    },
  },

  /*
    ── 阶梯的第 2 档（TODO §1 剩下的那个缺口）────────────────────

    `irreversible` (2) 一直是空的。`move_file` 指向它 —— 而它**不是** `delete_file`
    的复制品，三件事都不一样：

      1. **输入是两行**（来源 + 目标），目标不在任何闭集里。所以和 `write_file` /
         `delete_file` 一样，它由调用方的 `provideWriteInput` **生成**，不是从
         候选里挑的。★ 那个钩子能分辨自己被问的是哪个工具：`agent.ts` 在
         `resolveInput` **之前**就把 `ctx.lastTool` 设成了选中的工具。
      2. ★ **它拒绝覆盖已存在的目标**，而这一条正是它停在 2 档而不是 3 档的原因：
         改名之后原路径没了（不可逆），但**一个字节都没丢**。一旦允许覆盖，
         它就是 `destructive`（3）—— 被覆盖的那份捞不回来。档位是行为的结论，
         不是给工具贴的标签。
      3. **不创建父目录**。`write_file` 会建（写文件必然要建它的目录），
         而移动不该顺手造出目录：一个失败的操作不该在盘上留下东西。
         这也和 `mv` 的行为一致。

    ★ 为什么不是 shell：§8 的安全边界还开着（见下面 delete_file 那段说明）。
      这个工具仍然只动工作目录里的东西，路径照走 `safePath`，不起进程。
  */
  move_file: {
    name: 'move_file',
    description:
      '移动或重命名一个文件/目录。输入格式：`来源\\n目标`（两行，都相对工作目录）。不可逆：原路径会消失。不会覆盖已存在的目标',
    // 2 = irreversible：原路径没了，但内容还在目标位置上
    baseRisk: 2,
    // 不声明 timeoutMs：移动取消不掉，报超时而其实移成功了是最坏的一种谎
    // （见 Tool.timeoutMs 的说明）
    maxInputChars: 4096,
    async run(input: string, cwd: string): Promise<string> {
      const nl = input.indexOf('\n')
      if (nl < 0) throw new Error('move_file 需要两行输入：第一行来源，第二行目标')
      const from = safePath(cwd, input.slice(0, nl).trim())
      const to = safePath(cwd, input.slice(nl + 1).trim())

      if (from === to) throw new Error('来源与目标相同 —— 没有东西可以移动')

      const src = await stat(from).catch(() => undefined)
      if (!src) throw new Error(`来源不存在：${relative(cwd, from)}`)

      // ★ 拒绝覆盖：这一条就是 2 档与 3 档的分界。先查再移，不是移完再看
      const dst = await stat(to).catch(() => undefined)
      if (dst) {
        throw new Error(
          `目标已存在：${relative(cwd, to)} —— 移动不覆盖（覆盖会丢掉目标那份，那是破坏性操作）`,
        )
      }

      await rename(from, to)
      return `已移动 ${relative(cwd, from)} → ${relative(cwd, to)}`
    },
  },

  /*
    ── 为什么加一个**破坏性**工具（TODO §1）──────────────────────

    §1 写的是「风险阶梯要有真东西可爬」。四个工具里最危险的只是写文件，
    于是 `grade_risk` 的第 3、4 档（irreversible / destructive）**从来没有
    被真的走到过** —— 一条没人爬过的梯子，说它拦得住什么都是空的。

    ★ 为什么不是 shell / git：§8 的安全边界还开着（没有鉴权、没有 CPU/内存/
      磁盘/墙钟上限、沙箱只覆盖路径逃逸）。在这种情况下开一个能起进程的口子，
      是在**放宽**一个已知未加固的边界，而不是补上它。这个工具留在现有沙箱内：
      路径照走 `safePath`，只动工作目录里的东西，不起进程。

    ★ 它只删**空目录**：删非空目录要递归，而递归删是不可逆的失控面。真需要的话，
      让人先手动清空 —— 这条限制是刻意的，不是没做完。
  */
  delete_file: {
    name: 'delete_file',
    description: '删除一个文件或一个空目录。输入是相对工作目录的路径。不可撤销',
    // 3 = destructive：`DECISION.md` 风险阶梯的最高档，于是
    // `score:risk >= 2 → ask_human` 那道硬闸门第一次有真东西可指
    baseRisk: 3,
    // 不声明 timeoutMs：删除更不可能被取消，报「超时失败」而文件其实删掉了
    // 是最坏的一种谎（见 Tool.timeoutMs 的说明）
    maxInputChars: 4096,
    async run(input: string, cwd: string): Promise<string> {
      const path = safePath(cwd, input.trim())
      const info = await stat(path)
      const shown = relative(cwd, path)
      if (info.isDirectory()) {
        await rmdir(path)
        return `已删除空目录 ${shown}`
      }
      const size = info.size
      await unlink(path)
      return `已删除 ${shown}（${size} 字节）`
    },
  },

  done: {
    name: 'done',
    description: '任务已完成，不需要再调用任何工具',
    baseRisk: 0,
    async run(): Promise<string> {
      return '任务标记为完成'
    },
  },
} satisfies ToolRegistry

/**
 * 工具名的**封闭**联合。来自这份注册表的实际键，不是 `string`。
 *
 * 它跟着注册表落在提供者这一侧：`keyof` 只能从**具体的表**推出，
 * 而定义角不认识任何一个具体工具（见 `act.ts` 的 `ToolNameOf`）。
 */
export type ToolName = keyof typeof LOCAL_TOOLS
