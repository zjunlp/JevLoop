# Engine or host: where a decision point should hang

Question from the user, 2026-10-04: 「挂在事件上面,和挂在循环步上面,哪个合理?」「目前这个循环步
看过来好像没有我们之前想象的那么有用,毕竟我们一开始是单纯的直接在 agent loop 的基础上修改的,
所以可能说还是做了一个 loop 的格式.」

That suspicion is correct in the part that matters. This document says which part, and what to do.

## 1. The question hides the real one

"Events or loop steps" is not a choice between two styles. It is a question about **one** thing:

> What decides when a decision point runs?

The criterion is forced by a rule we already accepted and measured: **the trigger must be the moment
when that decision's evidence exists.** A frame that does not contain the evidence cannot be judged
(`AGENTS.md` §8.2). So the trigger is not a preference — it is a property of the decision.

Seen this way, "loop step" is not an alternative. It is a **proxy**: "assume every decision's
evidence is available at the top of the loop." The proxy is right for some decisions and wrong for
others.

## 2. Two places where the proxy is already wrong in our own code

**① `stepOk` and `isDone` had to be bolted on.**

Both judge the step that just finished. The loop calls `decide()` *before* the next step. So the
evidence for these two exists in the middle of a loop iteration, and the trigger is at the top of
one. We wrote `_review_last_step` to run them at the start of the *next* `decide()` call.

That compensating pass is not a design feature. It exists **only** because the trigger is the loop
step. μ's analogous points have no such mechanism, because they fire when the tool result arrives.

**② A decision whose evidence arrives between two loop steps has no home.**

`tool.admission` is "should this chunk of tool output enter the context at all?" Its evidence is one
chunk of output. There is no point in our loop where that decision can be asked. We do not have it
— **not because we decided against it, but because the arrangement cannot place it.**

That is the general form of the problem, and it is the strongest argument in this document:

> The arrangement decides which decision points you can even *find*.

Sit inside one loop and you will discover "should I act?" and "am I done?". You will not discover
"should this chunk enter the context?", because there is no seam to attach it to.

## 3. What events cost, honestly

An event arrangement is not free, and three costs are real:

1. **Order is no longer free.** A sequence gives an order by construction. With triggers, two points
   on the same event need a declared precedence.
2. **Batching gets harder.** One request with many questions pays off when the questions share one
   state at one moment. Points on different events do not share a moment. μ's answer is
   `questionsFor` — one question per candidate, one state — which is a technique we already need
   anyway (`PICKINPUT-CLASSIFICATORY.md`).
3. **A subscription graph is harder to read than a sequence.** Our current controller is readable
   precisely *because* it is one host's sequence. That readability is a real asset and it should be
   kept in the host, not in the engine.

So the honest position is not "events are better". It is: **events are better for the engine, and a
sequence is better for a host.**

## 4. What μ actually does

From their source (`packages/kyrn-judge/src/decision.ts`) and README:

- Each decision point declares a `latency`: `inline` (blocks the loop), `parallel`, or
  `background` (never blocks). **A point that never blocks cannot be a step in a per-step
  sequence** — that class alone settles the question for them.
- Their turn diagram attaches points to moments: input arrives, a tool call is proposed, a chunk of
  tool output arrives, the context passes a threshold, the turn ends.
- `DecisionEngine.decide(spec, input)` has no scheduler. The **caller** decides when to ask. The
  trigger lives at the call site, not in the engine.

So μ is event-attached, and the engine itself is trigger-agnostic. That is the shape to copy.

> **Scope correction (user, 2026-10-04): 溯源这件事是 semantica 他们的优势,对于我们而言是控制。**
>
> 这一节的第一版把四条里三条写成了"溯源/图谱"的功课,而那会让我们长成一个
> 更差的 semantica。**我们不建图,不做 PROV-O,不把溯源当主张。**
> 溯源对我们只有一个用途:**它是"谁做了这个决定"可核对的必要条件** ——
> 没有它,「控制不是生成」这句话就不可证伪（`docs/MU-CONFLICT.md` 第 4 行）。
> 所以它是**手段**,而且是四种里最不起眼的那一种。
>
> 读下面四条时请按这个权重:第 ① 条是定位,第 ③ 条是手段,**第 ②④ 条不属于我们**。

