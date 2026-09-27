/**
 * JevLoop · margin 分析
 *
 * ══════════════════════════════════════════════════════════════
 *  **margin 能不能预测出错？**
 * ══════════════════════════════════════════════════════════════
 *
 * 这是 TODO §2 那个「报 margin」背后的**可证伪假设**：
 *
 *     H：margin 低的判定，出错率更高。
 *
 * 如果 H 成立，margin 就是一个**不需要金标**的线上健康指标 —— 它在生产流量上
 * 跑得起来（只要答案 + 策略），而任务成功率那种滞后指标要等坏答案已经发出去。
 * 如果 H 不成立，那 margin 只是一个诊断读数，主张就得收窄。
 *
 * ── 它读什么 ────────────────────────────────────────────────────
 *
 * `bench/run.ts --json <path>` 落下来的**逐判定原始记录**。所以要复算这里
 * 任何一个数，先把那一跑重做出来（后端必须带 key，判定后端换一个数就全变）。
 *
 * ★ 样本量是这套东西的**硬约束**：21 次运行 / 7 条任务换来的两三百个判定，
 *   分桶之后每格可能只有个位数。所以下面**每一桶都打分母**，而且样本太少的
 *   桶会被标出来 —— 「3/3 = 100%」和「30/30 = 100%」不是同一句话。
 *
 * @module JevLoop/margin
 */

import { readFile } from 'node:fs/promises'

import { C } from './util.ts'

interface Dump {
  providerChain: string
  generator: string
  tasks: number
  repeat: number
  failedRuns: number
  judgements: {
    task: string
    node: string
    verdict: 'right' | 'wrong' | 'unjudged'
    provider: string | null
    model: string | null
    prob: number
    margin: number | null
    marginOf: string | null
    threshold: number | null
    value: number | null
    action: string
    why: string
  }[]
}

const argv = process.argv.slice(2)
const argOf = (flag: string): string | undefined =>
  argv.includes(flag) ? argv[argv.indexOf(flag) + 1] : undefined

const aPath = argOf('--a')
const bPath = argOf('--b')

async function load(p: string): Promise<Dump> {
  return JSON.parse(await readFile(p, 'utf8')) as Dump
}

function median(xs: number[]): number | undefined {
  if (xs.length === 0) return undefined
  const s = [...xs].sort((x, y) => x - y)
  const m = Math.floor(s.length / 2)
  return s.length % 2 ? s[m] : (s[m - 1]! + s[m]!) / 2
}

const num = (v: number | undefined, d = 2): string => (v === undefined ? '  —  ' : v.toFixed(d))

/** 分桶的界线。和 `bench/run.ts` 的 `THIN_MARGIN` 对齐：0.10 以内算「贴边」 */
const BUCKETS: [string, number, number][] = [
  ['<0.10', 0, 0.1],
  ['0.10–0.25', 0.1, 0.25],
  ['0.25–0.50', 0.25, 0.5],
  ['≥0.50', 0.5, Infinity],
]

