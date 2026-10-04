# The paper story (2026-10)

Dialectical reading of the advisor's brainstorm (`Think in Language, Act through Code: Compiling
Control Policies for LLM Agents`, Control Entropy, H1–H3), against what this repo has already
claimed and measured. Written to be argued with.

Read first: `docs/PAPER-CLAIM-2026-09.md` (the existing claim, with its evidence table and its
three rejected candidates) and `docs/ENGINE-VS-HOST.md` (engine vs host, and the scope decision
that text→contract extraction is **out**).

## 0. The measurement that governs everything below

Computed from the ledger of the 20-task ALFWorld run, `request_digest` as the state key, one row
per decision. **Decision-level** agreement means: `noul` read as `prob_true() >= threshold`,
`choice` as the chosen option, `score` as the band. **Value-level** means the raw number matched.

| node | rows | distinct states | rows in repeated states | decision stable | value stable |
|---|---:|---:|---:|---|---|
| `stepOk` | 216 | 80 | 171 | **35/35** | 16/35 |
| `risk` | 231 | 97 | 167 | **32/33** | 32/33 |
| `needs_auth` | 231 | 97 | 167 | **33/33** | 1/33 |
| `pickTool` | 220 | 100 | 154 | **34/34** | 34/34 |
| `isDone` | 215 | 172 | 48 | 5/5 | 0/5 |
| `pickInput` | 245 | 207 | 44 | **4/6** | 4/6 |
| `needsTool` | 240 | 207 | 40 | 7/7 | 2/7 |
| `deliverable` | 29 | 25 | 8 | 4/4 | 2/4 |
| `unsupported` | 29 | 25 | 8 | 4/4 | 1/4 |

Three readings, in order of how much they change our own prior statements:

**① The jitter is in the confidence, not in the decision.** Eight of nine nodes never flipped a
decision across 5–171 repeats. We had written *"retrying an identical request is a lottery"*
(`BELOW_THRESHOLD_POLICY`, `docs/RETRY-DOES-NOT-HELP.md`) on the strength of "19 of 20 identical
digests came back with different confidence". **That sentence was overstated.** It is true for
exactly one node — `pickInput`, the only one whose decision is a near-tie — and that is the node the
`accept` policy was written for. The policy stands; its justification narrows.

**② Therefore a confidence-thresholded policy converts a stable decision into an unstable one.**
`risk` was decision-stable 32/33 and got discarded anyway, because a `Question.threshold` default
of 0.5 read the *number*. 4 of 20 tasks died without a single tool call
(`docs/ALFWORLD-ESCAPE.md` §4). This is the empirical argument for `threshold=0.0` on the
confirm/object questions: **read decisions, not confidences.**

**③ Recurrence is measurable and it splits the nodes in two.** In 63–79% of rows, `stepOk`,
`risk`, `needs_auth`, `pickTool` are answering a state they have answered before. For
`pickInput`, `needsTool`, `isDone` it is 17–22% — those states are almost always new. That is the
"where does compilation help" axis, computed rather than asserted.

## 1. Thesis: what to keep from the brainstorm

**K1. The core question is right, and it is the sharpest sentence in the list.**
Not "can code improve agents" but *"which decisions should remain stochastic language reasoning, and
which should be compiled into executable policies"*. Keep it as the paper's question.

**K2. "What should NOT be compiled?" is the best item, because it is a boundary and not a benefit.**
Our repo can answer it with a criterion and a negative result — see §3.

**K3. State consistency: policy reads environment state, not the model's memory of its own
history.** We have measured this in both directions. When the state was missing from the frame, the
controller looped (13/20 tasks declined before `already_done` entered the frame). When our *own*
state bookkeeping was wrong, the accounting lied (413 rows, 20%, labelled as judgments). This is not
an advantage we assert; it is a failure mode we have already paid for twice.

**K4. Long-horizon is where the mechanism shows.** Not as an accuracy claim — as a cost claim. The
single-variable escape A/B (20 tasks, one flag):

| | no escape | escape |
|---|---:|---:|
| native `won` | 1/20 | **1/20** |
| tool calls | 386 | **220** |
| decision rows | 3528 | **2107** |
| tasks with a ≥10× repeated command | **9** | **4** |
| silent failures (exhausted + declined) | **15** | **8** |

Same score, 40% less work, seven tasks moved from silent failure to honest failure. That is the
mechanism, measured, with the benchmark's own metric provably blind to it.

## 2. Antithesis: what I would change or drop

**A1. `H(A|S) = 0` is not what we do, and our own data says so.**
We did not remove decision entropy; we *relocated* it. Judge share (`source="judge"`) is 0.64–0.92
across runs. And the residuals are not small: `needs_auth` at a fixed state disagreed with itself on
the raw value in 32 of 33 repeats. Claiming H=0 would be refuted by our own ledger in one table.

**Repair, and it is a better claim:** define **decision entropy as an empirical property of a
controller at a fixed state** — the disagreement rate when the *same request* (byte-identical frame
+ questions) is asked more than once. It is measurable on any agent that logs its requests. It
decomposes per decision point. It is zero for compiled decisions **by construction** and it is a
number we measured for the rest. That sentence is falsifiable, portable, and nobody has to accept a
theoretical idealisation. **It also lands the point the brainstorm wanted:** the interesting fact is
not that entropy is zero, it is that entropy is *attributable* — you can see which decision point
carries it, and a policy that reads the confidence rather than the decision moves entropy from the
number into the behaviour (finding ② above).

**A2. "Automatic Policy Compilation" promises something we decided not to do.**
Extraction (text → contract) is out of scope by the scope decision recorded in
`docs/ENGINE-VS-HOST.md`: we do not have enough natural language, and datasets do not carry process
descriptions. A title promising automatic compilation over-claims the mechanism, and a reviewer
will ask for the compiler.

**Repair:** there is an automatic step available that needs **no NLP** — **discover rules from the
ledger**. Count `request_digest` recurrence, measure decision stability at fixed state, and propose a
rule for the nodes that are both recurrent and stable. That is the §0 table, mechanised. It earns
"compilation" without the extraction promise, and it makes H3 concrete. It is also honest about the
loop: discover → **shadow** (μ's discipline: judged, logged, changes nothing) → compare with
outcomes → activate. That is the defensible form of the brainstorm's point 10, and it is strictly
weaker than "recursive self-improvement", which is why it can be published.

**A3. `0.98^50` is the wrong model, and we can show the right one.**
The independence assumption is false, and at fixed state decisions are largely *stable*: errors do
not accumulate as independent noise, they **repeat**. We measured the repetition: one command chosen
30 times in a task. So the long-horizon argument should not be "independent per-step error
compounds" — it should be:

> A wrong control decision is not resampled into a right one. It is **re-executed**. And a stable
> wrong decision is invisible to a per-step accuracy metric, because the controller agrees with
> itself every time.

That is a stronger argument for compilation, it needs no distributional assumption, and it explains
why compilation helps: it makes a stable error into an **editable artifact** (change one rule)
instead of an untraceable one.

**A4. "Decision Drift" is not new as a phenomenon.**
Goal drift / task derailment is named in the literature, and μ already ships `turn.drift` as a
decision point. Claiming the phenomenon would be naive.

**Narrow, defensible version:** drift *at a repeated state* — the controller's answer at the same
`request_digest` changing over the trajectory. That is a measurable refinement, not a new
phenomenon, and finding ② is its first result.

**A5. H1 as written will fail, and we should say so before a reviewer does.**
"Compiled decisions have lower error rates than repeated language decisions" needs a per-decision
error oracle, and at the decision level the judge is already **stable** on 8 of 9 nodes — there is no
error rate to lower. What compilation actually removes is (i) the **confidence channel** (finding
②), (ii) the **cost** of asking a question whose answer is already determined, (iii) the
**un-auditability** of the decision. Error rate only improves if the judge is *stably wrong*, and
that case is where compilation pays best, because it is the case a per-step metric cannot see.

## 3. Synthesis: what we can actually claim

**The object of the paper is the boundary, and both sides get a criterion.**

> **Control decisions should be declared where they are stable, generated where they are not — and
> the boundary between the two is measurable before you build either.**

**The criterion (our contribution, and it is a criterion rather than a system):**

A decision point is a compilation candidate iff

1. **its state recurs** — most of its rows are states it has seen before
   (`stepOk` 79%, `risk` 72%, `needs_auth` 72%, `pickTool` 70% vs `pickInput` 18%, `needsTool` 17%);
   **and**
2. **its decision at fixed state is stable** — 8 of 9 nodes qualify; `pickInput` does not (2 of 6
   repeated states flipped); **and**
3. **its evidence is a certificate** — a check that runs on the artifact with no model judgement
   inside it, so the rule can be *verified* rather than trusted. We have three
   (`empty_draft`, `ungrounded_number`, `no_evidence`) and two explicit anti-certificates
   (`tool_error_ignored`, `goal_signal_absent`), with the measured failure mode of compiling the
   latter anyway: under monotonicity a crude detector's false positive becomes a **permanent
   refusal** that the judge is forbidden to relax.

**The 2×2 this gives**, which is the "where does compilation help / what should NOT be compiled"
section of the paper:

| | decision stable at fixed state | decision flaps |
|---|---|---|
| **state recurs** | **compile it** — `stepOk`, `pickTool`, `risk`, `needs_auth`; asking again buys nothing and pays for a confidence channel | **do not compile** — `needs_auth`'s *value* flaps 32/33; freezing it would freeze a coin flip |
| **state is new** | keep it judged — recurrence is what makes a rule safe to state (`needsTool`, `isDone`) | keep it judged — `pickInput`; and this is the node where a retry really is a lottery |

**The residual contract, and this is the part the literature does not have:**

For every decision that stays judged, the interface must be **monotone**: the judge may only make
the outcome stricter, never looser. Refusal is the rule's job, and a rule refuses only when it holds
a certificate. Two consequences we measured, not asserted: an unsure judge can no longer end a task
(the path that killed 4/20 is gone by construction), and a judge that disagrees with a rule is
**recorded** but does not release it — so rule quality becomes a number instead of an opinion.

**And the accounting that makes all of it auditable:** every decision row says who produced it
(`rule` / `judge` / `generate` / `fallback`) and, when a fallback ran, its name. That is what makes
`判定占比`, rule-block precision and judge-tightening rate computable — and it is a **means** for us,
not a product (user, 2026-10-04: 溯源是 semantica 的优势,对于我们而言是控制).

## 4. H1–H3, repaired into measurable form

| | brainstorm | repaired | instrument we have |
|---|---|---|---|
| **H1** | compiled decisions have lower error rates | compiled decisions **remove the confidence channel**, and are lower-*cost* at equal decision quality. Error rate improves only when the judge is *stably wrong*, and that is the case a per-step metric cannot see | `source` accounting + per-decision cost (tokens, round trips) + the decision-level stability table |
| **H2** | advantage grows with the number of control decisions | the advantage is in **redundant decisions avoided**, and it grows with horizon **only where control is load-bearing** | `request_digest` recurrence vs horizon; the escape A/B (tool calls 386→220, score unchanged) shows the cost half; ternary-judge shows the accuracy half (false claims 12→0 at 1/3 tokens) |
| **H3** | recurring decisions can be progressively compiled | **discover from the ledger**: recurrence × stability, then shadow, then activate on evidence | the §0 table, mechanised — no NLP, no RSI claim |

## 5. What we already have versus what is missing

| piece | status |
|---|---|
| a measured, decision-level stability profile per node | ✅ §0 (one dataset, 20 tasks) |
| a compilability criterion with a worked boundary | ✅ §3, with 3 certificates + 2 anti-certificates |
| a monotone residual contract, enforced and pinned | ✅ `docs/GATES-RULES-FIRST.md`, 14 tests |
| attribution of every decision to rule/judge/fallback | ✅ `source` / `fallback` |
| a cost half (fewer decisions, equal score) | ✅ the escape A/B |
| an accuracy half (control decision moves the score) | ✅ ternary-judge, 4 arms |
| **stability profile on a second dataset** | ❌ needed — one dataset is an anecdote |
| **a canonical state key** | ❌ **the main methodological gap.** `request_digest` includes incidental frame variation (truncation, field order), so "distinct state" is over-counted and recurrence is under-detected. A canonical projection of the frame is required before the recurrence numbers mean what we say |
| **decision-level correctness, not just stability** | ❌ stability says nothing about rightness. Need a hand-labelled sample of decisions |
| **a `tool.admission`-class decision the loop host cannot place** | ❌ this is the falsifier for the engine claim |

## 6. What would falsify the story

1. **Recurrence and stability do not predict the benefit.** Compile a high-recurrence/stable node
   (e.g. `pickTool`) and a low-recurrence node, and the benefit does not track the 2×2. Then the
   criterion is decoration and we are back to "code is cheaper", which is known.
2. **The confidence-channel claim does not generalise.** If on a second dataset `stepOk`/`needsTool`
   *do* flip at fixed state, then finding ① is one judge's quirk, not a property of the
   configuration.
3. **The canonical state key cannot be built.** If frame variation cannot be separated from genuine
   state change, then recurrence is unmeasurable, and H3 has no instrument.
4. **The score moves when the story says it cannot.** We claim the native metric is blind to control
   cost. If it turns out to be sensitive, the factorization story weakens.

## 7. Position: do not start a new claim, extend the existing one

`docs/PAPER-CLAIM-2026-09.md` already rejected *"declarative contract beats workflow/if-else"* — with
evidence (the policy layer is provably equivalent, cell for cell). The brainstorm is **adjacent** to
that rejected claim, and the paper must draw the line explicitly:

- the rejected claim compares **code form against code form** (declarative spec vs equivalent
  `if/else`);
- this one compares **generation against declaration** (a decision re-generated per step vs a
  decision compiled once).

Those are different axes, and the existing claim's C1 result does not touch the second one. If we do
not say this in one sentence, a reviewer will collapse them and the paper dies in round one.

And the two claims compose rather than compete:

| | compiled side | judged side |
|---|---|---|
| governed by | **recurrence × stability × certificate** | **evidence coupling + calibration** (existing C1–C4) |
| measured by | the §0 stability table | the evidence-substitution manipulation |
| interface rule | the rule holds a certificate | **the judge may only tighten** |

One paper, one object (the decision), two contracts, one accounting layer. The existing claim doc's
strategic instruction still governs: **sell the criterion, not the system** — a criterion can be
taken and used on somebody else's validation layer, which is what gets cited.

---

# 9. 预计达到的结果（2026-10-04 的总结）

## 9.1 一句话

> **控制决定应该在稳定的地方声明,在不稳定的地方生成 —— 而"哪个是哪个"在你动手之前就是可测的。**

这句是论文的记忆点。它不是"我们做了一个 agent",是一句**判据**,别人可以拿去测他们自己的控制器。

## 9.2 交付物是什么

| 交付物 | 是什么 | 现在有没有 |
|---|---|---|
| **契约 schema** | 领域无关:位置 / 题 / 策略 / 兜底 / 结果词表 / `decided_by` / 模式 | ✅ `core/contract.py` |
| **引擎** | 执行一份契约:该问的题问出去,规则先筛,判官只确认 | 🟡 部分(问法还没从契约读) |
| **判据 + 脚本** | 从**任何** agent 的账本里算出「这个判定点该不该编译」 | 🟡 测量方法已验证,缺规范状态键 |
| **判定账** | 每条决定说得出是谁做的(`rule`/`judge`/`generate`/`fallback`) | ✅ |
| **N 份契约** | 每个数据集一份,手写、带版本、带指纹 | 🟡 1 份(ALFWorld);ternary 待写 |
| **N 个数据集的数** | 原判分不动 + 控制成本 + claim×truth 交叉表 | 🟡 部分 |

## 9.3 论文的骨架（七节）

1. **问题**:不是"代码能不能让 agent 更好",而是**哪些决定该保持语言推理,哪些该被编译成策略**。
2. **定位**:Code-as-Policies / Voyager / StateFlow / 神经符号这一线都做了"把控制写成代码";**没有人给判据**,也没有人有**残差契约**。这一句必须在第一页说清,否则审稿人会说"这是 LangGraph"。
3. **编译那一侧(新)**:判据三条 —— **状态重复 × 决定稳定 × 证据是证书**。附 2×2 表、三条证书、两条"看着像证书其实不是"的负面结果。
4. **判官那一侧(已有)**:证据耦合 + 校准(C1–C4 加负面结果)。仪器是**证据替换操纵**。
5. **接口(新,且文献里没有)**:单调性 —— **判官只能收紧**。不确定永远不产生拒绝;判官否定一条规则会被**记下来但不放行**,于是规则质量变成一个数。14 条测试钉住。
6. **账与盲区**:每条决定可归因;**而基准自己的指标看不见控制成本**(退出口那次:分数 1/20 不变,工具调用 386→220)。
7. **负面结果与效度威胁**,包括我们抓到的自己的 bug。

## 9.4 三档结果

| 档 | 需要什么 | 现在离它多远 |
|---|---|---|
| **能发**(好会议/workshop) | 一个引擎 × N 个数据集 × N 份手写契约;原判分不动;退出口那次单变量 A/B;基准指标盲区那一条 | **近**。缺第二、第三个数据集的契约与跑批 |
| **强**(主会) | 上面 + **判据在至少 2 个数据集上被验证**(重复/稳定能预测编译收益)+ 规范状态键 + 一个手工标注的决定样本(证明稳定性 ≠ 正确性)+ 逐判定点的编译/不编译消融(Decision Substitution) | **中**。主要工作是测量,不是写代码 |
| **Best Paper 档** | 上面 + **判据在样本外预测成功**(在一个我们没参与设计的控制器/数据集上,先预测后验证)+ **单调性被证明是必要的**(去掉它,量到伤害)+ 别人能复现 | **远**。前两条各需要一个我们控制不了的条件 |

★ 老实说:Best Paper 那一档的关键不是"结果更好",是**先预测后验证**。那才是判据和系统的区别。老师那份 brainstorm 里 H1–H3 都是系统性能假设,都不是"先预测后验证",所以照它写顶到第二档。

## 9.5 明确不做的（划出去,免得被当成没做完）

| 不做 | 为什么 | 谁做 |
|---|---|---|
| 文本 → 契约(提取) | 没有足够的自然语言,数据集也不自带流程描述;而且**手写契约本身是调参面**,要交代写它的时间点 | —— |
| 图 / PROV-O / 先例查询 / 因果链 | 那是 **semantica 的优势**;我们做它只会变成更差的 semantica | semantica |
| 递归自我改进 | 我们的单次 run 噪声 SD=1.30 题,在这种信噪比上主张 RSI 是负债 | —— |
| "决策漂移"当新现象 | 文献里有,μ 的 `turn.drift` 就是一个判定点;只保留"**重复状态上的漂移**"这个细化 | —— |

## 9.6 三个方法学缺口（按重要性）

1. **规范状态键。** `request_digest` 含无关的帧差异(截断、字段顺序),所以"不同状态"被高估、重复被低估。**在它做出来之前,那些重复率只能叫"请求重复率",不能叫"状态重复率"。** 它决定整张 2×2 表能不能用。
2. **稳定性 ≠ 正确性。** `pickTool` 34/34 一致也可能是**稳定地错**。需要一个手工标注的决定级样本,报一致性。
3. **第二个数据集。** 一个数据集是轶事,而且 20 题的噪声是 1.30 题。

## 9.7 最不容易被别人复制的东西

不是引擎,也不是判据 —— 是**测量纪律**。我们抓到了自己的四个错,而且都有数字:

| 自己抓到的 | 数字 |
|---|---|
| 一个读置信度的默认门限杀掉 4/20 道题 | 11/12 次丢弃落在 `risk`,置信度 0.23–0.41,门限 0.5 |
| 自查告警被记成判定 | 413 行(20%),`判定占比` 0.918 → 真值 0.898 |
| 退出口没有消灭循环 | 重复 ≥10 次的题 9 → 4,不是 → 0 |
| 判官的抬档通道是死的 | `too_low` 在 ALFWorld 上 14/14 没响,全是 `unsure` |
| 我们把"重试是抽奖"说重了 | 抖的是置信度,不是决定:八个节点 33–171 次重复零翻转 |

审稿人给分的是这个,不是又一个 agent 框架。

---

# 10. "控制熵"到底怎么量 —— 以及我们自己的数据推翻了它的一种说法

## 10.1 先记一次自己被自己咬

算这篇文章要用的熵时,我第一次得到 **30.3% 的翻转率**,而前面按状态算是 3/135。
差了 43 倍。原因是 **413 行那个记账 bug**:旧 run 里"自查告警"行还带着问题节点的名字
（`pickTool` / `pickInput`）和 `(candidate_already_done)` 这个答案,于是每个状态看起来
被问了两次、答了两次不同的东西。修完之后是 **0.1%**。

★ 这条比数字重要:**记账的标签错了,不只是账难看,是它下游的每一个统计都错。**
而且错得**看起来很正常** —— 30.3% 是个像样的数,不会有人怀疑它。
这就是"标签必须由结构隐含,不能靠人填"那条教训的第二次现身。

## 10.2 三个候选定义,以及哪一个站得住

| | 定义 | 怎么量 | 实测 | 判决 |
|---|---|---|---|---|
| **D1** | 答案熵 `H(答案 ∣ 状态)` | 同一请求重复问,答案的分布 | **0.1%** 翻转 | ❌ **它推翻了"编译降低决策熵"这句话** —— 本来就没多少可降 |
| **D2** | 数值熵 `H(置信度 ∣ 状态)` | 同一请求 `top()` 的分布 | 抖得厉害(0.44 / 0.40 / 0.46) | ⚠️ 弱:没人关心一个不被读的数 |
| **D3** | **有效控制熵** = **会被策略读到的**方差 | 固定状态下**策略输出**改变的比例 | 0.1%,而那一次翻转在 `risk` | ✅ **只有它站得住** |

D3 的定义一句话:

> **在同一个规范状态下,重采样会让策略的输出改变的概率。**

它是**策略感知**的 —— 它算的是"这个数有没有被读进去",而不是"这个数抖不抖"。

## 10.3 两种熵:潜伏的,和生效的

这是这一节最值钱的一条:

> **判官让「潜伏的熵」很大(数值抖),而让「生效的熵」很小(结果几乎不翻)——
> 除非你的策略去读那个数。**

数值抖:同一 digest 下置信度 0.44 / 0.40 / 0.46。
结果不翻:761 行重复状态里,只有 **1** 行翻转。

而一旦策略读那个数,潜藏的熵就**立刻变成行为的熵**。我们的证据:

```
step0 risk digest=88fff539a6972473 conf=0.390 ans=1  fallback=drop_below_bar
step1 risk digest=88fff539a6972473 conf=0.390 ans=1  fallback=drop_below_bar
step2 risk digest=88fff539a6972473 conf=0.410 ans=1  fallback=drop_below_bar
```

档位 32/33 稳定,而一个读 `top()` 的 0.5 门限把它丢掉 ⇒ **20 题里 4 题死,一次工具都没调。**

⇒ **设计规则:读决定,不读置信度。** `typed-4` 那两道确认题门限取 0 就是这条。
⇒ **也是对"控制熵"这个概念的正确用法**:它不是"我们要消灭的东西",它是
**"一旦被策略读到就会变成行为的东西"**,所以要么把那个读数去掉(编译),
要么把判据建在决定上而不是数值上。

## 10.4 那"编译"到底减少了什么(不是熵)

| 编译消掉的是 | 数字 | 来源 |
|---|---|---|
| **抽样次数** | 74.3 次模型调用/题,其中 **51% 落在重复状态上** | 上面那张表 |
| **去掉整条置信度通道** | `risk` 的档位从"判官给的分数"变成"规则查出来的档位" | typed-4 vs typed-3 |
| **一条稳定的错误变得可编辑** | 改一处规则 vs 改 prompt 然后祈祷 | 论断,还没量 |
| **可归因** | 89.6% 的决定是判官的 —— 这个数以前不存在 | 上面那张表 |

**而精度不该动**,因为每个决定本来就只有 0.1% 的翻转。这正好对上退出口那次 A/B:
**分数 1/20 两边一样,而工具调用 386→220。** 不是巧合,是同一个机制。

## 10.5 分离怎么被**证明**是真的分开了:替换消融

"把需要推理的和不需要推理的分开"不能靠说,要靠一次**替换**:
把某个判定点从"判官"换成"声明/缓存",然后看三件事 —— **行为、成本、跨次方差**。

| 替换之后 | 说明 | 该怎么做 |
|---|---|---|
| 行为**不变**,成本↓ | 它**不需要推理**,原来被误当成推理问题 | 编译它 |
| 行为**变坏** | 它**需要推理** | 留判官 |
| 行为**变好** | 判官**稳定地错** | 编译 + 修规则 —— 这是收益最大的一格 |

★ 我们已经有这个消融的两个实例,只是当时没这么叫它:
1. **退出口**:改了判官**能回答什么**(不是冻住它)→ 行为大变(重复 ≥10 次的题 9→4),而分数不动;
2. **`risk` 改成规则**:去掉了置信度通道 → 4/20 那道死法**构造上消失**。

## 10.6 该报的四个数,和三个坑

| 数 | 定义 | 现在 |
|---|---|---|
| **声明率** | `source="rule"` 的行 / 真判定行 | 0.2%(typed-3)/ 13.2%(typed-4) |
| **抽样次数/题** | `source="judge"` 的行 / 题数 | 74.3 / 57.0 |
| **有效控制熵** | 重复状态里策略输出翻转的比例 | 0.1% |
| **翻转暴露/题** | `Σ(该判定点的抽样次数 × 该点翻转率)` | 0.05 |

三个坑:

1. **状态键不是规范的。** `request_digest` 含无关的帧差异 ⇒ 重复率被**低估** ⇒ 熵的分母偏小。
   在规范状态键做出来之前,这些只能叫**请求**层面的数。
2. **旧 run 里的记录行会污染统计**(§10.1,43 倍)。
   分析任何旧 run 都必须按答案的括号约定剔除,不能只靠 `::violation` 后缀。
3. **翻转测"同不同",不测"对不对"。** 稳定地错不在这四个数里,要另用手工标注的决定样本。
