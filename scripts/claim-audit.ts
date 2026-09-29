/**
 * JevLoop · 声称 vs 证据：把已有会话判成五种结局（TODO §10 之前那一步）
 *
 *   npm run claim-audit -- <会话日志.jsonl> [--no-action | --needs-action]
 *
 * ── 它离线跑、不花钱 ────────────────────────────────────────────
 *
 * 数据就在会话日志里：`run:start` 有任务，`tool:call`/`tool:result` 是轨迹，
 * `run:end` 有最终回答。所以**已有的每一轮历史都可以直接拿来对账**，
 * 不需要重跑任何模型。
 *
 * ── ★ 为什么不给一个统一的「假完成率」 ──────────────────────────
 *
 * 判定「这轮该不该动手」需要**任务规格**，而日志里没有。没有规格时诚实的结果
 * 只能是 `unknown`（或 `suspect`）—— 所以本命令默认**如实报 unknown**，并让你用
 * `--no-action` / `--needs-action` 把规格补上再看它怎么变。**这本身就是演示**：
 * 同一批日志，补上规格前后那两个数是不同的，而**只有后者能当结论**。
 *
 * @module JevLoop/claim-audit
 */

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { basename, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parseSessionLine } from '../src/session-log.ts'
import { claimOf, classify, evidenceOf, tally, OUTCOME_LABEL, type Outcome, type Step } from '../src/claim-outcome.ts'

const B = (s: string) => `\x1b[1m${s}\x1b[0m`
const D = (s: string) => `\x1b[2m${s}\x1b[0m`
const R = (s: string) => `\x1b[31m${s}\x1b[0m`
const Y = (s: string) => `\x1b[33m${s}\x1b[0m`
const G = (s: string) => `\x1b[32m${s}\x1b[0m`

/** 一轮：任务 + 回答 + 轨迹 */
interface Run {
  file: string
  task: string
  answer: string
  halt: string
  history: Step[]
}

/** 一个日志文件 → 它里面的每一轮 */
function runsOf(file: string): Run[] {
  const out: Run[] = []
  let cur: Run | undefined
  const calls = new Map<string, { tool: string; input: string }>()

  for (const line of readFileSync(file, 'utf8').split('\n')) {
    if (!line.trim()) continue
    const parsed = parseSessionLine(line)
    if (!parsed || parsed.kind !== 'event') continue
    const e = parsed.e as Record<string, unknown>

    if (e.type === 'run:start') {
      cur = { file, task: String(e.task ?? ''), answer: '', halt: '', history: [] }
      calls.clear()
      continue
    }
    if (!cur) continue
    if (e.type === 'tool:call' && typeof e.step === 'number') {
      calls.set(String(e.step), { tool: String(e.tool ?? '?'), input: String(e.input ?? '') })
      continue
    }
    if (e.type === 'tool:result' && typeof e.step === 'number') {
      const c = calls.get(String(e.step))
      if (c) cur.history.push({ ...c, result: String(e.output ?? '') })
      continue
    }
    if (e.type === 'run:end') {
      cur.answer = String(e.answer ?? '')
      cur.halt = String(e.halt ?? '')
      out.push(cur)
      cur = undefined
    }
  }
  return out
}

function collect(target: string): Run[] {
  if (statSync(target).isDirectory()) {
    return readdirSync(target).filter((f) => f.endsWith('.jsonl')).flatMap((f) => runsOf(join(target, f)))
  }
  return runsOf(target)
}

/** 报表里的结局配色：要抓的那一类标红，成对的那一类标黄 */
const paint = (o: Outcome, s: string) =>
  o === 'unsupported-completion' ? R(s) : o === 'over-abstention' || o === 'suspect' ? Y(s) : o === 'correct-completion' ? G(s) : s

function main(argv: string[]): number {
  const flag = argv.includes('--needs-action') ? true : argv.includes('--no-action') ? false : undefined
  const target = argv.find((a) => !a.startsWith('--'))
  if (!target) {
    console.error('用法：npm run claim-audit -- <会话日志.jsonl | 目录> [--needs-action | --no-action]')
    return 1
  }

  const runs = collect(target)
  if (runs.length === 0) {
    console.error('这份日志里没有跑完的轮次（没有 run:end）')
    return 1
  }

  console.log(`\n${B('JevLoop · 声称 vs 证据')}`)
  console.log(`${D('  来源  :')} ${target}`)
  console.log(
    `${D('  规格  :')} ${
      flag === undefined ? '未提供（不知道这几轮该不该动手）' : flag ? '需要动手' : '不需要动手'
    }\n`,
  )

  const outcomes: Outcome[] = []
  for (const r of runs) {
    const claim = claimOf(r.answer)
    const evidence = evidenceOf(r.history)
    const outcome = classify({ claim, evidence, taskNeedsAction: flag })
    outcomes.push(outcome)

    console.log(`  ${paint(outcome, OUTCOME_LABEL[outcome].padEnd(22))} ${D(basename(r.file))}`)
    console.log(`    ${D('任务')} ${r.task.slice(0, 70)}${r.task.length > 70 ? '…' : ''}`)
    console.log(
      `    ${D('声称')} 完成=${claim.claimsDone ? '是' : '否'} 测试通过=${claim.claimsTests ? '是' : '否'} ` +
        `承认失败=${claim.admitsFailure ? '是' : '否'} 升级=${claim.escalates ? '是' : '否'}`,
    )
    console.log(
      `    ${D('证据')} ${evidence.steps} 步 · 状态改变=${evidence.changedState ? evidence.changedBy.join(',') : '无'} · ` +
        `起过进程=${evidence.ranCommand ? '是' : '否'} · 失败调用=${evidence.failedCalls}`,
    )
    if (claim.hits.length > 0) console.log(`    ${D('撞在')} ${claim.hits.slice(0, 6).join(' / ')}`)
    console.log(`    ${D('halt')} ${r.halt}`)
    console.log('')
  }

  const t = tally(outcomes)
  console.log(B('  ── 分布 ──────────────────────────────────────────────'))
  for (const [k, n] of Object.entries(t.counts)) {
    if (n > 0) console.log(`  ${paint(k as Outcome, String(n).padStart(3))}  ${OUTCOME_LABEL[k as Outcome]}`)
  }
  const pct = (x: number | null) => (x === null ? '—' : `${(x * 100).toFixed(1)}%`)
  console.log(`\n  ${D('能判的轮次')} ${t.judged} / ${runs.length}`)
  console.log(`  ${R('假称完成率')} ${pct(t.unsupportedRate)}   ${D('（分子 = 假称完成；分母 = 能判的）')}`)
  console.log(`  ${Y('冤枉率')}     ${pct(t.overAbstentionRate)}   ${D('★ 必须和上面一起看：单看上面，一个「一律说没做完」的回答能拿满分')}`)

  if (flag === undefined) {
    console.log(
      `\n${Y('  ▲ 这一份没有任务规格，所以多数轮次只能判 unknown —— 不许把它们算成抓到了。')}` +
        `\n${D('    补上规格再看：npm run claim-audit -- <日志> --no-action（或 --needs-action）')}`,
    )
  }
  console.log('')
  return 0
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)))
}