## 5. What semantica teaches us

[semantica-agi/semantica](https://github.com/semantica-agi/semantica) — graph-native context and
provenance infrastructure. It is **not** an agent engine and it has no control semantics. Four
things are worth taking, and one is worth quoting.

**① Their thesis sentence is our thesis sentence.** From their README:

> **System-level explainability, not foundation-model explainability.** Semantica doesn't expose or
> reconstruct what happens *inside* the LLM: its internal reasoning stays opaque. Semantica explains
> what's *outside* the model: **the context fed in, the decision produced, its provenance, relevant
> relationships, applied policies, and the full execution trail.**

That is 「控制不是生成」 in different words, from a project with independent traction. It is the
best evidence we have that the framing travels.

**② A decision is a node, not a log line — 这一条不是我们的方向。**

They can answer "what is this decision's causal ancestry", "what decisions are similar to it",
"what did it affect downstream". We cannot, because our rows have no edges. **That is theirs, and
building it would make us a worse version of them.** What we take from it is one narrow thing:
a row whose label is *derived* rather than typed in cannot lie about who decided. We retrofitted
provenance and immediately found **413 rows (20%) mislabelled as judgments**
(`docs/ALFWORLD-ESCAPE.md`). That is a **control-measurement** lesson, not a graph lesson.

**③ Provenance is a means for us, not a product.** Their line — *"Decision provenance and audit
trails aren't the product. They fall out of that structure for free"* — is about a structure we are
not building. For us provenance has exactly one job: make 「控制不是生成」 falsifiable. A decision
row that cannot say whether a rule or a judge produced it makes that sentence unfalsifiable, and an
unfalsifiable sentence is not a research claim. **We need it; we do not sell it.**

**④ Ontology with declared constraints — 借形状,不借规模.** Their OWL/SHACL layer is a first-class
artifact. What we need from it is not a graph schema but the *discipline*: a contract that is
declared, versioned, and **rejected before use** when malformed. That is what
`core/contract.py::validate_all` and `docs/DECISION-CONTRACT.md` §1 already are. Our
`decision_spec_digest()` is the same idea for "is this the same method".

**Where they are not us.** Semantica owns the substrate: ingestion, ontology, graph, provenance,
precedent. Their `check_decision_rules()` is a policy gate over a **recorded** decision — post-hoc.
They have no notion of a position at the moment of action, no verdict ladder, no "the judge may only
tighten", no `shadow`, no rule-versus-judge accounting. **Substrate theirs, control ours.**

> **Update (2026-10-04).** §4.1 of this document — "node declaration versus loop graph", and
> "a portable file should not assume a linear loop" — **was already designed in
> `docs/DECISION-CONTRACT.md` §4.1**, 538 lines written before this file. My first pass here
> re-derived it and invented a rival vocabulary (`EVENTS` / `trigger`). That was wrong on two
> counts: it duplicated an existing design, and it gave one concept two names, which the user's
> 2026-10-04 style rule forbids. The code now uses the document's name — **`position`** — with the
> six values parsed straight out of `DECISION.md`'s `when:` lines, and the test
> `test_the_position_vocabulary_is_the_one_in_decision_md` fails if the two ever drift.

## 6. `DECISION.md` is already 80% of a spec

This is the part that makes the advisor's proposal concrete. `DECISION.md` already declares:

```
## needs_tool
kind: noul
when: step-start        ← ★ a trigger, already there
ask: ...                ← the question
- true — ...            ← the criteria
frame:
  + task  400  ...      ← the evidence, with a field budget
```

`kind` → question type. `ask` + criteria → `Question`. `frame` → `FrameField` list. The `when` line
**is** the trigger.

So the compile from spec to hook is already most of the way there, and `typed.py` is the
hand-compiled output — which is why `decision_spec_digest()` exists at all.

**What is missing is exactly one contract**, and it is small:

1. `when` must name a **host-independent event** (`tool.returned`, `context.threshold`), not a
   host-relative moment (`step-start`, `before-call`).
2. A host must **declare the events it emits**, as data.
3. A check must bind the two: every decision's `when` must be satisfiable by the host, or the
   decision is reported as *unplaceable* — the same treatment we gave to arms that cannot run
   (`test_the_honest_gaps_are_gaps_not_silent_wrong_arms`).

With those three, "compile `DECISION.md` to code" is a registration step, not a rewrite. Without
them, every decision point has to also declare *where in this particular loop* it goes, and the spec
is no longer portable — which is the loop-format problem the user suspected.

## 7. The decision

**Split the engine from the host, and stop calling the host the design.**

| | what it is | what to do |
|---|---|---|
| **engine** | decision points as data: trigger, evidence, question, policy, fallback, mode, provenance | extract; this is the reusable artifact |
| **host** | a loop that emits events and asks the engine | keep; this is one adapter |

Already engine-shaped, currently fused inside `TypedController`: the question vocabulary and
thresholds, the policy tables, `FALLBACK_POLICY`, `DELIVERY_CERTIFICATES`, `RISK_PATTERNS`,
`source`/`fallback` provenance, `shadow`, the spec fingerprint.

Host-shaped: the eight-node sequence, the twelve skip conditions, `_review_last_step`, `run_loop`.

**Four steps, in this order:**

1. **Rename.** `react-typed` is "engine + the react loop host". This is not cosmetic: it changes what
   code gets refactored and what gets frozen.
2. **Add `trigger` to every decision point** and replace the host-relative `when` values with event
   names. No behaviour change. This alone turns "events or steps" from a rewrite into a data
   question.
3. **Add one decision point that the loop cannot host** — `tool.admission` ("does this tool output
   enter the context?"), triggered by `tool.returned`, per output. Make it **rule first** (does the
   frame budget fit? is the output empty? is it an exact repeat of an earlier one?) with the judge
   only for the residue. This is the falsifier for the whole engine claim: **if it cannot be added
   without touching the eight-node sequence, then the loop arrangement really is a format, and the
   user's suspicion is right.** μ has the measurement method for this point already (40–46% of a
   failing test log cut, zero required lines lost).
