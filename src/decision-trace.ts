/**
 * JevLoop · 判定记录的**人可读形态**（Decision Trace）
 *
 * ══════════════════════════════════════════════════════════════
 *  **一个决策一个 `.md` 文件 —— 而且那份 `.md` 本身是可复核的。**
 * ══════════════════════════════════════════════════════════════
 *
 * 起因：展示形式想做成 `decisions/2026-09-29-001.md` 这样一个决策一份文件。
 * 记录本身早就有（`decision-record/v1`，一个会话一份 append-only 日志），
 * 缺的只是一个**渲染视图**。
 *
 * ── ★ 这个文件里唯一要紧的设计决定 ─────────────────────────────
 *
 * **人读的那一份，必须就是可复核的那一份。**
 *
 * 最省事的做法是把指纹印在表格里就算「内嵌了」。那不够：指纹**打印出来**和
 * 指纹**能被重算**是两件事。前者只是装饰，后者才叫可审计 —— 而定位文档的结论是，
 * 契约真正多出来的只有「跨宿主一致性」与「第三方可审计性」两样（且要等第二个
 * 消费者）。把一个不可重算的 `.md` 当成人看的最终件，等于悄悄丢掉其中之一。
 *
 * 所以这里把**当时那条 decision 事件原样**嵌进 `.md` 的一个机器可读块里
 * （`parseTrace` 能原样取回来），指纹由它**重算**，不是由上面的表格猜。
 * 表格为了好读**会截断**，这一点在文件里明说 —— 权威的是那个块。
 *
 * ── 另一件刻意放进来的事：合并判定 ──────────────────────────────
 *
 * 一条记录可能装着**几个节点合并后**发出去的帧，所以有 `batchIds` 与
 * `sentFrameDigest`。改成「一个决策一份文件」时，这个关系是唯一真正会丢的信息
 * —— 单看一条 `.md` 会以为它就是一个节点的判定。所以 `batchIds.length > 1` 时
 * 文件里显式写出合并了谁，并说明 `sentFrameDigest ≠ frameDigest` 是**正常的**。
 *
 * ── 范围：只有 `decisions/`，而且只有它 ──────────────────────────
 *
 * 展示的目录树里，`memory/facts`、`memory/beliefs`、`memory/experiences`、
 * `skills/` **不是这一层负责的**，也不该由这个模块生成 —— 它们是另一套东西
 * （认知怎么更新、撤销、互相矛盾怎么办），体量和协议都另算。
 *
 * 把它们一并渲染出来的诱惑很大，因为一棵长得满的树看起来更像一个成品。但那等于
 * 宣称我们有那套记忆架构，而**这个项目一路在拒绝的正是这种安静的过度主张**：
 * 契约只管判定这一层（`DECISION.md` 自己就写着它不是 agent 设计规范），
 * 所以这里也只产出判定这一层的产物。
 *
 * ── 为什么不能再拆（§12：超过 300 行必须说清）────────────────────
 *
 * 最自然的一刀是「产出」与「复核」分开：`renderTrace` 一个文件，
 * `parseTrace` / `checkTrace` 另一个。**不拆是刻意的。**
 *
 * 复核里最要紧的一项是「正文与机器可读块一致不一致」，而它的做法是**重算正文**
 * 再逐字比对 —— 也就是说，「文件该长什么样」必须由**同一个**函数回答。一拆就
 * 变成消费者手里攥着一份可能过期的渲染函数：改了排版而忘了同步那边，结果是
 * 「所有文件都报被手改过」（吵，但至少不静默），或者更糟 —— 校验被写成对着旧
 * 版式比对，于是**真被改过的文件反而通过**。
 *
 * 这个文件总共只管道一件事：**这一种 `.md` 格式**。生产者与消费者是同一个格式
 * 的两面，分开住才是错的。
 *
 * @module JevLoop/decision-trace
 */

import { recordOf, type ReplayRecord } from './replay-schema.ts'
import { verifyRecord, type ReplayVerdict } from './replay-verify.ts'

/** 机器可读块的标记。用 HTML 注释 —— 人看不见，解析器找得到 */
export const TRACE_MARKER = '<!-- jevloop:decision-record -->'

