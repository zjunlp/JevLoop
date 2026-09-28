/**
 * JevLoop · **帧投影的能力声明** —— TODO §12 第二条
 *
 * ══════════════════════════════════════════════════════════════
 *  外部宿主必须实现这 14 个名字，而它们的含义此前只存在于我们的实现里
 * ══════════════════════════════════════════════════════════════
 *
 * `DECISION.md` 的 `frame:` 行可以点名一个投影（`+ task 400 earlierMaybe`）。
 * 文件写不出函数 —— 所以「那个名字到底做什么」只能由宿主提供。而在这次声明
 * 之前，宿主能拿到的只有**名字**：他得读我们的 `decisions.ts` 才知道
 * `lastOrNone` 与 `resultMaybe` 的区别（一个缺省时发「（还没有做过任何动作）」，
 * 另一个发空串），而那两个区别**是判据的一部分**。
 *
 * ── 这一层声明什么、不声明什么 ────────────────────────────────
 *
 * 声明：**名字、读哪一格、返回什么形状、以及它对缺省值的承诺**。
 * 不声明：实现。函数住在 `decisions.ts`（L4），因为投影体要用到 `AgentCtx`
 * 和工具注册表 —— 那些不属于可移植的词汇层。
 *
 * ★ **名字与 `from` 的唯一出处是这里。** `decisions.ts` 只写函数体，键名由
 *   `Record<ProjectionName, …>` 强制一一对应：
 *
 *     声明里加了名字而没写实现   → 编译不过
 *     写了实现而声明里没有       → 编译不过
 *
 *   于是「声明和实现对不上」这件事在这一层是不可能的，而不是靠人记得。
 *
 * ⚠️ `from` 在这里是 `string`，不是 `keyof AgentCtx`：那个类型住在 `frame.ts`
 *    （L3），而这一层必须是 L0（否则 `contract.ts` 这个可移植入口 import 不到它，
 *    见 `src/contract.ts` 的层号说明）。代价是 `decisions.ts` 里需要一次类型
 *    断言 —— 而 `tests/frame-projections.test.ts` 会断言每一个 `from` 都真的是
 *    `AgentCtx` 的格名，所以那次断言是被核对的，不是空头支票。
 *
 * @module JevLoop/frame-projections
 */

/** 投影返回的形状。`chars` 界只管字符串、`listMax` 只管列表，所以这个字段是**逐栏预算怎么落**的依据 */
export type ProjectionReturns = 'string' | 'list' | 'count'

export interface ProjectionSpec {
  /**
   * 读 `AgentCtx` 的哪一格。
   *
   * 这是「这个判定看了什么」的**唯一出处** —— `frameSpecFromBlock` 用它填
   * `FrameField.from`，而 `frameSpecViolations` 靠 `from` 检查「每一格要么被读、
   * 要么带理由排除」。写错会当场被测试挡下（见文件头那句断言说明）。
   */
  from: string
  /** 返回形状。错标会让那一栏的预算**静默失效**（字符串标成列表 ⇒ `chars` 不再生效） */
  returns: ProjectionReturns
  /** 它对缺省值的承诺。**这一段是给外部实现者的**：照它实现，判据才和参考实现一致 */
  about: string
}

/**
 * 14 个投影的名字、来源格、返回形状与缺省承诺。
 *
 * ★ 分组不是装饰，是**三种不同的缺省语义**，实现时选错会让判定看到不一样的东西：
 *
 *     空值兜底    缺省时发空串 / 空表（原来写作 `?? ''` / `?? []`）
 *     非空兜底    ★ 缺省时那句**默认话本身就是判据的一部分** —— 不能发空串
 *     派生        从历史或注册表算出来的值
 */
