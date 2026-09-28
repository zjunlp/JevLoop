/**
 * JevLoop · DECISION.md 合规（conformance）
 *
 * ══════════════════════════════════════════════════════════════
 *  `DECISION.md` 是**可以被机器检查**的规格 —— 这个脚本就是那句话的凭据。
 * ══════════════════════════════════════════════════════════════
 *
 * 它做三件事：
 *
 *   一、对**真文件**跑三层检查，并证明基线是干净的。
 *       三层：`parse`（词法/语法）、`policy`（谓词编不编得出来）、
 *       `frame`（声明完不完整）。
 *
 *   二、对每一类「**会安静地判错**」的改法，证明它被挡下。
 *       改法不是另写一份玩具文件 —— 是拿**真的 `DECISION.md`** 改一处。
 *       锚点必须**恰好命中一次**，否则这个脚本自己报错（见 `runConformance`）。
 *
 *   三、证明它**不是永远红的**（`SHAM`）：改法变了、意思没变的那种，
 *       必须一行问题都不报。
 *
 * ── 为什么会有这个脚本 ────────────────────────────────────────
 *
 * 因为 `frameSpecViolations` 写好了、**却从来没有在真文件上跑过** ——
 * 单测拿的是手拼的 spec，`jevloop spec` 只跑前两层。
 * 实测（2026-09-23）：把 `needs_tool` 的 `- cwd —— …` 整行删掉，
 *
 *     parse 0 · policy 0 · jevloop spec 打印「✓ parses clean」· 相关 61 个测试全绿
 *
 * 于是 §8.14 那条「删掉一个字段之后没有任何东西记得它曾经在过」
 * **原样活在这份用来消灭它的文件里**。检查写好了没人跑，等于没有检查。
 *
 * ── 用法 ──────────────────────────────────────────────────────
 *
 *     npm run conformance          # 默认读仓库根的 DECISION.md，打印全表
 *     npm run conformance -- <路径>  # 换一份文件（层检查照跑，突变锚点会失配）
 *
 * 退出码 0 = 基线干净且每个突变都被挡下；1 = 有漏网或脚本自己失效。
 *
 * @module JevLoop/conformance
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { compilePolicy } from '../src/decision-compile.ts'
import { parseDecisionDoc, schemaProblems, summarize, type DecisionDoc } from '../src/decisiondoc.ts'
import { frameSpecsOf } from '../src/decisions.ts'
import { frameSpecViolations } from '../src/frame.ts'

// ═══════════════════════════════════════════════════════════
// 三层检查
// ═══════════════════════════════════════════════════════════

/** `DECISION.md` 的四层，从外到里。层号用在输出里 */
export type Layer = 'parse' | 'policy' | 'frame' | 'schema'

export const LAYERS: readonly Layer[] = ['parse', 'policy', 'frame', 'schema']

/** 四层各自的问题。全空 = 这份文件合格 */
export interface Problems {
  parse: string[]
  policy: string[]
  frame: string[]
  schema: string[]
}

function parseLayer(doc: DecisionDoc): string[] {
  return doc.problems.map((p) => `L${p.line} ${p.message}`)
}

function policyLayer(doc: DecisionDoc): string[] {
  const out: string[] = []
  for (const b of doc.blocks) {
    for (const x of compilePolicy(b)?.problems ?? []) out.push(`${b.id}: ${x}`)
  }
  return out
}

/**
 * 帧层。
 *
 * ★ 这一层和上两层的**形状不一样**：它是**抛**而不是收集。
 *   `frameSpecFromBlock` 对「格名认不出」当场抛（不抛的话那一栏会永远
 *   取到 `undefined`），`frameSpecsOf` 对「块少了」也抛。
 *   所以这里接住异常、把 message 当成一条问题 —— 对调用方来说
 *   「抛出来」和「列出来」都是「被挡下」，不该有两种说法。
 */
function frameLayer(doc: DecisionDoc): string[] {
  try {
    return frameSpecViolations(frameSpecsOf(doc))
  } catch (err) {
    return [(err as Error).message]
  }
}

