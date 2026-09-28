/**
 * JevLoop · capability report 核对（`npm run adapter-report`）
 *
 * ══════════════════════════════════════════════════════════════
 *  `examples/external-host.capabilities.json` **必须和代码对得上**。
 * ══════════════════════════════════════════════════════════════
 *
 * ── 为什么需要这个脚本 ────────────────────────────────────────
 *
 * 那份 JSON 是**给外部看的声明**：这个宿主支持哪些位置、哪些动作、注册了哪些
 * 投影与动态提供者。它写出来的当天是对的 —— 然后代码改了，它不会跟着改。
 *
 * 实测过这个形状的后果：在此之前，全仓库**只有 README 提到它**，没有任何一行
 * 代码读它。于是它是一份**没有消费方的声明** —— 而这个仓库记过好几次
 * （§8.16：「声明了却没有消费方」，等于没有声明）。一份会悄悄过期的能力报告
 * 比没有报告更糟：它让人以为自己知道边界在哪。
 *
 * 所以这个脚本把两件事对上：
 *
 *     代码里 export 的 CAPABILITIES / GRAPH / HOST_POSITIONS
 *        ↕  必须一致
 *     examples/external-host.capabilities.json
 *
 * 并且顺手证明**声明出来的能力真的够用** —— 拿它去核对两份契约：
 *
 *     DECISION.md                      参考契约（六个核心位置）
 *     examples/custom-graph.DECISION.md 自定义节点 + host: 命名空间
 *
 * 只对 JSON 不核对契约是不够的：那样「报告和代码一致」可能只是**两边一起错**。
 *
 * ── 用法 ──────────────────────────────────────────────────────
 *
 *     npm run adapter-report       # 一致 → 0；漂移 → 1，并逐条说明差在哪
 *
 * @module JevLoop/adapter-report
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { adapterProblems, type AdapterCapabilities } from '../src/adapter.ts'
import { CURRENT_SCHEMA, parseDecisionDoc, schemaProblems } from '../src/decisiondoc.ts'
import { CAPABILITIES, GRAPH, HOST_POSITIONS } from '../examples/external-host.ts'

/** 报告的形状。手写的那份 JSON 必须满足它 —— 写错了要当场说，不是运行时才 undefined */
export interface CapabilityReport {
  adapter: string
  contractSchema: string
  level: number
  description: string
  positions: Record<string, string[]>
  hostPositions: Record<string, string[]>
  customGraphNodes: string[]
  terminalStates: string[]
  graphFeatures: string[]
  projections: string[]
  dynamicProviders: string[]
  conformance: { command: string; negativeFixtures: string; dispatchAfterCapabilityCheck: boolean }
  knownLimitations: string[]
}

/**
 * 图特征能不能在**这张图里**演示出来。
 *
 * ★ `graphFeatures: ["branch", "retry", …]` 是报告里最像广告的一行 ——
 *   四个词全都可以照抄，而图里一个都没有。所以每个词都要有**机械定义**，
 *   演示不出来就报错。这和 `scripts/conformance.ts` 用「阴性对照」钉住
 *   整套检查是同一个态度：一句不能被证伪的话不算声明。
 */
function demonstratedFeatures(): Record<string, boolean> {
  const nodes = Object.keys(GRAPH)
  const targets = nodes.flatMap((n) => Object.values(GRAPH[n]!))
  return {
    // 至少一个节点有两条出路
    branch: nodes.some((n) => Object.keys(GRAPH[n]!).length >= 2),
    // 至少一条边指回自己
    retry: nodes.some((n) => Object.values(GRAPH[n]!).includes(n)),
    // 至少一条边叫 `escalate` —— 交回上层是这个动作的全部含义
    escalation: nodes.some((n) => 'escalate' in GRAPH[n]!),
    // 至少一个目标不是任何节点的起点 —— 走到那里就停
    'terminal-state': targets.some((t) => !(t in GRAPH)),
  }
}

const REPORT = fileURLToPath(new URL('../examples/external-host.capabilities.json', import.meta.url))
const REFERENCE_CONTRACT = fileURLToPath(new URL('../DECISION.md', import.meta.url))
const CUSTOM_CONTRACT = fileURLToPath(new URL('../examples/custom-graph.DECISION.md', import.meta.url))

/** 两边都排个序再比 —— JSON 里键的顺序不是语义 */
function sameSet(a: readonly string[], b: readonly string[]): boolean {
  return [...a].sort().join('\u0000') === [...b].sort().join('\u0000')
}

