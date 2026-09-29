/**
 * JevLoop · 把一份会话日志导出成指标（TODO §11）
 *
 *   npm run metrics -- <会话日志.jsonl> [--format prom|json]
 *
 * 离线、不需要服务在跑 —— 数据就在日志里（每一轮 `run:end` 带着那一轮的账目）。
 * 格式与取舍见 `src/metrics.ts`。
 *
 * @module JevLoop/metrics-cli
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { parseSessionLine } from '../src/session-log.ts'
import { metricsFrom, renderMetricsJson, renderPrometheus } from '../src/metrics.ts'

function usage(): void {
  console.error('用法：npm run metrics -- <会话日志.jsonl> [--format prom|json]')
}

function main(argv: string[]): number {
  const fmtAt = argv.indexOf('--format')
  const format = fmtAt === -1 ? 'prom' : (argv[fmtAt + 1] ?? 'prom')
  const file = argv.find((a, i) => !a.startsWith('--') && (fmtAt === -1 || i !== fmtAt + 1))
  if (!file || (format !== 'prom' && format !== 'json')) {
    usage()
    return 1
  }

  // ★ 事件藏在包装行里（`{kind:'event', run, at, e}`）；认不出的行**计数**，不静默丢
  const events: unknown[] = []
  let skipped = 0
  for (const raw of readFileSync(file, 'utf8').split('\n')) {
    if (!raw.trim()) continue
    const line = parseSessionLine(raw)
    if (!line) {
      skipped++
      continue
    }
    if (line.kind === 'event') events.push(line.e)
  }

  const snap = metricsFrom(events)
  process.stdout.write(format === 'json' ? `${renderMetricsJson(snap)}\n` : renderPrometheus(snap))
  if (skipped > 0) console.error(`跳过 ${skipped} 行（坏行或认不出的形状）`)
  return 0
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)))
}
