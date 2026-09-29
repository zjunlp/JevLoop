/**
 * JevLoop · 把判定记录渲染成 `decisions/2026-09-29-001.md`
 *
 * ══════════════════════════════════════════════════════════════
 *  一个决策一份文件 —— 而且**那份文件本身可以重算指纹**
 * ══════════════════════════════════════════════════════════════
 *
 * ── 用法 ──────────────────────────────────────────────────────
 *
 *     npm run trace -- <会话日志.jsonl> [--out <目录>]
 *         渲染。默认写到 `agent/decisions/`
 *
 *     npm run trace -- --verify <目录>
 *         只看**那些 .md 文件本身**（不碰原始日志），逐份重算指纹
 *
 * ── 为什么要有 `--verify` ───────────────────────────────────────
 *
 * 指纹**印在文件里**和指纹**能被重算**是两件事。没有前者只是不好看，没有后者
 * 就只是装饰 —— 而定位文档的结论是，契约真正多出来的只有「跨宿主一致性」与
 * 「第三方可审计性」两样。人最终拿到的是 `.md`，所以**可审计的那一份必须就是它**。
 *
 * 因此 `--verify` 只读 `.md`：它从每份文件里的机器可读块取回记录、重算指纹，
 * 顺带核对**文件名的日期**与记录的时间对不对得上（名字因此不再是装饰）。
 *
 * ★ 它验证不了什么，与记录层**完全一致**：不验证帧是不是从原始 ctx 正确编出来的，
 *   也不验证判定对不对。那两句照抄自 `REPLAY_NOTES`，不另写一套说法 ——
 *   两处措辞一旦分叉，读的人就会以为口径也不同。
 *
 * @module JevLoop/trace
 */

import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parseSessionLine } from '../src/session-log.ts'
import { REPLAY_NOTES } from '../src/replay-schema.ts'
import { verifyRecord, type ReplayStatus } from '../src/replay-verify.ts'
import { checkTrace, renderTrace, traceFileName } from '../src/decision-trace.ts'
import { recordFromTrace, traceAtOf } from '../src/decision-trace.ts'

const B = (s: string) => `\x1b[1m${s}\x1b[0m`
const D = (s: string) => `\x1b[2m${s}\x1b[0m`
const G = (s: string) => `\x1b[32m${s}\x1b[0m`
const R = (s: string) => `\x1b[31m${s}\x1b[0m`
const Y = (s: string) => `\x1b[33m${s}\x1b[0m`

const STATUS_COLOR: Record<ReplayStatus, (s: string) => string> = {
  verified: G,
  partial: Y,
  unverifiable: Y,
  mismatch: R,
}

const DEFAULT_OUT = 'agent/decisions'

/** 落盘的每一行 → 一条可渲染的记录。认不出、不是判定的行**计数**，不静默丢 */
interface Traced {
  line: unknown
  record: NonNullable<ReturnType<typeof recordFromTrace>>
  at: number
}

function collect(raw: string): { traced: Traced[]; skipped: number; undated: number } {
  const traced: Traced[] = []
  let skipped = 0
  let undated = 0
  for (const text of raw.split('\n')) {
    if (!text.trim()) continue
    const parsed = parseSessionLine(text)
    if (!parsed) {
      skipped++
      continue
    }
    if (parsed.kind === 'turn') continue // v1 遗留：没有事件，没有判定可渲染
    const record = recordFromTrace(parsed)
    if (!record) continue // `header`，或不是 decision 的事件 —— 都不是「坏行」
    /*
      ★ 没有时间戳的行照样渲染，但**日期用 0**（于是文件名是 1970-01-01），
        并且计进 `undated` 报出来 —— 而不是拿当前时间冒充。一个编出来的日期
        会让「文件名能不能核对」这条保证当场失效。
    */
    const at = traceAtOf(parsed)
    if (at === undefined) undated++
    traced.push({ line: parsed, record, at: at ?? 0 })
  }
  return { traced, skipped, undated }
}