/**
 * 报告与代码的每一处不一致。
 *
 * @returns 每条一句话；空数组 = 对得上
 */
export function reportDrift(report: CapabilityReport): string[] {
  const out: string[] = []

  if (report.positions === undefined) {
    out.push('报告缺少 positions —— 没有它，位置/动作那层核对等于没做')
    return out
  }

  for (const [name, actions] of Object.entries(CAPABILITIES.positions)) {
    const declared = report.positions[name]
    if (!declared) {
      out.push(`报告没写位置 '${name}'（代码里有，动作：${actions.join(' / ')}）`)
      continue
    }
    if (!sameSet(declared, actions)) {
      out.push(`位置 '${name}' 的动作对不上：报告 [${[...declared].sort().join(', ')}] · 代码 [${[...actions].sort().join(', ')}]`)
    }
  }
  for (const name of Object.keys(report.positions)) {
    if (!(name in CAPABILITIES.positions)) out.push(`报告写了位置 '${name}'，而代码里没有 —— 报告在描述一个不存在的宿主`)
  }

  if (!sameSet(report.projections, CAPABILITIES.projections)) {
    out.push(`投影对不上：报告 ${report.projections.length} 个 · 代码 ${CAPABILITIES.projections.length} 个`)
  }
  if (!sameSet(report.dynamicProviders, CAPABILITIES.dynamicProviders)) {
    out.push(`动态候选提供者对不上：报告 [${report.dynamicProviders.join(', ')}] · 代码 [${CAPABILITIES.dynamicProviders.join(', ')}]`)
  }

  const nodes = Object.keys(GRAPH)
  if (!sameSet(report.customGraphNodes, nodes)) {
    out.push(`自定义图节点对不上：报告 [${report.customGraphNodes.join(', ')}] · 代码 [${nodes.join(', ')}]`)
  }

  // 每个列出来的节点都要真的是图里的一条起点 —— 只在清单里存在的节点是空头支票。
  const referenced = new Set(Object.values(GRAPH).flatMap((edges) => Object.values(edges)))
  for (const node of report.customGraphNodes) {
    if (!(node in GRAPH)) out.push(`报告里的图节点 '${node}' 不是任何一条边的起点 —— 它在图里没有位置`)
  }
  for (const node of referenced) {
    if (!report.customGraphNodes.includes(node) && !(report.terminalStates ?? []).includes(node)) {
      out.push(`图里的 '${node}' 被某条边指向，却既不在节点清单里、也不在终止态清单里`)
    }
  }

  // 终止态：走出去就回不来的那些目标。它们在报告里要单列，不能混进节点清单 ——
  // 混进去就等于声称有一个「起点」叫 done，而图里并没有。
  const terminal = [...referenced].filter((t) => !(t in GRAPH))
  if (!sameSet(report.terminalStates ?? [], terminal)) {
    out.push(`终止态对不上：报告 [${(report.terminalStates ?? []).join(', ')}] · 代码 [${terminal.join(', ')}]`)
  }

  // 声明出来的每一个图特征都要能在这张图里演示出来
  const features = demonstratedFeatures()
  for (const feature of report.graphFeatures) {
    if (!(feature in features)) {
      out.push(`报告声明了本脚本认不出的图特征 '${feature}' —— 加一个机械定义，或者把它删掉`)
    } else if (!features[feature]) {
      out.push(`报告声明了图特征 '${feature}'，而这张图里演示不出来`)
    }
  }

  // 自定义位置（`host:` 命名空间）也要对得上：只有声明了它们的宿主才认得
  const declaredHost = report.hostPositions ?? {}
  for (const [name, actions] of Object.entries(HOST_POSITIONS)) {
    const declared = declaredHost[name]
    if (!declared) {
      out.push(`报告没写自定义位置 '${name}'（代码里有，动作：${actions.join(' / ')}）`)
      continue
    }
    if (!sameSet(declared, actions)) {
      out.push(`自定义位置 '${name}' 的动作对不上：报告 [${[...declared].sort().join(', ')}] · 代码 [${[...actions].sort().join(', ')}]`)
    }
  }
  for (const name of Object.keys(declaredHost)) {
    if (!(name in HOST_POSITIONS)) out.push(`报告写了自定义位置 '${name}'，而代码里没有`)
  }

  if (report.level !== 2) {
    out.push(`报告的 level 是 ${report.level} —— 这个 fixture 跑的是「局部判定 + 宿主自己的多节点图」，应当报 2`)
  }

  // 报告声称自己实现的是哪一版语义。它必须**正好**是当前这一版 ——
  // 报一个不存在的版本，和没报是一样的：消费方无法据此判断能不能读。
  if (report.contractSchema !== CURRENT_SCHEMA) {
    out.push(`报告的 contractSchema 是 '${report.contractSchema}' —— 当前版本是 '${CURRENT_SCHEMA}'`)
  }

  if (report.conformance?.dispatchAfterCapabilityCheck !== true) {
    out.push('报告没有声明「先核对能力再执行动作」—— 那正是 adapterProblems 存在的理由')
  }

  return out
}

