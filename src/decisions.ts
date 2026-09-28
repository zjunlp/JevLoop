/**
 * JevLoop · agent 的全部判定
 *
 * ══════════════════════════════════════════════════════════════
 *  这个文件就是 JevLoop 的全部主张。
 * ══════════════════════════════════════════════════════════════
 *
 * 一个常规 agent 的 loop 里，下面这些事都会写成一次大模型调用：
 *
 *     要不要动手？  用哪个工具？  读哪个文件？  这个操作危险吗？
 *     成功了吗？    做完了吗？    这个回答能发出去吗？
 *
 * 它们全都不是「生成」，而是「选择 / 打分 / 是否」。
 * 也就是说：**你一直在用生成的价格，买判定的答案。**
 *
 * 这些判定每个只要一次前向传播，加起来通常几十到几百毫秒，
 * 换来的是整个 loop 里只剩一次真正的大模型调用。
 *
 * ── 这里只剩「帧」，问题和策略来自 DECISION.md ────────────────
 *
 * 每个节点现在长这样：
 *
 *     defineDecision({
 *       id: 'loop.needsTool',
 *       state: ctx => ({ ... }),        ← 留在这里：帧构造器是个**函数**
 *       ...compiled('needs_tool'),      ← questions + policy 来自文件
 *     })
 *
 * **为什么帧必须留在这里**：`DECISION.md` 是一门声明式的格式，能表达
 * 「问什么」和「答成什么就走哪一步」，但它表达不了**函数** ——
 * 而帧恰恰是「从完整的 ctx 里挑哪几个字段、各截多长」的一段代码。
 * 硬把它塞进 markdown 只有两条路：发明一门真正的 DSL，或者让帧退化成
 * 「把 ctx 全塞进去」（那会撑爆 512/1024 的上下文，见 §8.2）。
 * 两条都不划算，所以这条边界是**刻意的**，不是没做完。
 *
 * 好处是那句主张现在成立：改 `DECISION.md` 里的问题和策略，
 * 运行时跟着变，不需要改这个文件。
 *
 * ## 为什么不能再拆
 *
 * 七个判定节点是**同一件事** —— 这个 loop 会问哪些问题 —— 每个 35-45 行，
 * 每个本身就是最小闭包。拆成七个文件只会让「一共有哪些判定」从一眼可见
 * 变成要翻目录。**内聚不是越小越好**；docs/CODE-STYLE.md §12 特意把它留作反例。
 * **行数不在这里写** —— 它会漂，跑 `npm run check` 看当前值。
 *
 * @module JevLoop/decisions
 */

import { readFileSync } from 'node:fs'

import { defineDecision } from './vocab-decision.ts'
import { choice } from './vocab.ts'
import type {
  AnswerSet,
  ChoiceQuestion,
  NoulQuestion,
  QuestionSet,
  ScoreQuestion,
} from './vocab.ts'
import type { PolicyRule } from './vocab-decision.ts'
import { clip } from './budget.ts'
import { isToolName } from './act.ts'
import { LOCAL_TOOLS } from './act-local.ts'
import { parseDecisionDoc, type DecisionDoc, type DocBlock } from './decisiondoc.ts'
import { hasThreshold, predicateQuestion } from './decision-compile.ts'
import { parseGates, splitGates, type GateOverrides } from './gates.ts'
import { compilePolicy, compileQuestions } from './decision-compile.ts'

import { toolsFor, fileOptions, pickInputInstructions, describeDone, lastInput } from './frame.ts'
import type { AgentCtx, FrameSpec } from './frame.ts'
import { compileFrame, frameSpecViolations, AGENT_CTX_KEYS } from './frame.ts'
export type { AgentCtx, StepRecord } from './frame.ts'

// ═══════════════════════════════════════════════════════════
// 七个判定的**帧声明**（§8.14：帧是声明出来的，不是拼出来的）
//
// 放在一处是有意的：这七份**要能并排读**。「为什么 `pickTool` 看得到历史
// 摘要而 `pickInput` 看不到」「为什么只有 `stepOk` 没有 task」—— 这些问题
// 以前要靠逐个读函数体回答，而函数体里只有当时写它的人才知道答案。
//
// 每一栏的 `why` 不是文档礼貌，是**产生这一栏的那次实测**。§8.14 记着：
// 四次事故全部在帧上、没有一次是判定模型判错了，而四次读起来都像模型错。
// 那四次的经验只活在这里和 `docs/` 里 —— 删掉 `why`，下一个人会把
// 「这里少了个字段」当成 bug 然后好心地加回去。
//
// `frameSpecViolations()` 会检查：`AgentCtx` 的**每一格**要么被某栏读、
// 要么出现在 `excluded` 里且写明了为什么。**没有第三种状态。**
// ═══════════════════════════════════════════════════════════

/**
 * 上文进决策帧的字符上限。
 *
 * 200 是**背景**的量级：要能说清「前面问过什么」，但不能挤掉这一轮真正
 * 要看的东西（任务 400、上次结果 300）。帧上下文只有 512/1024，
 * 多轮的代价必须显式地小（§8.2）。
 */
const EARLIER_MAX_CHARS = 200

/**
 * 一行「已经做过什么」的预算。
 *
 * ★ 这一栏此前**根本没有预算** —— `describeDone()` 的返回值原样进帧。
 *   而 §8.2 要求帧必须有界，所以这是一处漏掉的界。300 高于任何现实取值
 *   （工具名去重后最多几十个），因此**补上它不改变今天的输出**；
 *   它防的是以后工具变多时这一栏悄悄长起来。
 */
const DONE_LINE_MAX_CHARS = 300

// ═══════════════════════════════════════════════════════════
// `frame:` 里的**投影注册表** —— 文件写不出函数，所以派生值只能点名
//
// ★ **封闭集合，而且它是 `from` 的唯一出处。** 文件只写投影名，读到哪一格由
//   这里说了算 —— 于是**文件没法声称自己读的是别处**（那正是「声明和实现对不上」
//   的形状，§8.16）。名字写错会被 `frameFromDoc` 当场抛出来，不会静默当成原样取。
//
// ★ 为什么需要这么多：`AgentCtx` 的格是可选的，而**每一栏缺省时发什么**是一个
//   决定（空串？空表？省略这一栏？）。原来那些决定散在 `?? ''` 里。
// ═══════════════════════════════════════════════════════════
const FRAME_PROJECTIONS: Record<string, { from: keyof AgentCtx; fn: (ctx: AgentCtx) => unknown }> = {
  // ── 空值兜底：缺省时发空串 / 空表（原来写作 `?? ''` / `?? []`）──
  earlierMaybe: { from: 'earlier', fn: (ctx) => ctx.earlier ?? '' },
  filesMaybe: { from: 'files', fn: (ctx) => ctx.files ?? [] },
  readMaybe: { from: 'readFiles', fn: (ctx) => ctx.readFiles ?? [] },
  resultMaybe: { from: 'lastResult', fn: (ctx) => ctx.lastResult ?? '' },
  draftMaybe: { from: 'draft', fn: (ctx) => ctx.draft ?? '' },
  toolOrEmpty: { from: 'lastTool', fn: (ctx) => ctx.lastTool ?? '' },
  // ── 非空兜底（缺省时那句默认话本身就是判据的一部分）──
  lastOrNone: {
    from: 'lastResult',
    fn: (ctx) => ctx.lastResult ?? '（还没有做过任何动作）',
  },
  toolOrUnknown: { from: 'lastTool', fn: (ctx) => ctx.lastTool ?? 'unknown' },
  // ── 派生 ──
  describeDone: { from: 'history', fn: (ctx) => describeDone(ctx) },
  lastInput: { from: 'history', fn: (ctx) => lastInput(ctx) },
  readCount: { from: 'readFiles', fn: (ctx) => (ctx.readFiles ?? []).length },
  recentSteps: {
    from: 'history',
    fn: (ctx) =>
      (ctx.history ?? []).slice(-5).map((h) => `${h.tool}(${clip(h.input, 60)}) → ${clip(h.result, 200)}`),
  },
  writeEvidence: {
    from: 'history',
    fn: (ctx) =>
      (ctx.history ?? []).slice(-3).map((h, i, all) => {
        const writes = h.tool === 'write_file'
        const inputBudget = writes ? 600 : 60
        const resultBudget = writes ? 60 : i === all.length - 1 ? 600 : 200
        return `${h.tool}(${clip(h.input, inputBudget)}) → ${clip(h.result, resultBudget)}`
      }),
  },
  /**
   * 工具的静态风险基线。认不出的工具名**不放这一栏** ——
   * 0 分的意思是「只读」，不能用它冒充「未知」（`absent` 与 `unfilled` 必须分开）。
   */
  localToolRisk: {
    from: 'lastTool',
    fn: (ctx) => {
      const t = ctx.lastTool
      return t && isToolName(LOCAL_TOOLS, t) ? LOCAL_TOOLS[t].baseRisk : undefined
    },
  },
}

