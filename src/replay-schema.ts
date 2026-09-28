/**
 * JevLoop · **决策记录与重放**（TODO §12 最后一项）
 *
 * ══════════════════════════════════════════════════════════════
 *  这一层回答的问题是：**这条记录，换个地方还讲得通吗？**
 * ══════════════════════════════════════════════════════════════
 *
 * `decision` 事件本来就有 `state` / `frame` / `requestDigest` / `questions` /
 * `answers`，而且逐行落进会话日志。所以材料是现成的 —— 缺的是**格式**（哪些
 * 字段是重放必需的）和**验证器**（怎么判它自洽）。
 *
 * ── 重放分三层，这一层只做第一层 ──────────────────────────────
 *
 *   ① **记录完整性**（这里做）：记录里的指纹和记录里的 state / questions 是否
 *      自洽。能抓出手改过的日志、算错的指纹、字段错配。
 *   ② **请求同一性**（这里做）：`requestDigest` 能不能从 `sentFrameDigest` +
 *      `questions` 重算出来 —— 这是「两次跑的是不是同一个请求」的判据（§8.17）。
 *   ③ **从原始状态重导**（**这里不做，也做不到**）：帧是不是从原始 ctx 按契约
 *      正确编出来的。原始 ctx **按设计不落盘**，落盘的只有**有界帧**。
 *      没有它就没有可比对的东西 —— 这不是没做完，是记录的边界。
 *
 * ★ 还有一件这一层**永远**答不了的：**判定对不对**。那要外部 oracle（测试结果、
 *   文件状态、exit code），不是重放能给的。把「可重放」读成「可复现」「可判对错」
 *   是这一层最大的误读风险，所以 `verifyRecord` 的返回里带了 `notes`，
 *   逐条说清**验证不了什么**。
 *
 * ── 为什么合并那一档必须单独说 ────────────────────────────────
 *
 * `askMany([needsTool, pickTool])` 把两个节点合到一次前向里（每步都发生）：
 *
 *     state          = **合并后**的帧（两个节点的事件里一模一样）
 *     frame.digest   = **该节点自己**那份帧的指纹
 *     sentFrameDigest= 合并帧的指纹 —— 不等于任何一个节点的 frame.digest
 *
 * ⇒ 合并判定里，`frameDigest(node, state) === frame.digest` **不成立**，而且不是
 *   因为出了错。诚实的做法是**说清哪项检查适用**（`batchIds.length > 1`），
 *   而不是偷偷跳过或者报一条假失败。
 *
 * @module JevLoop/replay-schema
 */

/**
 * 记录格式的版本。
 *
 * ★ 有它才有「这条记录我读不读得懂」这个判断 —— 和 `DECISION.md` 的
 *   `schema:` 是同一个理由（见 `schemaProblems`）：没有版本，一份旧记录会被
 *   按新语义读，而且一个错都不报。
 */
export const REPLAY_SCHEMA = 'decision-record/v1'

/**
 * 一条**可移植**的判定记录 —— 重放需要的那些字段，以及各自为什么需要。
 *
 * 它是 `decision` 事件的一个**子集**：事件还带姿势性的东西（耗时、provider、
 * margin、warnings），那些对重放不是必需的，但保留下来能解释「为什么两次不同」。
 *
 * ★ 名字是 `ReplayRecord` 而**不是** `DecisionRecord`：后者已经被记账本
 *   （`vocab-records.ts`）用掉了 —— 那是「这次判定花了多少、谁答的」的**账目**，
 *   和「这条记录还讲不讲得通」的**重放**是两件事。同名会让两边的消费方互相认错。
 *   格式自己的名字仍然是 `decision-record/v1`（那是格式，不是类型）。
 */
export interface ReplayRecord {
  /** 格式版本。读到不认识的版本要**拒绝**，不是猜着读 */
  schema: string
  /** 哪一步 */
  step: number
  /** 判定节点 id（`loop.pickTool` 这种）。进帧指纹，所以必需 */
  node: string
  /** 实际送出去的那份帧 */
  state: Record<string, unknown>
  /** 该节点**自己**那份帧的指纹。仅当 `batchIds.length === 1` 时可从 `state` 重算 */
  frameDigest?: string
  /** 实际送出去的那份帧的指纹。合并时它不等于 `frameDigest` */
  sentFrameDigest?: string
  /** 参与这次前向的节点 id。> 1 = 合并判定 */
  batchIds: string[]
  /** **请求**的指纹：`sentFrameDigest` + `sentQuestions` */
  requestDigest?: string
  /** 这个节点**自己被问了什么**（含选项 —— `choice` 的候选集是请求的一部分，§8.17） */
  questions: Record<string, unknown>
  /**
   * 这次前向**实际发出去的**问题集。合并判定里它是合并后的那一份。
   *
   * ★ 请求指纹算的是**它**，不是 `questions` —— 合并时两者不同，用错了每一条
   *   合并记录都会报假 mismatch（第一版实测就是如此）。
   */
  sentQuestions: Record<string, unknown>
  /** 后端给的答案。重放**不核对**它，但留着才能解释「为什么两次不同」 */
  answers: Record<string, unknown>
  /** 策略算出的动作 */
  action?: string
  reason?: string
  /** 谁答的。两次跑出不同答案时，第一件要看的就是它 */
  provider?: string
  model?: string
}

