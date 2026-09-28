/**
 * JevLoop · `when:` 与 `dynamic:` 的**语法**
 *
 * 从 `decision-shape.ts` 拆出来 —— 那个文件的头部写着「只描述 `DocBlock` 这一族
 * 类型，不认识 Markdown、也不认识策略」，而**拆字符串是语法，不是形状**。
 * 把两个解析器塞进去之后它一夜之间从 260 行涨到 374 行，`npm run check` 的
 * file-focus 当场报出来：一个文件同时管「形状」和「两行头部的写法」，
 * 下一次改其中一半的人会以为自己在改另一半。
 *
 * ── 为什么这两个解析器值得单独存在 ────────────────────────────
 *
 * 因为在这之前，「一整根字符串，谁用谁拆」：
 *
 *     `when`     被 `adapter.ts`、界面那一侧、测试里各拆了一遍
 *     `dynamic`  被 `adapter.ts` 和别处各拆了一遍
 *
 * 同一个格式有几种拆法，就有几个会分叉的定义 —— 界面上显示的位置和适配器
 * 核对的位置可以不是同一个，而且**谁都不会报错**。所以语法收在这里一次，
 * 解析期拆好，消费方只读字段。
 *
 * 这一层**零 import**：它只做字符串 → 结构，不认识位置表、不认识策略、
 * 也不认识 Markdown 的其余部分。校验（位置存不存在、动作合不合法）在
 * `decisiondoc.ts` 里做，因为那要连着 `POSITIONS` 和 `policy` 一起看。
 *
 * @module JevLoop/decision-syntax
 */

// ═══════════════════════════════════════════════════════════
// `when: <位置> —— <说明>`
// ═══════════════════════════════════════════════════════════

/** `when:` 拆开之后的样子 */
export interface ParsedWhen {
  /** 机器认的那一半：位置名 */
  position: string
  /** 人读的那一半：`——` 之后的说明。可以没有 */
  purpose: string
  /** 位置后面、`——` 之前多出来的字。非空就是写法问题，见 `whenProblems()` */
  leftover: string
}

/**
 * `when: <位置> —— <说明>` → 两半。
 *
 * 位置是**第一个 token**（空白或左括号都算分隔），这样 `input-choice` 这种
 * 带连字符的名字、以及 `host:review` 这种命名空间都原样拿得到。
 */
