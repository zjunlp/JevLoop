/**
 * JevLoop · L0 词汇 —— **两个判定能不能共用一帧**
 *
 * 零 import、零 IO 的纯函数，所以放最底下：`frame.ts`(L3) 与 `decide.ts`(L2)
 * 都要用它，而 §11 不许 L2 import L3 —— 同 `frame-digest.ts` / `http-error.ts`
 * 的先例：**共用的东西必须下沉，不能就地复制一份**。
 *
 * ══════════════════════════════════════════════════════════════
 *  **它把 §8.18 的散文变成机器检查**
 * ══════════════════════════════════════════════════════════════
 *
 * `AGENTS.md` §8.18 记着「`stepOk` 与 `isDone` 两份帧**合不成一份**」，理由
 * （`stepOk` 故意没有 `task`）是**人推出来的**。那个理由是对的，但**合并不拦
 * 这件事**：谁把两个规格并到一起，它会静默成功，然后违反其中一个的声明 ——
 * 而声明存在的全部意义就是不让这种事发生（§8.14）。
 *
 * 现在「看了什么」（`fields[].from`）和「故意不看什么」（`excluded`）都是
 * 可读的，于是规则只剩一条：
 *
 *     **一格的「故意不看」和另一格的「要看」，不能共存于同一份帧。**
 *
 * ★ 有意思的是这条规则**自己就推出了 §8.18 记的那两处**，不用人去记：
 *
 *     stepOk     排除 task     vs  isDone      读 task      → 冲突
 *     pickInput  排除 history  vs  gradeRisk   读 history   → 冲突
 *
 * ⇒ 合并的边界从此**从声明算出来**，不靠人记（同 §11 那条层规则的做法）。
 *
 * @module JevLoop/frame-merge
 */

/** 判定这一件事只需要帧制品的这三样 —— 完整形状在 `frame.ts`(L3) */
export interface MergeableFrame {
  /** 判定节点 id，报冲突时要说是谁和谁 */
  node: string
  /** 每一栏读的是哪一格 */
  fields: readonly { key: string; from: string }[]
  /** **故意不看**的格，每条带理由 */
  excluded: readonly (readonly [string, string])[]
}

export interface MergeConflict {
  /** 被一格排除、又被另一格读的那个 ctx 栏 */
  field: string
  /** 是谁声明「故意不看它」 */
  excludedBy: string
  /** 又是谁要读它 */
  readBy: string
  /** `excludedBy` 给出的**理由** —— 冲突时要把它原样报出来给人看 */
  reason: string
}

/**
 * 查一批帧能不能共用一份。
 *
 * `ok: false` 时 `conflicts` 里每一条都说清**是哪一格、谁排除的、谁要读、
 * 以及当初排除它的理由** —— 报错不写理由，读的人就只能去翻代码，
 * 而那正是这份声明要消灭的东西。
 */
export function mergeConflicts(frames: readonly MergeableFrame[]): {
  ok: boolean
  conflicts: MergeConflict[]
} {
  const conflicts: MergeConflict[] = []
  for (const f of frames) {
    const reads = new Set(f.fields.map((x) => x.from))
    for (const [cell, why] of f.excluded) {
      // 自己声明又自己读：那是 `frameSpecViolations` 的活，这里不重复报
      if (reads.has(cell)) continue
      for (const other of frames) {
        if (other === f) continue
        if (!other.fields.some((x) => x.from === cell)) continue
        conflicts.push({ field: cell, excludedBy: f.node, readBy: other.node, reason: why })
      }
    }
  }
  return { ok: conflicts.length === 0, conflicts }
}
