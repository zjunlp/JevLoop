/**
 * JevLoop · 重放一个**真实会话**里的每一条判定记录 —— `npm run replay <会话文件>`
 *
 * ══════════════════════════════════════════════════════════════
 *  它回答的是：**这份落盘的轨迹，事后再读还讲得通吗？**
 * ══════════════════════════════════════════════════════════════
 *
 * 会话日志是**一行一条事件**的追加式文件（`session-store.ts`），而且它同时是
 * 给人看的轨迹、给界面回放的数据、和这里的重放输入 —— 三件事共用一个文件，
 * 所以它必须自洽。这个脚本就是那一层核对：把每一行 `decision` 事件变成记录，
 * 逐项验证指纹，并把**验证不了什么**一并打出来。
 *
 * ── 为什么值得有它 ────────────────────────────────────────────
 *
 * 理由和 `conformance.ts` 一样：**光有指纹、没有验证方，等于没有指纹**。
 * `frameDigest` / `requestDigest` 一直在算、一直在落盘，而在这次改动之前
 * **没有任何东西读过它们**（§8.16 那个「声明了却没有消费方」的形状）。
 *
 * ── 用法 ──────────────────────────────────────────────────────
 *
 *     npm run replay -- ~/.jevloop/sessions/<id>.jsonl
 *     npm run replay -- <会话文件> --verbose     # 逐条列出，不只报异常
 *
 * 退出码：0 = 每条记录要么 verified 要么 partial；1 = 有 mismatch 或读不动。
 * **`partial` 不算失败** —— 合并判定的那一项检查本来就做不了，把它算失败
 * 会让这个命令永远是红的，而永远是红的检查等于没有检查。
 *
 * @module JevLoop/replay
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { foldSessionLog } from '../src/session-log.ts'
import { recordOf, REPLAY_NOTES, REPLAY_SCHEMA } from '../src/replay-schema.ts'
import { verifyRecord, type ReplayStatus } from '../src/replay-verify.ts'

const B = (s: string) => `\x1b[1m${s}\x1b[0m`
const D = (s: string) => `\x1b[2m${s}\x1b[0m`
const G = (s: string) => `\x1b[32m${s}\x1b[0m`
const R = (s: string) => `\x1b[31m${s}\x1b[0m`
const Y = (s: string) => `\x1b[33m${s}\x1b[0m`

/** 一条记录的结果，加上它在文件里的位置 —— 「哪一条不对」比「有一条不对」有用 */
interface Line {
  run: number
  step: number
  node: string
  status: ReplayStatus
  detail: string
}

export function main(argv: readonly string[]): number {
  const verbose = argv.includes('--verbose')
  const file = argv.find((a) => !a.startsWith('--'))
  if (!file) {
    console.error('用法：npm run replay -- <会话文件.jsonl> [--verbose]')
    console.error('  会话文件在 ~/.jevloop/sessions/ 下（每个会话一个 .jsonl）')
    return 1
  }

  let raw: string
  try {
    raw = readFileSync(resolve(file), 'utf8')
  } catch (err) {
    console.error(R(`✗ 读不到 ${file}：${(err as Error).message}`))
    return 1
  }

  const folded = foldSessionLog(raw)
  const lines: Line[] = []
  let decisions = 0
  let nonDecisions = 0

  folded.runs.forEach((run, runIndex) => {
    for (const e of run.events) {
      const rec = recordOf(e)
      if (!rec) {
        nonDecisions++
        continue
      }
      decisions++
      const v = verifyRecord(rec)
      const bad = v.checks.find((c) => c.outcome === 'fail')
      lines.push({
        run: runIndex,
        step: rec.step,
        node: rec.node,
        status: v.status,
        detail: bad?.detail ?? v.checks.find((c) => c.outcome === 'skipped')?.detail ?? '',
      })
    }
  })

  console.log(B('\nJevLoop · 决策记录重放'))
  console.log(D(`  file      : ${resolve(file)}`))
  console.log(D(`  schema    : ${REPLAY_SCHEMA}`))
  console.log(
    D(
      `  records   : ${decisions} 条判定 · ${nonDecisions} 条其它事件 · ` +
        `${folded.runs.length} 轮` +
        (folded.skipped ? ` · ${folded.skipped} 行读不动（追加式格式允许撕裂尾行）` : ''),
    ),
  )
  if (folded.header) console.log(D(`  session   : ${folded.header.id}`))

  const by = (s: ReplayStatus) => lines.filter((l) => l.status === s)
  const verified = by('verified')
  const partial = by('partial')
  const unverifiable = by('unverifiable')
  const mismatch = by('mismatch')

  console.log('')
  console.log(`  ${G('✓ verified    ')} ${String(verified.length).padStart(4)}  ${D('该做的检查都做了，全部通过')}`)
  console.log(
    `  ${Y('~ partial     ')} ${String(partial.length).padStart(4)}  ${D('通过了一部分；其余说清了为什么做不了（合并判定的常态）')}`,
  )
  console.log(
    `  ${Y('? unverifiable')} ${String(unverifiable.length).padStart(4)}  ${D('缺重放必需的字段（旧日志，或不是本实现写的）')}`,
  )
  console.log(`  ${R('✗ mismatch    ')} ${String(mismatch.length).padStart(4)}  ${D('记录不自洽 —— 指纹和内容对不上')}`)

  const show = (ls: Line[], color: (s: string) => string) => {
    for (const l of ls) {
      console.log(`      ${color(l.status.padEnd(13))} run ${l.run} · step ${l.step} · ${l.node}`)
      if (l.detail) console.log(D(`        ${l.detail}`))
    }
  }
  if (mismatch.length) {
    console.log(B('\n  ── 不自洽的记录 ────────────────────────────────────────'))
    show(mismatch, R)
  }
  if (unverifiable.length && (verbose || unverifiable.length <= 3)) {
    console.log(B('\n  ── 无法重放的记录 ──────────────────────────────────────'))
    show(unverifiable, Y)
  }
  if (verbose) {
    console.log(B('\n  ── 全部记录 ────────────────────────────────────────────'))
    show(lines, (s) => s)
  }

  /*
    ★ **把「验证不了什么」打出来。** 一个只说「全部通过」的重放器最容易被读成
      「这次运行被复现了」或「判定是对的」—— 两件它都给不了的事。
      所以那三条注意事项是**输出的一部分**，不是文档里的脚注。
  */
  if (lines.length) {
    console.log(B('\n  ── 这一层验证不了什么 ──────────────────────────────────'))
    for (const n of REPLAY_NOTES) console.log(Y(`      · ${n}`))
  }

  const ok = mismatch.length === 0
  console.log(
    ok
      ? G('\n  ✓ 没有不自洽的记录（partial / unverifiable 的原因见上）\n')
      : R('\n  ✗ 有记录不自洽 —— 那份轨迹不能当作证据用\n'),
  )
  return ok ? 0 : 1
}

// 直接跑时进 main；被 import（单测）时不跑。
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)))
}
