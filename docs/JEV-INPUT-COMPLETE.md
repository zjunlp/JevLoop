# What Jev actually receives — the complete request, and a bug it exposed

Companion to `docs/FRAME-ASSEMBLY-PICKINPUT.md`. That document described the assembly from the
code. This one shows the **complete request body** as sent, taken from a real run with
`--dump-requests` and the real `jev-1.13.0` backend.

## The call

`experiments/core/deciding.py:309` — `HttpJevClient.decide`:

```python
POST https://api.typesafe.ai/v1/systemone
body = {"model": ..., "state": request.state, "questions": request.questions}
```

There is **no system prompt and no message list**. `state` and `questions` are the entire input.
`state` is `{"frame": frame.render()}`.

## The complete body — first `pickInput` of a real run

Task: *"Place a heated mug in a cabinet."* (`pick_heat_then_place_in_recep-Mug-None-Cabinet-10`)

```json
{
 "model": "jev-1.13.0",
 "state": {
  "frame": "task: Place a heated mug in a cabinet.\nalready_done: (none)\n(absent — redirect_note)\n\n# Question\nWhich action should be taken next to make progress on the task?\n# Options\n1. go to cabinet 1\n2. go to cabinet 2\n...\n28. look"
 },
 "questions": {
  "pickInput": {
   "type": "choice",
   "instructions": "Which action should be taken next to make progress on the task?",
   "criteria": {
    "go to cabinet 1": "move to that location so its contents can be inspected",
    "...": "...",
    "inventory": "check what you are currently holding",
    "look": "look around — reports information and changes nothing"
   }
  }
 }
}
```

Rendered as text (which is what the dump stores, and what a human would read):

```
task: Place a heated mug in a cabinet.
already_done: (none)
(absent — redirect_note)

# Question
Which action should be taken next to make progress on the task?
# Options
1. go to cabinet 1
… 28 lines …
28. look
```

Three things to note about the shape:

- **`state.frame` and `questions` are separate.** The frame carries the state; the *options*
  travel inside the question, not in the frame. That is why a frame digest cannot tell whether
  two runs asked the same thing.
- **`(absent — redirect_note)`** — a declared optional field that is empty renders as an
  explicit absence. An empty *list* renders as `(none)`. "Not fed" and "nothing there" are
  deliberately different strings.
- **The question text and the options are duplicated** between `state.frame` and
  `questions[...].instructions`. The frame's `# Question` / `# Options` block is for reading;
  the wire form is what is actually consumed.

## A second request in the same run — two questions, one round trip

```
risk      -> 0       digest=e63d9cb2928a38d7
needs_auth-> 0.190   digest=e63d9cb2928a38d7
```

Same `request_digest` ⇒ one request carrying both questions. That is the merge the
`questions_in_batch` / `requests_in_batch` counters exist to make visible.

## The bug: `input` was `str(dict)`

A later `pickInput` in the same run, with history:

```
already_done: {'command': 'open microwave 1'}) -> You open the microwave 1. The microwave 1 is open. In it,..., act({'command': 'go to cabinet 1'}) -> You arrive at cabinet 1. On the cabinet 1, you see a dish..., act({'command': 'go to microwave 1'}) -> …
(truncated — history: 400→300)
```

**The judge was reading Python dict literals instead of commands.** Cause,
`experiments/core/frame.py:191`:

```python
input=str(s.action.arguments or s.action.content)
```

`s.action.arguments` is `{"command": "open microwave 1"}`; `str()` gives the literal.

Three consequences, the third of which was invisible until the request was printed:

1. **The judge read Python syntax, not the action.** `already_done` spent its budget on
   `{'command': …}` — measured at **400 → 300 characters of truncation**, i.e. the same number
   of steps gets cut sooner.
2. **`gradeRisk`'s `target` field** (`FrameField("last_input", 200, "target")`) was the same
   literal — the risk gate judged `{'command': 'rm -rf /'}` rather than `rm -rf /`.
3. **`candidate_already_done` was silently dead for `pickInput`.** That check intersects
   `r.input` with `question.options`; with a dict literal on one side and a bare command on the
   other, **the intersection is always empty**. A warning that never fires is the exact failure
   that check was written to prevent.

### Fix

`render_tool_input(arguments, content)`: a single argument yields **its value**, several yield
`k=v` pairs. Single-argument is the shape the typed controller produces
(`{first: picked.choice}`), and the candidate side already offers bare values, so the two sides
now have the same shape and the intersection is meaningful.

Measured on the same six real steps:

```
old: act({'command': 'go to microwave 1'})       624 characters total
new: act(go to microwave 1)                      534 characters total   (−14%)
```

## A second thing this exposed

One of the runs showed this in `already_done`:

```
already_done: __parse_error__() -> Could not parse an action. Reply with exactly one of: Act...
```

`run_loop` records a failed parse as a `Step` with the pseudo-tool `__parse_error__`
(`baseline/common.py:327`). That is correct for the trajectory — it happened — but it now
appears in the frame's history **as though it were a tool call**. `core/types.py::is_tool_call`
exists precisely to tell the two apart, and `ctx_from_steps` does not use it. Worth deciding:
either mark the pseudo-step as such in the rendering, or exclude it from `already_done`.

## Still open from the previous document

Unchanged, and still worth a decision:

- **`last_result` is excluded from `pickInput`** while `already_done` truncates each result to
  60 characters — the judge may be choosing its next move from a truncated view of the current
  state.
- **The frame text is only persisted with `--dump-requests`.** This entire document exists
  because that flag was passed; without it, neither bug above would have been findable from the
  logs.

## Artifacts

- real dumps: `experiments/result/_external/frame-dump-real/`,
  `experiments/result/_external/frame-dump/`
- fix: `experiments/core/frame.py` — `render_tool_input`, used by `ctx_from_steps`
- test: `experiments/tests/test_frame.py::test_tool_input_is_rendered_for_reading_not_as_a_python_dict`
- 450 tests pass; `check` clean