/**
 * 把**一个块**的 `frame:` 声明编成 `FrameSpec`。没写 `frame:` 就返回 `null`，
 * 消费方回退到代码里那份 —— **迁移因此可以逐个节点做，不必一次全搬**。
 *
 * 参数是 `DocBlock` 而不是块 id：**合规检查要对任意一份文本跑**
 * （`scripts/conformance.ts` 喂进来的是改坏过的），按 id 查只能看磁盘上那一份。
 *
 * ★ 两条**当场抛**（不是收进 `problems`）：投影名不在注册表里、格名既不是
 *   `AgentCtx` 的格又没给投影。不抛的话，那一栏会永远取到 `undefined` ——
 *   判定静默地少看一栏，而「少看一栏」正是这份文件要防的那件事。
 */
export function frameSpecFromBlock(b: DocBlock, node: string): FrameSpec | null {
  const f = b.frame
  if (!f) return null
  const where = `DECISION.md 的 '${b.id}'`
  return {
    node,
    fields: f.fields.map((x) => {
      const p = x.project ? FRAME_PROJECTIONS[x.project] : undefined
      if (x.project && !p) {
        throw new Error(
          `${where} 里，frame 投影 '${x.project}' 不在注册表里 —— ` +
            `可选：${Object.keys(FRAME_PROJECTIONS).join(' / ')}`,
        )
      }
      // 不写投影 ⇒ 格名就是格（`task` 读 `task`）。写错要当场报，不能静默当成原样取
      if (!p && !AGENT_CTX_KEYS.includes(x.key as keyof AgentCtx)) {
        throw new Error(
          `${where} 里，frame 的 '${x.key}' 既不是 ctx 的格名，也没给投影 —— ` +
            `ctx 只有 ${AGENT_CTX_KEYS.join(' / ')}`,
        )
      }
      return {
        key: x.key,
        from: p ? p.from : (x.key as keyof AgentCtx),
        // 界写一个数，按类型落到 chars（字符串）或 listMax（列表）——
        // 对另一种是惰性的，所以一个数就够（见 `FrameField`）
        chars: x.bound,
        listMax: x.bound,
        why: x.why,
        ...(p ? { project: p.fn } : {}),
      }
    }),
    excluded: f.excluded.map((e) => {
      if (!AGENT_CTX_KEYS.includes(e.field as keyof AgentCtx)) {
        throw new Error(
          `${where} 里，排除项 '${e.field}' 不是 ctx 的格名 —— ctx 只有 ${AGENT_CTX_KEYS.join(' / ')}`,
        )
      }
      return [e.field as keyof AgentCtx, e.why] as const
    }),
  }
}

/** 磁盘上那份 `DECISION.md` 里某个块的帧声明。消费方（`framed`）走这条 */
function frameFromDoc(blockId: string, node: string): FrameSpec | null {
  return frameSpecFromBlock(block(blockId), node)
}

/** 把声明编成 `state` —— 节点不再手拼 dict，帧的形状由声明决定 */
function framed(spec: FrameSpec, blockId: string) {
  // ★ **文件里写了 `frame:` 就以文件为准**，否则回退到代码里那份。
  //   于是迁移是逐节点可做的，而且「文件赢了」这件事有单测钉住。
  const use = frameFromDoc(blockId, spec.node) ?? spec
  const compile = (ctx: AgentCtx) => compileFrame(use, ctx)
  return {
    state: (ctx: AgentCtx) => compile(ctx).state,
    // ★ 同一份编译结果交给 `decide.ts`，让它把指纹 / 截断 / 「故意不看什么」
    //   带进 `decision` 事件。没有这一条，`compileFrame` 算出来的指纹
    //   **没有任何消费者** —— 那正是 §8.16 记的「声明了却没消费方」。
    frameArtifact: compile,
  }
}

/** 1 · 这一步需要动手吗 */
const FRAME_NEEDS_TOOL: FrameSpec = {
  node: 'loop.needsTool',
  fields: [
    { key: 'task', from: 'task', chars: 400, why: '整个判定的主体：问的是「这个任务还有没有没做的动作」' },
    {
      key: 'earlier',
      from: 'earlier',
      chars: EARLIER_MAX_CHARS,
      project: (ctx) => ctx.earlier ?? '',
      why: '多轮下「再读一遍那个文件」里的「那个」唯一能落地的地方（§8.2）',
    },
    {
      key: 'already_done',
      from: 'history',
      chars: DONE_LINE_MAX_CHARS,
      project: (ctx) => describeDone(ctx),
      why:
        '★ 必须是一份**清单**，不是一个计数。原来这里是 `steps_done: 2`，' +
        '实测任务「把 alpha.ts 里的 totalOf 抄到新文件 summary.ts」读完 alpha.ts 后判了' +
        '「不需要工具」，**文件从没被写出来** —— 因为「读过」和「写过」在计数里长得一样',
    },
    {
      key: 'files_known',
      from: 'files',
      chars: 200,
      listMax: 15,
      project: (ctx) => ctx.files ?? [],
      why: '任务里的「这两个文件」是一个**指代**，没有它落不到具体路径上',
    },
    {
      key: 'already_read',
      from: 'readFiles',
      chars: 200,
      listMax: 15,
      project: (ctx) => ctx.readFiles ?? [],
      why: '分不出「读了一个还是两个」，就无法确认任务说的「这两个」读完了没有（实测 0.86 误判）',
    },
    {
      key: 'last',
      from: 'lastResult',
      chars: 300,
      project: (ctx) => ctx.lastResult ?? '（还没有做过任何动作）',
      why: '刚刚发生了什么 —— 判「还要不要动手」时最近一步的结果是主要依据',
    },
  ],
  excluded: [
    ['cwd', '路径不进判定：目标由 `target` 那一栏（gradeRisk）或候选（pickInput）表达，工作目录本身没有信息'],
    ['canWrite', '「能不能写」是**代码**按精确规则判的（§8.1 第三行），不该让判定模型再判一遍'],
    ['canDelete', '「能不能删」是**代码**的规则，和 canWrite 同一道门 —— 它决定 `delete_file` 进不进候选，不进帧'],
    ['lastTool', '工具名单独列出来会诱导它去评判「上一个工具选得对不对」——那是 `stepOk` 的职责'],
    ['draft', '草稿是生成之后才有的东西；这一步根本还没到生成'],
  ],
}

