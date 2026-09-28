/**
 * A minimal external host for the portable `DECISION.md` contract.
 *
 * This host deliberately does not import `agent.ts`, `decisions.ts`, `AgentCtx`,
 * or JevLoop's local tools. It supplies its own state-cell and projection
 * registry, asks a deterministic mock provider, evaluates the compiled policy,
 * and dispatches the returned actions through host-owned handlers.
 *
 * ── Why the pieces below are exported ─────────────────────────
 *
 * `CAPABILITIES` and `GRAPH` are **exported facts**, not prose about this file.
 * `scripts/adapter-report.ts` imports them and checks
 * `examples/external-host.capabilities.json` against them, so the published
 * capability report cannot drift from the code it describes. Before that, the
 * report was a hand-written JSON file that **nothing read** — a declaration with
 * no consumer, which is the failure mode this repository keeps recording.
 *
 * @module JevLoop/external-host
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
/*
  ★ 全部从**可移植入口**拿 —— 这是外部宿主该用的那一个。
    它不含参考运行时，所以这个文件里 `AgentCtx`、`decisions.ts`、`agent.ts`
    一次都不出现，而这不是靠自律：`src/contract.ts` 登记在 L3，
    `decisions.ts`(L4) / `agent.ts`(L5) / `frame.ts`(L3) 都 import 不进来。
*/
import {
  adapterProblems,
  compilePolicy,
  compileQuestions,
  parseDecisionDoc,
  resolvePolicy,
  type AdapterCapabilities,
  type Answer,
  type AnswerSet,
  type DocBlock,
  type DocFrameField,
  type Question,
  type QuestionSet,
} from '../src/contract.ts'

interface HostState {
  task: string
  earlier: string
  already_done: string
  files_known: string[]
  already_read: string[]
  last: string
  tool: string
  input: string
  output: string
  target: string
  evidence: string
  answer: string
}

type Projection = (state: HostState) => unknown

const PROJECTIONS: Record<string, Projection> = {
  earlierMaybe: (state) => state.earlier,
  describeDone: (state) => state.already_done,
  filesMaybe: (state) => state.files_known,
  readMaybe: (state) => state.already_read,
  lastOrNone: (state) => state.last,
  toolOrEmpty: (state) => state.tool,
  lastInput: (state) => state.input,
  toolOrUnknown: (state) => state.tool || 'unknown',
  localToolRisk: () => 'host-defined',
  resultMaybe: (state) => state.output,
  readCount: (state) => state.already_read.length,
  recentSteps: (state) => state.output,
  draftMaybe: (state) => state.answer,
  writeEvidence: (state) => state.evidence,
}

const BASE_STATE: HostState = {
  task: 'Read the requested file and report what was found.',
  earlier: '',
  already_done: 'list_dir',
  files_known: ['notes.ts'],
  already_read: [],
  last: 'directory listed',
  tool: 'read_file',
  input: 'notes.ts',
  output: 'notes.ts exists and contains the requested information.',
  target: 'notes.ts',
  evidence: 'notes.ts exists and contains the requested information.',
  answer: 'The requested file was read.',
}

function frameFor(block: DocBlock, state: HostState): Record<string, unknown> {
  const frame: Record<string, unknown> = {}
  for (const field of block.frame?.fields ?? []) frame[field.key] = project(field, state)
  return frame
}

function project(field: DocFrameField, state: HostState): unknown {
  const value = field.project ? PROJECTIONS[field.project]?.(state) : state[field.key as keyof HostState]
  if (value === undefined) throw new Error(`external host cannot map frame field '${field.key}'`)
  if (typeof value === 'string') return value.slice(0, field.bound)
  if (Array.isArray(value)) return value.slice(0, field.bound)
  return value
}

function mockAnswer(question: Question, blockId: string): Answer {
  if (question.type === 'noul') return { type: 'noul', noul: blockId === 'needs_tool' ? 0.9 : 0.9 }
  if (question.type === 'score') {
    const score = question.criteria.length > 1 ? 0 : 0
    return {
      type: 'score',
      score,
      legend: Object.fromEntries(question.criteria.map((text, i) => [String(i), text])),
      probabilities: Object.fromEntries(question.criteria.map((_, i) => [String(i), i === score ? 0.9 : 0.1 / Math.max(1, question.criteria.length - 1)])),
      confidence: 0.9,
    }
  }
  const options = Object.keys(question.criteria)
  const choice = options[0] ?? ''
  return {
    type: 'choice',
    choice,
    probabilities: Object.fromEntries(options.map((name) => [name, name === choice ? 0.9 : 0.1 / Math.max(1, options.length - 1)])),
    confidence: 0.9,
  }
}

function mockAnswers(questions: QuestionSet, blockId: string): AnswerSet {
  return Object.fromEntries(Object.entries(questions).map(([id, question]) => [id, mockAnswer(question, blockId)]))
}