export function parseWhen(raw: string): ParsedWhen {
  const src = raw.trim()
  const cut = src.indexOf('——')
  const head = (cut >= 0 ? src.slice(0, cut) : src).trim()
  const purpose = cut >= 0 ? src.slice(cut + 2).trim() : ''
  const position = head.split(/\s|（|\(/)[0] ?? ''
  return { position, purpose, leftover: head.slice(position.length).trim() }
}

/**
 * `when:` 写法上的毛病。每条一句话，由调用方补行号。
 *
 * ★ 位置**必填**。这里返回的第一条就是「没写」—— 在它之前，没写 `when:` 的块
 *   整个跳过位置层：一个产出 `deliver` 的块，而没有任何位置说它会处理它，
 *   `problems` 却是空的。那正是位置层存在的理由（「会被问、会被记，而没有
 *   东西照它做」），所以「没写」必须和「写错」一样出声。
 */
export function whenProblems(parsed: ParsedWhen): string[] {
  if (parsed.position === '') {
    return ['when: 没有点名一个位置 —— 位置决定这个判定的动作由谁处理；写不出位置，就没有东西会按它的动作做事']
  }
  if (parsed.leftover) {
    return [
      `when: 位置 '${parsed.position}' 后面还有 '${parsed.leftover}' —— 说明那句话要用 \`——\` 接` +
        `（\`when: ${parsed.position} —— ${parsed.leftover}\`）。` +
        '现在它既不进 purpose，也没有别的地方读它：写给人看，而没有人看得到',
    ]
  }
  return []
}

// ═══════════════════════════════════════════════════════════
// `dynamic: <提供者>(ctx) → <输出> —— <为什么>`
// ═══════════════════════════════════════════════════════════

/**
 * 动态提供者能产出什么 —— **封闭集合**。
 *
 * ★ 只有一个元素是**诚实的**，不是没做完：今天所有 `dynamic:` 都是在给
 *   `choice` 喂候选集，没有第二种用法。等真的出现第二种（比如整个问题集都由
 *   运行时算），这里是「加一个」并同时给宿主一个处理分支 —— 那才是
 *   docs/RESEARCH…§6 说的「有明确的 conformance 需求才扩 DSL」。
 */
export const DYNAMIC_OUTPUTS: readonly string[] = ['candidates']

/**
 * 候选是每步算出来的，不是这份文件里列的。
 *
 * 选项必须每步重建（docs/CODE-STYLE.md §8.4）—— 固定的候选会让模型去选一个已经
 * 不适用的动作。有这一项时，文件里列的选项只是**默认全集或示例**，
 * 校验也不再要求至少两个。
 */
export interface DocDynamic {
  /**
   * 宿主必须注册的提供者名。
   *
   * 文件里写不出函数，所以只能点名；**这个名字是宿主封闭表里的一个键**，
   * 认不出就是宿主没实现它 —— 由 `adapterProblems()` 报出来。
   */
  provider: string
  /**
   * 它读 `AgentCtx` 的哪几格（TODO §12 第三条）。
   *
   * ★ 以前这里只有一个 `(ctx)`，等于说「它读上下文」—— 而候选是**算出来的**，
   *   「算它的时候看了什么」才是宿主需要知道的东西：少喂一格，候选会**静默地**
   *   少一类。现在必须逐格写出来：`toolsFor(ctx: history, files, …)`。
   */
  reads: readonly string[]
  /** 它产出什么形状。见 `DYNAMIC_OUTPUTS`：目前只有一种 */
  output: string
  /** 为什么候选必须每步重算（`——` 之后那句）。**必填** */
  why: string
}

/** `dynamic:` 拆开之后的样子 */
export interface ParsedDynamic {
  /** 宿主要注册的提供者名。解析不出来时是空串 */
  provider: string
  /** 它声明读哪几格 */
  reads: readonly string[]
  /** 产出形状。解析不出来时是空串 */
  output: string
  /** `——` 之后那句为什么 */
  why: string
  /** 写法上的毛病。每条一句话，由调用方补行号 */
  problems: string[]
}

/**
 * 提供者调用：`<名字>(ctx)` 或 `<名字>(ctx: <格名>, <格名>, …)`。
 *
 * 冒号后面允许为空（由下面单独报「一格都没写」），这样 `(ctx)` 这种旧写法
 * 得到的是一条**说清怎么改**的错误，而不是一条「格式不对」。
 */
const RE_DYNAMIC_CALL = /^([A-Za-z_][A-Za-z0-9_]*)\s*\(\s*ctx\s*(?::\s*(.*?))?\s*\)$/

/** 一格名字长什么样 */
const RE_CELL = /^[A-Za-z_][A-Za-z0-9_]*$/

/**
 * `dynamic: <提供者>(ctx: <格名>, …) → <输出> —— <为什么>` → 四个字段。
 *
 * ★ 为什么要 `(ctx: …)` 而不是光一个名字：动态提供者的全部意义就是「它从当前
 *   状态算」，而**读了哪几格**决定了宿主必须备好什么。只给一个名字，宿主接不上
 *   的时候只能靠猜 —— 而猜错的表现是候选静默地少一类。
 *
 * ★ 为什么要 `→ <输出>`：宿主得知道这个提供者返回什么形状才能接上
 *   （候选集？问题集？）。
 */
export function parseDynamic(raw: string): ParsedDynamic {
  const src = raw.trim()
  const cut = src.indexOf('——')
  const head = (cut >= 0 ? src.slice(0, cut) : src).trim()
  const why = cut >= 0 ? src.slice(cut + 2).trim() : ''
  const problems: string[] = []

  if (!why) {
    problems.push('`dynamic:` 没有写为什么（用 —— 接一句理由）—— 候选为什么必须每步重算，是这一行真正承载的信息')
  }

  const arrow = head.split('→')
  const call = (arrow[0] ?? '').trim()
  const output = (arrow[1] ?? '').trim()
  if (arrow.length < 2) {
    problems.push(
      `\`dynamic:\` 缺 \`→ <输出>\`（可选：${DYNAMIC_OUTPUTS.join(' / ')}）—— ` +
        '宿主需要知道这个提供者产出什么形状才接得上',
    )
  } else if (arrow.length > 2) {
    problems.push(`\`dynamic:\` 只能有一个 '→'（收到 ${arrow.length - 1} 个）`)
  } else if (!DYNAMIC_OUTPUTS.includes(output)) {
    problems.push(`不认识的 dynamic 输出 '${output}'（可选：${DYNAMIC_OUTPUTS.join(' / ')}）`)
  }

  const m = RE_DYNAMIC_CALL.exec(call)
  let reads: string[] = []
  if (!m) {
    problems.push(
      `\`dynamic:\` 的提供者要写成 \`<名字>(ctx: <格名>, …)\`（收到 '${call}'）—— ` +
        '宿主按名字注册实现、按格名核对状态，两样都写不出来就没法接',
    )
  } else {
    reads = (m[2] ?? '')
      .split(/[\s,]+/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (reads.length === 0) {
      problems.push(
        '`dynamic:` 没有写它读哪几格（写成 `<名字>(ctx: <格名>, …)`）—— ' +
          '候选是从状态算出来的，少喂一格它会**静默地**少一类，所以哪几格必须写出来',
      )
    }
    for (const cell of reads) {
      if (!RE_CELL.test(cell)) problems.push(`\`dynamic:\` 里的格名 '${cell}' 不是一个标识符`)
    }
    const dup = reads.filter((c, i) => reads.indexOf(c) !== i)
    if (dup.length) problems.push(`\`dynamic:\` 里重复写了格名：${[...new Set(dup)].join(', ')}`)
  }

  return { provider: m ? m[1]! : '', reads, output, why, problems }
}