/** 2 · 调哪个工具 */
const FRAME_PICK_TOOL: FrameSpec = {
  node: 'loop.pickTool',
  fields: [
    { key: 'task', from: 'task', chars: 400, why: '选工具的唯一依据是任务要什么' },
    {
      key: 'earlier',
      from: 'earlier',
      chars: EARLIER_MAX_CHARS,
      project: (ctx) => ctx.earlier ?? '',
      why: '挑工具时「上文」尤其重要 ——「那个文件」要靠它才能落到具体路径',
    },
    {
      key: 'already_done',
      from: 'history',
      chars: DONE_LINE_MAX_CHARS,
      project: (ctx) => describeDone(ctx),
      why: '★ 用一句话讲清「已经做过什么」，不丢一个数组让模型自己解析 —— 实测只放数组时它会重复选做过的动作',
    },
    {
      key: 'files_known',
      from: 'files',
      chars: 200,
      listMax: 20,
      project: (ctx) => ctx.files ?? [],
      why: '「还有没有可读的文件」决定 read_file 还在不在候选里',
    },
    {
      key: 'already_read',
      from: 'readFiles',
      chars: 200,
      listMax: 10,
      project: (ctx) => ctx.readFiles ?? [],
      why: '少了它会重复读同一个文件（§8.2：帧里没有的信号它判不出来）',
    },
    {
      key: 'last_result',
      from: 'lastResult',
      chars: 300,
      project: (ctx) => ctx.lastResult ?? '',
      why: '上一步的结果决定下一步该做什么',
    },
  ],
  excluded: [
    ['cwd', '同 needsTool：工作目录本身没有信息，目标由候选表达'],
    ['canWrite', '「能不能写」是代码的规则，不是判定 —— 它决定 `write_file` 进不进候选，不进帧'],
    ['canDelete', '同 canWrite：它决定 `delete_file` 进不进候选；进了候选就说明调用方已经开了这道门'],
    ['lastTool', '★ 候选本身**已经按做过的动作重建过**（§8.4）；再把「上一个是什么」放进来，会让「还有哪些工具」和「已经做过什么」互相打架'],
    ['draft', '还没到生成那一步'],
  ],
}

/** 3 · 挑哪个输入 */
const FRAME_PICK_INPUT: FrameSpec = {
  node: 'loop.pickInput',
  fields: [
    { key: 'task', from: 'task', chars: 400, why: '判「要读哪个文件」必须知道任务要什么' },
    {
      key: 'tool',
      from: 'lastTool',
      chars: 40,
      project: (ctx) => ctx.lastTool ?? '',
      why: '同一个输入槽对不同工具含义不同：read_file 挑的是「读哪个」',
    },
    {
      key: 'already_read',
      from: 'readFiles',
      chars: 200,
      listMax: 10,
      project: (ctx) => ctx.readFiles ?? [],
      why: '读过的要从候选里去掉，判定得看得见「读过哪些」才知道剩哪些',
    },
    {
      key: 'candidates',
      from: 'files',
      chars: 200,
      listMax: 20,
      project: (ctx) => ctx.files ?? [],
      why: '候选的**全集**。真正发出去的是 fileOptions 的重建结果，这一栏是让判定知道总体有多少',
    },
  ],
  excluded: [
    ['cwd', '同前：目标由候选表达，不由工作目录表达'],
    [
      'history',
      '★ 候选（`fileOptions`）本身已经是「还没读过的那些」这个闭集的投影；再给一遍历史会让「还剩哪些」和「做过什么」两个信号互相打架（§8.4 的同一个坑）',
    ],
    ['canWrite', '写路径的候选不由这里产生 —— `write_content` 生成路径，判定不参与'],
    ['canDelete', '删哪一个不由这一栏产生 —— 目标路径来自调用方的输入来源（同 `write_file`）'],
    ['earlier', '这一步是在一个已经选定的工具内部挑参数，指代关系由 task + 候选表达就够了'],
    ['lastResult', '结果的**内容**与「挑哪个文件」无关；它是 `stepOk` 与 `canDeliver` 的依据'],
    ['draft', '还没到生成那一步'],
  ],
}

/** 4 · 这次调用多危险 */
const FRAME_GRADE_RISK: FrameSpec = {
  node: 'loop.gradeRisk',
  fields: [
    {
      key: 'tool',
      from: 'lastTool',
      chars: 40,
      project: (ctx) => ctx.lastTool ?? 'unknown',
      why: '风险的第一依据是哪个工具 —— 但**认不出来时不编一个数**',
    },
    {
      key: 'base_risk',
      from: 'lastTool',
      chars: 12,
      project: (ctx) => {
        const t = ctx.lastTool
        return t && isToolName(LOCAL_TOOLS, t) ? LOCAL_TOOLS[t].baseRisk : undefined
      },
      why:
        '工具的静态风险基线（`act-local.ts` 的 `baseRisk`）。' +
        '★ 认不出的工具名**不放这一栏** —— 0 分的意思是「只读」，不能用它冒充「未知」。' +
        '这就是 `absent` 与 `unfilled` 必须分开的原因：这一栏「今天不适用」是**正常状态**',
    },
    {
      key: 'target',
      from: 'history',
      chars: 200,
      project: (ctx) => lastInput(ctx),
      why: '判风险要看**这一调的目标**，不是工具名 —— `rm -rf /` 和 `ls` 的危险程度差在参数上',
    },
    { key: 'task', from: 'task', chars: 300, why: '同一个动作在不同任务下风险不同（写配置文件 vs 写 /etc）' },
  ],
  excluded: [
    ['cwd', '工作目录由 target 的路径体现；单列出来是冗余'],
    ['files', '目录里有哪些文件与「这一次调用多危险」无关'],
    ['readFiles', '读过什么与风险无关'],
    ['canWrite', '能不能写是另一道门；这里问的是**已经决定要做的这一调**有多危险'],
    ['canDelete', '能不能删是另一道门（同 canWrite）；这里问的是**已经决定要做的这一调**有多危险，而 base_risk 已经把 destructive 标出来了'],
    ['earlier', '多轮的上文不改变这一次调用的风险'],
    [
      'lastResult',
      '★ 上一步的**输出内容**绝不能进这一栏：它是不可信文本，而这一栏的输出会驱动授权闸门 —— 让它读工具输出，等于让工具输出有机会推动风险分',
    ],
    ['draft', '还没到生成那一步'],
  ],
}

/** 5 · 这一步成功了吗 */
const FRAME_STEP_OK: FrameSpec = {
  node: 'loop.stepOk',
  fields: [
    {
      key: 'tool',
      from: 'lastTool',
      chars: 40,
      project: (ctx) => ctx.lastTool ?? 'unknown',
      why: '判据里写着「the target it names is the one that was requested」，得知道是哪个工具',
    },
    {
      key: 'input',
      from: 'history',
      chars: 200,
      project: (ctx) => lastInput(ctx),
      why: '判据包含「返回的目标就是请求的那个」—— 没有请求就没有可比的对象',
    },
    { key: 'output', from: 'lastResult', chars: 500, project: (ctx) => ctx.lastResult ?? '', why: '这一步的**唯一证据**' },
    {
      key: 'already_read',
      from: 'readFiles',
      chars: 12,
      project: (ctx) => (ctx.readFiles ?? []).length,
      why: '一个计数就够：这一步判的是单次成功与否，不需要读过的清单',
    },
  ],
  excluded: [
    [
      'task',
      '★★ 四次事故里最贵的一次。帧里带着 task、问题写着「for the task」、判据写着「what the task needed」，' +
        '三处一起把**这一步**的判定拉到了**任务级**。实测任务「读一下 invoice.ts」第一步 list_dir 返回文件列表，' +
        '它确实成功了，但没回答「这个文件定义了哪些函数」，于是 ok=0.470 判否 → stop → **整个循环结束**：' +
        '任何需要多于一个工具的任务都跑不完。「任务完成了吗」是 isDone 的职责',
    ],
    ['cwd', '与「这一次调用本身成没成」无关'],
    ['files', '同上：成功与否看的是这一次的输入与输出'],
    ['canWrite', '与这一步的成败无关'],
    ['canDelete', '与这一步的成败无关'],
    ['earlier', '★ 上文会把判定拉向「整体进展如何」，而这一栏问的是刚刚那一次调用'],
    ['draft', '草稿在这一步之后才有'],
  ],
}