export const CAPABILITIES: AdapterCapabilities = {
  stateCells: ['task', 'earlier', 'already_done', 'files_known', 'already_read', 'last', 'tool', 'input', 'output', 'target', 'evidence', 'answer'],
  projections: Object.keys(PROJECTIONS),
  dynamicProviders: ['toolsFor', 'unreadFiles'],
  positions: {
    'step-start': ['use_tool', 'answer'],
    'tool-choice': ['call'],
    'input-choice': ['use'],
    'before-call': ['auto', 'auto_audit', 'ask_human'],
    'after-tool': ['continue', 'stop', 'finish', 'keep_going'],
    'after-generate': ['deliver', 'revise'],
  },
  actions: ['answer', 'ask_human', 'auto', 'auto_audit', 'call', 'continue', 'deliver', 'escalate', 'finish', 'keep_going', 'revise', 'stop', 'use', 'use_tool'],
}

/**
 * 这份 fixture 认得的自定义位置与它们的动作 —— 报告要和它对账。
 *
 * `examples/custom-graph.DECISION.md` 用的是 `host:` 命名空间，所以这些名字
 * 不在 `POSITIONS` 里：只有声明了它们的宿主才认得。
 */
export const HOST_POSITIONS: Readonly<Record<string, readonly string[]>> = {
  'host:issue-triage': ['call'],
  'host:test-failure': ['call'],
  'host:review': ['ask_human', 'finish'],
}

interface GraphState {
  node: string
  retries: number
  trace: string[]
}

export const GRAPH: Readonly<Record<string, Readonly<Record<string, string>>>> = {
  classify_issue: { inspect: 'inspect_repository', escalate: 'request_review' },
  inspect_repository: { found: 'plan_patch', missing: 'request_review', retry: 'inspect_repository' },
  plan_patch: { ready: 'run_tests', revise: 'plan_patch' },
  run_tests: { pass: 'prepare_candidate', fail: 'interpret_failure', retry: 'run_tests' },
  interpret_failure: { fixable: 'plan_patch', blocked: 'request_review' },
  prepare_candidate: { deliver: 'done', revise: 'plan_patch' },
  request_review: { approved: 'done', rejected: 'plan_patch' },
}

function nextNode(graph: GraphState, action: string): void {
  const next = GRAPH[graph.node]?.[action]
  if (!next) throw new Error(`graph has no transition from '${graph.node}' on '${action}'`)
  graph.trace.push(`${graph.node} --${action}--> ${next}`)
  graph.node = next
}

function runBlock(block: DocBlock, state: HostState): string {
  const questions = compileQuestions(block)
  if (!questions) return `  ${block.id}: rule block has no model questions`
  const policy = compilePolicy(block)
  if (!policy?.ok) throw new Error(`${block.id}: ${policy?.problems.join('; ') ?? 'missing policy'}`)
  const answers = mockAnswers(questions, block.id)
  const outcome = resolvePolicy(policy.rules, answers)
  const frame = frameFor(block, state)
  return `  ${block.id}: fields=${Object.keys(frame).length}, action=${outcome.action}, rule=${outcome.ruleIndex}`
}

/**
 * 跑一遍 fixture，**返回**每一行而不是自己打印。
 *
 * 返回而不是打印，是为了让 `scripts/adapter-report.ts` 能在不产生输出的情况下
 * 复用同一条路径 —— 报告要核对的是**同一份**能力，不是另抄一遍。
 */
export function runDemo(path = new URL('../DECISION.md', import.meta.url).pathname): string[] {
  const out: string[] = []
  const doc = parseDecisionDoc(readFileSync(path, 'utf8'))
  if (doc.problems.length > 0) throw new Error(doc.problems.map((problem) => `${problem.line}: ${problem.message}`).join('\n'))

  const capabilities = adapterProblems(doc, CAPABILITIES)
  if (capabilities.length > 0) throw new Error(capabilities.map((problem) => `${problem.block}:${problem.line} ${problem.message}`).join('\n'))

  const state = { ...BASE_STATE }
  out.push('external host: parsed DECISION.md without JevLoop agent loop')
  for (const id of ['needs_tool', 'pick_tool', 'step_ok', 'is_done']) {
    const block = doc.blocks.find((candidate) => candidate.id === id)
    if (!block) throw new Error(`missing block '${id}'`)
    out.push(runBlock(block, state))
  }

  const graph = { node: 'classify_issue', retries: 0, trace: [] } satisfies GraphState
  for (const action of ['inspect', 'retry', 'found', 'ready', 'fail', 'fixable', 'ready', 'pass', 'deliver']) {
    if (action === 'retry') graph.retries += 1
    nextNode(graph, action)
  }
  out.push(`external host: custom graph reached ${graph.node} after ${graph.retries} retry`)
  out.push(`external host: graph trace ${graph.trace.join(' | ')}`)

  const escalation = { node: 'classify_issue', retries: 0, trace: [] } satisfies GraphState
  for (const action of ['escalate', 'approved']) nextNode(escalation, action)
  out.push(`external host: escalation graph reached ${escalation.node}`)
  out.push('external host: adapter conformance probe passed')
  return out
}

// 直接跑时进 runDemo；被 import（报告脚本、单测）时不跑 —— 否则核对能力这件事
// 会顺带把整张演示表打出来。
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  for (const line of runDemo(process.argv[2])) console.log(line)
}