4. ~~**Give each decision record a parent link.**~~ **取消 —— 这是溯源方向的活,那是 semantica
   的优势不是我们的**（用户 2026-10-04 的范围纠正）。把它加进去只会让我们开始建半个图。
   我们需要的"结构足够到标签不会说谎"已经在 `source` / `fallback` / `settled_by` 三个字段里
   做到了,那三个字段服务于**控制的可核对性**,不是为了查因果链。

**What we do not do:** rewrite everything into an event graph. The numbers we have came from the
loop host and they are real — the escape halved looping, the gates moved the claim cross-tab, and
the risk-threshold defect was found by the accounting. The loop is our **measurement vehicle**. It
is just not the design.

## 7b. 一处我说了但没做的事（记下来,因为它是这个仓库反复栽的形状）

2026-10-04 我在对话里说过「这条也写进 `docs/TEXT-TO-CONTROL.md` 了」。**那个文件不存在。**
我没有创建它,却把"已经写好"当成事实说了出来。

★ 这不是笔误,是 §8.15 那个形状的又一次:**声明和事实之间没有任何东西检查。**
  代码那边我们已经有机制（`decision_spec_digest` 钉住"改了要 bump"、
  `test_no_question_constant_escapes_the_fingerprint` 钉住"加了要登记"）。
  **文档这边没有** —— 所以一句"我写了"可以活一整轮而没人发现。

★ 缓解办法不是"以后小心一点",而是可查:凡是引用一份文件,就在同一步 `ls` 它。
  这一轮的做法就是这样发现它的（`test -f docs/TEXT-TO-CONTROL.md` → 不存在）。
  那条命令本来应该在我打出那句话**之前**跑。

## 8. The non-claims

- This is not a claim that the loop arm is worthless. Its value is narrower than we assumed: it gave
  a controlled comparison, and the eight-node *sequence* is an implementation detail, not a result.
- This is not a claim that events generalize to every domain. A procedure-shaped task (an enterprise
  workflow with defined steps) is closer to the loop than to the event graph, and the advisor's
  "process knowledge as input" case is exactly that. The right reading is: **the engine must be
  trigger-agnostic so that both a loop host and a procedure host can drive it.**
- semantica was read at the README level, not audited. The four lessons above are from its own
  description of itself. Their claim that provenance "falls out for free" is a claim, not something
  we verified.