/** 从一条落盘的事件里取字段。**日志是可以手改的**，所以逐字段验，不硬转 */
function str(o: Record<string, unknown>, key: string): string | undefined {
  const v = o[key]
  return typeof v === 'string' ? v : undefined
}

function obj(o: Record<string, unknown>, key: string): Record<string, unknown> | undefined {
  const v = o[key]
  return v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : undefined
}

/**
 * 一条事件 → 一条记录。不是 `decision` 事件、或缺了重放必需的字段时返回 `null`。
 *
 * ★ 宽容**读**、严格**判**：这里只负责把能取到的取出来，缺什么由
 *   `verifyRecord` 说 —— 一个缺字段的旧记录应当得到「无法重放」，
 *   而不是在读取时抛异常（那会让整个日志文件读不下去）。
 */
export function recordOf(event: unknown): ReplayRecord | null {
  if (!event || typeof event !== 'object') return null
  const e = event as Record<string, unknown>
  if (e.type !== 'decision') return null
  const state = obj(e, 'state')
  const questions = obj(e, 'questions')
  if (!state || !questions) return null

  const frame = obj(e, 'frame')
  const node = str(e, 'id')
  const step = typeof e.step === 'number' ? e.step : undefined
  if (node === undefined || step === undefined) return null

  const batchIds = Array.isArray(e.batchIds)
    ? (e.batchIds as unknown[]).filter((x): x is string => typeof x === 'string')
    : []

  return {
    schema: REPLAY_SCHEMA,
    step,
    node,
    state,
    ...(frame && typeof frame.digest === 'string' ? { frameDigest: frame.digest } : {}),
    ...(str(e, 'sentFrameDigest') ? { sentFrameDigest: str(e, 'sentFrameDigest')! } : {}),
    batchIds,
    ...(str(e, 'requestDigest') ? { requestDigest: str(e, 'requestDigest')! } : {}),
    questions,
    // 旧记录没有 sentQuestions：退回 `questions`。合并那一档会因为缺
    // `sentFrameDigest` 而整体 skip，所以这个退回**不会**制造假 mismatch
    sentQuestions: obj(e, 'sentQuestions') ?? questions,
    answers: obj(e, 'answers') ?? {},
    ...(str(e, 'action') ? { action: str(e, 'action')! } : {}),
    ...(str(e, 'reason') ? { reason: str(e, 'reason')! } : {}),
    ...(str(e, 'provider') ? { provider: str(e, 'provider')! } : {}),
    ...(str(e, 'model') ? { model: str(e, 'model')! } : {}),
  }
}

/**
 * 这一层**验证不了什么**。格式级的事实，所以导出给命令行直接用 ——
 * 也正因为它是输出的一部分，「可重放」才不会被读成「可复现」。
 */

export const REPLAY_NOTES: readonly string[] = [
  '不验证帧是从**原始 ctx** 正确编出来的：原始 ctx 按设计不落盘，落盘的只有有界帧。' +
    '要查那件事，需要原始 ctx + 当时的契约版本 —— 这不是没做完，是记录的边界。',
  '不验证判定**对不对**：那要外部 oracle（测试结果、文件状态、exit code），重放给不了。',
  '不核对 `answers`：同一条记录重问一次可以合法地给出不同答案（门限边上的判定尤其是）。' +
    '要查那件事是**模型级复现**，是另一个问题。',
]

/**
 * 验证一条记录是否自洽。
 *
 * 三项检查，各自独立：
 *
 *     frame-solo      单节点时，`state` 能否重算出 `frameDigest`
 *     sent-frame      单节点时 `sentFrameDigest` 应当等于 `frameDigest`；合并时只记账
 *     request         `requestDigest(sentFrameDigest, questions)` 能否重算出记录里的请求指纹
 */