function renderMode(file: string, outDir: string): number {
  const raw = readFileSync(file, 'utf8')
  const { traced, skipped, undated } = collect(raw)
  if (traced.length === 0) {
    console.error(`没有可渲染的判定记录（${skipped} 行认不出）`)
    return 1
  }

  mkdirSync(outDir, { recursive: true })
  const perDay = new Map<string, number>()
  const written: string[] = []
  for (const t of traced) {
    const day = traceFileName(t.at, 1).slice(0, 10)
    const n = (perDay.get(day) ?? 0) + 1
    perDay.set(day, n)
    const name = traceFileName(t.at, n)
    const md = renderTrace(t.record, t.line, verifyRecord(t.record), t.at, n)
    writeFileSync(join(outDir, name), md)
    written.push(name)
  }

  console.log(`\n${B('JevLoop · 判定记录 → 可读视图')}`)
  console.log(`${D('  源    :')} ${file}`)
  console.log(`${D('  输出  :')} ${outDir}（${written.length} 份）`)
  if (skipped > 0) console.log(`${Y(`  ▲ 跳过 ${skipped} 行（坏行或认不出的形状）`)}`)
  if (undated > 0) console.log(`${Y(`  ▲ ${undated} 条没有时间戳 —— 文件名里的日期是 1970-01-01`)}`)
  for (const w of written.slice(0, 5)) console.log(`${D('  ·')} ${w}`)
  if (written.length > 5) console.log(`${D(`  · …还有 ${written.length - 5} 份`)}`)
  console.log(`\n${D('  这些 .md **自己**就能复核：')} npm run trace -- --verify ${outDir}\n`)
  return 0
}

function verifyMode(dir: string): number {
  let files: string[]
  try {
    files = readdirSync(dir)
      .filter((f) => f.endsWith('.md'))
      .sort()
  } catch (err) {
    console.error(`读不到目录 ${dir}：${(err as Error).message}`)
    return 1
  }
  if (files.length === 0) {
    console.error(`${dir} 里没有 .md`)
    return 1
  }

  const counts: Record<ReplayStatus, number> = { verified: 0, partial: 0, unverifiable: 0, mismatch: 0 }
  let problematic = 0
  let unreadable = 0

  console.log(`\n${B('JevLoop · 从 .md 本身复核判定记录')}`)
  console.log(`${D('  目录  :')} ${dir}\n`)

  for (const f of files) {
    const md = readFileSync(join(dir, f), 'utf8')
    /*
      ★ 复核走 `checkTrace`，它查四件事：块取不取得到、块里是不是一条记录、
        记录自不自洽、以及**正文与块一致不一致**。

        最后那一条是端到端跑出来的教训：第一版只查前三件，于是把表格里的命令
        从 `ls -la` 改成 `rm -rf /` 之后仍然报 `verified` —— 因为改的不是那个块。
        一份能被人读出错误结论却报 verified 的文件，不算可审计。
    */
    const c = checkTrace(md, f)
    if (c.verdict) counts[c.verdict.status]++
    else unreadable++
    if (c.problems.length > 0) problematic++

    const status = c.verdict?.status ?? 'unverifiable'
    const paint = STATUS_COLOR[status]
    const who = c.record ? `${c.record.node} → ${c.record.action ?? '(无动作)'}` : '取不回记录'
    console.log(`  ${c.ok ? paint('·') : R('✗')} ${f.padEnd(22)} ${paint(status.padEnd(13))}${D(who)}`)
    for (const p of c.problems) console.log(`      ${Y(`↳ ${p}`)}`)
  }

  console.log('')
  for (const s of ['verified', 'partial', 'unverifiable', 'mismatch'] as ReplayStatus[]) {
    console.log(`  ${STATUS_COLOR[s](s.padEnd(13))} ${counts[s]}`)
  }
  if (unreadable > 0) console.log(`  ${R('取不回机器可读块')} ${unreadable}`)

  console.log(`\n${B('  ── 这一层验证不了什么 ──────────────────────────────────')}`)
  for (const n of REPLAY_NOTES) console.log(Y(`      · ${n}`))
  if (problematic === 0) {
    console.log(G('\n  ✓ 这些 .md 文件本身都自洽，正文也没有被改过\n'))
    return 0
  }
  console.log(R(`\n  ✗ ${problematic} 份有问题（见上面的 ↳）\n`))
  return 1
}

function usage(): void {
  console.error('用法：')
  console.error('  npm run trace -- <会话日志.jsonl> [--out <目录>]   渲染成 decisions/*.md')
  console.error('  npm run trace -- --verify <目录>                  只从 .md 本身复核')
}

function main(argv: string[]): number {
  const verifyAt = argv.indexOf('--verify')
  if (verifyAt !== -1) {
    const dir = argv[verifyAt + 1]
    if (!dir) {
      usage()
      return 1
    }
    return verifyMode(dir)
  }
  const outAt = argv.indexOf('--out')
  const outDir = outAt !== -1 ? argv[outAt + 1] : DEFAULT_OUT
  const file = argv.find((a, i) => !a.startsWith('--') && (outAt === -1 || i !== outAt + 1))
  if (!file) {
    usage()
    return 1
  }
  if (!outDir) {
    usage()
    return 1
  }
  return renderMode(file, outDir)
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)))
}