/** 对**任意**一份 `DECISION.md` 文本跑四层检查 */
export function inspect(md: string): Problems {
  const doc = parseDecisionDoc(md)
  return {
    parse: parseLayer(doc),
    policy: policyLayer(doc),
    frame: frameLayer(doc),
    // ★ 版本单独一层，而**不是**并进 parse：`problems` 说「文件写错了」，
    //   这一层说「文件声称的语义我读不懂」。后者在一份旧文件上**是正常的** ——
    //   文件没错，是消费者该说不。混在一起，这两种结论就再也分不开。
    schema: schemaProblems(doc),
  }
}

/** `inspect` 的汇总：四层各几条 */
export function counts(p: Problems): Record<Layer, number> {
  return { parse: p.parse.length, policy: p.policy.length, frame: p.frame.length, schema: p.schema.length }
}

/** 四层加起来几条 */
export function total(p: Problems): number {
  return p.parse.length + p.policy.length + p.frame.length + p.schema.length
}

// ═══════════════════════════════════════════════════════════
// 突变
// ═══════════════════════════════════════════════════════════

/**
 * 一条演示的公共部分。
 *
 * `find` 是 `DECISION.md` 里的**原文**，必须**恰好命中一次** ——
 * 命中 0 次说明这段演示已经过期，命中多次说明锚点选得不够特别。
 * 两种情况都让脚本自己报错：一份悄悄失效的演示，比一份报错的演示危险得多。
 *
 * 分成 `Mutation` / `Sham` 两支是为了让「对照没有 `expect`」这件事**由编译器管**：
 * 写成可选字段的话，一条突变漏写 `expect` 就会静默退化成对照 ——
 * 而「一个不可能失败的检查」正是这个脚本要防的东西。
 */
interface Demo {
  /** 稳定 id，测试和输出都用它 */
  id: string
  /** 归到哪一类静默失败。见 `FAMILIES` */
  family: Family
  /** 改了什么，一行 */
  edit: string
  /** ★ 不改的话，会怎么**安静**地错 —— 这才是这条检查存在的理由 */
  silent: string
  /** 在文件里必须唯一命中的原文 */
  find: string
  /** 换成什么。空串 = 删掉这一行（含行尾换行） */
  to: string
  /** 哪一层必须挡下它（对照则记为「哪一层都不许响」） */
  layer: Layer
}

/** 一个突变：`layer` 层必须报出命中 `expect` 的问题 */
export interface Mutation extends Demo {
  expect: RegExp
  mustPass?: false
}

/**
 * 阴性对照：改法变了、**意思没变**，必须一行都不报。
 *
 * ★ 这一支是给整套检查做的阴性对照。§「一个不可能失败的检查和一个通过的
 *   检查无法区分」反过来也成立：**一个永远红的检查和一个真的在检查的检查
 *   同样无法区分** —— 所以「不该响的时候不响」必须被证明，不能假定。
 */
export interface Sham extends Demo {
  mustPass: true
  expect?: undefined
}

export type Case = Mutation | Sham

/** 四类静默失败。分组的理由是**补救动作不同**，不是严重程度 */
export const FAMILIES = {
  gate: '闸门静默失效 —— 该拦住的那一步直接放行（fail open）',
  declaration: '声明静默缩水 —— 判定少看一栏，而没有人记得它曾经在过',
  action: '判定静默走空 —— 问了、记了，而没有东西照它做',
  version: '版本静默消失 —— 文件不再说自己按哪一版语义读',
} as const

export type Family = keyof typeof FAMILIES

/** 四条锚点的原文，集中在这里方便对着 `DECISION.md` 核 */
const NEEDS_TOOL_CWD =
  '  - cwd                                 —— 路径不进判定：目标由 `target` 那一栏（gradeRisk）或候选（pickInput）表达，工作目录本身没有信息\n'
const NEEDS_TOOL_CANWRITE =
  '  - canWrite                            —— 「能不能写」是**代码**按精确规则判的（§8.1 第三行），不该让判定模型再判一遍\n'
const NEEDS_TOOL_TASK =
  '  + task          400                   —— 整个判定的主体：问的是「这个任务还有没有没做的动作」'
