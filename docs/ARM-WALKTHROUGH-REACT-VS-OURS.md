# `react` vs our method, on one real task

Written for line-by-line review. Every claim below is from the code as it stands and from a
real log; line numbers are given so they can be checked.

**Read this first:** the typed trajectory in §4 is from batch `2026-10-02T13-56-37Z`, which
**predates three fixes** made later the same day. §5 lists exactly what changed, so the
observed death is *historical*, not current behaviour. I am showing it because it is the
clearest illustration of the difference in kind between the two arms.

---

## 1. What is shared

Both arms are the same loop. `experiments/baseline/common.py:293`:

```python
def run_loop(session, cfg):
    controller = cfg.controller or LLMController()
    while len(steps) < session.max_steps:
        with session.span(...):
            prompt = build_prompt(session, cfg, steps)          # ① 拼 prompt
            view = DecisionView(prompt=prompt, tools=..., task_prompt=...,
                                step=len(steps), history=tuple(steps))
            parsed = controller.decide(session, view)           # ② ★ 岔路口
            if parsed.kind == "unparsed": ... continue
            if parsed.kind == "answer":  ... return AgentOutcome(final_answer=...)
            if parsed.kind == "ask":     ... return AgentOutcome(escalated=True, ...)
            observation = session.call_tool(parsed.tool, parsed.arguments)   # ③ 执行
            steps.append(Step(...))
    return AgentOutcome(escalated=True, error="用满步数")
```

Everything downstream — tool execution, accounting, scoring, the event stream — is identical.
**The only difference between the arms is what `controller.decide()` returns.** That is the
whole experiment.

`Decision` (`core/controller.py`) has four kinds: `tool`, `answer`, `ask`, `unparsed`.

---

## 2. `react`: the decision *is* the generation

`experiments/baseline/common.py:396`:

```python
class LLMController:
    def decide(self, session, view):
        reply = session.call_model([Message(role="user", content=view.prompt)])
        return parse_step(reply.text, view.tool_names(), ...)
```

One model call. The prompt is the whole scratchpad (`build_prompt` re-sends everything each
step). Whether to act, which tool, which argument, and whether to stop are **all encoded in
free text** and recovered by regex in `parse_step`.

Consequences, all mechanical:

- the stop decision exists only as the substring `Action: finish[...]` inside generated text;
- there is no separate object to ask about, log, replace or audit;
- argument values are whatever the model typed — for ALFWorld that means it can emit a
  command the environment does not accept.

---

## 3. Our method: the decision is a sequence of answered questions

`experiments/jloop/typed.py:519`, `TypedController.decide`. Per call:

```
ctx = ctx_from_steps(view.task_prompt, view.history)
ctx.remaining = candidates(session, ctx) 去掉 DONE        # 帧要装"还剩哪些事"
ctx.done_tools = 已调工具 + 它们的描述

① _review_last_step(...)      ← 补判「上一次 decide 之后发生的那一步」
                                 · stepOk  → 那一步成没成
                                 · isDone  → 整件事做完没有（过了 stepOk 才问）
② if not view.tools: _finish(deliver=False)   ← 没有工具就一次判定都不发
③ needsTool                   ← 还要不要动作
④ pickTool                    ← 挑哪个工具（候选每步重建）
⑤ gradeRisk(+needs_auth)      ← 多危险 / 要不要求授权（风险的来源见 §5）
⑥ pickInput                   ← 挑哪个参数
⑦ 执行工具
   …最终 _finish() → canDeliver（deliverable + unsupported）→ 交付 / 撤回 / 改道
```

Key structural properties:

- **`decide()` is called once per step, before the action** — so `stepOk` and `isDone`, which
  are about the *previous* step, can only run at the *start of the next* call (line 540).
- **`canDeliver` lives inside `_finish`, after the draft is generated** — because its object is
  the draft. Putting it in `decide()` would judge an answer that has already been returned.
- **`needsTool` and `pickTool` are deliberately not merged** (line 568): when the candidates
  run out, `candidates()` returns `[DONE]` and `pickTool` must not be asked at all.
- **Nothing is generated for the action path.** On ALFWorld the generator is called **zero
  times** during the loop; it is called only to write the final answer.

---

## 4. The same task, both arms

`pick_cool_then_place_in_recep-Bread-None-CounterTop-10`
Task: *"Put chilled bread on the counter, right of the fridge."*
`react` → **True**, 21 steps. `react-typed` → **False**, 2 steps, `declined`.

### `react`

Prompt, first call, 4236 characters (excerpt of the tail — the scratchpad is empty, so it ends
with the task):

```
… "Nothing happens." will not work — repeating it ten times will also not work.
  Look somewhere else, check `inventory` to see what you are carrying, and never
  repeat a command that just failed.

# Task
Put chilled bread on the counter, right of the fridge.
```

Model reply:

```
Thought: I need to find bread first. I will start by checking the fridge since bread
is often stored there, and the task mentions placing it right of the fridge.
Action: act[go to fridge 1]
```

Actions (20 tool calls total):

```
 1 go to fridge 1      -> You arrive at fridge 1. The fridge 1 is closed.
 2 open fridge 1       -> You open the fridge 1. …
 3 go to cabinet 1     -> You arrive at cabinet 1. …
 …
20 …                   -> won = True
```

The model is doing the deciding: it chose the fridge, then the cabinets, then the rest of the
sequence, and it chose to stop. It also wrote the command strings itself.

### `react-typed` (batch predating three fixes — see §5)

```
判定# 1  needsTool   -> 0.960
判定# 2  pickInput   -> go to countertop 1     conf=0.44   top=0.440 < 0.5
判定# 3  needsTool   -> 0.960
判定# 4  pickTool    -> act                    conf=0.84
判定# 5  pickInput   -> go to countertop 1     conf=0.40   top=0.400 < 0.5
判定# 6  needsTool   -> 0.950
判定# 7  pickTool    -> act                    conf=0.87
交付     text=None  escalated=True
         error="连续 3 步解析不出动作（最后一段: 'typed: pickInput —
                pickInput: top=0.460 < 0.5（答得不果断,不许拿它往下走）'）"
```

**Zero tool calls, zero generations.** The arm was asked "which command next?", produced a
perfectly reasonable answer (`go to countertop 1` — the counter is where the bread has to end
up), and **the confidence gate refused to act on its own answer** because `0.44 < 0.5`. The
retry is an identical request, so it fails the same way three times and the task ends as
`declined`.

That single trace is the difference in kind:

| | `react` | `react-typed` |
|---|---|---|
| who decides | the generative model, in text | the decision model, per question |
| argument selection | free text typed by the model | a choice among environment-provided candidates |
| stop decision | the substring `finish[...]` | an answer to `needsTool` / `isDone`, plus a delivery gate |
| when the gate refuses | nothing — there is no gate | a recorded `revise`/`blocked` with a reason |
| what is logged per step | prompt + completion + parsed action | one row per question, with confidence and frame/request digests |

---

## 5. What has changed since that batch

The `declined`-in-2-steps behaviour above is **no longer current**. Four fixes landed after it:

1. **`pickInput` no longer discards a below-threshold answer.**
   `BELOW_THRESHOLD_POLICY = {"pickInput": "accept"}` — for nodes whose failure the loop can
   observe and correct, the best candidate is used and the low confidence is recorded in the
   note instead of blocking the step. Reason: the retry was an *identical request*, and
   identical requests are not deterministic — 19 of 20 repeated digests returned different
   confidences (`docs/DECIDER-JITTER.md`).

2. **`pickInput`'s frame now carries `history`.** It previously excluded it, so the judge was
   asked "what next?" with no record of what it had already tried — it looped on
   `examine cabinet 1` 56 times in one run.

3. **`gradeRisk` looks up a declared risk** where the tool declares one
   (`Tool.base_risk`); only tools that cannot state a risk are judged.

4. **`stepOk` / `isDone` short-circuit on environment signals** where the tool declares them
   (`Tool.observation_signals`: `Nothing happens.` / `[task complete]`), and the delivery gate
   runs a deterministic number-grounding check before asking anything.

Current ALFWorld typed results after these: 1/6 on a fresh batch. Still far below `react`'s
8–14/20, and the cause is now **action-selection quality** — the judge prefers inspection and
navigation over the take/open/place sequence — not the plumbing
(`docs/ALFWORLD-TYPED-ROUND2.md`).

---

## 6. Two further differences worth reviewing

**What each arm sends to a decision backend.** `react` sends one prompt per step. Typed sends
typed questions with a *frame* (a declarative field list with per-field character budgets) and
a *request digest* covering frame + question + options. That is what makes "was this the same
question twice?" a checkable question, and what the jitter measurement above relied on.

**Where the arms diverge in the accounting.** Per task, `Result` records `stop_reason`
(§ recently added), `failure_class`, and for gated arms `gate_false_reject` /
`gate_corrected` / `gate_false_deny` / `gate_draft_correct`. `react` has all of the gate fields
false because it has no gate — which is a fact about the arm, not a measurement of zero error.

---

## Files to read, in order

| purpose | file |
|---|---|
| the shared loop | `experiments/baseline/common.py:293` |
| the undecoupled controller | `experiments/baseline/common.py:396` |
| typed controller entry | `experiments/jloop/typed.py:519` |
| the frame / question shapes | `experiments/core/frame.py` |
| the four decision kinds | `experiments/core/controller.py` |
| per-task result fields | `experiments/core/spec.py` (class `Result`) |
| real traces | `experiments/log/alfworld/{react,react-typed}/*seed20261003*` |
