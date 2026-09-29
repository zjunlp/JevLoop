/**
 * JevLoop · Codex **transcript 读取** —— 把 codex 的 rollout JSONL 变成契约要的 state
 *
 * ══════════════════════════════════════════════════════════════
 *  ⚠️ 这是一个**内部格式**，而这里诚实的做法与别处相反
 * ══════════════════════════════════════════════════════════════
 *
 * codex 自己的 `RolloutLine` 文档写着：
 *
 *     This intentionally does not implement Deserialize: JSONL readers must use
 *     codex_rollout's canonical parser
 *
 * 也就是说：**官方的解析器在 codex 内部（Rust）**，外部按字节去读是读一个没有
 * 兼容承诺的内部格式。所以这个文件的写法是**防御式**的：
 *
 *     · 认不出的行类型 → **跳过**，不抛（格式会加东西，那是正常的）
 *     · 行坏掉         → 跳过并**计数**（追加式格式允许撕裂尾行）
 *     · 读不到要的字段 → `undefined`，让上层**拒绝**（不是补空串）
 *
 * 这样格式变了之后的行为是「判定被拒、并说明为什么」，而不是「判定拿到一份
 * 悄悄少了几栏的帧」。前者吵，后者安静 —— 而安静的那个才危险。
 *
 * ── 为什么要分头/尾两段读 ────────────────────────────────────
 *
 * transcript 的长度**没有上界**（它是一次会话的全部经过）。而这里只要两样东西：
 *
 *     第一次用户消息   → 在**头部**
 *     最近几次工具调用 → 在**尾部**
 *
 * 所以文件很大时只读这两段窗口，而不是整个读进内存。这是适配器替宿主承担的
 * 「读取并裁剪」义务（见 `docs/ADAPTER-CODEX-SCOPE.md`）里最硬的一条。
 *
 * @module JevLoop/adapters/codex/transcript
 */

import { openSync, closeSync, fstatSync, readSync } from 'node:fs'

/**
 * 头部读多少字节去找「第一次用户消息」。
 *
 * 64KB：一条用户消息 + session_meta 远不到这个量级，而留够余量是为了容忍
 * 前面出现大段的 reasoning/工具输出。
 */
const HEAD_BYTES = 64 * 1024

/**
 * 尾部读多少字节去找「最近做过什么」。
 *
 * 256KB：够放下最近若干次工具调用与它们的输出（输出本身在 codex 那边也有上限），
 * 所以最近几步一定在这个窗口里。
 */
const TAIL_BYTES = 256 * 1024

/** 历史里最多保留几步。**帧那边还会按声明的界再截一次** —— 这里是聚合上界 */
const MAX_STEPS_KEPT = 5

/** 一步里「输入」和「结果」各自的上界。同样是聚合上界，不是帧的界 */
const STEP_INPUT_CHARS = 120
const STEP_RESULT_CHARS = 300

/** 整体历史文本的上界，防止把几十步拼成一个巨大的串 */
const MAX_HISTORY_CHARS = 4000

export interface TranscriptFacts {
  /** 第一次用户消息。**读不到就是 `undefined` ⇒ 上层拒绝**，不是空串 */
  task: string | undefined
  /** `工具(输入) → 结果` 的最近几步，已按聚合上界裁剪。读不到就是 `undefined` */
  historyText: string | undefined
  /** 最近一次工具输出 */
  lastResult: string | undefined
  /** 这次会话见过的文件（**近似**：从工具参数里认出来的，见 `filesAreApproximate`） */
  files: string[]
  /** 读过哪些文件 —— `is_done` 的 `already_read` 那一栏靠它 */
  readFiles: string[]
  /** transcript 里报的会话信息 */
  sessionId?: string
  cwd?: string
  model?: string
  /** 读的时候发生了什么（截断、跳过、认不出）。**要给运维看，也要进记录** */
  notes: string[]
  /** 是否只读了两段窗口（文件很大） */
  windowedRead: boolean
  /** 跳过了几行（坏行或认不出的形状） */
  skippedLines: number
  /** `files` 是**近似**的 —— 见下面 `collectFiles` 的说明 */
  filesAreApproximate: true
}

/** 一条工具调用。`call_id` 用来和它的输出配对 */
interface Call {
  name: string
  input: string
  result?: string
  /** 这次调用参数里出现的路径（认不出就是空数组） */
  paths: string[]
  /** 是不是读类工具 —— `readFiles` 只从这些调用里取 */
  isRead: boolean
}

function clip(v: string, max: number): string {
  return v.length <= max ? v : `${v.slice(0, max)}…[+${v.length - max}]`
}

/** 从窗口里切出**完整的**行：窗口边界会切在行中间，那半行要丢掉 */
function linesOf(text: string, dropFirst: boolean): string[] {
  const lines = text.split('\n')
  if (dropFirst) lines.shift() // 尾部窗口的第一行多半是半行
  return lines.filter((l) => l.trim() !== '')
}

