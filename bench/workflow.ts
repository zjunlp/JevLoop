/**
 * JevLoop · 第三条臂：**手写 workflow**
 *
 * ══════════════════════════════════════════════════════════════
 *  **为什么要有这一条臂**
 * ══════════════════════════════════════════════════════════════
 *
 * 大厂至今在很多地方用 workflow 而不是 agent，理由只有一个：**它可靠、
 * 不会出错。** 所以「JevLoop 比 agent 可控」这句话，只有在**和 workflow
 * 比过**之后才算数 —— 和自己比不算。
 *
 * 这条臂的定义，和另外两条严格对齐（§8.15 的先例：四个臂共用同一个 `run_loop`、
 * 同一个 `build_prompt`、同一批工具，**唯一不同的那个字段就是决策者**）：
 *
 *     同一批夹具 · 同一个 `callTool` + `LOCAL_TOOLS` · 同一套验收
 *     唯一不同的：**分支由谁决定**
 *
 *     JevLoop   判定模型给 typed 答案，策略是纯代码
 *     ReAct     生成模型每一步说一次
 *     Workflow  **人写死的代码**          ← 这里
 *
 * ── ★★ 读这一臂的数字时必须先知道的三件事 ──────────────────────
 *
 * **① 它会 100% 通过 —— 而那不是结果，那是定义。**
 *   一个为这批任务写出来的 workflow 当然全对。所以**冻结夹具上的三方对比
 *   证明不了任何事**。真正要量的是同族里**没为它写过**的任务：workflow 在
 *   那里不是「答错」，是**根本跑不起来**。
 *
 * **② 它的成本是「每个任务一段代码」。**
 *   所以这里逐条报**手写行数**，并且这个数**随任务数线性增长** ——
 *   而另外两条臂写完一次就不用再写。
 *
 * **③ 它的回答是写死的模板。**
 *   真实 workflow 也往模板里填值（这里从工具结果里抠），但**没有一次模型调用**。
 *   哪些答案是「抠出来的」、哪些是「背下来的」，每条都标了。
 *
 * @module JevLoop/workflow
 */

import { callTool } from '../src/act.ts'
import { LOCAL_TOOLS, type ToolName } from '../src/act-local.ts'
import type { BenchTask } from './tasks.ts'

export interface WorkflowStep {
  tool: ToolName
  /** 空串 = 用 `task.writeInput`（写操作的载荷是生成出来的，三条臂都一样） */
  input: string
}

export interface Workflow {
  /** 手写的调用序列 —— **这就是那张图** */
  steps: (task: BenchTask) => WorkflowStep[]
  /** 手写的回答。可以往模板里填工具结果，但**不调任何模型** */
  answer: (task: BenchTask, results: string[]) => string
  /** 手写的行数（步骤 + 回答模板）—— 编写成本的那把尺子 */
  lines: number
  /** 这条回答里哪一部分是**背下来的**、哪一部分是**算出来的** */
  note: string
}

/** 从源码里抠出导出的函数名 —— workflow 能做的那种「解析」 */
const exportedFunction = (src: string): string => /export function (\w+)/.exec(src)?.[1] ?? '(没找到)'

/** 抠出文档注释里的正文（`discriminate` 要从散文里拿答案） */
const docComment = (src: string): string => /\/\*\*([\s\S]*?)\*\//.exec(src)?.[1]?.replace(/\*/g, '').trim() ?? ''

/**
 * 七个任务各自的 workflow。
 *
 * ★ 这些计划是**从任务那句话写出来的**，不是从 `task.required` 抄的 ——
 *   判据机那份是**答案键**，抄它等于拿答案去考自己。
 */
