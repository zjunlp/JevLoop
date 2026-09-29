/**
 * JevLoop · Codex 适配器的**类型** —— 宿主事件、宿主状态、裁决
 *
 * 单独一个文件是为了让「codex 那边长什么样」和「契约那边长什么样」在类型上
 * 分得开：`core.ts` 的职责就是在这两者之间翻译，而翻译的输入输出值得各自有个名字。
 *
 * ★ 这里的每个字段都来自 codex 自己的协议，不是我们编的。出处见
 *   `docs/ADAPTER-CODEX-SCOPE.md`（`codex-rs/hooks/src/schema.rs`）。
 *
 * @module JevLoop/adapters/codex/types
 */

/**
 * codex 传给 hook 的事件（stdin 上的一份 JSON）。
 *
 * 只列我们用到的字段 —— 其余（`agent_id` / `agent_type` / `permission_mode` …）
 * 原样留着不读，因为读一个不理解的字段然后据此判定，比不读更危险。
 */
export interface CodexHookEvent {
  hook_event_name: string
  session_id?: string
  turn_id?: string
  /** codex 给的 transcript 路径。**history 从这里来**，所以它必须被裁剪后再进帧 */
  transcript_path?: string | null
  cwd?: string
  model?: string
  tool_name?: string
  tool_input?: unknown
  tool_use_id?: string
}

/**
 * 适配器维护的宿主状态 —— 也就是**契约层格名的取值**。
 *
 * ★ 与参考实现的 `AgentCtx` 不是同一个东西，这是有意的：那份活在参考运行时里，
 *   而这份是**这个宿主**的。名字对齐到契约的格名，是为了让「文件说什么」和
 *   「我有什么」能一一对上（对不上就是适配器错误，不是空串）。
 *
 * ★★ `files` / `readFiles` 在这里出现，是因为 **codex 不维护它们** ——
 *    参考 loop 自己记，外部宿主只能自己记。参 `docs/ADAPTER-CODEX-SCOPE.md`。
 */
export interface HostState {
  task: string
  cwd: string
  /** 上一个工具名（这次 PreToolUse 就是当前工具） */
  tool?: string
  /** 这一调的目标/参数 */
  input?: string
  /** 从 transcript 读来的、**已裁剪**的历史摘要 */
  historyText?: string
  /** 上一步的工具输出 */
  lastResult?: string
  /** 适配器自己维护的：已知文件 */
  files?: string[]
  /** 适配器自己维护的：读过哪些 */
  readFiles?: string[]
  /** 调用方是否允许写入（codex 的 permission_mode 是最近的信号） */
  canWrite?: boolean
  /** 更早的轮次摘要 */
  earlier?: string
}

/** 裁决的种类。**四种，对应 codex 实际接受的那四种** */
export type VerdictKind =
  /** 什么都不说 = 放行。★ codex 里「允许」的正确写法是沉默，不是 `allow` */
  | 'silence'
  /** `permissionDecision: allow` + `updatedInput` —— 唯一被 codex 接受的 allow 写法 */
  | 'allow_rewrite'
  /** 顶层 `decision: block` + reason（Stop / PostToolUse） */
  | 'block'
  /** `permissionDecision: deny` + 非空 reason */
  | 'deny'

export interface CodexVerdict {
  kind: VerdictKind
  reason: string
  /** `allow_rewrite` 时改写成的输入 */
  updatedInput?: unknown
  /** 这一路映射**丢了什么**。有损就要说出来，不能让它变成「契约支持了」 */
  loss?: string
  /** `auto_audit` 的「说了留痕就必须真的留」—— 由适配器自己写一条 */
  audit?: boolean
}

/** 一次判定的附带产物：记录 + 给运维看的说明 */
export interface AdapterOutcome {
  /** `decision-record/v1` 记录；跳过或失败时为 `null` */
  record: Record<string, unknown> | null
  /** 这一路发生了什么（不可信字段、有损映射、动作语义）。**给人读的** */
  notes: string[]
}