/** 读文件的某一段。`from` 为负 = 从末尾算 */
function readWindow(fd: number, size: number, head: boolean): string {
  const length = Math.min(head ? HEAD_BYTES : TAIL_BYTES, size)
  const position = head ? 0 : Math.max(0, size - length)
  const buf = Buffer.allocUnsafe(length)
  const read = readSync(fd, buf, 0, length, position)
  return buf.subarray(0, read).toString('utf8')
}

/** 一个 `response_item` 的 payload 是不是某种形状。**认不出就返回 false，不抛** */
function isShape(payload: unknown, type: string): payload is Record<string, unknown> {
  return (
    typeof payload === 'object' &&
    payload !== null &&
    (payload as { type?: unknown }).type === type
  )
}

/** 消息里的文本：`content` 是 `[{type:'input_text'|'output_text', text}]` */
function textOfContent(content: unknown): string {
  if (!Array.isArray(content)) return ''
  return content
    .map((c) => (c && typeof c === 'object' ? ((c as { text?: unknown }).text as string | undefined) : undefined))
    .filter((t): t is string => typeof t === 'string')
    .join('\n')
}

/**
 * 工具输出 → 文本。
 *
 * `output.body` 是 **untagged** 的：要么是字符串，要么是内容项数组
 * （`FunctionCallOutputBody`）。所以这里两种都收，未知形状返回 `''`。
 */
function outputText(payload: Record<string, unknown>): string {
  const output = payload.output
  if (typeof output === 'string') return output
  if (output && typeof output === 'object') {
    const body = (output as { body?: unknown }).body
    if (typeof body === 'string') return body
    if (Array.isArray(body)) return textOfContent(body)
  }
  return ''
}

/** 工具参数是**一个 JSON 字符串**（codex 的原话：returns the arguments as a string that contains JSON） */
function inputText(payload: Record<string, unknown>): string {
  const args = payload.arguments
  if (typeof args !== 'string') return ''
  try {
    const parsed = JSON.parse(args) as Record<string, unknown>
    // 路径类的参数优先显示 —— 它才是「这一调的目标」
    for (const k of ['path', 'file_path', 'file', 'filename', 'cmd', 'command']) {
      const v = parsed[k]
      if (typeof v === 'string') return v
    }
    return args
  } catch {
    // 参数不是 JSON（codex 也说它是个字符串）—— 原样用，别丢
    return args
  }
}

/** 哪些工具名算「读了一个文件」。**宿主自己的表** —— 契约不管这个 */
const READ_TOOLS = new Set(['read_file', 'read', 'cat', 'open_file', 'view_file'])

/** 从一次调用里认出它碰过的文件。**近似**，所以返回空数组而不是猜 */
function pathOf(payload: Record<string, unknown>): string[] {
  const args = payload.arguments
  if (typeof args !== 'string') return []
  try {
    const parsed = JSON.parse(args) as Record<string, unknown>
    const out: string[] = []
    for (const k of ['path', 'file_path', 'file', 'filename']) {
      const v = parsed[k]
      if (typeof v === 'string' && v.trim()) out.push(v.trim())
    }
    return out
  } catch {
    return []
  }
}

/**
 * 把一段 transcript 窗口解析成「调用 + 输出」的有序列表。
 *
 * ★ 配对靠 `call_id`：模型给的 `function_call` 和它后面的 `function_call_output`
 *   是两条独立的行。不配对的话「哪一步做了什么」就串不起来，而 `step_ok` 那种
 *   判定正是靠这个。
 */
function callsIn(lines: string[], skipped: { n: number }): Call[] {
  const calls: Call[] = []
  const byId = new Map<string, Call>()

  for (const line of lines) {
    let row: Record<string, unknown>
    try {
      row = JSON.parse(line) as Record<string, unknown>
    } catch {
      skipped.n++ // 坏行（撕裂的尾行、或别的什么东西）—— 跳过并计数
      continue
    }
    if (row.type !== 'response_item') continue
    const payload = row.payload
    if (!payload || typeof payload !== 'object') {
      skipped.n++
      continue
    }
    const p = payload as Record<string, unknown>

    if (isShape(p, 'function_call')) {
      const name = typeof p.name === 'string' ? p.name : '(unknown tool)'
      const call: Call = {
        name,
        input: clip(inputText(p), STEP_INPUT_CHARS),
        paths: pathOf(p),
        isRead: READ_TOOLS.has(name),
      }
      calls.push(call)
      const id = p.call_id ?? p.id
      if (typeof id === 'string') byId.set(id, call)
      continue
    }

    if (isShape(p, 'function_call_output')) {
      /*
        ★ `p` 在这里被 TS 收窄成 `never`：`isShape` 是 `payload is Record<string, unknown>`
          而两次判别式调用叠在一起之后类型分析算不出更细的东西。运行期完全正常
          （测试全绿），但这是那种「类型说不行、值是对的」的情形 —— 与其加一个
          `as` 掩盖，不如就地取一个明确的局部变量，读的人也看得懂。
      */
      const out = p as Record<string, unknown>
      const id = out.call_id
      const text = clip(outputText(out), STEP_RESULT_CHARS)
      const found = typeof id === 'string' ? byId.get(id) : undefined
      if (found) found.result = text
      // 配对不上就**不硬塞进历史**（塞了会读成「某一步的结果」）
      else calls.push({ name: '(unpaired output)', input: '', result: text, paths: [], isRead: false })
      continue
    }
    // 其余 ResponseItem（message / reasoning / …）在这里不关心，不算「跳过」
  }
  return calls
}

