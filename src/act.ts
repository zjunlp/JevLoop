/**
 * JevLoop · L2 接缝 —— 工具的**定义角**
 *
 * 能力缝是三角（docs/CODE-STYLE.md §10）：定义 / 提供者 / 消费。
 *
 *     定义     `Tool` 接口 + 注册表契约 + 两道检查   ← 这里
 *     提供者   本地文件系统实现                      （act-local.ts）
 *     消费     gradeRisk / pickTool / 调用路径        （decisions.ts / agent.ts）
 *
 * 这个文件**没有 IO、没有实现、没有注册表** —— 和 `seam-provider.ts` 同一个形状。
 * 谁能提供一张「名字 → `Tool`」的表，谁就能当工具后端：本地文件系统、沙箱、
 * 远程 FS、测试里的桩，都只认这一个契约。
 *
 * **为什么值得拆**（docs/CODE-STYLE.md §10）：`Tool` 是全仓库唯一产生**真实
 * 副作用**的能力，此前却是最不可替换的一个 —— 接口、实现、注册表、调用路径
 * 四件事挤在同一个文件里，想把它指向沙箱或远程 FS 必须改内核。
 *
 * ★ 两道检查（`isToolName` / `callTool`）住在这里而不是提供者里，理由同
 *   `seam-provider.ts` 把失败分类下沉到 L0：**边界靠人记就会漏**。
 *   换一个后端时「模型给的工具名不可信」这条必须还在，所以它属于契约。
 *
 * @module JevLoop/act
 */

// ═══════════════════════════════════════════════════════════
// Tool —— 内核与副作用之间的唯一界面
// ═══════════════════════════════════════════════════════════

export interface Tool {
  name: string
  description: string
  /** 静态风险基线 0..3。判定节点会参考它，但最终判定由模型做 */
  baseRisk: number
  run(input: string, cwd: string): Promise<string>
}

/**
 * 一张工具表：名字 → 工具。
 *
 * 用普通的对象而不是 `Map`，是因为注册表本身是一份**声明** —— 名字在源码里
 * 逐字可读，`ToolName` 从它推出封闭联合（见 `act-local.ts`）。
 */
export type ToolRegistry = Record<string, Tool>

/** 注册表里**实际存在**的名字。从具体的表推出，不是 `string` */
export type ToolNameOf<T extends ToolRegistry> = keyof T & string

// ═══════════════════════════════════════════════════════════
// 两道契约 —— 每个提供者都必须走这两条，不许自己实现一份
// ═══════════════════════════════════════════════════════════

/**
 * 模型返回的工具名是**不可信输入** —— 调用前必须过这一道
 * （docs/CODE-STYLE.md §6 允许的真实边界）。
 *
 * 不过会怎样：`callTool` 返回「错误：没有这个工具」，而这个字符串会被当成
 * 普通工具输出喂给 `stepOk` 判定 —— 判定模型看到的是一段文本，它无法区分
 * 「工具跑出来的结果」和「工具根本不存在」。
 *
 * ★ 走 `Object.hasOwn` 而不是 `in`：后者会被 `__proto__` / `toString` 这类
 *   **继承来的键**骗过去，而那正是需要挡住的一类输入。
 */
export function isToolName<T extends ToolRegistry>(tools: T, v: string): v is ToolNameOf<T> {
  return Object.hasOwn(tools, v)
}

/**
 * 全部工具名，顺序即注册表的声明顺序。
 *
 * 用来展示或做基于名字的校验。**要判断一个字符串是不是工具名请用
 * `isToolName()`** —— 它走 `Object.hasOwn`，不会被继承来的键骗过去。
 */
export function toolNames<T extends ToolRegistry>(tools: T): ToolNameOf<T>[] {
  return Object.keys(tools) as ToolNameOf<T>[]
}

/**
 * 执行一次工具调用。
 *
 * 判定节点已经决定「放行 / 需要授权」了，这里只负责执行 ——
 * 但**执行结果永远要回传**，因为判定「成功了吗」需要看到它。
 */
export async function callTool<T extends ToolRegistry>(
  tools: T,
  name: ToolNameOf<T>,
  input: string,
  cwd: string,
): Promise<string> {
  const tool = tools[name]
  try {
    return await tool.run(input, cwd)
  } catch (err) {
    return `错误：${(err as Error).message}`
  }
}