/** 6 · 任务完成了吗 */
const FRAME_IS_DONE: FrameSpec = {
  node: 'loop.isDone',
  fields: [
    { key: 'task', from: 'task', chars: 400, why: '判的是「任务要求的都做了」—— 没有任务就没有判据' },
    {
      key: 'already_read',
      from: 'readFiles',
      chars: 200,
      listMax: 15,
      project: (ctx) => ctx.readFiles ?? [],
      why:
        '★ 这个问题靠**覆盖**就能答：任务说的那两个文件读了没有。' +
        '原来没有这一栏时，判定只能从被截断的结果里去找函数名（实测 0.22 误判 keep_going）',
    },
    {
      key: 'steps',
      from: 'history',
      chars: 260,
      project: (ctx) =>
        (ctx.history ?? []).slice(-5).map((h) => `${h.tool}(${clip(h.input, 60)}) → ${clip(h.result, 200)}`),
      why:
        '★ 结果留 **200 字符不是 80**，这是量出来的：任务「这两个文件各导出了什么函数」，' +
        '80 字符时 alpha.ts 那条正好断在 `Order` 接口之后、**函数名 totalOf 在截断点之后** —— ' +
        '结果留 80 判 keep_going(0.35)，留 200 判 finish(0.96)。' +
        '**内容看得到时它是直接判断，不是推理**，余量大得多',
    },
  ],
  excluded: [
    ['cwd', '与「任务做完没有」无关'],
    ['files', '「目录里有什么」不等于「任务要求的做完了没」—— 正是 needsTool 记的那个陷阱的另一面'],
    ['canWrite', '与完成度无关'],
    ['canDelete', '与完成度无关'],
    ['earlier', '多轮的上文属于「之前问过什么」；完成度由 task + 覆盖 + 步骤本身决定'],
    ['lastTool', '单列上一个工具会把判定拉向「刚才那步怎么样」—— 那是 stepOk 的层级'],
    ['lastResult', '最近一条结果已经**逐字**在 `steps` 里了，单列出来是重复的语气加强'],
    ['draft', '还没到生成那一步'],
  ],
}

/** 7 · 这个回答能交付吗 */
const FRAME_CAN_DELIVER: FrameSpec = {
  node: 'loop.canDeliver',
  fields: [
    { key: 'task', from: 'task', chars: 400, why: '判据是「任务要求的事做了、并如实报告」，两边都要有任务' },
    {
      key: 'answer',
      from: 'draft',
      chars: 900,
      project: (ctx) => ctx.draft ?? '',
      why: '★ 判的对象就是**刚生成的这份草稿** —— 它不在帧里，这一栏就没有意义',
    },
    {
      key: 'evidence',
      from: 'history',
      chars: 600,
      /*
        ★ 返回**字符串**，不是数组 —— 两个理由，都不是风格问题：

        ① 声明里写的是 `chars: 600`，而 `chars` 只管字符串。这一栏以前返回数组，
           于是那个预算**从来没有生效过** —— 真正起作用的是下面逐条的
           `inputBudget` / `resultBudget`（那也有用，见下）。一条写着 600 的预算
           没人读，正是 §8.16 那类「声明了却没有消费方」。

        ② 它读 `history` ⇒ 不可信（TODO §7）。而信任边界包的是字符串；
           数组要包就得把标签放进值里，那会弄坏把帧值当数据读的消费方
           （实测：`rule-judge` 读 `files_known` / `steps` / `already_read`
           走的是 `Array.isArray`）。这一栏**没有任何代码**按数组读它，
           所以它能安全地变成字符串，从而拿到边界。

        交付闸门是这个仓库里安全上最要紧的判定之一（它决定一份回答能不能发出去），
        而它的主输入以前既没有生效的预算、也没有信任标记。
      */
      project: (ctx) =>
        (ctx.history ?? [])
          .slice(-3)
          .map((h, i, all) => {
            // ★ 预算跟着**载荷**走，不跟着位置走。以前是「最后一条 600、其余 200」，
            //   而输入一律 clip 到 60。那对 read_file 对，对 write_file 两样都反了：
            //   写操作的载荷是**输入**（`路径\n内容`），结果只有一句「已写入 X」。
            //   实测：交付闸门核对一份如实报告「写进去的和原文不一样」的回答时，
            //   `unsupported` 判 0.70；把写的输入给到 600、结果压到 60 之后同一个回答判 0.21。
            const writes = h.tool === 'write_file'
            const inputBudget = writes ? 600 : 60
            const resultBudget = writes ? 60 : i === all.length - 1 ? 600 : 200
            return `${h.tool}(${clip(h.input, inputBudget)}) → ${clip(h.result, resultBudget)}`
          })
          .join('\n'),
      why:
        '★ 交付闸门要拿工具结果**逐句核对**回答，所以这一栏的预算比别处宽。' +
        '实测把证据 clip 到 100 字符时，它**正确地**判出 unsupported=0.67 —— ' +
        '判定是对的，是帧喂少了；改成 600 后立刻通过（§8.2 的原型事故）',
    },
  ],
  excluded: [
    ['cwd', '与「回答有没有证据支撑」无关'],
    ['files', '目录清单不是证据；证据是**做过什么、看到了什么**'],
    ['readFiles', '读过哪些文件同样不是证据本身'],
    ['canWrite', '与交付判据无关'],
    ['canDelete', '与交付判据无关'],
    ['earlier', '★ 多轮的上文会把「这份草稿说的是不是这一轮做过的事」冲淡；交付核对的是**这一轮**的证据'],
    ['lastTool', '单列上一个工具会把判定拉向「刚才那步」，而它要核对的是整份草稿'],
    [
      'lastResult',
      '★ 最近一条结果已经逐字在 `evidence` 里了。单列一份会让**最近一步**获得不成比例的权重，' +
        '而交付核对要求的是「每一句都能追溯到某条证据」',
    ],
  ],
}

/**
 * 七个声明的注册表，按节点 id 索引。
 *
 * 导出是为了让**上面**的层（`agent.ts`、测试、以及将来的轨迹视图）拿得到
 * 「这个判定该看什么」，而不必去读它的函数体。
 */
export const FRAME_SPECS: Readonly<Record<string, FrameSpec>> = {
  'loop.needsTool': FRAME_NEEDS_TOOL,
  'loop.pickTool': FRAME_PICK_TOOL,
  'loop.pickInput': FRAME_PICK_INPUT,
  'loop.gradeRisk': FRAME_GRADE_RISK,
  'loop.stepOk': FRAME_STEP_OK,
  'loop.isDone': FRAME_IS_DONE,
  'loop.canDeliver': FRAME_CAN_DELIVER,
}

// ═══════════════════════════════════════════════════════════
// DECISION.md 的编译
//
// ★ **这是运行时真的在用的那一份**，不是文档。
//
// 在这之前 `DECISION.md` 是一份被机器对账的文档：代码是正本，测试
// 双向检查两边一致。现在反过来了 —— 问到判定模型的**问题和策略**
// 都从文件里编译出来，代码只留帧构造器（理由见模块头）。
//
// ⚠️ **代价要说清楚：这个模块在 import 时会读盘。** 一个纯计算的内核
// 多了一处 IO 副作用。换来的是「改文件 → 行为变」这条主张成立，
// 而那正是 DECISION.md 存在的全部理由。
// ═══════════════════════════════════════════════════════════

/**
 * 读并解析 `DECISION.md`。
 *
 * 路径用 `import.meta.url` 相对定位，所以 `src/` 下跑和发布后从 `dist/`
 * 跑都找得到同一个文件（`package.json` 的 `files` 里有它）。
 *
 * @throws 文件读不到、或者解析出任何 problem。
 *   **解析出问题必须当场炸，不能降级。** 一个编译不了的谓词会变成
 *   「这条规则永不命中」= **一道空闸门** —— 作者以为自己加了一道人
 *   工审核，实际没有，而且是 fail open 的。§8.5 那两条闸门的存在理由
 *   就是这个，静默丢掉它们的后果比启动失败严重得多。
 */
