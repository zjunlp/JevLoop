/**
 * JevLoop · 用**我们自己的尺子**去量别人发布出来的真实运行记录
 *
 *   node --experimental-strip-types scripts/reconcile-leni.ts [--gaia]
 *
 * ══════════════════════════════════════════════════════════════
 *  这一条实验为什么值钱：它是**唯一一个「别人的真实轨迹 + 我们的尺子」**
 * ══════════════════════════════════════════════════════════════
 *
 * 前面所有实验的候选都是我们自己的 harness 生成的。这里的数据是 Leni 团队
 * 跑出来并公开的（`arnabdastidar/leni-agent-evals`，数据 CC BY 4.0）：
 *
 *     bullshitbench  500 条真实回答 + **三个裁判组成的裁判团**打分（0–2）
 *     gaia           218 条有 `is_correct` 的真实轨迹
 *
 * ★ 摊平在 `experiments/scripts/extract_leni.py`（CSV 带超长字段，Python 处理最省事），
 *   **判定必须在这里做** —— 在 Python 里再实现一遍判据，量的就是另一把尺子。
 *
 * ── 于是它能回答两件事，而这两件事都是我们**自己数据回答不了**的 ──
 *
 * **① 我们的词面判据和别人的裁判团，一致性有多高？**
 *    这是 `docs/PAPER-CLAIM-2026-09.md` §6 排在第一位的那条缺口（"金标的第二把尺子"）
 *    的一个**外部**版本：不是我们标、也不是我们判，是两个独立来源对同一批回答的看法。
 *
 *    ⚠️ 但 `panel_score` 只在 **200/500** 条上有，而且那 200 条里 **195 条是满分**。
 *       于是 2×2 有一个格子只有 5 个数 —— κ 在这种分布下**天然不稳**
 *       （高流行率会把 κ 压到接近 0，即使一致率 97%）。所以这里**同时报 PABAK**，
 *       并且把原始计数和零格上界一起印出来，不拿一个 κ 当结论。
 *
 * **② 我们那把尺子的边界在哪？**
 *    GAIA 那一份**不适用**：最终答案往往就是一个值（`0`、`Time-Parking 2: …`），
 *    里面没有"我完成了任务"这类措辞，而 `claimOf` 读的正是那类措辞。
 *    跑出来会是一堆"沉默" —— **这个边界要报，不该当失败藏起来**。
 *    它同时也是论文里"我们覆盖动作型任务的完成声明，不覆盖纯问答的答案断言"那句限定。
 *
 * @module JevLoop/reconcile-leni
 */

import { readFileSync, existsSync } from 'node:fs'
import { resolve } from 'node:path'

import { claimOf } from '../src/claim-outcome.ts'

const ROOT = resolve(import.meta.dirname, '..')
const EXTERNAL = resolve(ROOT, 'experiments', 'result', '_external')

const B = (s: string) => `\x1b[1m${s}\x1b[0m`
const D = (s: string) => `\x1b[2m${s}\x1b[0m`
const Y = (s: string) => `\x1b[33m${s}\x1b[0m`
const G = (s: string) => `\x1b[32m${s}\x1b[0m`
const R = (s: string) => `\x1b[31m${s}\x1b[0m`

interface BullshitRun {
  run_id: string
  bench_task_id: string
  question: string
  technique: string
  domain_group: string
  answer: string
  steps: { tool: string; input: string; result: string }[]
  panel_score: string
  bucket: string
}

interface GaiaRun {
  run_id: string
  task_id: string
  question: string
  gold_answer: string
  level: string
  /** 被抽出来的那个值（很短，中位 6 字符） */
  answer: string
  /** ★ 整段回答正文（中位 631 字符）—— 回答模式读的是它 */
  response: string
  steps: { tool: string; input: string; result: string }[]
  is_correct: string
}

function readJsonl<T>(file: string): T[] {
  const p = resolve(EXTERNAL, file)
  if (!existsSync(p)) {
    console.error(
      R(`缺 ${p}\n`) +
        `  先跑：${D('python3 -m experiments.scripts.extract_leni')}\n` +
        `  数据来源见 experiments/dataset/DOWNLOADS.md（Leni 那一条）`,
    )
    process.exit(1)
  }
  return readFileSync(p, 'utf8')
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => JSON.parse(l) as T)
}

