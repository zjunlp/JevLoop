# Grounding on a real tool-using benchmark: the check must be searchable

Closes the gap left by `docs/GROUNDING-STEP2-POINTER.md`, which had the mechanism unit-tested
but never exercised end to end. It now has been — and the first version was **wrong in a way
that only a real run could show.**

## The venue

ALFWorld × `react-termination` × 20 tasks, seed 20261007, real Jev. This arm routes its
delivery gate through the same `TypedController._can_deliver`, so the pointer applies; it is
also the arm that actually works on this dataset (14/20).

The pointer only fires when **both** hold: the gate asserts `deliverable ≥ 0.6`, *and* the
draft contains digits. In this batch that intersection is **1 task in 20** — ALFWorld answers
are mostly prose. Two earlier attempts to exercise it failed for instructive reasons:

- **FTA**: single-shot tasks with the failure pre-staged in the prompt, **zero tool calls**.
  Nothing to point at, so the pointer is correctly `None`.
- **BFCL `act-typed`**: real tool calls, but `deliverable` was 0.04–0.59 on every task, never
  reaching the 0.6 `Pointer` threshold. The pointer only constrains *affirmative* verdicts, so
  it was never asked. Correct behaviour, no exercise.

## The failure the real run exposed

First implementation: **ask the model which recorded step contains the numbers, then validate
that cited step.** It fired twice, and **both were false positives on tasks that had already
been won**:

| task | first verdict | after grounding | truth | tool output in evidence |
|---|---|---|---|---|
| `pick_and_place_simple-Watch-None-Safe-219` | `deliverable=0.900` | **0.000** | `won=True` | `You move the watch 1 to safe 1. [task complete]` |
| `pick_and_place_simple-SaltShaker-None-Drawer-10` | `deliverable` affirmative | **0.000** | `won=True` | `You move the saltshaker 1 to the drawer 1. [task complete]` |

The numbers **were** in the evidence. **Jev answered the pointer question with
`none_of_the_recorded_steps` and was simply wrong.**

> **The pointer is itself a model judgement, with its own error rate.** A validator that only
> checks *the cited item* cannot detect that the model failed to cite an available one — so it
> converts the model's mistake into a confident downgrade of a correct verdict.

That is the same class of error this whole line of work exists to catch, appearing one level
up: a check that looks grounded, backed by a judgement that is not.

## The fix — and the simplification it implies

If the check is **searchable**, the model should not be asked at all.

> Where a verdict can be checked by retrieval, check it by retrieval. Ask the model to point
> only where the check cannot be done by search.

"Does this number appear in the recorded evidence?" is searchable. So `deliverable` now runs a
**deterministic pre-check before any model call**: every number in the draft must appear in
some recorded tool output. If not, the draft is asserting something the evidence does not
contain, the gate returns `revise / overclaim` immediately, and a row
`deliverable::grounding → (ungrounded:7,...)` records exactly which numbers failed.

Three consequences, all wanted:

- **the false positives are gone by construction** — the check searches all evidence, so a
  model that forgets to cite an available step can no longer block a correct answer;
- **it costs no model call** when the draft is ungrounded — the gate short-circuits;
- **the citation question is dropped**, because it was buying nothing: a searchable check does
  not need a model's opinion about where the thing is.

## Re-run

Same 20 tasks, seed 20261007: **14/20, identical**, and **0 ungrounded records**. The one
numeric draft was grounded and passed. The mechanism is exercised and, on this batch, never
fires — which is the correct outcome for a draft whose numbers came from real observations.

## Honest scope

- **It only governs numbers.** Prose assertions are not lexically groundable: "placed the
  microwaved apple in the fridge" against "The fridge 1 is closed." shares enough tokens that
  no search separates them. So this is a *narrow* grounding, and its coverage is
  batch-dependent — **1 task in 20 here**. Report the coverage alongside any number derived
  from it.
- **`won` is unaffected either way.** ALFWorld scores by replaying actions, so a gate that
  edits the answer cannot move the score. The 14/20 is the same before and after; this
  exercise tests the mechanism, not an effect.
- The pointer mechanism itself remains necessary for checks that are **not** searchable —
  the ternary case ("which document certifies this claim?"), where "supports" is open-ended
  and cannot be reduced to retrieval.

## What this changes about the design rule

The rule from `docs/UNDECIDED-DIAGNOSIS.md` — *a verdict must be able to point at something* —
needs one refinement:

> **Prefer a check the code can perform itself. Ask the model to point only when the check is
> not searchable — and then remember that the pointer is a judgement, and measure its error
> rate like any other.**

## Artifacts

- `experiments/jloop/typed.py` — deterministic number grounding in `_can_deliver`;
  `_numbers_in`; `Pointer` retained for non-searchable checks
- run: `experiments/log/alfworld/react-termination/*seed20261007*` (two batches, 14/20 each)
- tests: `experiments/tests/test_typed_controller.py` —
  `test_can_deliver_grounds_the_drafts_numbers_deterministically` covers grounded, ungrounded
  (asserting **no model call is made**), and no-numbers cases