/** 版本声明那一行的原文。删掉它 / 只改空格，是两个相反的演示 */
const SCHEMA_LINE = 'schema: decision-contract/v1\n'
/** `needs_tool` 的 `when:` 整行 —— 删掉它、或把 `——` 换成空格，是两个演示 */
const NEEDS_TOOL_WHEN = 'when: step-start —— 每个 step 的开头。判否就直接跳到生成，整个工具循环省掉\n'
/** `pick_tool` 的 `dynamic:` 整行 —— 输出写成别的、或丢掉理由，是两个演示 */
const PICK_TOOL_DYNAMIC =
  'dynamic: toolsFor(ctx: history, files, readFiles, canWrite, canDelete) → candidates —— ' +
  '候选每步重建，下面列的是默认全集。★ 读哪几格要写出来：宿主得知道算候选时看了什么，少喂一格候选会**静默地**少一类\n'

export const CASES: readonly Mutation[] = [
  {
    id: 'action-typo',
    family: 'gate',
    edit: 'grade_risk 的策略里 `ask_human` 拼成 `ask_humam`',
    silent:
      '闸门编译成功、`isGate()` 返回 false、界面把这个块显示成正常，而 ' +
      '`resolvePolicy` 会返回一个**没有任何消费方能处理**的动作 —— 本该拦住的那一步直接放行。fail open。',
    find: '  - score:risk >= 2 → ask_human\n',
    to: '  - score:risk >= 2 → ask_humam\n',
    layer: 'parse',
    expect: /不认识的 action 'ask_humam'/,
  },
  {
    id: 'gate-predicate-dead',
    family: 'gate',
    edit: 'grade_risk 里 `risk` 的一个档位补上「名字 — 说明」（写法的标点变化）',
    silent:
      '`risk` 从 score 变成 choice，于是 `score:risk >= 2 → ask_human` 这条**硬规则编译不出来**，' +
      '退化成一条永不命中的规则 —— 一道不存在的闸门。解析期只报「选项写法不一致」，' +
      '真正致命的后果在**另一层**。',
    find: '- read-only\n',
    to: '- read-only — 只读取，不改变任何东西\n',
    layer: 'parse',
    expect: /问题 'risk' 的选项写法不一致/,
  },
  {
    id: 'exclusion-dropped',
    family: 'declaration',
    edit: 'needs_tool 的 frame 里整行删掉 `- cwd —— …`',
    silent:
      '★★ §8.14 那条「删掉一个字段之后没有任何东西记得它曾经在过」—— ' +
      '**在这个脚本存在之前，四层全绿**：解析器不管、帧编译不管、`jevloop spec` 打印 ✓、' +
      '相关测试全过。`cwd` 就这么从声明里消失了。',
    find: NEEDS_TOOL_CWD,
    to: '',
    layer: 'frame',
    expect: /ctx\.'cwd' 既没被看，也没声明/,
  },
  {
    id: 'exclusion-no-reason',
    family: 'declaration',
    edit: 'needs_tool 的 `- canWrite —— …` 删掉理由，只留格名',
    silent:
      '`excluded` 的全部价值就是那句为什么。没有理由的排除项是一条**没有内容的声明**，' +
      '而它在文件里长得和一条有理由的一模一样。',
    find: NEEDS_TOOL_CANWRITE,
    to: '  - canWrite\n',
    layer: 'parse',
    expect: /frame 行 '- canWrite' 没有写为什么/,
  },
  {
    id: 'field-typo',
    family: 'declaration',
    edit: '`+ task` 写成 `+ taskk`（理由原样留着）',
    silent:
      '帧里多一个永远取到 `undefined` 的 `taskk`，而**真正该看的 `task` 一栏没了** —— ' +
      '判定静默地少看一栏。报错点的是 `taskk`，症状在 `task`。',
    find: NEEDS_TOOL_TASK,
    to: NEEDS_TOOL_TASK.replace('+ task ', '+ taskk'),
    layer: 'frame',
    expect: /frame 的 'taskk' 既不是 ctx 的格名/,
  },
  {
    id: 'field-unbounded',
    family: 'declaration',
    edit: '`+ task 400` 的界删掉，只留格名和理由',
    silent:
      '§8.2：没有界的一栏会**原样进帧**。界是**逐栏**的硬要求，所以少了它不会有别的地方响 —— ' +
      '代价（token）和「帧必须有界」这条不变量一起悄悄不成立。',
    find: NEEDS_TOOL_TASK,
    to: NEEDS_TOOL_TASK.replace('          400', ''),
    layer: 'parse',
    expect: /frame 的 'task' 缺一个正的界/,
  },
  {
    id: 'when-not-a-position',
    family: 'action',
    edit: 'needs_tool 的 `when: step-start` 改成 `when: loop-start`',
    silent:
      '判定会被问、会被记进 `decision` 事件，而**没有任何东西会按它的动作做事**。' +
      '位置是「加一个判定只改文件」那句话的边界 —— 写不出位置，就没有消费者。',
    find: 'when: step-start ——',
    to: 'when: loop-start ——',
    layer: 'parse',
    expect: /when: 'loop-start' 不是一个位置/,
  },
  {
    id: 'action-not-in-position',
    family: 'action',
    edit: 'is_done 的兜底 `else → keep_going` 改成 `else → revise`',
    silent:
      '★★ 这不是假想的：`is_done` 的兜底**以前写的就是** `else → revise`（`revise` 的意思是「重写答案」）。' +
      '位置 `after-tool` 只处理 `finish` / `keep_going`，而 loop 只判 `finish` —— ' +
      '于是它**碰巧**表现得像 `keep_going`。行为对了，理由是错的，一直等到有人真去实现 `revise`。',
    find: '  - prob:done >= 0.6 → finish\n  - else → keep_going\n',
    to: '  - prob:done >= 0.6 → finish\n  - else → revise\n',
    layer: 'parse',
    expect: /'after-tool' 这个位置不处理动作 'revise'/,
  },
  {
    id: 'kind-unknown',
    family: 'action',
    edit: 'needs_tool 的 `kind: noul` 改成 `kind: bool`',
    silent:
      '`kind` 认不出 ⇒ `kind` 保持 null ⇒ 块**退回 `rule`** ⇒ 一个本该问模型的判定' +
      '静默变成**代码判定**。文件里看不出区别，只有 headline 会变。',
    find: '## needs_tool\n\nkind: noul\n',
    to: '## needs_tool\n\nkind: bool\n',
    layer: 'parse',
    expect: /kind 只能是 .*收到 'bool'/,
  },
  {
    id: 'block-id-duplicate',
    family: 'action',
    edit: '`## step_ok` 标题改成 `## is_done`',
    silent:
      '两个块抢同一个 id，其中一个赢。而且七个判定各要一个块 —— ' +
      '少了 `step_ok`，帧层当场抛。**解析期只报「id 重复」，看不出少了一个判定。**',
    find: '## step_ok\n',
    to: '## is_done\n',
    layer: 'parse',
    expect: /判定 id 'is_done' 重复/,
  },
  {
    id: 'schema-dropped',
    family: 'version',
    edit: '删掉文件头的 `schema: decision-contract/v1` 整行',
    silent:
      '★ 这一行删掉之后**其余三层一条都不响**：块、问题、策略、帧全都还是合法的，' +
      '`jevloop spec` 也照样打印 ✓ —— 而这份文件从此**不再说自己按哪一版语义读**。' +
      '等语义真的改了，它会被按新语义读，而且没有任何东西能发现。',
    find: SCHEMA_LINE,
    to: '',
    layer: 'schema',
    expect: /没有声明 `schema:`/,
  },
  {
    id: 'when-dropped',
    family: 'action',
    edit: '删掉 needs_tool 的 `when:` 整行',
    silent:
      '★★ 位置层**整段跳过** —— 这一段以前写成 `if (position) { … }`，于是没写 `when:` 的块' +
      '根本不进这一层。一个产出 `use_tool` 的块，而没有任何位置说它处理 `use_tool`，' +
      '`problems` 却是空的。实测（2026-09-28）：这种文件三层全绿。',
    find: NEEDS_TOOL_WHEN,
    to: '',
    layer: 'parse',
    expect: /没有点名一个位置/,
  },
  {
    id: 'when-purpose-unread',
    family: 'declaration',
    edit: 'needs_tool 的 `when:` 里 `——` 换成空格（位置后面直接接散文）',
    silent:
      '位置照样解析得出来，所以**没有任何一层会响** —— 而「—— 每个 step 的开头…」那句话' +
      '从此既不进 `purpose`，也没有别的地方读它：写给人看，而没有人看得到。',
    find: NEEDS_TOOL_WHEN,
    to: 'when: step-start 每个 step 的开头。判否就直接跳到生成，整个工具循环省掉\n',
    layer: 'parse',
    expect: /要用 `——` 接/,
  },
  {
    id: 'dynamic-output-unknown',
    family: 'declaration',
    edit: 'pick_tool 的 `dynamic:` 输出从 `candidates` 改成 `everything`',
    silent:
      '宿主认的输出形状是**封闭表**。写成别的而没人报的话，宿主拿到一个不知道该怎么调的' +
      '提供者 —— 候选根本不会重建，而问题照样发出去，用的还是文件里那个占位选项。',
    find: PICK_TOOL_DYNAMIC,
    to:
      'dynamic: toolsFor(ctx: history, files, readFiles, canWrite, canDelete) → everything —— ' +
      '候选每步重建，下面列的是默认全集。★ 读哪几格要写出来：宿主得知道算候选时看了什么，少喂一格候选会**静默地**少一类\n',
    layer: 'parse',
    expect: /不认识的 dynamic 输出 'everything'/,
  },
  {
    id: 'dynamic-why-dropped',
    family: 'declaration',
    edit: 'pick_tool 的 `dynamic:` 删掉 `—— 为什么` 那半句',
    silent:
      '`——` 之后那半句是这一行**唯一承载的信息**：候选为什么必须每步重算。' +
      '删掉之后它长得和一条写全的完全一样，而下一个改这里的人只能靠猜。',
    find: PICK_TOOL_DYNAMIC,
    to: 'dynamic: toolsFor(ctx: history, files, readFiles, canWrite, canDelete) → candidates\n',
    layer: 'parse',
    expect: /没有写为什么/,
  },
]