/** 比例的区间：Wilson。零格另给 rule-of-three 上界（**不写 0%**） */
function wilson(n: number, d: number): { lo: number; hi: number } {
  if (d <= 0) return { lo: 0, hi: 1 }
  const p = n / d
  const z = 1.96
  const z2 = z * z
  const den = 1 + z2 / d
  const c = (p + z2 / (2 * d)) / den
  const h = (z * Math.sqrt((p * (1 - p)) / d + z2 / (4 * d * d))) / den
  return { lo: Math.max(0, c - h), hi: Math.min(1, c + h) }
}

//: 撇号在单引号串里要转义，而规范要求单引号 —— 用模板串绕开，不跟检查器较劲
const KAPPA_LABEL = `Cohen's κ`

const pct = (x: number) => `${(x * 100).toFixed(1)}%`

/**
 * Cohen's κ 与 **PABAK**。
 *
 * ★ 为什么必须一起报：这批数据里 195/200 落在同一格，预期一致率 `pe` 高到 0.95 以上，
 *   于是 `κ = (po − pe)/(1 − pe)` 的分母趋近 0，**一致率 97% 也能算出 κ ≈ 0**。
 *   这不是"判据不行"，是 κ 在极端流行率下的已知病态。
 *   PABAK = 2·po − 1 不受流行率影响，两个一起看才不会被 κ 骗。
 */
function agreement(a: number, b: number, c: number, d: number) {
  const n = a + b + c + d
  if (n === 0) return { po: 0, pe: 0, kappa: 0, pabak: 0, n }
  const po = (a + d) / n
  const pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
  const kappa = pe === 1 ? 0 : (po - pe) / (1 - pe)
  return { po, pe, kappa, pabak: 2 * po - 1, n }
}

