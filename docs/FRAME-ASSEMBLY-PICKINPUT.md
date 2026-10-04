# How a decision frame is assembled — `pickInput` end to end

For line-by-line review. Everything below is quoted from the code or from a real dump
(`experiments/result/_external/frame-dump/`, produced with `--dump-requests`).

## The pipeline

```
DecisionView(task_prompt, history, tools)
   │  ctx_from_steps(task_prompt, history)        frames.py:181
   ▼
AgentCtx(task, history, last_tool, last_input, last_result, remaining, done_tools, …)
   │  compile_frame(frame_for("pickInput"), ctx)  frames.py:352
   ▼
Frame(node, lines, truncations, missing, missing_required, excluded)
   │  Request(frame=frame, questions=(…))         frames.py:765
   ├─ .render()  → the human-readable text (what --dump-requests writes)
   └─ .digest()  → frame + question + options     (what every decision row records)
   │
   ▼  _wire(question)                             typed.py:1626
DecideRequest(state={"frame": frame.render()}, questions={id: {type, instructions, criteria}})
```

Two different things leave the process, and it matters which is which:

- **`state.frame`** — the frame's `render()`, i.e. the labelled lines;
- **`questions[id]`** — the question and, for `choice`, a map from **option → criterion**.

The options are *not* in the frame. They travel in the question. That is why
`Frame.digest()` alone cannot tell whether two runs asked the same thing — hence
`Request.digest()` (line 805) covering frame + question + options.

## 1. `pickInput`'s declared fields

`experiments/core/frame.py`, `NODE_FRAMES["pickInput"]`:

```python
FrameSpec(
    node="pickInput",
    fields=(
        FrameField("task", 400, "task", required=True),
        FrameField("history", 300, "already_done", clip="list"),
        FrameField("redirect_note", 400, "redirect_note"),
    ),
    excluded=(("last_result", "判的是**这一调**的目标,不是上一步返回了什么"),),
)
```

`compile_frame` (line 371) then, for each declared field:

```python
raw = getattr(ctx, spec_field.name, None)
if raw is None or (isinstance(raw, str) and not raw.strip()):
    missing.append(name)
    if spec_field.required: missing_required.append(name)
    continue                                  # ← 不渲染,只记进 missing
if isinstance(raw, (list, tuple)):
    items = list(raw)[:MAX_LISTED_CANDIDATES]  # 20
    body = ", ".join(str(x) for x in items) if items else "(none)"
else:
    body = str(raw)
body, original = _clip(body, spec_field.budget, spec_field.clip)
if original > len(body):
    truncations[name] = (original, len(body))
lines.append(f"{spec_field.label}: {body}")
```

So three declared fields, one excluded, and each line carries a **label** (`task`, `already_done`,
`redirect_note`) rather than the ctx attribute name.

`StepRecord.__str__` (line 70) is what makes `already_done` readable:

```python
def __str__(self):
    arg = f"({self.input})" if self.input else "()"
    res = " ".join(self.result.split())
    if len(res) > 60: res = res[:57] + "..."
    return f"{self.tool}{arg} -> {res}" if res else f"{self.tool}{arg}"
```

→ `act(go to cabinet 1) -> You arrive at cabinet 1. On the cabinet 1, you see a pla...`

## 2. Where the options come from

`TypedController._arguments` (`typed.py`, the `pickInput` block):

```python
provider = candidate_provider(tool)          # frame.py:997
options  = [o for o in provider(ctx)]
…
criteria = {o: _input_criterion(o) for o in options}
```

`candidate_provider` for a tool with `live_candidates`:

```python
if tool.live_candidates is not None:
    return lambda ctx: [str(v) for v in tool.live_candidates()]
```

For ALFWorld, `live_candidates=self.admissible` → the environment's `admissible_commands`
**for the current step**. That is the whole reason `pickInput` is a closed-set question rather
than free text.