/**
 * 把报告里那部分能力**当作宿主的声明**拿去核对两份契约。
 *
 * @returns 每条一句话；空数组 = 声明出来的能力真的够用
 */
export function contractProblems(report: CapabilityReport): string[] {
  const out: string[] = []

  const capsFromReport: AdapterCapabilities = {
    // 报告不列 state 格名（它是内部细节），所以核对参考契约时借用**代码**那份；
    // 这一项由 `runDemo()` 那一侧在真跑时覆盖，这里只是把报告的那几项放进来。
    stateCells: CAPABILITIES.stateCells,
    projections: report.projections,
    dynamicProviders: report.dynamicProviders,
    positions: report.positions,
    actions: CAPABILITIES.actions,
  }

  const reference = parseDecisionDoc(readFileSync(REFERENCE_CONTRACT, 'utf8'))
  for (const problem of schemaProblems(reference)) out.push(`参考契约 ${problem}`)
  for (const problem of adapterProblems(reference, capsFromReport)) {
    out.push(`参考契约 ${problem.block}: ${problem.message}`)
  }

  const custom = parseDecisionDoc(readFileSync(CUSTOM_CONTRACT, 'utf8'))
  for (const problem of schemaProblems(custom)) out.push(`自定义契约 ${problem}`)
  const customCaps: AdapterCapabilities = { ...capsFromReport, positions: HOST_POSITIONS }
  for (const problem of adapterProblems(custom, customCaps)) {
    out.push(`自定义契约 ${problem.block}: ${problem.message}`)
  }

  return out
}

/** 读并粗略校验那份 JSON 的形状（手写文件，所以边界上要放宽也要查） */
export function loadReport(file = REPORT): CapabilityReport {
  const raw = JSON.parse(readFileSync(file, 'utf8')) as Partial<CapabilityReport>
  const missing = (['positions', 'projections', 'dynamicProviders', 'customGraphNodes', 'level'] as const).filter(
    (k) => raw[k] === undefined,
  )
  if (missing.length > 0) throw new Error(`${file} 缺少字段：${missing.join(' / ')}`)
  return raw as CapabilityReport
}

function main(): number {
  let report: CapabilityReport
  try {
    report = loadReport()
  } catch (err) {
    console.error(`✗ ${(err as Error).message}`)
    return 1
  }

  const drift = reportDrift(report)
  const contracts = contractProblems(report)

  console.log('\nJevLoop · adapter capability report')
  console.log(`  report    : ${resolve(REPORT)}`)
  console.log(`  adapter   : ${report.adapter}`)
  console.log(`  schema    : ${report.contractSchema}`)
  console.log(`  level     : ${report.level}`)
  console.log(`  positions : ${Object.keys(report.positions).length} · actions: ${CAPABILITIES.actions.length} · projections: ${report.projections.length}`)
  console.log(`  graph     : ${report.customGraphNodes.length} nodes · ${report.graphFeatures.join(', ')}`)

  if (drift.length === 0) {
    console.log('\n  ✓ 报告与代码一致（位置 / 动作 / 投影 / 动态提供者 / 图节点）')
  } else {
    console.log(`\n  ✗ 报告与代码不一致（${drift.length} 处）—— 报告在描述一个不存在的宿主：`)
    for (const m of drift) console.log(`      ${m}`)
  }

  if (contracts.length === 0) {
    console.log('  ✓ 声明出来的能力足以消费两份契约（参考契约 + 自定义图 fixture）')
  } else {
    console.log(`\n  ✗ 声明出来的能力不够用（${contracts.length} 处）：`)
    for (const m of contracts) console.log(`      ${m}`)
  }

  const clean = drift.length === 0 && contracts.length === 0
  console.log(clean ? '\n  ✓ capability report 可信\n' : '\n  ✗ capability report 不可信\n')
  return clean ? 0 : 1
}

// 直接跑时进 main；被 import（单测）时不跑。
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main())
}