export const PROJECTIONS = {
  // ── 空值兜底 ──────────────────────────────────────────────
  earlierMaybe: {
    from: 'earlier',
    returns: 'string',
    about: '上文摘要；没有上文时发空串。用来落地指代（「那个文件」）',
  },
  filesMaybe: {
    from: 'files',
    returns: 'list',
    about: '已知文件列表；还不知道时发空表',
  },
  readMaybe: {
    from: 'readFiles',
    returns: 'list',
    about: '已读过的文件；一个都没读过时发空表',
  },
  resultMaybe: {
    from: 'lastResult',
    returns: 'string',
    about: '上一步的工具输出；还没有过任何一步时发空串',
  },
  draftMaybe: {
    from: 'draft',
    returns: 'string',
    about: '刚生成的草稿；还没到生成那一步时发空串',
  },
  toolOrEmpty: {
    from: 'lastTool',
    returns: 'string',
    about: '上一个工具名；没有时发空串',
  },

  // ── 非空兜底：缺省时那句默认话**本身是判据的一部分** ──────
  lastOrNone: {
    from: 'lastResult',
    returns: 'string',
    about:
      '★ 与 resultMaybe 的区别只在缺省值上：没有结果时发「（还没有做过任何动作）」而不是空串。' +
      '空串会让判定分不清「没有结果」和「结果是空的」——而那是两件事',
  },
  toolOrUnknown: {
    from: 'lastTool',
    returns: 'string',
    about:
      '★ 与 toolOrEmpty 的区别同上：认不出来时发 `unknown`，而不是空串 ——' +
      '「认不出来」必须如实说，不能让它长得像「没有工具」',
  },

  // ── 派生 ──────────────────────────────────────────────────
  describeDone: {
    from: 'history',
    returns: 'string',
    about: '把「已经做过什么」压成一句话（去重后的工具名 + 步数）。**不丢一个数组让模型自己解析** —— 实测只放数组时它会重复选做过的动作',
  },
  lastInput: {
    from: 'history',
    returns: 'string',
    about: '最近一步的**工具参数**。判风险要看这一调的目标（`rm -rf /` 与 `ls` 差在参数上），而工具名说不出来',
  },
  readCount: {
    from: 'readFiles',
    returns: 'count',
    about: '读过的文件**个数**（不是清单）。§8.14 记着这个判定曾经拿计数冒充证据，所以它只该用在这种地方',
  },
  recentSteps: {
    from: 'history',
    returns: 'list',
    about: '最近几步的 `工具(输入) → 结果` 摘要，每步的输入与结果各有预算。用于「这一步成没成」与「整件事完没完」',
  },
  writeEvidence: {
    from: 'history',
    returns: 'string',
    about:
      '交给交付闸门逐句核对的证据。**按载荷分配预算**：写操作的载荷在输入（`路径\\n内容`）、结果只有一句「已写入」，' +
      '读操作反过来 —— 一律按位置分预算会让两种情形各错一半',
  },
  localToolRisk: {
    from: 'lastTool',
    returns: 'count',
    about:
      '工具的静态风险基线 0..3（注册表里的 `baseRisk`）。' +
      '★ 认不出的工具名返回 `undefined` ⇒ 这一栏**整个不出现在帧里**（记进 `absent`）——' +
      '0 分的意思是「只读」，不能拿它冒充「未知」',
  },
} as const satisfies Record<string, ProjectionSpec>

/** 投影名的**封闭**联合。来自上面那张表，不是 `string` */
export type ProjectionName = keyof typeof PROJECTIONS

/** 全部投影名（运行时）。用于完整性检查、报错信息与外部宿主的清单核对 */
export const PROJECTION_NAMES = Object.keys(PROJECTIONS) as ProjectionName[]

/**
 * 这个名字是不是注册表里的投影 —— `DECISION.md` 是**手写文件**，所以它给的
 * 投影名是不可信输入，查表前要过这一道（同 `act.ts` 的 `isToolName`）。
 *
 * ★ 走 `Object.hasOwn` 而不是 `in`：后者会被 `toString` / `constructor` 这类
 *   **继承来的键**骗过去，而那正是需要挡住的一类写法。
 *
 * ★ 有了它，`FRAME_PROJECTIONS` 才能是 `Record<ProjectionName, …>` 而不是
 *   `Record<string, …>` —— 后者会让「文件里写了一个拼错的投影名」在类型上
 *   看起来完全合法。
 */
export function isProjectionName(v: string): v is ProjectionName {
  return Object.hasOwn(PROJECTIONS, v)
}
