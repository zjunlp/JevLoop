/**
 * JevLoop · 公开 API
 *
 *   import { Decider, runAgent, defineDecision, noul, choice, score } from 'jevloop';
 *
 * 概念只有三个：Question / Decision / Provider。
 *
 * @module JevLoop/index
 */

// ── 概念 ─────────────────────────────────────────────────────
export type {
  QuestionType,
  NoulQuestion,
  ChoiceQuestion,
  ScoreQuestion,
  Question,
  QuestionSet,
  NoulAnswer,
  ChoiceAnswer,
  ScoreAnswer,
  Answer,
  AnswerSet,
  AnswerMap,
} from './vocab.ts'
export type { PolicyRule, DecisionSpec, DecisionResult } from './vocab-decision.ts'
export type { Provider, DecideRequest, DecideResponse } from './seam-provider.ts'
// 失败分类：**按 code 分支，不要解析 message**（见 seam-provider.ts）
export { ProviderError, isRetryable, RETRYABLE_CODES } from './seam-provider.ts'
export type { ProviderErrorCode } from './seam-provider.ts'
export { httpErrorCode, parseRetryAfter, httpFailure, transportFailure } from './http-error.ts'
export { noul, choice, score, confidenceOf } from './vocab.ts'
export { defineDecision, isDecision } from './vocab-decision.ts'

// ── 判定 ─────────────────────────────────────────────────────
export { Decider } from './decide.ts'
export type { DeciderOptions, DecideOptions } from './decide.ts'
export { resolvePolicy, gte, topGte, probGte, probLt, scoreGte, picked, probabilityOf } from './policy.ts'
export type { PolicyOutcome, PolicyWarning } from './policy.ts'
export { clip, pick, estimateTokens, validate, LIMITS } from './budget.ts'
export type { BudgetWarning, Checkpoint } from './budget.ts'

// ── 后端 ─────────────────────────────────────────────────────
export { HttpProvider, normalizeAnswers } from './provider-http.ts'
export { MockProvider } from './provider-mock.ts'
export { FallbackProvider } from './provider-fallback.ts'
// 重试：每一跳自己的策略，降级链在外面组合（见 provider-retry.ts 的文件头）
export { RetryingProvider } from './provider-retry.ts'
// 生成那条缝的同名机制（DSH 的 `llm-retry` 说的「model request」是这一条）
export { RetryingGenerator } from './llm.ts'
// 重试机制与失败分类本身：两条缝共用，调用方要自己接的话从这里拿
export { resolveRetry, retryCall, planDelay, RETRY_DEFAULTS } from './retry.ts'
export type { RetryInfo, RetryOptions, ResolvedRetry } from './retry.ts'
export type { HttpProviderOptions } from './provider-http.ts'

// ── 记账 ─────────────────────────────────────────────────────
export { Meter, formatRatio } from './meter.ts'
export { assertNever } from './util.ts'
export type { MeterStats, DecisionRecord, ModelCallRecord, AuditRecord } from './meter.ts'

// ── agent ────────────────────────────────────────────────────
export { runAgent } from './agent.ts'
export type { AgentOptions, AgentResult } from './agent.ts'

// ── 事件缝 ───────────────────────────────────────────────────
export { decisionEvent, fanOut } from './events.ts'
export type { AgentEvent, AgentObserver } from './events.ts'
export { DEFAULT_MAX_OUTPUT_CHARS, callTool, toolNames, isToolName } from './act.ts'
export type { ToolLimits } from './act.ts'
/**
 * 决策记录与重放：把一条落盘的判定记录拿走，在别处验证它自不自洽。
 *
 * ★ 它验证**记录完整性**与**请求同一性**，不验证「帧从原始 ctx 编得对不对」，
 *   也不验证「判定对不对」—— 后者要外部 oracle。`REPLAY_NOTES` 逐条写明了。
 */
export { REPLAY_SCHEMA, REPLAY_NOTES, recordOf } from './replay-schema.ts'
export type { ReplayRecord } from './replay-schema.ts'
/** 一条记录能不能自洽：四项检查，四档结论（`verified` / `partial` / `unverifiable` / `mismatch`） */
export { verifyRecord } from './replay-verify.ts'
export type { ReplayCheck, ReplayStatus, ReplayVerdict } from './replay-verify.ts'
export { PROJECTIONS, PROJECTION_NAMES, isProjectionName } from './frame-projections.ts'
export type { ProjectionName, ProjectionReturns, ProjectionSpec } from './frame-projections.ts'
export { ACTION_SEMANTICS } from './action-semantics.ts'
export type { ActionSemantics } from './action-semantics.ts'
export { ACTIONS } from './vocab-decision.ts'
export type { Action } from './vocab-decision.ts'
export { LOCAL_TOOLS } from './act-local.ts'
export type { Tool, ToolRegistry, ToolNameOf } from './act.ts'
export type { ToolName } from './act-local.ts'
export { adapterProblems } from './adapter.ts'
export type { AdapterCapabilities, AdapterProblem } from './adapter.ts'
// ★ 只把**判版本**这一件事放到包根：它是「我读不读得懂这份文件」的问题，
//   任何消费方都要问，包括已经用了参考运行时的那些。完整的可移植入口
//   （parse / compile / policy / adapter）在 `jevloop/contract`，见 `contract.ts`。
export { CURRENT_SCHEMA, SUPPORTED_SCHEMAS, schemaProblems } from './decisiondoc.ts'
export type { DecisionDoc, DocBlock, DocDynamic } from './decisiondoc.ts'
export type { ContextReport, RequestEstimate, EvidencePolicy } from './context.ts'
export { foldConversation, CONVERSATION_POLICY } from './conversation.ts'
export type { ConversationPolicy, ConversationReport, ConversationTurn, FoldedConversation } from './conversation.ts'
export { ScriptedGenerator, HttpGenerator } from './llm.ts'
export type { Generator, GenerateRequest, GenerateResult } from './llm.ts'

// ── 预设的判定节点 ───────────────────────────────────────────
export { needsTool, pickTool, pickInput, gradeRisk, stepOk, isDone, canDeliver } from './decisions.ts'
export { hasFileOptions, unreadFiles } from './frame.ts'
export type { AgentCtx, StepRecord } from './frame.ts'

// ── 环境 ─────────────────────────────────────────────────────
export { listDirs, createDir } from './dir-browse.ts'
export type { DirEntry, DirListing } from './dir-browse.ts'
export { WorkspaceStore } from './workspace.ts'
export type { Workspace, CreateResult } from './workspace.ts'
export { WorkspaceError } from './vocab-workspace.ts'
export type { WorkspaceErrorCode } from './vocab-workspace.ts'
export { SessionStore, assertSessionId, SESSION_FORMAT_VERSION } from './session-store.ts'
export type { StoredRun, SessionSummary } from './session-store.ts'
export { encodeSegment, projectKey, logPath } from './session-path.ts'
export { loadEnv } from './env.ts'
export type { LoadEnvOptions, LoadEnvResult } from './env.ts'

// ── 后端解析 ─────────────────────────────────────────────────
export { resolveProvider, resolveGenerator } from './backends.ts'
export type { ProviderChoice, GeneratorChoice, FallbackNotice } from './backends.ts'
