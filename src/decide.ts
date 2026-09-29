/**
 * JevLoop · decide()
 *
 * 一个判定走六步：
 *
 *   ① State 投影      把 ctx 压成有界决策帧
 *   ② 取问题          可以是 ctx 的函数（选项随状态变化）
 *   ③ 预算校验        发请求【之前】检查模型限制
 *   ④ 一次前向        拿到所有问题的答案
 *   ⑤ 策略            答案 → 动作（纯代码）
 *   ⑥ 记账            进 meter
 *
 * 后台挂了也不会崩：记一笔 degraded，然后交回上层，而不是瞎猜一个动作。
 *
 * ── 为什么不能再拆（§12：超过 300 行必须说清）────────────────────
 *
 * 一句话：**这个文件负责「一次判定」**。
 *
 * 上面那六步是**一条序列**，而序列本身就是这里唯一的内容：②合成 state 必须在
 * ①各自投影之后、③的预算校验必须在发请求之前、⑥的策略必须拿到④的答案。
 * §12 的两个判据（「输入输出形状变了」「消费者不是同一批人」）在这里都不成立 ——
 * 每一步吃的是同一个 `projected`，吐给同一条链的下一步，消费者只有 `agent.ts`。
 * 按步拆成六个文件，等于把「顺序」这件事从一眼可见变成要跨文件拼。
 *
 * 反例对照：`decisions.ts`（L4）超线**不该拆**，理由是「七个节点是同一件事」；
 * 这里是「六步是同一件事」。两类都是**内聚**，不是体量问题。
 *
 * ★ 真到了要拆的时候，第一条缝是**合并那一块**（②③两段，合帧 + 合题 + 撞了抛），
 *   它有自己的输入输出形状（多投影 → 一次请求），可以单独测。
 *
 * @module JevLoop/decide
 */

import type { Provider, Usage } from './seam-provider.ts'
import type { DecisionSpec, DecisionResult } from './vocab-decision.ts'
import type { QuestionSet, AnswerMap, AnswerSet } from './vocab.ts'
import { resolvePolicy, closestMargin, type PolicyWarning } from './policy.ts'
import { validate, type BudgetWarning, type Checkpoint } from './budget.ts'
import { frameDigest, requestDigest } from './frame-digest.ts'
import { mergeConflicts } from './frame-merge.ts'
import { Meter } from './meter.ts'

export interface DeciderOptions {
  provider: Provider
  /**
   * 不传就自建一个 —— **永远不会是 undefined**。
   *
   * 早先这里是可选的，于是 `runAgent` 里写成 `decider.meter ?? new Meter()`：
   * 判定记进了 `undefined`，而返回给调用方的是那个新建的、没人写过的 Meter。
   * 结果是最自然的用法（`new Decider({ provider })`）拿到的比值是 `0 : 1` ——
   * 这个项目赖以成立的数字什么都报不出来。改成必填后，那个状态在类型上不存在。
   */
  meter?: Meter
  checkpoint?: Checkpoint
  /** 预算超限时直接抛，而不是只告警 */
  strict?: boolean
  timeoutMs?: number
  onWarn?: (id: string, warnings: BudgetWarning[]) => void
  onPolicyWarn?: (id: string, warnings: PolicyWarning[]) => void
}

export interface DecideOptions {
  step?: number
  model?: string
}

/**
 * 判定器 —— 把一次判定从 ctx 跑到动作。构造一次、用一整个 loop。
 *
 * `setStep()` 标步号，`decide()` 是唯一入口。后端整个挂掉时它**不抛**，
 * 而是记一笔 `degraded` 并返回 `escalate`：判定失败不该让 loop 崩，
 * 但也**不能**被下游当成一次正常判定 —— 那正是 `degraded` 与 `escalate`
 * 两个字段同时存在的理由。
 */
export class Decider {
  readonly provider: Provider
  readonly meter: Meter
  readonly checkpoint: Checkpoint
  readonly strict: boolean
  #timeoutMs: number
  #onWarn: DeciderOptions['onWarn']
  #onPolicyWarn: DeciderOptions['onPolicyWarn']
  #step = 0

  constructor(opts: DeciderOptions) {
    this.provider = opts.provider
    this.meter = opts.meter ?? new Meter()
    this.checkpoint = opts.checkpoint ?? 'typed-decisions'
    this.strict = opts.strict ?? false
    this.#timeoutMs = opts.timeoutMs ?? 30_000
    this.#onWarn = opts.onWarn
    this.#onPolicyWarn = opts.onPolicyWarn
  }

  setStep(n: number): void {
    this.#step = n
  }