/**
 * 阴性对照：改法变了、**意思没变** —— 必须一行都不报。
 *
 * 两条都在证明同一件事：这份检查认的是**结构**，不是**排版**。
 */
export const SHAM: readonly Sham[] = [
  {
    id: 'sham-whitespace',
    family: 'declaration',
    edit: '`+ task          400` 的补白压成一个空格',
    silent: '（对照：空格是分隔符，不是语法）',
    find: NEEDS_TOOL_TASK,
    to: NEEDS_TOOL_TASK.replace('          400', ' 400'),
    layer: 'frame',
    mustPass: true,
  },
  {
    id: 'sham-prose',
    family: 'action',
    edit: '在一个块里插一行装饰性 markdown（`**…**`）',
    silent: '（对照：装饰性 markdown 不参与解析，只进 rationale）',
    find: 'policy:\n  - prob:needs_tool >= 0.5 → use_tool\n',
    to: '**这一行是后来补的说明，只给人读。**\n\npolicy:\n  - prob:needs_tool >= 0.5 → use_tool\n',
    layer: 'parse',
    mustPass: true,
  },
  {
    id: 'sham-schema-spacing',
    family: 'version',
    edit: '`schema: decision-contract/v1` 的冒号后空格去掉',
    silent: '（对照：冒号两侧的空格是分隔符，不是版本的一部分）',
    find: SCHEMA_LINE,
    to: SCHEMA_LINE.replace(': ', ':'),
    layer: 'schema',
    mustPass: true,
  },
  {
    id: 'sham-dynamic-spacing',
    family: 'declaration',
    edit: '`toolsFor(ctx) → candidates` 箭头两侧的空格压掉',
    silent: '（对照：箭头两侧的空格是分隔符 —— 它拆出来的两个 token 没变）',
    find: PICK_TOOL_DYNAMIC,
    to:
      'dynamic: toolsFor(ctx: history, files, readFiles, canWrite, canDelete)→candidates —— ' +
      '候选每步重建，下面列的是默认全集。★ 读哪几格要写出来：宿主得知道算候选时看了什么，少喂一格候选会**静默地**少一类\n',
    layer: 'parse',
    mustPass: true,
  },
]