function loadDecisionDoc(): DecisionDoc {
  const url = new URL('../DECISION.md', import.meta.url)
  let md: string
  try {
    md = readFileSync(url, 'utf8')
  } catch (err) {
    // 吞的是「文件不在」—— 把它换成一条**能直接照做**的报错。
    // 内核没有 DECISION.md 就没有判定规格，没有可用的降级。
    throw new Error(
      `读不到判定规格 ${url.pathname}（${(err as Error).message}）—— ` +
        `JevLoop 的问题与策略都从 DECISION.md 编译，没有它就没有判定节点`,
    )
  }
  const doc = parseDecisionDoc(md)
  if (doc.problems.length > 0) {
    const lines = doc.problems.map((p) => `  DECISION.md:${p.line}  ${p.message}`).join('\n')
    throw new Error(`DECISION.md 有 ${doc.problems.length} 处解析不了：\n${lines}`)
  }
  return doc
}

const DOC = loadDecisionDoc()

/**
 * `DECISION.md` 里 `## generator` 那一段 —— **生成器的 system prompt**。
 *
 * 这就是「一份文件，两个消费者」的另一半：结构块编译成判定模型的问题，
 * 散文进 system prompt。它和判定节点住同一个文件，所以「这条 loop 怎么
 * 作决定」和「它怎么写答案」是放在一起改的，不会一个改了另一个忘掉。
 *
 * 空字符串是允许的（解析器不强制这一段），这时 `HttpGenerator` 退回它
 * 内置的那句 —— 见 `llm.ts` 的 `DEFAULT_INSTRUCTION`。
 */
export const GENERATOR_INSTRUCTION: string = DOC.generatorSection

/** 按块 id 取块。写错名字要当场知道，不是静默给一个空问题集 */
function block(id: string): DocBlock {
  const b = DOC.blocks.find((x) => x.id === id)
  if (!b) {
    throw new Error(
      `DECISION.md 里没有 '${id}' 这个块（现有：${DOC.blocks.map((x) => x.id).join('、')}）`,
    )
  }
  return b
}

/**
 * 把一条策略编译出来。
 *
 * 两条策略（`pick_tool` / `pick_input`）的**问题**是运行时算的（候选每步
 * 重建），所以它们不能整块编译 —— 但策略仍然是文件说了算，分开取。
 */
function policyOf(id: string, gates: GateOverrides = {}): { policy: PolicyRule<AnswerSet>[]; applied: string[] } {
  const pol = compilePolicy(block(id), gates)
  if (!pol) throw new Error(`DECISION.md 的 '${id}' 没有 policy —— 一个没有策略的判定节点不会产生任何动作`)
  if (!pol.ok) {
    throw new Error(
      `DECISION.md 的 '${id}' 有编译不了的谓词：${pol.problems.join('；')} —— ` +
        `「看不懂这个谓词」不能编码成「这条永远命中」，所以只能停下`,
    )
  }
  return { policy: pol.rules, applied: pol.applied }
}

// ═══════════════════════════════════════════════════════════
// 门限覆盖
// ═══════════════════════════════════════════════════════════

/**
 * 七份规格各自对应 `DECISION.md` 里的哪个块。
 *
 * 名字对照写在这里、只写一次：规格的 `id` 是 `loop.pickTool`（给事件和界面看），
 * 块的 id 是 `pick_tool`（文件里的标题）。两者**故意不同** —— 一个是运行时
 * 身份，一个是文档锚点 —— 但覆盖表用的是后者，因为写覆盖的人手上是那份文件。
 */
const SPEC_BLOCKS: ReadonlyArray<readonly [string, string]> = [
  ['needs_tool', 'loop.needsTool'],
  ['pick_tool', 'loop.pickTool'],
  ['pick_input', 'loop.pickInput'],
  ['grade_risk', 'loop.gradeRisk'],
  ['step_ok', 'loop.stepOk'],
  ['is_done', 'loop.isDone'],
  ['can_deliver', 'loop.canDeliver'],
]

/**
 * 一份 `DECISION.md` 的**全部**帧声明 —— 合规检查的入口（`frameSpecViolations` 的输入）。
 *
 * ★★ 这个函数是**为了补一个洞**才存在的。`frameSpecViolations` 在此之前
 *   只被单测拿手拼的 spec 调过，磁盘上那份文件**从来没被它检查过**。
 *   后果实测过（2026-09-23）：把 `needs_tool` 的
 *   `- cwd —— 路径不进判定：…` 整行删掉，
 *
 *     · 解析器不管 —— 行没了就是没了，没有东西记得它曾经在
 *     · `frameSpecFromBlock` 也不管 —— 剩下的每一行都是合法的
 *     · `jevloop spec` 打印「✓ parses clean and every predicate compiles」，exit 0
 *     · `npm test` 61 个相关用例全绿
 *
 *   于是 §8.14 那条「删掉一个字段之后没有任何东西记得它曾经在过」
 *   **原样活在这份用来消灭它的文件里**。检查写好了、没人跑，
 *   和没有检查是同一件事（§8.16 的「声明了却没消费方」）。
 *
 * 拿 `DecisionDoc` 而不是读磁盘，是为了让合规检查能对**改坏过的文本**跑。
 * 缺块要当场抛：`SPEC_BLOCKS` 里少一个块，说明文件已经不合格了。
 */
export function frameSpecsOf(doc: DecisionDoc): FrameSpec[] {
  const out: FrameSpec[] = []
  for (const [blockId, node] of SPEC_BLOCKS) {
    const b = doc.blocks.find((x) => x.id === blockId)
    if (!b) {
      throw new Error(
        `DECISION.md 里没有 '${blockId}' 这个块（现有：${doc.blocks.map((x) => x.id).join('、')}）—— ` +
          `七个判定各对应一个块，少一个就没有判定规格`,
      )
    }
    const spec = frameSpecFromBlock(b, node)
    if (spec) out.push(spec)
  }
  return out
}

// ═══════════════════════════════════════════════════════════
// 加载即验：帧声明不完整就**不许加载**
// ═══════════════════════════════════════════════════════════
//
// ★ 放在这里而不是 `loadDecisionDoc()` 里：`frameSpecsOf` 依赖 `SPEC_BLOCKS`，
//   而 `SPEC_BLOCKS` 在 `DOC` 之后才定义（模块尾的 `const`）。
//
// ★ 这一段补的是一个**实测过的洞**（2026-09-23）：`frameSpecViolations` 在此之前
//   只被单测拿手拼的 spec 调过。把 `needs_tool` 的 `- cwd —— …` 整行删掉，
//   解析、谓词、`jevloop spec`、相关测试**四层全绿** —— §8.14 那条
//   「删掉一个字段之后没有任何东西记得它曾经在过」原样活在这份用来消灭它的文件里。
//
//   和上面 `loadDecisionDoc` 对解析问题抛是同一个态度：**没有判定规格就没有
//   可用的降级**，所以宁可在加载时停住，也不带着一份缩水的声明跑起来。
{
  const bad = frameSpecViolations(frameSpecsOf(DOC))
  if (bad.length > 0) {
    throw new Error(
      `DECISION.md 的帧声明不完整（${bad.length} 处）—— ` +
        `每一个判定都要说清它**看什么**、以及**故意不看什么（带理由）**：\n` +
        bad.map((m) => `  ${m}`).join('\n'),
    )
  }
}

/**
 * 覆盖表里可以写哪些键 —— 由 `DECISION.md` **现算**，不是抄一份清单。
 *
 * 抄一份的话，文件里改了问题名而清单没改，报错信息就会指着一个不存在的键。
 */