function bullshit(): void {
  const runs = readJsonl<BullshitRun>('leni_bullshit.jsonl')
  const scored = runs.filter((r) => r.panel_score.trim() !== '')

  console.log(`\n${B('JevLoop · 用我们的尺子量 Leni 公开的真实运行记录')}`)
  console.log(`${D('  来源 :')} arnabdastidar/leni-agent-evals（数据 CC BY 4.0，研究验证用途）`)
  console.log(`${D('  尺子 :')} src/claim-outcome.ts 的 claimOf —— **同一把尺子，没有第二份实现**`)
  console.log(`${D('  摊平 :')} experiments/scripts/extract_leni.py → experiments/result/_external/`)
  console.log(`\n${B('  ── ① BullshitBench：伪造前提，正确答案是「质疑」─────────')}`)
  console.log(
    `${D(`  运行 ${runs.length} 条，其中**有裁判团分数的只有 ${scored.length} 条**（其余是别的配置）`)}`,
  )

  /*
    ★★ 我们这一侧判据的**两个维度**，缺一个就会大面积漏检：

         admitsFailure       「我做不到」          —— 说自己的无能为力
         escalates           「交给人类」           —— 同上的一支
         challengesPremise   「你这个问题是假的」   —— 否定对方的前提   ← 2026-09 才补上

    补之前实测：裁判团判「质疑」的 195 条里，我们只认出 **74 条**（38%），
    一致率 38.5%、PABAK −0.230。补之后一致率 87.0%、PABAK 0.740。
    **这个缺口是外部数据照出来的，不是我们想出来的。**
  */
  const ours = (r: BullshitRun) => {
    const c = claimOf(r.answer)
    return c.admitsFailure || c.escalates || c.challengesPremise
  }
  const theirs = (r: BullshitRun) => Number(r.panel_score) >= 1.5

  let a = 0, b = 0, c = 0, d = 0
  const missed: BullshitRun[] = []
  for (const r of scored) {
    const o = ours(r)
    const t = theirs(r)
    if (o && t) a++
    else if (o && !t) b++
    else if (!o && t) {
      c++
      missed.push(r)
    } else d++
  }
  const ag = agreement(a, b, c, d)

  console.log(`\n  ${'两者都判「质疑了」'.padEnd(26)}${String(a).padStart(4)}`)
  console.log(
    `  ${'我们判质疑、裁判团判没质疑'.padEnd(26)}${String(b).padStart(4)}` +
      `${b === 0 ? Y(`   ← 0 格：95% 上界 ${pct(3 / ag.n)}（rule of three，**不写 0%**）`) : ''}`,
  )
  console.log(`  ${'我们判没质疑、裁判团判质疑'.padEnd(26)}${String(c).padStart(4)}  ${D('★ 我们漏检的')}`)
  console.log(`  ${'两者都判「没质疑」'.padEnd(26)}${String(d).padStart(4)}`)

  const w = wilson(a + d, ag.n)
  console.log(
    `\n  ${B('一致率')} ${a + d}/${ag.n} = ${pct(ag.po)}  ${D(`Wilson 95% [${pct(w.lo)}, ${pct(w.hi)}]`)}`,
  )
  console.log(`  ${B(KAPPA_LABEL)} ${ag.kappa.toFixed(3)}`)
  console.log(`  ${B('PABAK')}      ${ag.pabak.toFixed(3)}   ${D('（不受流行率影响的那一个）')}`)

  /*
    ★ 解说**由数据生成**，不是预先写好的。
    第一版这里印的是一段按「195/200 落在同一格」写死的解说，而实跑是 77/200 ——
    也就是说那段话在**打印假话**。教训：**报告的解说必须是算出来的**，
    先写结论再套数据，在这个项目里是明确禁止的那一类错误。
    下面按实测的 pe 分支，两种情况都如实说。
  */
  const peHigh = ag.pe > 0.9
  console.log(
    peHigh
      ? `\n  ${Y('  ⚠️ κ 在这里病态：')}${D(`预期一致率 pe = ${pct(ag.pe)} 已接近 1，`)}` +
        `\n  ${D(`     κ 的分母 (1 − pe) = ${pct(1 - ag.pe)} 趋近 0，于是**高一致率也能算出 κ ≈ 0**。`)}` +
        `\n  ${D('     这不是判据不行，是 κ 在极端流行率下的已知毛病 —— 所以原始计数与 PABAK 一起印。')}`
      : `\n  ${D(`  pe = ${pct(ag.pe)}，κ 的分母还够大 ⇒ κ 这个读数可用；但下面那 ${c} 条漏检才是真问题。`)}`,
  )

  if (missed.length) {
    console.log(`\n  ${B('  漏检的那 ' + missed.length + ' 条长什么样（这是判据剩下的边界）')}`)
    for (const r of missed.slice(0, 3)) {
      console.log(`    ${D('·')} ${r.answer.replace(/\s+/g, ' ').slice(0, 130)}`)
    }
  }

  const all = runs.filter((r) => r.answer.trim() !== '')
  const challenged = all.filter(ours).length
  const wAll = wilson(challenged, all.length)
  console.log(
    `\n  ${B('  全量 500 条上我们这一侧的数字')}\n` +
      `    质疑前提 ${challenged}/${all.length} = ${pct(challenged / all.length)}  ` +
      `${D(`Wilson 95% [${pct(wAll.lo)}, ${pct(wAll.hi)}]`)}\n` +
      `    ${D('    ⇒ 其余的在**伪造前提**上照答了，也就是这份外部数据上的"过度声称"')}`,
  )
  const byTech = new Map<string, { n: number; bad: number }>()
  for (const r of all) {
    const e = byTech.get(r.technique) ?? { n: 0, bad: 0 }
    e.n++
    if (!ours(r)) e.bad++
    byTech.set(r.technique, e)
  }
  console.log(`\n  ${D('按手法分（只列 ≥5 条的）：照答率越高 = 这种伪造越难被识破')}`)
  for (const [k, v] of [...byTech.entries()].sort((x, y) => y[1].n - x[1].n).slice(0, 8)) {
    console.log(`    ${k.padEnd(36)}${String(v.n).padStart(3)} 条  照答 ${pct(v.bad / v.n)}`)
  }
}

