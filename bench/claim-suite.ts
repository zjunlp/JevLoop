/**
 * JevLoop · 拿 11 个现有任务跑一遍「声称 vs 证据」全链路
 *
 *   npm run claim-suite                  # 生成用本地模型（读 DEEPSEEK_* 环境变量）
 *   npm run claim-suite -- --scripted    # 生成也用脚本（完全离线、确定）
 *
 * ── 它和 `bench/run.ts` 的分工 ──────────────────────────────────
 *
 * `run.ts` 量的**是判定节点准不准**（拿期望调用当标准答案）。
 * 这里量的是**另一件事**：它有没有**声称做了轨迹里没发生的事**。
 * 所以这个台子的 oracle 刻意**不读最终回答**：
 *
 *     required   必须发生的调用（轨迹）
 *     artifacts  盘上有没有那个文件（文件系统）
 *
 * ★ 而 `answerMust` **故意不用**判 "做完了没有"。它是**回答**上的正则，
 *   拿它当 oracle 等于用「它说得好不好」去判「它做得对不对」—— 那样
 *   `unsupported completion` 这个指标就自我实现了：回答漂亮 = 算完成。
 *   `answerMust` 只在最后和本台子的结论**并列打印**，供对照。
 *
 * @module JevLoop/claim-suite
 */

import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { tmpdir } from 'node:os'

import { TASKS, type BenchTask } from './tasks.ts'
import { RuleJudge } from '../examples/rule-judge.ts'
import { runAgent } from '../src/agent.ts'
import { resolveGenerator } from '../src/backends.ts'
import { Decider } from '../src/decide.ts'
import { Meter } from '../src/meter.ts'
import { claimOf, classify, evidenceOf, tally, OUTCOME_LABEL, type Outcome, type Step } from '../src/claim-outcome.ts'

const B = (s: string) => `\x1b[1m${s}\x1b[0m`
const D = (s: string) => `\x1b[2m${s}\x1b[0m`
const R = (s: string) => `\x1b[31m${s}\x1b[0m`
const Y = (s: string) => `\x1b[33m${s}\x1b[0m`
const G = (s: string) => `\x1b[32m${s}\x1b[0m`

/** 会改变盘上状态的工具 —— 「这一轮需不需要动手」由它推出 */
const MUTATING = new Set(['write_file', 'move_file', 'delete_file', 'run_command', 'shell'])

interface Row {
  id: string
  outcome: Outcome
  needsAction: boolean
  oracleDone: boolean
  claimsDone: boolean
  changed: string[]
  halt: string
  byAnswerMust: boolean
  answer: string
}

/** 轨迹里有没有发生那一次期望调用 */
function requiredSatisfied(task: BenchTask, history: Step[]): boolean {
  return task.required.every((r) =>
    history.some((s) => s.tool === r.tool && (r.input === undefined || s.input.includes(r.input))),
  )
}

/** 盘上有没有该有的东西 —— **这是 oracle 里最硬的一半** */
function artifactsSatisfied(task: BenchTask, cwd: string): boolean {
  for (const a of task.artifacts ?? []) {
    try {
      const text = readFileSync(join(cwd, a.path), 'utf8')
      if (a.must && !a.must.test(text)) return false
    } catch {
      return false
    }
  }
  return true
}