// ═══════════════════════════════════════════════════════════
// 跑
// ═══════════════════════════════════════════════════════════

export interface Outcome {
  c: Case
  /** 这条演示本身成不成立 */
  ok: boolean
  /** 不成立的原因，或挡下它的那条问题 */
  detail: string
  /** 这个改法**实际**在哪些层报了问题（可能不止 `c.layer`） */
  firedIn: Layer[]
}

/** `find` 在文本里出现几次。0 或 >1 都是这份演示失效了 */
function hits(md: string, find: string): number {
  return md.split(find).length - 1
}

/** 应用一个改法。返回 `null` 表示**这条演示已经失效**，原因是 `why` */
export function apply(md: string, c: Case): { bad: string } | { stale: string } {
  const n = hits(md, c.find)
  if (n === 0) return { stale: `锚点在 DECISION.md 里找不到 —— 这段演示已经过期：\n        ${oneLine(c.find)}` }
  if (n > 1) return { stale: `锚点在 DECISION.md 里命中 ${n} 次（必须恰好 1 次）—— 换个更特别的锚点：\n        ${oneLine(c.find)}` }
  const bad = md.replace(c.find, c.to)
  if (bad === md) return { stale: '这个改法**没有改动任何东西** —— 它证明不了任何事' }
  return { bad }
}