export function gateKeys(): string[] {
  const keys: string[] = []
  for (const [blockId] of SPEC_BLOCKS) {
    const b = block(blockId)
    // 同一个问题上带门限的规则数 —— 决定这个键要不要带下标（见 `compilePolicy`）
    const tiers = new Map<string, number>()
    for (const r of b.policy) {
      // 只列出**带门限**的谓词：`picked:` 没有数可以调，列进去等于骗人
      if (!hasThreshold(r.when)) continue
      const q = predicateQuestion(r.when, b)
      if (q) tiers.set(q, (tiers.get(q) ?? 0) + 1)
    }
    for (const [q, n] of tiers) {
      // 一档的写裸名字（最常见的写法最短）；多档的**逐档列出**，
      // 因为裸名字只改第 0 档，列一个 `x.q` 会让人以为改的是全部
      if (n === 1) keys.push(`${blockId}.${q}`)
      else for (let i = 0; i < n; i++) keys.push(`${blockId}.${q}[${i}]`)
    }
  }
  return [...new Set(keys)].sort()
}

/**
 * 覆盖之后，**同一个问题上的多档门限必须还保持可达**。
 *
 * ★ 这不是洁癖，是一个真的会静默发生的坑。`grade_risk` 有两条：
 *
 *     score:risk >= 2 → ask_human      （先判，严）
 *     score:risk >= 1 → auto_audit     （后判，宽）
 *
 *   `resolvePolicy` 是**顺序求值、第一条命中就返回**。所以把
 *   `grade_risk.risk` 覆盖成 3 会让两条都变成 `>= 3` —— 第二条**永远不可达**，
 *   而这个 agent 就少了一道「中等风险也要审计」的闸门，**一个错都不报**。
 *
 * 判据：同一个块里、同一个问题上、同样是 `>=` 的规则，门限必须**严格递减**。
 * 递增或相等都意味着后面那条被前面盖住了。
 */
function tierProblems(
  blockId: string,
  /**
   * ⚠️ **已经按块切好的**那张表（`{ 问题 id: 门限 }`），不是整份覆盖表。
   *
   * 第一版在这里又 `splitGates()` 了一次 —— 而入参已经没有 `<块>.` 前缀了，
   * 于是每一项都被当成「没有点」丢进 `unused`，`mine` 恒为空，
   * **这道校验从来没有生效过**（写测试时才发现）。`splitGates` 只吃整份表。
   */
  mine: Readonly<Record<string, number>>,
): { problems: string[]; keys: string[] } {
  const b = block(blockId)
  if (Object.keys(mine).length === 0) return { problems: [], keys: [] }
  const problems: string[] = []
  const keys: string[] = []
  const seen = new Map<string, number>()

  // 同一个问题上带门限的规则有哪些（下标），用来算档位
  const tierMap = new Map<string, number[]>()
  b.policy.forEach((r, i) => {
    if (!hasThreshold(r.when)) return
    const q = predicateQuestion(r.when, b)
    if (!q) return
    tierMap.set(q, [...(tierMap.get(q) ?? []), i])
  })
  const tiers = tierMap

  b.policy.forEach((r, index) => {
    const src = r.when.trim()
    if (!/^(?:top|prob:[\w.-]+|score:[\w.-]+)\s*>=/.test(src)) return
    const q = predicateQuestion(src, b)
    if (!q) return
    // 第 0 档认裸名字，其余档认下标 —— 和 `compilePolicy` 同一套规则
    const tier = (tiers.get(q) ?? []).indexOf(index)
    const override = mine[`${q}[${tier}]`] ?? (tier === 0 ? mine[q] : undefined)
    const effective = override ?? Number(/[0-9]*\.?[0-9]+$/.exec(src)?.[0] ?? NaN)
    const prev = seen.get(q)
    if (prev !== undefined && !(effective < prev)) {
      problems.push(
        `${blockId}.${q}：覆盖之后第 ${seen.size} 档是 >= ${prev}、这一档（${r.action}）是 >= ${effective} —— ` +
          `策略是**顺序求值、第一条命中就返回**，所以这一条**永远不会被求值**，` +
          `那等于这里少了一道闸门。同一问题上的多档门限必须严格递减`,
      )
      // **键由这里给出**，不让调用方回头去切那句话里的字符串
      keys.push(`${blockId}.${q}`)
    }
    seen.set(q, effective)
  })
  return { problems, keys }
}

/**
 * 整块编译：问题 + 策略都来自文件。
 *
 * 用于问题集**不随状态变**的那五个节点。候选每步重建的那两个用
 * `askOf` + `policyOf` —— 因为 markdown 表达不了 `toolsFor(ctx)`。
 *
 * ── 为什么要显式传 `expect` ────────────────────────────────────
 *
 * ★ 问题的名字现在住在 **markdown** 里，而代码在按名字读答案
 *   （`agent.ts` 读 `answers.risk.score`）。这层耦合是真的存在，
 *   藏起来只会让它变成运行时的 `undefined`。
 *
 *   传 `expect` 一次做两件事：
 *
 *   1. **类型**：TS 拿得到 `{ risk: ScoreQuestion }`，于是 `answers.risk.score`
 *      仍然是有类型的，不是 `any`。
 *   2. **启动时校验**：文件里的问题 id 和声明的不一致就当场炸 ——
 *      改错了名字会立刻知道，而不是等到某一步 `answers.risk` 是 undefined。
 *
 *   这比改之前**更严**：以前 id 只存在于代码里，没人检查文件对不对得上。
 */
function compiled<Q extends QuestionSet>(
  id: string,
  expect: readonly (keyof Q & string)[],
): { questions: Q; policy: PolicyRule<AnswerSet>[] } {
  const b = block(id)
  const q = compileQuestions(b)
  if (!q) throw new Error(`DECISION.md 的 '${id}' 编译不出问题集`)

  const actual = Object.keys(q).sort()
  const wanted = [...expect].sort()
  if (actual.join(',') !== wanted.join(',')) {
    throw new Error(
      `DECISION.md 的 '${id}' 问的是 [${actual.join(', ')}]，而代码声明的是 [${wanted.join(', ')}] —— ` +
        `代码在按名字读答案，对不上就是运行时的 undefined`,
    )
  }
  return { questions: q as Q, ...policyOf(id) }
}

/** 块里唯一那个问题的 `ask` 原文 —— 给「候选运行时算」的那两个块用 */
function askOf(id: string, expect: readonly string[]): string {
  const b = block(id)
  const actual = b.questions.map((q) => q.id)
  // 同样校验：这两个块的**问题**由代码算（候选每步重建），但问题 id
  // 仍然要和文件对上 —— 代码在按 `answers.tool` / `answers.file` 读
  if (actual.join(',') !== [...expect].join(',')) {
    throw new Error(
      `DECISION.md 的 '${id}' 问的是 [${actual.join(', ')}]，而代码声明的是 [${expect.join(', ')}]`,
    )
  }
  const q = b.questions[0]
  if (!q) throw new Error(`DECISION.md 的 '${id}' 里没有问题，取不到 ask`)
  return q.ask
}


// ═══════════════════════════════════════════════════════════
// 阈值集中在这里
//
// 单独抽出来是为了「改一个数就能调整行为」，而且这些数**不该拍脑袋定**：
// 判定模型出厂往往是未校准的，阈值该用你自己的标注数据算出来。
// ═══════════════════════════════════════════════════════════

/*
 * 门限**不在这里** —— 它们现在住在 `DECISION.md` 的 `policy:` 里
 * （`prob:ok >= 0.6` 这样写）。这里曾经有一个 `T` 对象，理由是
 * 「改一个数就能调整行为」；搬进文件之后同一个目的达标得更彻底：
 * 连**哪条规则用它、命中之后做什么**都在一起，不用两头看。
 */