/** 第一次用户消息 —— 只在头部窗口里找 */
function taskOf(lines: string[]): string | undefined {
  for (const line of lines) {
    let row: Record<string, unknown>
    try {
      row = JSON.parse(line) as Record<string, unknown>
    } catch {
      continue
    }
    if (row.type !== 'response_item') continue
    const p = row.payload
    if (!p || typeof p !== 'object') continue
    const item = p as Record<string, unknown>
    if (!isShape(item, 'message')) continue
    if (item.role !== 'user') continue
    const text = textOfContent(item.content).trim()
    if (text) return text
  }
  return undefined
}

/** `session_meta` 里有什么就取什么（认不出就跳过，不猜） */
function metaOf(lines: string[], facts: TranscriptFacts): void {
  for (const line of lines) {
    let row: Record<string, unknown>
    try {
      row = JSON.parse(line) as Record<string, unknown>
    } catch {
      continue
    }
    if (row.type !== 'session_meta') continue
    const p = (row.payload ?? {}) as Record<string, unknown>
    if (typeof p.id === 'string') facts.sessionId = p.id
    if (typeof p.cwd === 'string') facts.cwd = p.cwd
    if (typeof p.model === 'string') facts.model = p.model
    return
  }
}

/**
 * 读一份 transcript。
 *
 * @param path `hook` 事件里的 `transcript_path`
 * @returns 契约要的 state 片段 + **读的时候发生了什么**
 */
export function readTranscript(path: string): TranscriptFacts {
  const facts: TranscriptFacts = {
    task: undefined,
    historyText: undefined,
    lastResult: undefined,
    files: [],
    readFiles: [],
    notes: [],
    windowedRead: false,
    skippedLines: 0,
    filesAreApproximate: true,
  }

  let fd: number
  try {
    fd = openSync(path, 'r')
  } catch (err) {
    // 读不到就是读不到 —— 上层会因此拒绝，而不是拿一份空帧继续
    facts.notes.push(`transcript 读不到（${(err as Error).message}）`)
    return facts
  }

  try {
    const size = fstatSync(fd).size
    const skipped = { n: 0 }
    let calls: Call[]
    let headLines: string[]

    if (size <= HEAD_BYTES + TAIL_BYTES) {
      headLines = linesOf(readWindow(fd, size, true), false)
      calls = callsIn(headLines, skipped)
      metaOf(headLines, facts)
    } else {
      // ★ 文件很大：**只读头尾两段**。这不是优化，是不让「读一次会话」变成
      //   一次无界内存操作 —— 而 transcript 的长度没有上界。
      facts.windowedRead = true
      headLines = linesOf(readWindow(fd, size, true), false)
      const tailLines = linesOf(readWindow(fd, size, false), true)
      calls = callsIn(tailLines, skipped)
      metaOf(headLines, facts)
      facts.notes.push(
        `transcript ${size} 字节 —— 只读了头 ${HEAD_BYTES} 与尾 ${TAIL_BYTES} 字节（它没有上界）`,
      )
    }

    facts.task = taskOf(headLines)
    facts.skippedLines = skipped.n
    if (skipped.n > 0) facts.notes.push(`跳过了 ${skipped.n} 行（坏行或认不出的形状）`)
    if (facts.task === undefined) facts.notes.push('transcript 里找不到第一次用户消息 ⇒ task 无法确定')

    // ── 历史：只保留最近几步 ──
    const recent = calls.slice(-MAX_STEPS_KEPT)
    const built = recent
      .map((c) => `${c.name}(${c.input})${c.result === undefined ? '' : ` → ${c.result}`}`)
      .join('\n')
    if (built) facts.historyText = clip(built, MAX_HISTORY_CHARS)

    const last = [...calls].reverse().find((c) => c.result !== undefined)
    if (last?.result !== undefined) facts.lastResult = last.result

    /*
      ── files / readFiles：**近似**，所以要说清是近似的 ──

      codex 不维护「读过哪些文件」，而 transcript 里只有工具参数。所以这里只认
      **读类工具的路径参数**，认不出就不猜 —— 一个猜出来的 `readFiles` 会让
      `is_done` 的 `already_read` 那一栏说谎，而它正是「任务说的那两个文件读了没有」
      的判据（见 `DECISION.md` 的 is_done）。
    */
    const readSet = new Set<string>()
    const seenSet = new Set<string>()
    for (const c of calls) {
      for (const f of c.paths) {
        seenSet.add(f)
        if (c.isRead) readSet.add(f)
      }
    }
    facts.readFiles = [...readSet]
    facts.files = [...seenSet]
    if (readSet.size > 0) {
      facts.notes.push(
        `files/readFiles 是从**读类工具的参数**认出来的（${readSet.size} 个）—— 近似值，codex 不维护这份状态`,
      )
    }
    return facts
  } finally {
    closeSync(fd)
  }
}