export function runOne(md: string, c: Case): Outcome {
  const a = apply(md, c)
  if ('stale' in a) return { c, ok: false, detail: a.stale, firedIn: [] }

  const p = inspect(a.bad)
  const firedIn = LAYERS.filter((l) => p[l].length > 0)

  if (c.mustPass) {
    const all = [...p.parse, ...p.policy, ...p.frame]
    return all.length === 0
      ? { c, ok: true, detail: '一行都没报（对照成立）', firedIn }
      : { c, ok: false, detail: `对照必须不被挡下，却报了：\n        ${all[0]}`, firedIn }
  }

  const hit = p[c.layer].find((m) => c.expect.test(m))
  if (hit) return { c, ok: true, detail: hit, firedIn }
  if (p[c.layer].length === 0) {
    return { c, ok: false, detail: `**${c.layer} 层一条问题都没报** —— 这个改法溜过去了`, firedIn }
  }
  return { c, ok: false, detail: `${c.layer} 层报了，但没报成预期的样子：\n        ${p[c.layer][0]}`, firedIn }
}

/** 全部突变 + 对照，对一份文本跑一遍 */
export function runConformance(md: string): Outcome[] {
  return [...CASES, ...SHAM].map((c) => runOne(md, c))
}

/** 这个改法在某层报了几条 —— 用来在输出里标出「还有哪一层也响了」 */
function oneLine(s: string): string {
  return s.replace(/\n/g, '\\n').replace(/\s+/g, ' ').trim().slice(0, 96)
}

// ═══════════════════════════════════════════════════════════
// 打印
// ═══════════════════════════════════════════════════════════

const B = (s: string) => `\x1b[1m${s}\x1b[0m`
const D = (s: string) => `\x1b[2m${s}\x1b[0m`
const G = (s: string) => `\x1b[32m${s}\x1b[0m`
const R = (s: string) => `\x1b[31m${s}\x1b[0m`
const Y = (s: string) => `\x1b[33m${s}\x1b[0m`

/** 显示宽度：中文全角算两格，好让表对齐（`padEnd` 按字符数算，会歪） */
function width(s: string): number {
  let w = 0
  for (const ch of s) w += (ch.codePointAt(0) ?? 0) > 0x1f00 ? 2 : 1
  return w
}

function pad(s: string, n: number): string {
  return s + ' '.repeat(Math.max(0, n - width(s)))
}

