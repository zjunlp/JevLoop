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

import { readFile, writeFile, readdir, mkdir, stat, unlink, rmdir } from 'node:fs/promises'
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