  /** 跑一次判定 —— 单数形式，交给 `decideMany`（见那里的说明） */
  async decide<Ctx, Q extends QuestionSet>(
    spec: DecisionSpec<Ctx, Q>,
    ctx: Ctx,
    opts: DecideOptions = {},
  ): Promise<DecisionResult<AnswerMap<Q>>> {
    const [only] = await this.decideMany([spec as DecisionSpec<Ctx, QuestionSet>], ctx, opts)
    return only as DecisionResult<AnswerMap<Q>>
  }

  /**
   * 一次请求问**多个独立的**判定。
   *
   * ══════════════════════════════════════════════════════════════
   *  官方 skill 的原话：「**Ask independent questions over the same state
   *  together**, including useful speculative questions. They run in
   *  parallel and cannot see one another's answers.」
   * ══════════════════════════════════════════════════════════════
   *
   * 为什么要合并：**判定占墙钟 62–80%**（§8.11，托管 Jev 一次约 390ms），
   * 而循环里每一步要问好几次。合并之后请求数直接少掉一截，而每次请求的
   * 延迟**不随问题数增长**（所有问题对同一份 state 并行打分）。
   *
   * ── 「独立」是什么意思 ──────────────────────────────────────────
   *
   * **一个判定的问题不依赖另一个判定的答案。** 比如每步开头的
   * `needsTool`（要不要动手）和 `pickTool`（用哪个工具）：后者的候选由
   * `toolsFor(ctx)` 算出来，和前者答什么无关 —— 所以它们可以一起问，
   * 代码再按 `needsTool` 的答案决定要不要用 `pickTool` 那份。
   *
   * `gradeRisk`（这次调用多危险）就**不能**并进来：它的帧依赖
   * `pickTool` 选中的是哪个工具。
   *
   * ── 两处硬约束，撞了就抛 ────────────────────────────────────────
   *
   * · **问题 id 不能撞** —— 撞了答案会互相覆盖，而其中一个判定会拿着
   *   另一个的问题的答案去跑策略，**在轨迹上完全看不出来**。
   * · **状态里同名键不能有两个值** —— 合并取一个的话，其中一个判定看到的
   *   就不是它要的帧（§8.2 的错法，但更隐蔽：帧看起来「有」那个字段）。
   *
   * 两个都抛而不是取一个：这是**调用方接线错了**，不是运行时状况。
   */
  async decideMany<Ctx>(
    specs: readonly DecisionSpec<Ctx, QuestionSet>[],
    ctx: Ctx,
    opts: DecideOptions = {},
  ): Promise<DecisionResult<AnswerSet>[]> {
    const step = opts.step ?? this.#step
    if (specs.length === 0) return []

    // ① 各自投影
    const projected = specs.map((spec) => {
      /*
        ★ 帧由**声明**编出来的节点，用那一份 —— 同一份 state 上还带着指纹、
        截断记录、「故意不看什么」（§8.14）。手拼 dict 的节点没有 artifact，
        行为与以前逐字一致（这是加这一层时唯一的兼容要求）。
      */
      const artifact = spec.frameArtifact?.(ctx)
      return {
        spec,
        artifact,
        state: artifact ? artifact.state : spec.state(ctx),
        questions: (typeof spec.questions === 'function' ? spec.questions(ctx) : spec.questions) as QuestionSet,
      }
    })

    /*
      ② 合成 state。

      ★ **单数时原样用**，不做任何包装 —— 合并是为了省一次请求，不该顺手
      改变单次调用的帧形状（那会让已有的 bench 数字不再可比）。
    */
    let state: unknown = projected[0]!.state
    if (projected.length > 1) {
      /*
        ★★ **合并的合法性从声明算出来，不靠人记。**

        `FrameSpec.excluded` 声明了「这个判定故意不看 X」。如果另一个判定要看 X，
        合成一帧就等于把 X 塞进它的视野 —— 而在这段检查之前，合并**不会拦这件事**：
        它会静默成功，然后违反一个已经写下来的契约（而那份契约存在的全部意义
        就是不让这种事发生，§8.14）。

        §8.18 记的「`stepOk` 与 `isDone` 两份帧合不成一份」**正是这条规则自己
        推出来的**，不用人去记：`stepOk` 排除 `task`，而 `isDone` 读 `task`。

        ★ 只查**声明过帧**的节点（`artifact` 存在）。手拼 dict 的第三方节点没有
          可读的声明，硬猜一个只会误报 —— 那种情况由调用方自己负责。
      */
      const framed = projected.flatMap((p) => (p.artifact ? [p.artifact] : []))
      const verdict = mergeConflicts(framed)
      if (!verdict.ok) {
        throw new Error(
          `合并 ${projected.map((x) => x.spec.id).join(' 和 ')} 不合法：` +
            verdict.conflicts
              .map(
                (c) =>
                  `'${c.field}' 被 ${c.excludedBy} 声明为「故意不看」（${c.reason}），而 ${c.readBy} 要读它`,
              )
              .join('；') +
            ' —— 合成一帧会把不该看的塞进它的视野',
        )
      }
      const merged: Record<string, unknown> = {}
      for (const p of projected) {
        const obj = p.state as Record<string, unknown> | null
        if (obj === null || typeof obj !== 'object') {
          throw new Error(
            `合并 ${projected.map((x) => x.spec.id).join(' 和 ')} 时，'${p.spec.id}' 的 state 不是对象` +
              `（${typeof obj}）—— 合并只能用于「同一份上下文的两个投影」`,
          )
        }
        for (const [k, v] of Object.entries(obj)) {
          const seen = merged[k]
          if (k in merged && JSON.stringify(seen) !== JSON.stringify(v)) {
            throw new Error(
              `合并 ${projected.map((x) => x.spec.id).join(' 和 ')} 时，状态字段 '${k}' 有两个不同的值 —— ` +
                `这两个判定不是同一份上下文的投影，不该合并（静默取一个会让其中一个看到错的帧）`,
            )
          }
          merged[k] = v
        }
      }
      state = merged
    }

    // ③ 合成问题。id 撞了**抛**，不覆盖
    let questions: QuestionSet
    if (projected.length === 1) {
      questions = projected[0]!.questions
    } else {
      questions = {}
      for (const p of projected) {
        for (const [qid, q] of Object.entries(p.questions)) {
          if (qid in questions) {
            throw new Error(
              `合并 ${projected.map((x) => x.spec.id).join(' 和 ')} 时，问题 id '${qid}' 撞了 —— ` +
                `答案会互相覆盖，而其中一个判定会拿着另一个的答案跑策略，轨迹上看不出来`,
            )
          }
          questions[qid] = q
        }
      }
    }

    /*
      ★ 「它**被问了**什么」—— 帧 + 问题 + 选项（§8.17 更正的那一条）。

      只记帧指纹会漏掉「换掉候选集」那一类：`choice` 的选项不在帧里，
      换掉候选，帧指纹一动不动而答案会翻。单节点时帧指纹就是那个节点自己的；
      合并时发出去的是一份合成帧，所以按参与合并的节点名重算一个。

      ★★ `sentFrameDigest` **单独记下来**（TODO §12 最后一条：evidence/replay）。
        因为它是「实际送出去的那份帧」的指纹，而合并时它**既不等于**任何单个
        节点的 `frame.digest`、也**没法从单条记录重算**（重算需要参与合并的
        节点名列表 + 合并后的问题集，两者都不在一条记录里）。不记它，重放器
        在每一步合并判定上都会报假失败 —— 而合并是常态，不是例外。
    */
    const batchIds = projected.map((p) => p.spec.id)
    const sentFrameDigest =
      projected.length === 1 && projected[0]!.artifact
        ? projected[0]!.artifact.digest
        : frameDigest(batchIds.join('+'), state as Record<string, unknown>)
    const requestPrint = requestDigest(sentFrameDigest, questions)

    // ④ 发请求之前就检查预算
    for (const p of projected) {
      const warnings = validate(state, p.questions, this.checkpoint)
      if (warnings.length) this.#onWarn?.(p.spec.id, warnings)
      if (this.strict && warnings.some((w) => w.level === 'error')) {
        throw new Error(
          `决策 '${p.spec.id}' 超出 ${this.checkpoint} 限制：${warnings.map((w) => w.message).join('; ')}`,
        )
      }
    }

    // ⑤ 一次前向。`batch` 在这里分配：**从这里往下都是同一次请求**，
    // 投影出来的每个节点都归这一批（记 accounts 按批求和，见 `Meter.stats`）
    const batch = this.meter.nextBatch()
    let answers: AnswerSet = {}
    let latencyMs = 0
    // 后端报的 token（§9）。**没报就是 undefined**，见 DecisionResult 的说明
    let usage: Usage | undefined
    let provider = this.provider.name
    let model: string | undefined
    let degraded = false
    // 后端报的问题。**会随 DecisionResult 交出去**（见下面的 `warnings`）——
    // 它会进 `decision` 事件，所以轨迹里查得到 `degraded` 的原因
    const notes: string[] = []
    const t0 = performance.now()

    try {
      const res = await this.provider.decide({
        state,
        questions,
        // 合并的判定**必须用同一个模型** —— 两个判定发往不同模型的话，
        // 「一次请求」这件事就不成立了
        ...(opts.model ?? projected[0]!.spec.model ? { model: opts.model ?? projected[0]!.spec.model } : {}),
        timeoutMs: this.#timeoutMs,
      })
      answers = res.answers
      latencyMs = res.latencyMs
      usage = res.usage
      provider = res.provider
      model = res.model
      degraded = !!res.degraded
      if (res.warnings) notes.push(...res.warnings)
    } catch (err) {
      // 防线：后端整个不可用也不能让 loop 崩。
      // 记 degraded，然后交回上层 —— 不猜。
      const failedMs = performance.now() - t0
      // 失败也是**同一批**：一次请求挂了，投影出来的每个节点都记这一份耗时
      const batch = this.meter.nextBatch()
      return projected.map((p) => {
        const result: DecisionResult<AnswerSet> = {
          id: p.spec.id,
          step,
          state,
          // 挂掉也要带上帧的账：事后要能查「它当时看到的是什么」
          ...(p.artifact ? { frame: p.artifact } : {}),
          requestDigest: requestPrint,
          sentFrameDigest,
          sentQuestions: questions,
          batchIds,
          questions: p.questions,
          answers: {},
          action: 'escalate',
          reason: `${provider} 不可用：${(err as Error).message}`,
          latencyMs: failedMs,
          provider, // 记**原计划用的**，不覆盖成 "none"
          degraded: true,
          escalate: true,
          // 异常文本同时进 `reason` 和 `warnings`：前者是给人看的一句话，
          // 后者是**可枚举**的那一份。降级链上的每一跳都在里面。
          warnings: [`${provider} 不可用：${(err as Error).message}`],
        }
        this.meter.recordDecision(step, result, batch)
        return result
      })
    }

    // ⑥ 每个判定**各跑各的策略** —— 合并的只是那次前向，动作还是分开决定的
    return projected.map((p) => {
      const mine: AnswerSet = {}
      for (const qid of Object.keys(p.questions)) {
        const a = answers[qid]
        if (a !== undefined) mine[qid] = a
      }

      const policyWarnings: PolicyWarning[] = []
      const outcome = resolvePolicy(p.spec.policy, mine, (w) => policyWarnings.push(w))
      if (policyWarnings.length) this.#onPolicyWarn?.(p.spec.id, policyWarnings)

      /*
        ★ 这次判定离**翻掉**有多近（TODO §2）。

        只算到**决定它的那条规则为止** —— 后面的规则根本没被问到，拿它们算
        margin 是在报一个没发生过的比较。

        ★ 它**不需要标准答案**：margin 是「答案 + 策略」的性质，不是「对错」的
          性质。所以每个判定都报得出 —— 包括标定台判不了的那些，而那些恰恰
          最需要知道「它是不是在瞎猜」。
      */
      const margin = closestMargin(p.spec.policy, mine, outcome.ruleIndex)

      const result: DecisionResult<AnswerSet> = {
        id: p.spec.id,
        step,
        // `state` / `questions` 报的是**实际发出去的那一份**：合并时就是合并后的帧。
        // 报各自的投影会让轨迹看起来像发了两次请求，而实际只发了一次。
        state,
        // ★ 而 `frame` 是**这个节点自己**那一份（含它的指纹与「故意不看什么」）；
        //   合并时它与上面那份合成帧不同，这正是应该看得见的差别。
        ...(p.artifact ? { frame: p.artifact } : {}),
        requestDigest: requestPrint,
        sentFrameDigest,
        sentQuestions: questions,
        batchIds,
        // 贴在哪条门限边上（缺席 = 这次没有可比的带门限规则，**不用 0 冒充**）
        ...(margin ? { margin } : {}),
        questions: p.questions,
        answers: mine,
        action: outcome.action,
        reason: outcome.reason,
        latencyMs,
        // ★ 一次前向的 token 记在**每条**记录上，求和时按批去重（见 Meter.stats）
        ...(usage?.input_tokens !== undefined ? { inputTokens: usage.input_tokens } : {}),
        ...(usage?.output_tokens !== undefined ? { outputTokens: usage.output_tokens } : {}),
        ...(usage?.estimated !== undefined ? { usageEstimated: usage.estimated } : {}),
        provider,
        ...(model !== undefined ? { model } : {}),
        degraded: degraded || policyWarnings.length > 0,
        escalate: outcome.action === 'escalate',
        // ★ 后端报的问题**和**策略警告一起带上。
        //
        //   它们本来就被算出来了（`notes` / `policyWarnings`），只是**没有
        //   一个消费者** —— 于是 `degraded: true` 在轨迹上是一句没有下文的话。
        //   实测某个会话的每一次判定都 degraded，而没人说得出缺了什么。
        ...(notes.length || policyWarnings.length
          ? { warnings: [...notes, ...policyWarnings.map((w) => w.message)] }
          : {}),
      }

      // ⑦ 记账 —— 同一个 `batch`：这一批共用同一次请求，聚合时只算一次
      this.meter.recordDecision(step, result, batch)
      return result
    })
  }
}
