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
  /**
   * 这一调允许的最大**输入字符数**。超了 `callTool` **在执行之前**就拒绝。
   *
   * ★ 这才是「一个工具被允许写多少」的落点：`write_file` 的输入就是
   *   `路径\n内容`，所以给输入封顶等于给它能写下去的字节封顶 —— 而且检查
   *   发生在 `run()` 之前，也就是**在产生副作用之前**。等跑完再看结果就晚了：
   *   那时文件已经写在盘上了。
   *
   * 不声明 = 这一调不设输入上限（输出仍然受 `callTool` 的 `maxOutputChars` 约束）。
   */
  maxInputChars?: number
  /**
   * 这一调的超时（毫秒）。**只给「结果来晚了也无害」的工具声明。**
   *
   * ★★ 为什么不是一个全局超时，而是一个要逐个表态的字段：
   *   JS 里**取消不掉**一个已经在跑的 promise（`node:fs/promises` 没有
   *   cancel）。所以超时的真实语义是「**我不再等了**」，不是「它没发生」。
   *
   *   对 `read_file` 两者没区别 —— 迟到的内容丢掉就行。
   *   对 `write_file` / `delete_file` 差别是**致命的**：报「超时失败」而文件
   *   其实写成功了，等于让 loop 基于一件没发生的事继续往下走。所以那类工具
   *   **不声明**它，`callTool` 也就不会去 race 一个会留下副作用的调用。
   *
   * 一句话：超时是**观测**上的放弃，不是**执行**上的取消。
   */
  timeoutMs?: number
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
 * 一次工具调用返回的**输出**上限（字符）。
 *
 * ★ 做成**默认就开**的契约级上限，而不是靠每个工具自觉：`read_file` 自己
 *   截到 4000，但那是它的礼貌，不是保证 —— 换一个提供者（未来的 shell、
 *   远程 FS）就没人保证了。上限住在这里，谁都绕不过去。
 *
 * 8000 是**宽于**任何现有工具的自限（`read_file` 约 4020），所以对今天的
 * 行为是零改动；它挡的是以后接一个吐回 10MB 的提供者。
 */
export const DEFAULT_MAX_OUTPUT_CHARS = 8000

/** 一次工具调用的可调上限 */
export interface ToolLimits {
  /** 输出超过它就**截断并标注**（不静默截）。默认 `DEFAULT_MAX_OUTPUT_CHARS` */
  maxOutputChars?: number
}

/**
 * 执行一次工具调用。
 *
 * 判定节点已经决定「放行 / 需要授权」了，这里只负责执行 ——
 * 但**执行结果永远要回传**，因为判定「成功了吗」需要看到它。
 *
 * ★ 三道资源限制都在这里，因为它们属于**契约**而不是某个实现：换一个
 *   工具后端（沙箱、远程 FS、测试桩）时，这三条必须还在（同 `isToolName`）。
 *
 *   ① **输入上限**（工具自己声明的 `maxInputChars`）—— 在 `run()` **之前**查，
 *      所以超限不会产生任何副作用；
 *   ② **超时**（工具自己声明的 `timeoutMs`）—— 只对声明了它的工具生效，
 *      因为 JS 取消不掉已经在跑的调用，对会留下副作用的工具报超时是撒谎；
 *   ③ **输出上限** —— 截断**并标注**被截了多少，不静默缩水。
 */
export async function callTool<T extends ToolRegistry>(
  tools: T,
  name: ToolNameOf<T>,
  input: string,
  cwd: string,
  limits: ToolLimits = {},
): Promise<string> {
  const tool = tools[name]

  // ① 输入上限 —— **在产生副作用之前**
  const maxIn = tool.maxInputChars
  if (maxIn !== undefined && input.length > maxIn) {
    return `错误：输入 ${input.length} 字符超过 ${tool.name} 的上限 ${maxIn} —— 这一调**没有执行**`
  }

  const maxOut = limits.maxOutputChars ?? DEFAULT_MAX_OUTPUT_CHARS
  const finish = (text: string): string =>
    text.length > maxOut
      ? text.slice(0, maxOut) + `…[+${text.length - maxOut} chars 被工具层截断]`
      : text

  try {
    // ② 超时 —— 只对**声明了**的工具 race，见 `Tool.timeoutMs` 的说明
    const raw =
      tool.timeoutMs === undefined
        ? await tool.run(input, cwd)
        : await Promise.race([
            tool.run(input, cwd),
            new Promise<string>((resolve) =>
              setTimeout(
                () => resolve(`错误：${tool.name} 超过 ${tool.timeoutMs}ms 没有返回 —— 已放弃等待（它可能仍在后台进行）`),
                tool.timeoutMs,
              ),
            ),
          ])
    // ③ 输出上限
    return finish(raw)
  } catch (err) {
    return finish(`错误：${(err as Error).message}`)
  }
}