export const WORKFLOWS: Record<string, Workflow> = {
  direct: {
    steps: () => [],
    answer: () => '1 加 1 等于 2。',
    lines: 2,
    note: '**背下来的**：答案直接写在模板里，没读任何东西',
  },

  list: {
    steps: () => [{ tool: 'list_dir', input: '' }],
    answer: (_t, r) => `工作目录里有：${(r[0] ?? '').split('\n').filter(Boolean).join('、')}。`,
    lines: 3,
    note: '**算出来的**：把 list_dir 的输出填进模板',
  },

  'read-one': {
    steps: () => [{ tool: 'read_file', input: 'alpha.ts' }],
    answer: (_t, r) => `alpha.ts 里导出的函数叫 ${exportedFunction(r[0] ?? '')}。`,
    lines: 4,
    note: '**抠出来的**：对源码做一次正则',
  },

  'read-both': {
    steps: () => [
      { tool: 'read_file', input: 'alpha.ts' },
      { tool: 'read_file', input: 'beta.ts' },
    ],
    answer: (_t, r) =>
      `alpha.ts 导出 ${exportedFunction(r[0] ?? '')}，beta.ts 导出 ${exportedFunction(r[1] ?? '')}。`,
    lines: 7,
    note: '**抠出来的**：两次正则。★ 文件名写死在这里 —— 目录一变就得改',
  },

  discriminate: {
    steps: () => [{ tool: 'read_file', input: 'beta.ts' }],
    answer: (_t, r) => {
      const doc = docComment(r[0] ?? '')
      return `beta.ts 里的 dedupe ${doc || '保留第一次出现的那个'}。`
    },
    lines: 5,
    // ★ 这一条最能说明 workflow 的性质：问题是「遇到重复项保留哪一个」——
    //   那是**散文里的知识**，代码算不出来。所以这里的做法是**把注释原文抠出来
    //   再拼进回答**。真实 workflow 退化的样子就是这样：正则抠散文。
    note: '**抠出来的（而且很脆）**：从文档注释里正则抠散文。代码算不出语义',
  },

  'count-ts': {
    steps: () => [
      { tool: 'list_dir', input: '' },
      { tool: 'read_file', input: 'alpha.ts' },
      { tool: 'read_file', input: 'beta.ts' },
    ],
    answer: (_t, r) => {
      const ts = (r[0] ?? '').split('\n').filter((f) => f.endsWith('.ts'))
      return `目录里有 ${ts.length} 个 TypeScript 文件：${ts.join('、')}。` +
        `alpha.ts 导出 ${exportedFunction(r[1] ?? '')}，beta.ts 导出 ${exportedFunction(r[2] ?? '')}。`
    },
    lines: 9,
    note: '**算出来的**：从 list_dir 的输出里数 `.ts`（而不是把「2」写死）',
  },

  write: {
    steps: (t) => [
      { tool: 'read_file', input: 'alpha.ts' },
      // 写操作的载荷由台子给（三条臂拿的是同一份 —— 内容属于生成，不属于判定）
      { tool: 'write_file', input: t.writeInput ?? '' },
    ],
    answer: () => '已经把 totalOf 抄进新文件 summary.ts 了。',
    lines: 6,
    note: '**背下来的回答**（写了什么由台子给），但调用序列是手写的',
  },
}

/**
 * 跑一条任务的手写 workflow。
 *
 * ★ **没有计划就抛** —— 而且这不是错误处理，这是这一臂**要量的那个性质**：
 *   workflow 不会「答错一个没见过的情况」，它**在没见过的情况上不存在**。
 */
export async function runWorkflow(
  task: BenchTask,
  cwd: string,
): Promise<{ calls: { tool: string; input: string }[]; answer: string }> {
  const wf = WORKFLOWS[task.id]
  if (!wf) {
    throw new Error(
      `没有为 '${task.id}' 写过 workflow —— 这正是要量的那件事：` +
        `workflow 的覆盖面等于**人替它写过的那些任务**，多一条都要再写一段代码`,
    )
  }
  const results: string[] = []
  const calls: { tool: string; input: string }[] = []
  for (const s of wf.steps(task)) {
    const input = s.input || (task.writeInput ?? '')
    calls.push({ tool: s.tool, input })
    results.push(await callTool(LOCAL_TOOLS, s.tool, input, cwd))
  }
  return { calls, answer: wf.answer(task, results) }
}

/** 这一臂的手写总行数 —— 报告里要打在表上（它随任务数线性长） */
export const workflowLines = (): number =>
  Object.values(WORKFLOWS).reduce((n, w) => n + w.lines, 0)

/**
 * 有没有为这条任务写过计划。
 *
 * ★ 单独导出的理由：**「没写过」不是可重试的失败**。第一版让 `runWorkflow`
 *   抛进 `withRetry`，于是它退避重试了两轮 —— 既浪费时间，又往计时表里
 *   塞进一段**不属于这条臂**的墙钟。判定「能不能跑」要在**重试之前**做。
 */
export const hasWorkflow = (taskId: string): boolean => taskId in WORKFLOWS