// ═══════════════════════════════════════════════════════════
// 1 · 这一步需要动手吗
//
// 不需要动手就直接生成回答，**省掉整个工具循环**。
// 常规 agent 也"判断"这件事，但方式是让大模型输出一段话来表达它。
// ═══════════════════════════════════════════════════════════

/**
 * 这一步需要动手吗。`use_tool` / `answer` —— 后者**直接跳到生成、省掉整个工具循环**，
 * 所以这是最省的一步，也是最该早判的一步。
 */
export const needsTool = defineDecision({
  id: 'loop.needsTool',
  describe: '这一步需要调用工具，还是可以直接回答？',

  ...framed(FRAME_NEEDS_TOOL, 'needs_tool'),

  // 问题与策略都来自 DECISION.md 的 needs_tool 块
  ...compiled<{ needs_tool: NoulQuestion }>('needs_tool', ['needs_tool']),
})

// ═══════════════════════════════════════════════════════════
// 2 · 用哪个工具
//
// ★ 选项**每一步重建**，不是一开始定死的。
//   定死的选项列表会让模型去选一个早就不存在的动作 ——
//   比如刚写完文件，"write_file" 就不该再出现在候选里。
// ═══════════════════════════════════════════════════════════

/**
 * 下一步调哪个工具。候选由 `toolsFor(ctx)` **每步重建**：做过的动作会消失，
 * 还没读过的文件仍然在。选中项概率不过门限就 `escalate`，**不猜**。
 */
export const pickTool = defineDecision({
  id: 'loop.pickTool',
  describe: '下一步调用哪个工具（选项随已做的动作动态重建）',

  ...framed(FRAME_PICK_TOOL, 'pick_tool'),

  // ★ 候选**每步重建**（`toolsFor`），而 markdown 表达不了函数 ——
  //   所以问题由代码算，`ask` 原文和策略仍来自文件。
  //   文件里那个块写了 `dynamic: toolsFor(ctx)` 就是在声明这件事。
  questions: (ctx: AgentCtx) => ({
    tool: choice(askOf('pick_tool', ['tool']), toolsFor(ctx)),
  }) satisfies { tool: ChoiceQuestion },
  ...policyOf('pick_tool'),
})

// ═══════════════════════════════════════════════════════════
// 2b · 给选定的工具挑一个输入
//
// 审计 N3：工具参数以前是**写死的代码**（`defaultInput` 永远返回 `files[0]`），
// 配合 `toolsFor` 会把用过的动作从候选里删掉，结果是
// **一个 agent 生命周期内 read_file 只能触发一次，且只能读第一个文件** ——
// 任务「读取目录里的**全部** TypeScript 文件」在这个实现下不可能完成。
//
// 按三分法，这是「挑选」不是「生成」，所以它该是一次判定：
// 候选 = 还没读过的文件，由 `fileOptions` 每步重建。
//
// 「写什么内容」是生成，仍由调用方提供（不在本次范围内）。
// ═══════════════════════════════════════════════════════════

/**
 * 给已选定的工具挑一个输入（读 / 写哪个文件）。
 *
 * 调用方必须先问 `hasFileOptions(ctx)`：**没有候选就不要问** ——
 * 一个 `criteria` 为空的 choice 是无效问题，只会拿到无意义的答案。
 */
export const pickInput = defineDecision({
  id: 'loop.pickInput',
  describe: '给已选定的工具挑一个输入（读/写哪个文件）',

  ...framed(FRAME_PICK_INPUT, 'pick_input'),

  // 同 `pickTool`：候选由 `fileOptions` 每步重建，问题留代码，策略来自文件
  // `satisfies` 在这里而不是在 `choice(...)` 上：要断言的是**这个对象**
  // 的形状 —— 代码在按 `answers.file` 读答案
  questions: (ctx: AgentCtx) =>
    ({
      file: choice(pickInputInstructions(ctx), fileOptions(ctx)),
    }) satisfies { file: ChoiceQuestion },
  ...policyOf('pick_input'),
})


// ═══════════════════════════════════════════════════════════
// 3 · 这次调用多危险
//
// 原始问题：以前的判断只有两种极端 ——
//   要么所有工具全放行（危险），要么每次都弹窗问人（没法用）。
// 按风险分级之后，只有真正不可逆的操作才需要授权。
//
// ★ 硬闸门：不可逆操作必须显式授权，**不给概率任何绕过机会**。
//   判定模型可以决定「要不要问人」，绝不能决定「要不要跳过授权」。
// ═══════════════════════════════════════════════════════════

/**
 * 给这次工具调用打风险分，驱动分级审批。`ask_human` / `auto_audit` / `auto`。
 *
 * ★ **授权闸门不接受概率绕过**：`risk ≥ 2` 是一条硬规则。
 * 判定模型可以决定「要不要问人」，**绝不能**决定「要不要跳过授权」。
 */
export const gradeRisk = defineDecision({
  id: 'loop.gradeRisk',
  describe: '给这次工具调用打风险分，驱动分级审批',

  ...framed(FRAME_GRADE_RISK, 'grade_risk'),

  // 问题与策略都来自 DECISION.md 的 grade_risk 块。
  // 那条硬闸门（risk 够高就必须授权）现在写在文件里 —— 见那个块的 policy。
  ...compiled<{ risk: ScoreQuestion; needs_auth: NoulQuestion }>('grade_risk', ['risk', 'needs_auth']),
})

// ═══════════════════════════════════════════════════════════
// 4 · 这一步成功了吗
//
// 常规做法是每一步都叫一次大模型来判断"工具输出看起来对吗"。
// ═══════════════════════════════════════════════════════════

/**
 * 刚才那次工具调用成功了吗。`continue` / `stop`。
 *
 * **没有重试分支**：重试需要一个错误分类策略，而那个策略不存在 ——
 * 所以动作名只承诺实际发生的事（以前叫 `retry_or_stop`，名字承诺了做不到的事）。
 */
export const stepOk = defineDecision({
  id: 'loop.stepOk',
  describe: '刚才那次工具调用是否达到了预期效果',

  ...framed(FRAME_STEP_OK, 'step_ok'),

  // 问题与策略都来自 DECISION.md 的 step_ok 块
  ...compiled<{ ok: NoulQuestion }>('step_ok', ['ok']),
})

// ═══════════════════════════════════════════════════════════
// 5 · 任务完成了吗
//
// 常规做法是 max_iter 硬切。语义早停能让简单的任务立刻结束，
// 而不是傻等到迭代上限。
// ═══════════════════════════════════════════════════════════

/**
 * 任务完成了吗。`finish` / `keep_going`。
 *
 * 语义早停：简单的任务立刻结束，而不是傻等到 `maxSteps` 上限。
 */
export const isDone = defineDecision({
  id: 'loop.isDone',
  describe: '任务是否已经完成，可以开始生成回答了',

  ...framed(FRAME_IS_DONE, 'is_done'),

  // 问题与策略都来自 DECISION.md 的 is_done 块
  ...compiled<{ done: NoulQuestion }>('is_done', ['done']),
})

// ═══════════════════════════════════════════════════════════
// 6 · 这个回答能交付吗
//
// 原始问题：以前根本没有这一步，生成完直接返回，
// 靠事后人工抽查。现在每条输出都能过一遍闸门。
// ═══════════════════════════════════════════════════════════

/**
 * 生成的回答能交付吗。`deliver` / `revise`。
 *
 * 它拿工具结果逐句核对回答，所以 `evidence` 的预算给得比别处宽（最近一次 600 字符）：
 * **帧喂少了会让它"正确地"判出「回答里有证据不支持的内容」—— 那是帧的问题，
 * 不是回答的问题**（§8.2）。
 */
export const canDeliver = defineDecision({
  id: 'loop.canDeliver',
  describe: '生成的回答是否完整、准确、可以直接交付',

  ...framed(FRAME_CAN_DELIVER, 'can_deliver'),

  // 问题与策略都来自 DECISION.md 的 can_deliver 块
  ...compiled<{ deliverable: NoulQuestion; unsupported: NoulQuestion }>('can_deliver', ['deliverable', 'unsupported']),
})

