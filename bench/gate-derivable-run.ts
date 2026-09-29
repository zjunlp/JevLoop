/**
 * JevLoop · 「可导出性」报告
 *
 *   node --experimental-strip-types bench/gate-derivable-run.ts
 *
 * 逻辑在 `bench/gate-derivable.ts`（可被 import），这里只负责跑出来、印出来。
 * 结论与它**不能**支持的读法写在 `docs/MEASUREMENT-gate-equivalence.md`。
 *
 * @module JevLoop/gate-derivable-run
 */

import { readFileSync } from 'node:fs'
import {
  HAND_GATE_DILIGENT,
  SIGNALS,
  dependencyCoverage,
  measureCoverage,
  specOf,
  withBound,
  withExtraCell,
  type HandGate,
} from './gate-derivable.ts'
import { compileFrame } from '../src/frame.ts'
import type { AgentCtx } from '../src/frame.ts'

const MD = readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8')
const NODE = 'can_deliver'
/** 实验用的新增格 —— 名字必须是**已注册**的投影，见 `withExtraCell` 注释 */
const EXTRA = '+ files_known  200     filesMaybe  —— 实验用：模拟契约作者新增一栏'

function line(label: string, value: string): void {
  console.log(`  ${label.padEnd(34)} ${value}`)
}

async function main(): Promise<void> {
  // ═══════════════════════════════════════════════════════
  // D1 加一格声明 —— 检查会不会自动跟上
  // ═══════════════════════════════════════════════════════
  console.log('\n★ D1　在 `frame:` 里加一格，存在性检查跟不跟得上\n')
  const before = measureCoverage(MD, NODE)
  line('原样声明', before.declared.join(', '))
  line('  被 unfilled 盖住', `${before.presenceCovered.join(', ')}　（${before.presenceCovered.length}/${before.declared.length}）`)

  const grown = withExtraCell(MD, NODE, EXTRA)
  const after = measureCoverage(grown, NODE)
  line('加一格之后声明', after.declared.join(', '))
  line('  被 unfilled 盖住', `${after.presenceCovered.join(', ')}　（${after.presenceCovered.length}/${after.declared.length}）`)
  line('  ★ 检查代码改动', '0 行 —— 它是从声明算出来的')

  // ═══════════════════════════════════════════════════════
  // D2 改一个声明的界 —— 截断跟不跟着变
  // ═══════════════════════════════════════════════════════
  console.log('\n★ D2　改一个声明里的预算，截断跟不跟着变（只动 .md，不动代码）\n')
  const fat = (boundMd: string) => {
    const spec = specOf(boundMd, NODE)
    const frame = compileFrame(spec, {
      task: 't',
      cwd: '/w',
      draft: 'x'.repeat(4000),
      history: [{ step: 0, tool: 'read_file', input: 'a', result: 'r' }],
    } as unknown as AgentCtx)
    return { bound: spec.fields.find((f) => f.key === 'answer')?.chars, len: String(frame.state.answer).length }
  }
  const b900 = fat(MD)
  const b50 = fat(withBound(MD, 'answer', 900, 50))
  line('声明 900', `进帧后 ${b900.len} 字符（预算 ${b900.bound}）`)
  line('声明 50（只改 .md）', `进帧后 ${b50.len} 字符（预算 ${b50.bound}）`)
  line('  ★ 截断代码改动', '0 行 —— chars 与 listMax 都从这一个数来')

  // ═══════════════════════════════════════════════════════
  // D3 信号产出了，谁消费
  // ═══════════════════════════════════════════════════════
  console.log('\n★ D3　这些信号产出了，参考运行时里谁读它\n')
  for (const s of SIGNALS) {
    line(s.signal, `产出=${s.produced ? '是' : '否'}　运行时消费=${s.consumedByRuntime ? '是' : '★ 否'}`)
    line('', `↳ ${s.where}`)
  }
  console.log('  核法：`grep -rn "\\.unfilled\\|\\.absent\\|\\.truncated" src/` ——')
  console.log('  src/ 里唯一的命中在 frame.ts 的**注释**里，decide.ts / agent.ts 一次都没有。')

  // ═══════════════════════════════════════════════════════
  // ★ 依赖覆盖率 —— 公平口径下的差距
  // ═══════════════════════════════════════════════════════
  console.log('\n★ 依赖覆盖率　（口径：门读的格子里，几格被漂移检查盖住）\n')
  const d0 = dependencyCoverage(HAND_GATE_DILIGENT, before)
  line('勤快的手写门（原依赖集）', `${d0.ratio}　（缺：${d0.uncovered.join(', ') || '无'}）`)

  // 依赖集变了：这个门现在也要读新加的那一格（契约那边是加一行声明）
  const grownGate: HandGate = {
    id: 'hand-diligent-after-change',
    dependsOn: [...HAND_GATE_DILIGENT.dependsOn, 'files_known'],
    guards: [...HAND_GATE_DILIGENT.guards], // ★ 代码还没改
  }
  const d1 = dependencyCoverage(grownGate, after)
  line('同一个门，依赖集变大、代码没改', `${d1.ratio}　（缺：${d1.uncovered.join(', ') || '无'}）`)
  const fixed: HandGate = { ...grownGate, guards: [...grownGate.guards, 'files_known'] }
  line('补上一行守卫之后', `${dependencyCoverage(fixed, after).ratio}　（缺：${dependencyCoverage(fixed, after).uncovered.join(', ') || '无'}）`)

  console.log('\n  ★ 契约那一侧：加一格声明，检查自动 3/3 → 4/4，**零行检查代码**。')
  console.log('  ★ 手写门那一侧：依赖集一变就漏一格，**补一行守卫即可恢复 100%**。')
  console.log('  ⇒ 差的不是能力，是**依赖集变化时有多少处要跟着改**（0 处 vs 1 处），')
  console.log('    以及那一处**能不能被忘掉**。勤快的作者两边都是 100%。')
  console.log('')
}

await main()
