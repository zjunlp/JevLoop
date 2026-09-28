/**
 * External host adapter conformance fixtures.
 *
 * These tests prove that capability omissions fail before a host can dispatch
 * a decision action. They intentionally use the real DECISION.md document.
 *
 * @module JevLoop/adapter.test
 */

import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import { parseDecisionDoc } from '../src/decisiondoc.ts'
import { adapterProblems, type AdapterCapabilities } from '../src/adapter.ts'

const doc = parseDecisionDoc(readFileSync(new URL('../DECISION.md', import.meta.url), 'utf8'))

const base: AdapterCapabilities = {
  stateCells: ['task', 'earlier', 'already_done', 'files_known', 'already_read', 'last', 'tool', 'input', 'output', 'target', 'evidence', 'answer'],
  projections: ['earlierMaybe', 'describeDone', 'filesMaybe', 'readMaybe', 'lastOrNone', 'toolOrEmpty', 'lastInput', 'toolOrUnknown', 'localToolRisk', 'resultMaybe', 'readCount', 'recentSteps', 'draftMaybe', 'writeEvidence'],
  dynamicProviders: ['toolsFor', 'fileOptions'],
  dynamicProviderReads: {
    toolsFor: ['history', 'files', 'readFiles', 'canWrite', 'canDelete'],
    fileOptions: ['files', 'readFiles'],
  },
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

function problems(change: (caps: AdapterCapabilities) => AdapterCapabilities): string[] {
  return adapterProblems(doc, change(base)).map((problem) => problem.message)
}

test('valid host capabilities consume the complete reference contract', () => {
  assert.deepEqual(adapterProblems(doc, base), [])
})

test('unknown projection fails before dispatch', () => {
  const out = problems((caps) => ({ ...caps, projections: caps.projections.filter((name) => name !== 'resultMaybe') }))
  assert.ok(out.some((message) => message.includes('projection \'resultMaybe\'')))
})

test('missing state cell fails before dispatch', () => {
  const out = problems((caps) => ({ ...caps, stateCells: caps.stateCells.filter((name) => name !== 'task') }))
  assert.ok(out.some((message) => message.includes('state cell \'task\'')))
})

test('missing dynamic provider fails before dispatch', () => {
  const out = problems((caps) => ({ ...caps, dynamicProviders: [] }))
  assert.ok(out.some((message) => message.includes('dynamic provider \'toolsFor\'')))
})

test('unhandled action fails before dispatch', () => {
  const out = problems((caps) => ({ ...caps, actions: caps.actions.filter((name) => name !== 'finish') }))
  assert.ok(out.some((message) => message.includes('action \'finish\'')))
})

test('position/action mismatch fails before dispatch', () => {
  const out = problems((caps) => ({ ...caps, positions: { ...caps.positions, 'after-tool': ['continue'] } }))
  assert.ok(out.some((message) => message.includes('位置 \'after-tool\' 不处理 action \'finish\'')))
})

test('missing position fails before dispatch', () => {
  const { 'after-generate': _removed, ...positions } = base.positions
  const out = problems((caps) => ({ ...caps, positions }))
  assert.ok(out.some((message) => message.includes('位置 \'after-generate\'')))
})

const customDoc = parseDecisionDoc(readFileSync(new URL('../examples/custom-graph.DECISION.md', import.meta.url), 'utf8'))

test('host namespace permits custom nodes when the adapter registers their positions', () => {
  assert.deepEqual(customDoc.problems, [])
  const customCaps: AdapterCapabilities = {
    stateCells: ['task', 'output', 'evidence', 'answer'],
    projections: [],
    dynamicProviders: [],
    positions: {
      'host:issue-triage': ['call'],
      'host:test-failure': ['call'],
      'host:review': ['ask_human', 'finish'],
    },
    actions: ['call', 'escalate', 'ask_human', 'finish'],
  }
  assert.deepEqual(adapterProblems(customDoc, customCaps), [])
})

test('unknown host namespace fails when the adapter does not register it', () => {
  const out = adapterProblems(customDoc, { ...base, positions: {} })
  assert.ok(out.some((problem) => problem.message.includes('host 没有注册位置 \'host:issue-triage\'')))
})