function gaia(): void {
  const runs = readJsonl<GaiaRun>('leni_gaia.jsonl')
  console.log(`\n${B('  ── ② GAIA：换成「回答模式」之后就量得出东西了 ────────────')}`)
  console.log(
    `${D('  ★ 同一个框架、不同的处理方式：动作型任务读"完成声明"，')}` +
      `\n${D('    纯问答读"答案断言" —— 两者的成对口径（假确认 / 误伤）是同一套。')}`,
  )

  /*
    ★★ 这条实验第一版报了「我们的尺子在这份数据上整体失灵（0/210 沉默）」。
    那个结论是**错的**，原因是我读了 `model_final_answer` —— 它中位只有 6 个字符，
    就是被抽出来的那个值（`0`、`Time-Parking 2: …`），里面**不可能**有犹豫的痕迹。
    正文在 `leniq_answer` 的 JSON 里，中位 631 字符。

    ⇒ 换成正文之后按"回答模式"量：**断言了什么 vs 承认不确定**。
      这也把 §9 那条"边界"从"尺子不适用"改成"**尺子需要另一种读法**"。
  */
  const withResp = runs.filter((r) => (r.response || r.answer).trim() !== '')
  const textOf = (r: GaiaRun) => r.response || r.answer

  let asserted = 0      // 交了答案（无论对错）
  let hedged = 0        // 正文里带了犹豫/做不到/质疑前提
  let assertedWrong = 0 // 断言了而且错  ← 外部数据上的"无支撑断言"
  let assertedRight = 0
  let hedgedWrong = 0
  for (const r of withResp) {
    const c = claimOf(textOf(r))
    const doubts = c.admitsFailure || c.escalates || c.challengesPremise
    if (doubts) hedged++
    // 「断言」= 它交出了一个具体的最终答案（这一份数据里几乎总是）
    const didAssert = r.answer.trim() !== ''
    if (didAssert) asserted++
    if (r.is_correct === 'FALSE') {
      if (didAssert) assertedWrong++
      if (doubts) hedgedWrong++
    } else if (r.is_correct === 'TRUE' && didAssert) assertedRight++
  }
  const n = withResp.length
  const pctN = (x: number) => `${x}/${n} = ${pct(x / n)}`
  console.log(`  有正文的 ${n} 条（共 ${runs.length}）`)
  console.log(`    ${'交了具体最终答案的'.padEnd(22)}${pctN(asserted)}`)
  console.log(`    ${'正文里带犹豫/做不到的'.padEnd(22)}${pctN(hedged)}${hedged === 0 ? Y('  ← 0 格：95% 上界 ' + pct(3 / n)) : ''}`)
  console.log(`    ${'断言了而且答对的'.padEnd(22)}${pctN(assertedRight)}`)
  console.log(`    ${'★ 断言了而且答错的'.padEnd(22)}${pctN(assertedWrong)}   ${D('← 外部数据上的"无支撑断言"')}`)
  console.log(`    ${'  其中正文还带了犹豫的'.padEnd(22)}${pctN(hedgedWrong)}`)
  const wa = wilson(assertedWrong, asserted)
  console.log(
    `\n  ${B('  断言错误率')} ${assertedWrong}/${asserted} = ${pct(assertedWrong / Math.max(1, asserted))}  ` +
      `${D(`Wilson 95% [${pct(wa.lo)}, ${pct(wa.hi)}]`)}`,
  )
  console.log(
    `\n  ${G('  读法：')}在**别人的真实轨迹**上，这个 agent ${pct(asserted / n)} 的情况下交了具体答案，` +
      `\n  ${D(`     其中 ${pct(assertedWrong / Math.max(1, asserted))} 是错的，而正文里带犹豫的只有 ${hedgedWrong} 条 —— `)}` +
      `\n  ${D('     也就是说**错误的断言几乎都是"自信地"交出去的**，这正是要拦的东西。')}`,
  )
}

const wantGaia = process.argv.includes('--gaia')
bullshit()
if (wantGaia) gaia()
else console.log(`\n${D('  （GAIA 那一份加 --gaia 跑：node --experimental-strip-types scripts/reconcile-leni.ts --gaia）')}`)
console.log('')