/** 表格里一格最多印多少字符。★ 截断只发生在**给人看**的那张表里 */
const CELL_CHARS = 400

/**
 * `at`（epoch 毫秒）→ `YYYY-MM-DD`。
 *
 * ★ 用 **UTC**，不用本地时区：文件名的排序要能被别人复现，而本地日期会让
 *   同一份日志在两台机器上落到不同的天里。
 */
export function traceDate(atMs: number): string {
  return new Date(atMs).toISOString().slice(0, 10)
}

/** 一天里的第几份 —— `NNN` 三位，从 1 开始。`ordinal` 是 1 基 */
export function traceFileName(atMs: number, ordinal: number): string {
  return `${traceDate(atMs)}-${String(ordinal).padStart(3, '0')}.md`
}

function clip(v: string): string {
  return v.length <= CELL_CHARS ? v : `${v.slice(0, CELL_CHARS)}…[+${v.length - CELL_CHARS}]`
}

/** 一格的值 → 一行文本。字符串原样（可读），其余用 JSON 让它**无歧义** */
function cellText(v: unknown): string {
  if (typeof v === 'string') return v
  try {
    return JSON.stringify(v) ?? String(v)
  } catch {
    return String(v)
  }
}

/** 反引号会破坏表格里的行内代码，换掉；换行会破坏表格结构，压平 */
function tableSafe(s: string): string {
  return s.replace(/`/g, `'`).replace(/\r?\n/g, ' ⏎ ')
}

function table(rows: [string, string][], headers: [string, string] = ['项', '值']): string {
  const out = [`| ${headers[0]} | ${headers[1]} |`, '|---|---|']
  for (const [k, v] of rows) out.push(`| ${tableSafe(k)} | ${tableSafe(clip(v))} |`)
  return out.join('\n')
}

/**
 * 一条记录 → 一份 `.md`。
 *
 * @param rec 重放记录（`recordOf` 的产物）
 * @param event 当时那条 decision 事件**原样** —— 它才是被嵌进去、被重算的那一份
 * @param verdict `verifyRecord(rec)` 的结论
 * @param atMs 这条记录落盘的时间（取文件名里的日期）
 * @param ordinal 这一天的第几条（1 基）
 */
export function renderTrace(
  rec: ReplayRecord,
  event: unknown,
  verdict: ReplayVerdict,
  atMs: number,
  ordinal: number,
): string {
  const merged = rec.batchIds.length > 1
  const L: string[] = []

  L.push(`# ${rec.node} · ${traceFileName(atMs, ordinal).replace(/\.md$/, '')}`)
  L.push('')
  L.push(`**结论：${verdict.status}** —— ${verdict.checks.length} 项检查：` +
    verdict.checks.map((c) => `${c.what}=${c.outcome}`).join(' · '))
  L.push('')
  L.push(
    table([
      ['节点', rec.node],
      ['动作', rec.action ?? '(记录里没有)'],
      ['理由', rec.reason ?? '(记录里没有)'],
      ['步', `step ${rec.step}`],
      ['后端', rec.provider ?? '(未记)'],
      ['批次', merged ? `合并判定：${rec.batchIds.join(' + ')}` : `${rec.batchIds[0] ?? rec.node}（单节点）`],
      ['格式', rec.schema],
    ]),
  )
  L.push('')

  L.push('## 当时**真正发出去**的那份帧')
  L.push('')
  L.push(
    table(
      Object.entries(rec.state).map(([k, v]) => [k, cellText(v)] as [string, string]),
      ['帧里的栏', '当时发出去的值'],
    ),
  )
  L.push('')
  L.push(
    '> ★ 这张表为了好读**会截断**（每格上限 ' +
      `${CELL_CHARS} 字符）。**权威的是文件末尾那个机器可读块**，指纹是从它重算的。`,
  )
  L.push('')

  L.push('## 问了什么 / 答了什么')
  L.push('')
  const qs = Object.entries(rec.questions)
  if (qs.length === 0) L.push('（没有记下问题）')
  else {
    L.push('| 问题 | 记录里的问法 | 后端给的答案 |')
    L.push('|---|---|---|')
    for (const [id, q] of qs) {
      const type = (q && typeof q === 'object' && 'type' in q ? String((q as { type: unknown }).type) : '?')
      const a = rec.answers[id]
      L.push(`| ${tableSafe(id)} | ${tableSafe(type)} | ${tableSafe(clip(a === undefined ? '(无答案)' : cellText(a)))} |`)
    }
  }
  L.push('')

  L.push('## 指纹')
  L.push('')
  L.push(`- \`frameDigest\` \`${rec.frameDigest ?? '(缺)'}\` —— 该节点**自己**那份帧`)
  L.push(`- \`sentFrameDigest\` \`${rec.sentFrameDigest ?? '(缺)'}\` —— **实际发出去**那份帧`)
  L.push(`- \`requestDigest\` \`${rec.requestDigest ?? '(缺)'}\` —— 发出去的帧 + 发出去的问题集`)
  L.push(`- \`batchIds\` \`${rec.batchIds.join(' + ')}\``)
  if (merged) {
    L.push('')
    L.push(
      `> ★ 这是一次**合并判定**：${rec.batchIds.join(' + ')} 的帧被合成一份发出去，` +
        '所以 `sentFrameDigest` 与 `frameDigest` **不同是正常的**。',
    )
  }
  L.push('')

  L.push('## 可复核的机器可读记录')
  L.push('')
  L.push('> 标记之后的这一段是**权威**的那一份；上面的表格只是它的渲染。')
  L.push('> 正文与它**必须一致** —— 手改上面任何一格，复核都会报出来。')
  L.push('')
  L.push('从**这个文件本身**重算指纹：`npm run trace -- --verify <目录>`')
  L.push('')
  return `${L.join('\n')}\n${TRACE_MARKER}\n\n\`\`\`json\n${JSON.stringify(event, null, 2)}\n\`\`\`\n`
}

/**
 * 一份 `.md` 的**正文** —— 标记之前的每一个字节。
 *
 * ★ 拆出这一层是为了让**正文本身可以被核对**。只把记录嵌进去是不够的：
 *   表格是给人看的、**能改**；如果复核只查那个块，那么一份把 `rm -rf /`
 *   渲染成「只读查询」的 `.md` 照样报 `verified` —— 人看的那一份与可审计的
 *   那一份就又分家了，而这个模块存在的全部理由就是不让它们分家。
 *
 *   （这不是假想：第一版的端到端验证就是这么漏的 —— 改掉表格里的命令之后，
 *     `--verify` 依然报 `verified`，因为改的不是那个块。单元测试当时没抓住，
 *     因为它改的是块。所以这里补的是**正文一致性**检查。）
 *
 *   渲染是**纯函数**，所以「正文该长什么样」可以重算：手改任何一格，重算出来
 *   的正文就与文件里的不一样。`checkTrace` 用的就是这一点。
 */
export function humanPartOf(md: string): string | null {
  const at = md.indexOf(TRACE_MARKER)
  return at === -1 ? null : md.slice(0, at)
}

/**
 * 从一份 `.md` 里把那条 decision 事件取回来。
 *
 * 认不出就返回 `null` —— 与记录层同一条纪律：**宽容读、严格判**。
 * 一个手工改坏的 `.md` 应当得到「取不回来」，而不是抛异常把整个目录读不下去。
 */
export function parseTrace(md: string): unknown | null {
  const at = md.indexOf(TRACE_MARKER)
  if (at === -1) return null
  const fence = md.indexOf('```json', at)
  if (fence === -1) return null
  const start = md.indexOf('\n', fence)
  if (start === -1) return null
  const end = md.indexOf('```', start)
  if (end === -1) return null
  try {
    return JSON.parse(md.slice(start, end))
  } catch {
    return null
  }
}

/**
 * 嵌进去的那一段 → 重放记录。
 *
 * ★ 两种形状都收：盘上是 `{kind:'event', run, at, e}` 的**包装行**（会话日志与
 *   `JEVLOOP_RECORDS` 都是这个形状），而裸的 decision **事件**也认。理由和
 *   `recordOf` 认两种指纹位置是同一条：把「格式对不上」误报成「不可验证」是最贵的错。
 */
export function recordFromTrace(embedded: unknown): ReplayRecord | null {
  if (!embedded || typeof embedded !== 'object') return null
  const o = embedded as Record<string, unknown>
  if (o.kind === 'event' && o.e !== undefined) return recordOf(o.e)
  return recordOf(embedded)
}

/** 嵌进去的那一段里记的落盘时间（毫秒）。没有就是 `undefined`，不编一个 */
export function traceAtOf(embedded: unknown): number | undefined {
  if (!embedded || typeof embedded !== 'object') return undefined
  const at = (embedded as { at?: unknown }).at
  return typeof at === 'number' ? at : undefined
}

/**
 * 文件名的日期与嵌入记录的时间**是否一致**。
 *
 * ★ 这是「人看的那一份就是权威那一份」的一个具体好处：文件名不再是装饰，
 *   它是**可以被核对**的。不一致就说明文件被挪过、改过名，或者手动拼过。
 */
export function traceNameMatches(fileName: string, atMs: number | undefined): boolean {
  if (atMs === undefined) return false
  return fileName.startsWith(traceDate(atMs))
}

/** 从文件名里取当天的序号（`2026-09-29-012.md` → `12`）。取不到就是 `undefined` */
export function ordinalOf(fileName: string): number | undefined {
  const m = /-(\d{3})\.md$/.exec(fileName)
  return m ? Number(m[1]) : undefined
}

/** 复核一份 `.md` 的结果 */
export interface TraceCheck {
  /** 文件自洽且正文与记录一致 */
  ok: boolean
  record: ReplayRecord | null
  verdict: ReplayVerdict | null
  /** 出了问题的地方。空数组 = 没问题 */
  problems: string[]
}

/**
 * **只读一份 `.md`**，把它能自证的东西全查一遍。
 *
 * 四件事，缺一不可：
 *
 *   ① 机器可读块取不取得到
 *   ② 它是不是一条可解析的判定记录
 *   ③ 记录**自己**自不自洽（`verifyRecord`：四档结论）
 *   ④ ★ **正文与块一致不一致** —— 即「人看的那一份」有没有被手改过
 *
 * ★ ④ 是这一版补上的，而且是端到端跑出来的教训：第一版只查①②③，于是把表格里的
 *   命令从 `ls -la` 改成 `rm -rf /` 之后，`--verify` 依然报 `verified` —— 因为改的
 *   不是那个块。**一份能被人读出错误结论却报 verified 的文件，不算可审计。**
 *
 * @param fileName 文件名本身参与核对（日期与序号都要与内容对得上）
 */
export function checkTrace(md: string, fileName: string): TraceCheck {
  const problems: string[] = []
  const embedded = parseTrace(md)
  if (embedded === null) {
    return { ok: false, record: null, verdict: null, problems: ['取不回机器可读块（缺标记或 JSON 坏了）'] }
  }
  const record = recordFromTrace(embedded)
  if (!record) {
    return { ok: false, record: null, verdict: null, problems: ['机器可读块里的东西不是一条判定记录'] }
  }
  const verdict = verifyRecord(record)
  if (verdict.status === 'mismatch') problems.push('记录不自洽 —— 指纹与内容对不上')

  const at = traceAtOf(embedded)
  const ordinal = ordinalOf(fileName)
  if (at === undefined) problems.push('记录里没有时间戳 ⇒ 无法核对文件名里的日期')
  else if (!traceNameMatches(fileName, at)) problems.push('文件名里的日期与记录的时间不一致')
  if (ordinal === undefined) problems.push('文件名不是 YYYY-MM-DD-NNN.md 的形状')

  // ④ 正文一致性：正文是纯函数的产物，所以「该长什么样」可以重算
  if (at !== undefined && ordinal !== undefined) {
    const expected = humanPartOf(renderTrace(record, embedded, verdict, at, ordinal))
    const actual = humanPartOf(md)
    if (expected !== null && actual !== null && expected !== actual) {
      problems.push('★ 正文与机器可读块不一致 —— 这份文件被手改过，正文不能信')
    }
  }

  return { ok: problems.length === 0, record, verdict, problems }
}