/**
 * 七个判定节点，**带着某一次运行的门限**。`buildDecisions` 的产物。
 *
 * 用具名类型而不是让消费者写 `typeof import('./decisions.ts').pickInput`
 * 那种东西 —— 后者能过，但读的人要停下来解一遍。
 */
export interface DecisionSet {
  needsTool: typeof needsTool
  pickTool: typeof pickTool
  pickInput: typeof pickInput
  gradeRisk: typeof gradeRisk
  stepOk: typeof stepOk
  isDone: typeof isDone
  canDeliver: typeof canDeliver
}

/**
 * 用一组**门限覆盖**把七个节点构建出来。
 *
 * ── 为什么是工厂，而不是读环境变量 ──────────────────────────────
 *
 * 模块级常量做不到「同一次运行用一个门限」：`decisions.ts` 在 import 时
 * 就编译完了，而环境变量是**进程**的。做成工厂之后，谁调谁决定 ——
 * 服务器一次运行一份、测试可以一份一份地建，**顺序无关**。
 *
 * 不传 = 一份默认值都不动（和直接 import 那些常量完全等价）。
 *
 * ── 覆盖写不对就**当场炸** ──────────────────────────────────────
 *
 * 三种写错法全部拦下，因为它们的表现都是「你以为改了一道闸门，其实没有」：
 *
 *   ① 块名不认识        → 列出有哪些块
 *   ② 问题名不认识      → 列出那个块有哪些问题
 *   ③ 那个问题上没有门限 → 列出**所有能覆盖的键**（`gateKeys()` 现算）
 *   ④ 覆盖把多档门限压成不可达 → 见 `tierProblems`
 *
 * @throws 任何一种写错法
 */
export function buildDecisions(gates: GateOverrides = {}): DecisionSet {
  const { byBlock, unused } = splitGates(gates)
  const problems: string[] = []
  /**
   * 已经报过问题的键。
   *
   * ★ 用**集合记账**，不是拿 `problems.some((p) => p.includes(key))` 去反查 ——
   *   那是按字符串猜自己刚才说过什么。实测第一版就是这么写的，于是同一个
   *   写错的键被报了两次（一次「没有这个块」，一次「这个键没有可覆盖的门限」），
   *   而两句说的是同一件事。**记账比反查可靠**。
   */
  const blamed = new Set<string>()

  for (const key of unused) {
    problems.push(`认不出 '${key}'（应当是 块.问题）`)
    blamed.add(key)
  }

  const known = new Set(SPEC_BLOCKS.map(([b]) => b))
  // ★ `byBlock` 的键**就是块 id**（`splitGates` 已经切好了）。
  //   第一版在这里又对键做了一次 `slice(0, indexOf('.'))` —— 而它已经没有
  //   点了，`indexOf` 给 -1，`slice(0, -1)` 于是把最后一个字符吃掉：
  //   每个键都被报成「没有 pick_too 这个块」。**切过一次的东西不要再切。**
  for (const blockId of Object.keys(byBlock)) {
    if (known.has(blockId)) continue
    // 只报「块名不认识」，不报问题名 —— 问题名要等块确定了才说得清
    problems.push(`没有 '${blockId}' 这个块（可选：${[...known].join('、')}）`)
    for (const q of Object.keys(byBlock[blockId]!)) blamed.add(`${blockId}.${q}`)
  }

  const appliedAll = new Set<string>()
  const patched = new Map<string, PolicyRule<AnswerSet>[]>()

  for (const [blockId, specId] of SPEC_BLOCKS) {
    if (!known.has(blockId)) continue
    const b = block(blockId)

    // ② 问题名不认识
    for (const raw of Object.keys(byBlock[blockId] ?? {})) {
      // 键可以带档位下标（`risk[1]`）—— 那是**规则的档位**，不是问题名的一部分，
      // 所以校验之前先剥掉。第一版没剥，于是 `grade_risk.risk[0]` 被报成
      // 「没有 risk[0] 这个问题」，而这个键**根本没法用**。
      const q = raw.replace(/\[[0-9]+\]$/, '')
      if (b.questions.some((x) => x.id === q)) continue
      problems.push(`${blockId} 里没有 '${q}' 这个问题（可选：${b.questions.map((x) => x.id).join('、')}）`)
      blamed.add(`${blockId}.${raw}`)
    }
    // ④ 档位下标越界：`risk[7]` 这种，既不是问题名也不是有效的档位
    const tierCounts = new Map<string, number>()
    for (const r of b.policy) {
      if (!hasThreshold(r.when)) continue
      const q = predicateQuestion(r.when, b)
      if (q) tierCounts.set(q, (tierCounts.get(q) ?? 0) + 1)
    }
    for (const raw of Object.keys(byBlock[blockId] ?? {})) {
      const m = /^(.+)\[([0-9]+)\]$/.exec(raw)
      if (!m) continue
      const n = tierCounts.get(m[1]!)
      if (n !== undefined && Number(m[2]) < n) continue
      problems.push(
        `${blockId}.${raw}：'${m[1]}' 上${n === undefined ? '没有带门限的规则' : `只有 ${n} 档`}（能写的是 ${m[1]}[0..${(n ?? 1) - 1}]）`,
      )
      blamed.add(`${blockId}.${raw}`)
    }

    // ⑤ 压成不可达
    const tiers = tierProblems(blockId, byBlock[blockId] ?? {})
    problems.push(...tiers.problems)
    for (const k of tiers.keys) blamed.add(k)

    const pol = policyOf(blockId, gates)
    for (const k of pol.applied) appliedAll.add(k)
    patched.set(specId, pol.policy)
  }

  // ③ 名字对得上、但那个问题上没有门限可调（比如覆盖了一个 `else`）
  const missing = Object.keys(gates).filter((k) => !appliedAll.has(k) && !blamed.has(k))
  if (missing.length > 0) {
    problems.push(`这些键没有可覆盖的门限：${missing.join('、')} —— 能覆盖的是：${gateKeys().join('、')}`)
  }

  if (problems.length > 0) {
    throw new Error(`门限覆盖有问题（一条都没生效，所以停下而不是带着一半继续）：\n  ${problems.join('\n  ')}`)
  }

  const withPolicy = <T extends { id: string }>(spec: T): T => {
    const p = patched.get(spec.id)
    return p ? ({ ...spec, policy: p } as T) : spec
  }

  return {
    needsTool: withPolicy(needsTool),
    pickTool: withPolicy(pickTool),
    pickInput: withPolicy(pickInput),
    gradeRisk: withPolicy(gradeRisk),
    stepOk: withPolicy(stepOk),
    isDone: withPolicy(isDone),
    canDeliver: withPolicy(canDeliver),
  }
}

/**
 * 一段文本（`--gate` 的值、`JEVLOOP_GATES`）→ **校验过的**覆盖表。
 *
 * 解析和校验一次做完，因为调用方（CLI / 服务端）要的永远是同一件事：
 * 「给我一份能用的覆盖，用不了就告诉我为什么」。分成两步的话，
 * 每个调用方都要自己记得去 `buildDecisions` 验一遍 —— 而**忘了验的后果
 * 是静默的**：名字写错的门限不生效，你以为加了一道闸门。
 *
 * @throws 解析不了、或者名字对不上（消息里列出所有能覆盖的键）
 */
export function resolveGates(spec: string): GateOverrides {
  const { overrides, problems } = parseGates(spec)
  if (problems.length > 0) {
    throw new Error(`门限覆盖解析不了（一条都没生效，所以停下）：\n  ${problems.join('\n  ')}`)
  }
  // 建一次就是校验一次：`buildDecisions` 会对每个键追到底
  buildDecisions(overrides)
  return overrides
}
