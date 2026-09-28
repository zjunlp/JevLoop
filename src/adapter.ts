/**
 * JevLoop · external Decision Contract adapter checks
 *
 * A parsed contract is not an executable Agent loop. This module checks whether
 * a host has declared the capabilities needed to consume each block, without
 * importing JevLoop's AgentCtx, tools, or control-flow implementation.
 *
 * @module JevLoop/adapter
 */

import type { DecisionDoc, DocBlock } from './decisiondoc.ts'

/** Capabilities supplied by a host runtime. */
export interface AdapterCapabilities {
  /** Raw state-cell names accepted by unprojected frame fields. */
  stateCells: readonly string[]
  /** Projection names understood by the host. */
  projections: readonly string[]
  /** Dynamic candidate provider names understood by the host. */
  dynamicProviders: readonly string[]
  /** Position name → actions the host dispatches at that position. */
  positions: Readonly<Record<string, readonly string[]>>
  /** Actions for which the host has a handler. */
  actions: readonly string[]
}

/** A source-located adapter capability problem. */
export interface AdapterProblem {
  block: string
  line: number
  message: string
}

/** Extract the structured position token from the current `when:` spelling. */
export function positionOf(block: DocBlock): string {
  return block.when.trim().split(/\s|（|\(/)[0] ?? ''
}

/** Extract the provider name from `dynamic: provider(ctx) —— explanation`. */
export function dynamicProviderOf(block: DocBlock): string | undefined {
  const first = block.dynamic.trim().split(/\s|（|\(/)[0] ?? ''
  return first || undefined
}

/**
 * Check whether a host can consume every declaration in a parsed document.
 *
 * The check is deliberately capability-based: a host may support any number of
 * block ids, but it must explicitly register every field, provider, position,
 * and action that the document uses. An empty result means the adapter is ready
 * for local block execution; it does not claim that the host graph is correct.
 */
export function adapterProblems(doc: DecisionDoc, caps: AdapterCapabilities): AdapterProblem[] {
  const stateCells = new Set(caps.stateCells)
  const projections = new Set(caps.projections)
  const dynamicProviders = new Set(caps.dynamicProviders)
  const actions = new Set(caps.actions)
  const out: AdapterProblem[] = []

  for (const block of doc.blocks) {
    const position = positionOf(block)
    const positionActions = caps.positions[position]
    if (!positionActions) {
      out.push({ block: block.id, line: block.line, message: `host 没有注册位置 '${position}'` })
    }

    const supportedAtPosition = new Set(positionActions ?? [])
    for (const rule of block.policy) {
      if (!actions.has(rule.action)) {
        out.push({ block: block.id, line: block.line, message: `host 没有处理 action '${rule.action}'` })
      }
      if (positionActions && !supportedAtPosition.has(rule.action) && rule.action !== 'escalate') {
        out.push({ block: block.id, line: block.line, message: `位置 '${position}' 不处理 action '${rule.action}'` })
      }
    }

    const provider = dynamicProviderOf(block)
    if (provider && !dynamicProviders.has(provider)) {
      out.push({ block: block.id, line: block.line, message: `host 没有注册 dynamic provider '${provider}'` })
    }

    for (const field of block.frame?.fields ?? []) {
      if (field.project) {
        if (!projections.has(field.project)) {
          out.push({ block: block.id, line: field.line, message: `host 没有注册 projection '${field.project}'` })
        }
      } else if (!stateCells.has(field.key)) {
        out.push({ block: block.id, line: field.line, message: `host 没有注册 state cell '${field.key}'` })
      }
    }
  }

  return out
}