export function main(argv: readonly string[]): number {
  const file = resolve(argv[0] ?? 'DECISION.md')
  let md: string
  try {
    md = readFileSync(file, 'utf8')
  } catch (err) {
    console.error(R(`✗ 读不到 ${file}：${(err as Error).message}`))
    return 1
  }

  const base = inspect(md)
  const s = summarize(parseDecisionDoc(md))

  console.log(B('\nJevLoop · DECISION.md conformance'))
  console.log(D(`  file      : ${file}`))
  console.log(
    D(
      `  spec      : ${s.blocks} blocks / ${s.questions} questions / ${s.options} options · ` +
        `${s.modelDecisions} to the decision model, ${s.codeDecisions} by code`,
    ),
  )
  console.log(D(`  schema    : ${parseDecisionDoc(md).schema ?? '（没声明 —— 这是不合格的）'}`))

  const ok0 = total(base) === 0
  console.log(
    `  baseline  : parse ${base.parse.length} · policy ${base.policy.length} · frame ${base.frame.length} · schema ${base.schema.length}   ` +
      (ok0 ? G('✓ clean') : R('✗ 真文件本身就不合格')),
  )
  for (const l of LAYERS) for (const m of base[l]) console.log(R(`      [${l}] ${m}`))

  const outcomes = runConformance(md)

  /** 一条演示的三行：标题、不改会怎样、实际被谁挡下 */
  const show = (o: Outcome): void => {
    console.log(`  ${o.ok ? G('✓') : R('✗')} ${pad(o.c.id, 24)} ${D(o.c.layer.padEnd(7))} ${o.c.edit}`)
    console.log(D(`    ${pad('', 24)} ↳ ${o.c.silent}`))
    const extra = o.firedIn.filter((l) => l !== o.c.layer)
    // ★ 对照的「成立」是**没被挡下**。和突变共用「挡下」那个词会把结论说反。
    const verdict = o.c.mustPass
      ? o.ok
        ? G('未挡下 ✓')
        : R('误报')
      : o.ok
        ? G('挡下')
        : R('漏过')
    console.log(
      `    ${pad('', 24)} ${verdict} ${D(`[${o.c.layer}]`)} ${oneLine(o.detail)}` +
        (extra.length ? D(`   （另在 ${extra.join(' / ')} 层也响）`) : ''),
    )
    console.log('')
  }

  for (const fam of Object.keys(FAMILIES) as Family[]) {
    const group = outcomes.filter((o) => o.c.family === fam && !o.c.mustPass)
    if (group.length === 0) continue
    console.log(B(`\n  ── ${FAMILIES[fam]} ${'─'.repeat(Math.max(0, 58 - width(FAMILIES[fam])))}`))
    group.forEach(show)
  }

  console.log(B(`\n  ── 阴性对照 —— 改法变了、意思没变，必须一行都不报 ${'─'.repeat(14)}`))
  outcomes.filter((o) => o.c.mustPass).forEach(show)

  const miss = outcomes.filter((o) => !o.ok && !o.c.mustPass)
  const sham = outcomes.filter((o) => !o.ok && o.c.mustPass)
  const caught = CASES.length - miss.length

  console.log(B('  ── 汇总 ────────────────────────────────────────────────'))
  console.log(
    `  ${caught} / ${CASES.length} 个「会安静地判错」的改法被挡下` +
      (miss.length ? R(` · ${miss.length} 个漏过：${miss.map((o) => o.c.id).join('、')}`) : ''),
  )
  console.log(
    `  ${SHAM.length - sham.length} / ${SHAM.length} 个「意思没变」的改法**没被**挡下（阴性对照）` +
      (sham.length ? R(` · ${sham.length} 个误报：${sham.map((o) => o.c.id).join('、')}`) : ''),
  )
  if (!ok0) console.log(R('  ✗ 基线不干净 —— 先修 DECISION.md，突变结果没有意义'))
  if (outcomes.some((o) => o.detail.includes('已经过期') || o.detail.includes('没有改动'))) {
    console.log(Y('  ⚠ 有演示过期了（锚点对不上）—— 那不是漏网，是这个脚本自己失效了'))
  }

  const clean = ok0 && miss.length === 0 && sham.length === 0
  console.log(clean ? G('\n  ✓ 每一类静默失败都被一层挡下，而对照没被误伤\n') : R('\n  ✗ 有漏网\n'))
  return clean ? 0 : 1
}

// 直接跑时进 main；被 import（单测）时不跑 —— 否则 `npm test` 会把整张表打两遍。
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)))
}
