# Grounding steps 3–5: environment signals, and two defects found by real runs

Continuing `docs/GROUNDING-STEP1-DECLARED-RISK.md` and `docs/GROUNDING-STEP2-POINTER.md`,
under the rule those produced:

> **Prefer a check the code can perform itself. Ask the model to point only when the check is
> not searchable.**

## 1. Environment signals are declared, not judged

ALFWorld's observations already carry two machine-readable signals, both from the environment:

| signal | string | source |
|---|---|---|
| `failure` | `Nothing happens.` | TextWorld's rejection of an inapplicable command |
| `goal_reached` | `[task complete]` | **our loader appends it from `infos["won"]`** — i.e. it *is* the scorer's truth, appearing early in the observation |

So `stepOk` and `isDone` are, in this environment, **searchable**. They are now declared by the
tool that produces the observations (`Tool.observation_signals`), on the same principle as
`base_risk`: the environment's properties belong to whoever owns the environment, not to the
controller.

The controller then short-circuits:

- failure signal in the last observation ⇒ `stepOk` is false, **no model call**;
- goal-reached signal anywhere in the history ⇒ `isDone` is true, **no model call**.

Both write a `…::environment` decision row so the account shows that the verdict was looked up
rather than judged. Tools that declare nothing behave exactly as before — an undeclared
signal must not be guessed, or every tool would be silently treated as failing.

**These did not fire in the run that tested them** (8 tasks, `react-typed`, seed 20261008):
the typed arm chooses only from `live_candidates`, so its commands are always legal and it
never sees `Nothing happens.`; and it won 0 of 8, so `[task complete]` never appeared. The
declarations are correct; this configuration does not reach them. `stepOk` and `isDone` were
therefore still asked of the model 122 times each.

## 2. The numeric grounding check fires — and misfires on enumerated prose

`deliverable::grounding` (from `docs/GROUNDING-REAL-RUN.md`) fired **4 times** in the first
8-task run. Auditing them required a fix first, because **the rejected draft was not being
recorded**, so there was no way to tell a true catch from a false one.

### Recording the rejected draft — and a field that silently went nowhere

The first attempt put the draft in `request_text`. That parameter is **not a field of
`DecisionRecord`**; it is only written to the `--dump-requests` file, which is opt-in. Without
that flag it is discarded — another instance of "configured, does not take effect". The draft
excerpt now goes into `note`, which is persisted unconditionally.

### An infinite feedback loop

The first version's feedback said:

> "答案里出现了工具输出里没有的数 ['3', '4', '5'] — …"

That text goes into the degrade prompt. The model **copied the numbers into the next draft**,
which the check then flagged again. The proof is in the final answers:

> "The tool failed to provide the specific numbers **['3', '4', '5']** required for the answer."

**The feedback was feeding itself.** It now states the *nature* of the problem and never
repeats the numbers: reflowed content becomes a new assertion.

### The remaining misfire: list markers are not assertions

With the drafts recorded, the flags could be read — and they are mechanically right but
semantically wrong. One rejected draft was:

```
Here is a step-by-step breakdown of the actions to put a warm mug on the coffee maker:

1.  **Pick up the mug**: Reach out and …
2.  …
3.  …
```

The observations contained 1 and 2 but not 3, so **`3` was flagged as an ungrounded value. It
is a list index.** The other rejected draft was an honest refusal — "I cannot perform physical
actions like placing a potato in a microwave…" — blocked and sent back for rewriting.

`_numbers_in` now strips leading list markers (`1.` / `2)` / `3、`) before extracting numbers,
with `(?!\d)` so `3.5` is not mistaken for a marker. Verified: enumerated prose yields no
numbers, `it weighs 3 kg` yields `3`, `1,284` still normalises to `1284`.

**A check that fires on every numbered answer is one nobody reads** — the same failure that
made `candidate_already_done` useless.

## What this sequence establishes

The rule earned across these steps, stated once:

1. **If a check is searchable** — strings in observations, membership in a declared set,
   numbers in recorded evidence — **do it in code and do not ask the model.**
2. **If it is not** — "does this document support this claim" — ask the model to point, and
   **measure the pointer's own error rate**, because the pointer is a judgement
   (`docs/GROUNDING-REAL-RUN.md` showed it blocking two won tasks).
3. **Whatever is extracted must be what was asserted**, not what was formatted. Numbers,
   in particular, are mostly structural in prose, and a checker that cannot tell the
   difference is worse than none.

## Still open

- **`needsTool`** was not touched. Its pointer would be "which required action has not
  happened" — searchable only where the task carries a structured requirement list, which
  none of our datasets currently do. Left alone rather than faked.
- **The environment signals remain unexercised.** They need either an arm that issues
  rejected commands or a batch that wins a task.
- **Coverage of numeric grounding is batch-dependent** — 4 firings in 8 tasks here, 0 in the
  20-task `react-termination` batch — and must be reported alongside any number derived from
  it.

## Artifacts

- `experiments/core/types.py` — `Tool.observation_signals`
- `experiments/benchmark/alfworld/alfworld.py` — the two declarations
- `experiments/jloop/typed.py` — `_signals`, `_hits`, short-circuits in `_review_last_step`;
  `_numbers_in` list-marker stripping; grounding record and non-echoing feedback
- runs: `experiments/log/alfworld/react-typed/*seed20261008*`
- tests: `experiments/tests/test_typed_controller.py` (449 total in the suite)