`_input_criterion` maps the command's **verb** to a sentence
(`go to` → "move to that location so its contents can be inspected"; `examine` → "inspect that
object — reports information and changes nothing"; unknown verb → a generic fallback).

## 3. The real thing, first step of a real run

`--agent react-typed --decider mock`, one ALFWorld task, `--dump-requests`. The rendered text:

```
task: Put chilled lettuce on the counter.
already_done: (none)
(absent — redirect_note)

# Question
Which action should be taken next to make progress on the task?
# Options
1. go to cabinet 1
…
28. look
```

Note `(absent — redirect_note)`: a declared-but-empty **optional** field is rendered as an
explicit absence, while an empty **list** renders as `(none)` — "not fed" and "nothing there"
are deliberately different strings.

And the wire payload:

```json
{"pickInput": {"type": "choice",
  "instructions": "Which action should be taken next to make progress on the task?",
  "criteria": {"go to cabinet 1": "move to that location so its contents can be inspected",
               …
               "look": "look around — reports information and changes nothing"}}}
```

28 options here (the environment's admissible set at step 0), each with its own criterion.

## 4. Four things I would review

**(a) `last_result` is excluded from `pickInput`, and `already_done` truncates each result to
60 characters.** The exclusion is justified in the code as "the judge is choosing this call's
target, not reporting the previous result" — that rationale comes from the **file-task** origin,
where the target is a path and the previous result is unrelated. In ALFWorld the next command
depends precisely on what the last observation said:

```
act(open cabinet 1) -> You open the cabinet 1. The cabinet 1 is open. In it, you see a
```

…and the observation continues past 60 characters with what is actually inside. So the judge
may be choosing its next move from a **truncated** view of the current state. Worth deciding
deliberately: either un-exclude `last_result` for this node, or raise the per-step result cap
in `StepRecord.__str__`. Both change behaviour and would need a fresh batch.

**(b) The frame text is only persisted when `--dump-requests` is passed.** `DecisionRecord`
carries `frame_digest` and `request_digest` but no text; `DecisionBatchEvent` carries neither.
So for an ordinary run you can prove *that* two requests were identical, and you cannot read
*what* was asked. Given how much of this project's work has been "go back and look at what the
judge actually saw", this is uncomfortable. Making it default-on (or default-on for a sampled
fraction) is a one-line change with a size cost.

**(c) Options are budgeted separately from the frame.** `MAX_OPTIONS = 32` and
`MAX_REQUEST_CHARS = 4000` are checked in `Request.check`, and exceeding the option budget is
**non-fatal** — it is reported and the request still goes out. The comment records the
measurement behind this: 28 candidates judged *better* than 20 or 8, and 77 degraded to
`top = 0.425`. Nothing between 28 and 77 has been measured.

**(d) `already_done` is clipped to the tail.** `clip="list"` means `_clip` keeps
`text[-300:]`, so past roughly step 7 the earlier steps fall out of the frame and only the
recent ones are shown. That is almost certainly right (recent history is what matters), but it
means **a 30-step ALFWorld run hides most of its own history from `pickInput`**, and the
truncation is only recorded in `Frame.truncations` — which does not reach the decision row.

## Summary table

| what | where | budget / behaviour |
|---|---|---|
| `task` | `ctx.task` | 400 chars, **required** — missing ⇒ fatal, the request is not sent |
| `already_done` | `ctx.history` via `StepRecord.__str__` | 20 items, then tail 300 chars; each result capped at 60 |
| `redirect_note` | `ctx.redirect_note` | 400 chars, optional; empty ⇒ `(absent — …)` |
| `last_result` | — | **excluded** (rationale from the file-task origin; see (a)) |
| options | `tool.live_candidates()` | ≤ 32, **not in the frame**; over-budget is reported, not fatal |
| question | `PICK_INPUT_ASK` + `_input_criterion` | per-option criterion, sent in `questions[id].criteria` |
