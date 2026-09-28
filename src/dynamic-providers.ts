/**
 * JevLoop · **动态候选提供者的能力声明** —— TODO §12 第三条
 *
 * ══════════════════════════════════════════════════════════════
 *  `dynamic: toolsFor(ctx) → candidates` 说了收 ctx，没说**读哪几格**
 * ══════════════════════════════════════════════════════════════
 *
 * 那句话对宿主是不够的。候选是**从状态算出来的**，所以「算它的时候看了什么」
 * 决定了三件事：
 *
 *   1. 宿主得知道哪些格必须备好 —— 少喂一格，候选就会**静默地**少一类；
 *   2. 读帧的人得知道候选由什么决定（「为什么 read_file 还在候选里」）；
 *   3. 宿主能拿它去和**自己的**实现核对 —— 这正是这一层存在的理由。
 *
 * 所以现在文件里要写出来：
 *
 *     dynamic: toolsFor(ctx: history, files, readFiles, canWrite, canDelete) → candidates —— …
 *
 * ── 为什么这份声明值得信 ──────────────────────────────────────
 *
 * 光写一份表是没用的（那只是又一份会过期的散文）。所以
 * `tests/dynamic-providers.test.ts` 用**行为**核对它，而不是对着表再抄一遍：
 *
 *     声明的每一格：改它 → 候选**必须**变（说明实现真的读了它）
 *     没声明的格：  改它 → 候选**必须不变**（说明实现没有偷偷读别的）
 *
 * 第二条才是「声明你的输入」这句话的真正含义 —— 一个读了 `lastResult` 而没
 * 声明的提供者，会让宿主在缺那一格时拿到一份说不清来路的候选。
 *
 * @module JevLoop/dynamic-providers
 */

/** 一个动态候选提供者：读哪几格、产出什么形状 */
export interface DynamicProviderSpec {
  /**
   * 它读 `AgentCtx` 的哪几格。**这就是「候选由什么决定」的答案。**
   *
   * ⚠️ 名字是**契约层的格名**（`files` / `history` / …），不是某个宿主内部的
   * 字段名 —— 宿主拿它和自己的状态对上，对不上就是接不进来。
   */
  reads: readonly string[]
  /** 产出形状。取值来自 `DYNAMIC_OUTPUTS`（`decision-syntax.ts`），由测试核对一致 */
  output: string
  /** 一句话：这个提供者算什么。给外部实现者读的 */
  about: string
}

export const DYNAMIC_PROVIDERS = {
  /** 「下一步能用哪些工具」—— 做过的动作消失、未读文件还在、能力门决定写与删进不进来 */
  toolsFor: {
    reads: ['history', 'files', 'readFiles', 'canWrite', 'canDelete'],
    output: 'candidates',
    about:
      '从状态算出「这一步还能调用哪些工具」：做过的动作从候选里消失，还有没读过的文件时 read_file 留在候选里，' +
      '`canWrite` / `canDelete` 决定 write_file 与 delete_file 进不进来。**每步重建**',
  },
  /**
   * 「读哪个文件」—— `pickInput` 的候选，只服务 read_file。
   *
   * ★ 名字是 `fileOptions` 而**不是**它内部用的 `unreadFiles`：文件里点名的是
   *   「谁造出候选」，而 `unreadFiles` 只返回一个名字数组，判据是 `fileOptions`
   *   加上去的。声明一个帮手会让 `→ candidates` 这句话在两个提供者上**含义不同**
   *   （一个是判据表、一个是名字数组）—— 那种含糊正是这一层要消灭的东西。
   */
  fileOptions: {
    reads: ['files', 'readFiles'],
    output: 'candidates',
    about:
      '已知文件里**还没读过**的那些，每个候选带一句判据（「任务还需要它的内容，而它还没被读过」）—— ' +
      '`read_file` 挑的就是这个闭集。它只读这两格，所以候选不会因为别的什么原因多出来',
  },
} as const satisfies Record<string, DynamicProviderSpec>

/** 提供者名的**封闭**联合。来自上面那张表，不是 `string` */
export type DynamicProviderName = keyof typeof DYNAMIC_PROVIDERS

/** 全部提供者名（运行时）。用于报错信息与清单核对 */
export const DYNAMIC_PROVIDER_NAMES = Object.keys(DYNAMIC_PROVIDERS) as DynamicProviderName[]

/**
 * 这个名字是不是注册表里的提供者 —— `DECISION.md` 是**手写文件**，所以它给的
 * 名字是不可信输入，查表前要过这一道（同 `act.ts` 的 `isToolName`）。
 *
 * ★ 走 `Object.hasOwn` 而不是 `in`：后者会被 `toString` / `constructor` 这类
 *   **继承来的键**骗过去。
 */
export function isDynamicProviderName(v: string): v is DynamicProviderName {
  return Object.hasOwn(DYNAMIC_PROVIDERS, v)
}