async function main(): Promise<void> {
  if (!aPath) {
    console.error('用法：node --experimental-strip-types bench/margin.ts --a <dump.json> [--b <dump.json>]')
    console.error('      <dump.json> 由 bench/run.ts --json 生成')
    process.exit(1)
  }
  const a = await load(aPath)
  const b = bPath ? await load(bPath) : undefined

  const head = (d: Dump) => `${d.providerChain}（生成 ${d.generator}，${d.tasks} 任务 × ${d.repeat} 遍）`
  console.log('')
  console.log(C.bold('JevLoop · margin 分析'))
  console.log(C.dim(`  A: ${head(a)}`))
  if (b) console.log(C.dim(`  B: ${head(b)}`))

  // ── ① 对错各自的 margin（和「分离度」那张表同一个形状）──────────
  console.log('')
  console.log(C.bold('  ── 对与错，各自的 margin ────────────────────────────────'))
  console.log(C.dim('  margin = |判定读的那个量 − 门限|。它**不需要金标**，所以未判的也在'))
  console.log(C.dim(`  ${'节点'.padEnd(20)}${'可算'.padStart(5)}${'对/错'.padStart(8)}${'对的(中位)'.padStart(12)}${'错的(中位)'.padStart(12)}`))

  const nodes = [...new Set(a.judgements.map((j) => j.node))].sort()
  for (const node of nodes) {
    for (const [tag, d] of [['A', a], ['B', b]] as [string, Dump | undefined][]) {
      if (!d) continue
      const js = d.judgements.filter((j) => j.node === node && j.margin !== null)
      if (js.length === 0) continue
      const right = js.filter((j) => j.verdict === 'right').map((j) => j.margin!)
      const wrong = js.filter((j) => j.verdict === 'wrong').map((j) => j.margin!)
      const label = b ? `${tag} ${node}` : node
      console.log(
        `  ${label.padEnd(20)}${String(js.length).padStart(5)}` +
          `${`${right.length}/${wrong.length}`.padStart(8)}` +
          `${num(median(right)).padStart(12)}${(wrong.length ? num(median(wrong)) : '  —  ').padStart(12)}`,
      )
    }
  }

  // ── ② 按 margin 分桶看错判率（**假设 H 的直接检验**）────────────
  console.log('')
  console.log(C.bold('  ── 假设 H：margin 低 → 出错率高？ ───────────────────────'))
  console.log(C.dim('  ★ 每格打的是 错/总，不是只打百分比 —— 分母太小的桶读不出结论'))
  for (const [tag, d] of [['A', a], ['B', b]] as [string, Dump | undefined][]) {
    if (!d) continue
    const judged = d.judgements.filter((j) => j.margin !== null && j.verdict !== 'unjudged')
    if (judged.length === 0) continue
    console.log('')
    console.log(C.dim(`  ${tag}: ${d.providerChain}  已判 ${judged.length} 条`))
    console.log(C.dim(`    ${'margin 桶'.padEnd(12)}${'错/总'.padStart(10)}${'错判率'.padStart(10)}`))
    for (const [label, lo, hi] of BUCKETS) {
      const bucket = judged.filter((j) => j.margin! >= lo && j.margin! < hi)
      if (bucket.length === 0) continue
      const wrong = bucket.filter((j) => j.verdict === 'wrong').length
      const rate = `${Math.round((wrong / bucket.length) * 100)}%`
      const line = `    ${label.padEnd(12)}${`${wrong}/${bucket.length}`.padStart(10)}${rate.padStart(10)}`
      console.log(wrong > 0 && rate !== '0%' ? C.yellow(line) : line)
    }
    // 一句话结论：两极对比。样本太小时**明说不能下结论**
    const low = judged.filter((j) => j.margin! < 0.25)
    const high = judged.filter((j) => j.margin! >= 0.25)
    if (low.length && high.length) {
      const rl = low.filter((j) => j.verdict === 'wrong').length / low.length
      const rh = high.filter((j) => j.verdict === 'wrong').length / high.length
      const enough = Math.min(low.length, high.length) >= 10
      const verdict = rl > rh ? '低 margin 的错判率更高 —— H 的方向对' : '低 margin 的错判率**没有更高** —— H 不成立'
      console.log(
        `    ${enough ? '' : C.yellow('（样本不足，只报数不下结论）')}` +
          ` margin<0.25: ${(rl * 100).toFixed(0)}%（n=${low.length}） vs ≥0.25: ${(rh * 100).toFixed(0)}%（n=${high.length}） → ${verdict}`,
      )
    }
  }

  // ── ③ 两个后端：同一个节点的 margin 分布（诊断读数）───────────
  if (b) {
    console.log('')
    console.log(C.bold('  ── 换一个判定后端，margin 分不分得开？ ──────────────────'))
    console.log(C.dim('  ★ 这一栏是**不需要金标**的那一半：任务成功率要跑完才知道，'))
    console.log(C.dim('    margin 拿答案本身就能算 —— 所以它能在生产流量上一直跑'))
    console.log(C.dim(`    ${'节点'.padEnd(20)}${'A 中位'.padStart(10)}${'B 中位'.padStart(10)}`))
    for (const node of nodes) {
      const ma = median(a.judgements.filter((j) => j.node === node && j.margin !== null).map((j) => j.margin!))
      const mb = median(b.judgements.filter((j) => j.node === node && j.margin !== null).map((j) => j.margin!))
      if (ma === undefined && mb === undefined) continue
      console.log(`  ${node.padEnd(20)}${num(ma).padStart(10)}${num(mb).padStart(10)}`)
    }
  }

  console.log('')
  const errs = a.judgements.filter((j) => j.verdict === 'wrong').length
  if (errs === 0) {
    console.log(
      C.yellow('  ⚠️ A 这一跑**一个错都没有** —— 假设 H 在这条 bench 上问不出来。') +
        '\n' +
        C.dim('     判据机自己在「没能测到什么」那一节已经说了：全对只说明这批任务上没犯错，'),
    )
    console.log(C.dim('     不说明它有判别力。要检验 H 需要一条**难到会出错**的 bench。'))
  }
  console.log('')
}

await main()