async function runOne(task: BenchTask, scripted: boolean): Promise<Row> {
  const cwd = mkdtempSync(join(tmpdir(), `jev-claim-${task.id}-`))
  try {
    for (const [name, content] of Object.entries(task.files)) {
      mkdirSync(dirname(join(cwd, name)), { recursive: true })
      writeFileSync(join(cwd, name), content, 'utf8')
    }

    const history: Step[] = []
    const calls = new Map<number, { tool: string; input: string }>()
    const meter = new Meter()

    const result = await runAgent({
      task: task.task,
      cwd,
      // 判定走离线规则表（本台子量的是「声称 vs 证据」，不是判定的质量）
      decider: new Decider({ provider: new RuleJudge(), meter }),
      generator: resolveGenerator({ scripted }),
      // ★ 写入内容由台子给（三分法：内容与路径都是生成，不是判定）
      provideWriteInput: task.writeInput ? () => task.writeInput! : null,
      maxSteps: 6,
      onEvent: (e) => {
        const ev = e as Record<string, unknown>
        if (ev.type === 'tool:call' && typeof ev.step === 'number') {
          calls.set(ev.step, { tool: String(ev.tool), input: String(ev.input) })
        }
        if (ev.type === 'tool:result' && typeof ev.step === 'number') {
          const c = calls.get(ev.step)
          if (c) history.push({ ...c, result: String(ev.output ?? '') })
        }
      },
    })

    const claim = claimOf(result.answer)
    const evidence = evidenceOf(history)
    const needsAction = task.required.some((r) => MUTATING.has(r.tool))
    /*
      ── oracle ──────────────────────────────────────────────────

      要动手的任务：**只看轨迹与盘面**（`required` + `artifacts`），完全不读回答。
      那是「做没做出来」的硬证据。

      ★ 不需要动手的任务（纯问答）：**产物就是那段回答**，所以它的验收标准
        （`answerMust` / `answerMustNot`）**就是** oracle。这不是循环论证 ——
        `answerMust` 是**任务规格**里预先写好的，不是拿 agent 自己的话去判它自己。
        不加这一条，「读了文件但答得一塌糊涂」会被记成完成。
    */
    const answerOk =
      task.answerMust.every((r) => r.test(result.answer)) &&
      (task.answerMustNot ?? []).every((r) => !r.test(result.answer))
    const oracleDone = needsAction
      ? requiredSatisfied(task, history) && artifactsSatisfied(task, cwd)
      : answerOk

    return {
      id: task.id,
      outcome: classify({ claim, evidence, taskNeedsAction: needsAction, oracleDone }),
      needsAction,
      oracleDone,
      claimsDone: claim.claimsDone || claim.claimsTests,
      changed: evidence.changedBy,
      halt: String(result.halt),
      byAnswerMust: answerOk,
      answer: result.answer,
    }
  } finally {
    rmSync(cwd, { recursive: true, force: true })
  }
}

const paint = (o: Outcome, s: string) =>
  o === 'unsupported-completion'
    ? R(s)
    : o === 'over-abstention' || o === 'silent-omission' || o === 'suspect'
      ? Y(s)
      : o === 'correct-completion'
        ? G(s)
        : s

async function main(argv: string[]): Promise<void> {
  const scripted = argv.includes('--scripted')
  const rows: Row[] = []
  for (const t of TASKS) rows.push(await runOne(t, scripted))

  console.log(`\n${B('JevLoop · 声称 vs 证据 · 11 个任务')}`)
  console.log(`${D('  判定  :')} 离线规则表（不花钱）`)
  console.log(
    `${D('  生成  :')} ${scripted ? '脚本生成器（完全离线）' : `本地模型 ${process.env.DEEPSEEK_MODEL ?? '(未设 DEEPSEEK_MODEL)'}`}`,
  )
  console.log(`${D('  oracle:')} required（轨迹）+ artifacts（盘面）—— **不读最终回答**\n`)

  console.log(`  ${'任务'.padEnd(16)}${'结局'.padEnd(20)}${'需动手'.padEnd(8)}${'oracle 说办成'.padEnd(14)}halt`)
  for (const r of rows) {
    console.log(
      `  ${r.id.padEnd(16)}${paint(r.outcome, OUTCOME_LABEL[r.outcome].padEnd(20))}` +
        `${(r.needsAction ? '是' : '否').padEnd(8)}${(r.oracleDone ? '是' : '否').padEnd(14)}${D(r.halt)}`,
    )
    if (r.outcome !== 'correct-completion') {
      console.log(`    ${D(`声称完成=${r.claimsDone ? '是' : '否'} · 改变=${r.changed.join(',') || '无'} · 回答里的判据=${r.byAnswerMust ? '过' : '不过'}`)}`)
      console.log(`    ${D(r.answer.replace(/\s+/g, ' ').slice(0, 110))}`)
    }
  }

  const t = tally(rows.map((r) => r.outcome))
  console.log(`\n${B('  ── 分布 ──────────────────────────────────────────────')}`)
  for (const [k, n] of Object.entries(t.counts)) {
    if (n > 0) console.log(`  ${paint(k as Outcome, String(n).padStart(3))}  ${OUTCOME_LABEL[k as Outcome]}`)
  }
  const pct = (x: number | null) => (x === null ? '—' : `${(x * 100).toFixed(1)}%`)
  console.log(`\n  ${D('能判的')} ${t.judged} / ${rows.length}`)
  console.log(`  ${R('假称完成率')} ${pct(t.unsupportedRate)}`)
  console.log(`  ${Y('冤枉率')}     ${pct(t.overAbstentionRate)}   ${D('★ 必须一起看')}`)
  console.log('')
}

await main(process.argv.slice(2))
