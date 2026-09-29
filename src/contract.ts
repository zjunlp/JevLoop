/**
 * JevLoop · 可移植的 contract 入口（`jevloop/contract`）
 *
 * ══════════════════════════════════════════════════════════════
 *  给**不是 JevLoop** 的宿主用的那一半：读文件、编问题与策略、判版本、
 *  核对宿主自己的能力。**不包含**参考运行时。
 * ══════════════════════════════════════════════════════════════
 *
 * ── 为什么必须单独开一个入口 ──────────────────────────────────
 *
 * 因为 `jevloop` 的包根（`index.ts`）**转出了 `decisions.ts`**，而它在
 * **模块加载时**就把本仓库那份 `DECISION.md` 读进来、解析、按块校验帧声明，
 * 不合格当场抛。于是外部 runtime 只要写
 *
 *     import { adapterProblems } from 'jevloop'
 *
 * 就会被拖进整个参考运行时 —— 而且还得**我们那份** `DECISION.md` 存在且合格，
 * 哪怕它想检查的是**自己**的契约。那不是「可移植」，那是「先安装我们」。
 *
 * 所以这个入口**只**包含可移植的那部分，并且靠层号把这件事钉住：
 * `scripts/check.ts` 把本文件登记为 L3，而 `decisions.ts` 是 L4、`agent.ts` 是 L5、
 * `frame.ts` 是 L3 —— **依赖只能指向编号更小的层**，所以这三者从本文件里
 * import 不进来，写了就红。这条保证是机器检查的，不是注释里的承诺。
 *
 * ── 这里面各是什么 ────────────────────────────────────────────
 *
 *     parseDecisionDoc / schemaProblems   读文件、判版本
 *     compileQuestions / compilePolicy    编成问题与策略
 *     resolvePolicy                       答案 → 动作
 *     adapterProblems                     宿主声明出来的能力够不够
 *
 * 消费方（`examples/external-host.ts`）就是这么用的。完整的边界与合规检查表
 * 在 `docs/DECISION-CONTRACT.md`。
 *
 * @module JevLoop/contract
 */

// ── 读文件 ──────────────────────────────────────────────────
export { parseDecisionDoc, schemaProblems, summarize, headline, isGate } from './decisiondoc.ts'
export { CURRENT_SCHEMA, SCHEMA_KEY, SUPPORTED_SCHEMAS, DYNAMIC_OUTPUTS, parseDynamic, parseWhen, whenProblems } from './decision-shape.ts'

// ── 形状：消费方要能命名它拿到的每一个东西 ──────────────────
export { ANY_POSITION_ACTIONS, KINDS, POSITIONS } from './decision-shape.ts'
/*
  两种指纹 —— 宿主**产出**可验证记录必须用到它们。

  ★ 这一条是被适配器练习逼出来的：`verifyRecord` 早就在可移植面上，而**造**一条
    能通过验证的记录所需的那两个函数却不在 —— 等于告诉宿主「你的记录必须可验证」
    而不给他工具。两个指纹都是 L0 纯函数（零依赖），本来就该在这一层。
*/
export { DIGEST_CHARS, frameDigest, requestDigest } from './frame-digest.ts'

// 决策记录与重放：宿主可以把一条记录拿走、在别处验证它自不自洽
export { REPLAY_SCHEMA, REPLAY_NOTES, recordOf } from './replay-schema.ts'
export type { ReplayRecord } from './replay-schema.ts'
export { verifyRecord } from './replay-verify.ts'
export type { ReplayCheck, ReplayStatus, ReplayVerdict } from './replay-verify.ts'

// 帧投影的能力声明：宿主必须实现这几个名字，这里说清各自读哪一格、返回什么
export { PROJECTIONS, PROJECTION_NAMES, isProjectionName } from './frame-projections.ts'
export type { ProjectionName, ProjectionReturns, ProjectionSpec } from './frame-projections.ts'

// 动作语义：外部实现者照 `next` 写 switch 就够了，不必读我们的循环
export { ACTION_SEMANTICS } from './action-semantics.ts'
export type { ActionSemantics } from './action-semantics.ts'
export { ACTIONS } from './vocab-decision.ts'
export type { Action } from './vocab-decision.ts'
export type {
  BlockKind,
  DecisionDoc,
  DocBlock,
  DocDynamic,
  DocFrame,
  DocFrameExclusion,
  DocFrameField,
  DocOption,
  DocPolicyRule,
  DocProblem,
  DocQuestion,
  DocSummary,
  ParsedDynamic,
  ParsedWhen,
  Primitive,
} from './decision-shape.ts'

// ── 编问题与策略 ────────────────────────────────────────────
export { compilePolicy, compilePredicate, compileQuestions, hasThreshold, predicateQuestion } from './decision-compile.ts'
export type { CompiledPredicate } from './decision-compile.ts'

// ── 答案 → 动作 ─────────────────────────────────────────────
export {
  closestMargin,
  gte,
  picked,
  probGte,
  probLt,
  probabilityOf,
  resolvePolicy,
  scoreGte,
  thresholdOf,
  topGte,
  topLt,
} from './policy.ts'
export type { PolicyOutcome, PolicyWarning, ThresholdSpec } from './policy.ts'

// ── 宿主能力核对 ────────────────────────────────────────────
export { adapterProblems } from './adapter.ts'
export type { AdapterCapabilities, AdapterProblem } from './adapter.ts'

// ── 原语：问题长什么样、答案回来是什么形状 ──────────────────
export { choice, confidenceOf, noul, score } from './vocab.ts'
export type {
  Answer,
  AnswerMap,
  AnswerSet,
  ChoiceAnswer,
  ChoiceQuestion,
  NoulAnswer,
  NoulQuestion,
  Question,
  QuestionSet,
  QuestionType,
  ScoreAnswer,
  ScoreQuestion,
} from './vocab.ts'
