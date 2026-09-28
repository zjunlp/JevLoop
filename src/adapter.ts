/**
 * JevLoop · external Decision Contract adapter checks
 *
 * A parsed contract is not an executable Agent loop. This module checks whether
 * a host has declared the capabilities needed to consume each block, without
 * importing JevLoop's AgentCtx, tools, or control-flow implementation.
 *
 * @module JevLoop/adapter
 */

import type { DecisionDoc } from './decisiondoc.ts'

/** Capabilities supplied by a host runtime. */
export interface AdapterCapabilities {
  /** Raw state-cell names accepted by unprojected frame fields. */
  stateCells: readonly string[]
  /** Projection names understood by the host. */
  projections: readonly string[]
  /** Dynamic candidate provider names understood by the host. */
  dynamicProviders: readonly string[]
  /**
   * 每个动态提供者**读契约层的哪几格** —— TODO §12 第三条。
   *
   * ★ 文件里现在写着 `toolsFor(ctx: history, files, …)`。那句话是**对实现的声明**，
   *   所以宿主必须给出自己那份，**两边要一模一样**：
   *
   *     少了 → 宿主没实现它声称会读的输入（候选会静默地少一类）
   *     多了 → 实现偷偷读了没声明的格（候选说不清来路）
   *
   *   可选字段，是因为**没写 `dynamic:` 的宿主不需要它**；一旦文件里出现了
   *   `dynamic:`，缺这一项就会被报出来（不是静默放行）。
   */
  dynamicProviderReads?: Readonly<Record<string, readonly string[]>>
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

/**
 * Check whether a host can consume every declaration in a parsed document.
 *
 * The check is deliberately capability-based: a host may support any number of
 * block ids, but it must explicitly register every field, provider, position,
 * and action that the document uses. An empty result means the adapter is ready
 * for local block execution; it does not claim that the host graph is correct.
 *
 * ★ `position` 和 `dynamic.provider` 是**解析期就拆好的字段**，这里不再拆字符串。
 *   以前这里有两个拆字符串的帮手（`positionOf` / `dynamicProviderOf`），
 *   而界面和测试各自又拆了一遍 —— 同一个格式几处拆法就会分叉，所以语法收回
 *   `decision-shape.ts` 一次，这里只读字段。
 */
export function adapterProblems(doc: DecisionDoc, caps: AdapterCapabilities): AdapterProblem[] {
  const stateCells = new Set(caps.stateCells)
  const projections = new Set(caps.projections)
  const dynamicProviders = new Set(caps.dynamicProviders)
  const actions = new Set(caps.actions)
  const out: AdapterProblem[] = []

  for (const block of doc.blocks) {
    const position = block.position
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

    const provider = block.dynamic?.provider
    if (provider && !dynamicProviders.has(provider)) {
      out.push({ block: block.id, line: block.line, message: `host 没有注册 dynamic provider '${provider}'` })
    }
    /*
      `dynamic:` 声明的**输入格**要和宿主那份一模一样（TODO §12 第三条）。

      ★ 两个方向都要报，因为两边的病不一样：
          文件多写了 → 宿主没实现它声称会读的输入 ⇒ 候选静默地少一类
          宿主多读了 → 实现读了没声明的格 ⇒ 候选说不清来路
        只查一个方向会把另一半留成盲区。
    */
    if (provider && block.dynamic) {
      const declared = block.dynamic.reads
      const hostReads = caps.dynamicProviderReads?.[provider]
      if (!hostReads) {
        out.push({
          block: block.id,
          line: block.line,
          message: `host 没有声明 provider '${provider}' 读哪几格（文件里写的是 ${declared.join(', ')}）`,
        })
      } else {
        const missing = declared.filter((c) => !hostReads.includes(c))
        const extra = hostReads.filter((c) => !declared.includes(c))
        if (missing.length) {
          out.push({
            block: block.id,
            line: block.line,
            message: `provider '${provider}' 声明读 [${missing.join(', ')}]，而宿主那份没有 —— 少了它候选会静默地少一类`,
          })
        }
        if (extra.length) {
          out.push({
            block: block.id,
            line: block.line,
            message: `宿主那份说 provider '${provider}' 还读 [${extra.join(', ')}]，而文件里没声明 —— 候选会因为没写出来的格而变`,
          })
        }
      }
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
