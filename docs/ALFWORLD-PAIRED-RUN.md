# Paired ALFWorld run: what it found, and one structural result

## Setup

20 tasks, `valid_unseen`, `--seed 20261003 --max-steps 30 --max-tokens 2048`, local
`qwen3.5-9b-local`, arms `react` and `react-termination` (real Jev, no fallback). Tree dirty
at 38 files and **unchanged across both arms**.

This batch has been run twice: once broken, once fixed. Both are recorded because the
broken one is the more useful lesson.

## Attempt 1 — void, and why

`react` 10/20, `react-termination` 3/20. The gap looked like a strong negative result for
the gate.

It was not. **The two arms received different prompts**:

```
react              prompt 3939 chars   (includes AlfWorld.exemplars())
react-termination  prompt 1690 chars   (exemplars silently dropped)
```

`run.py::make_agent` decides by **signature** whether to forward `bench.exemplars()`.
`react` is the bare class and declares `exemplars`; `react-termination` was
`lambda: ReAct(controller=...)`, which takes no arguments, so the exemplars were dropped
**without a word**. The signature check was written to prevent `TypeError`, and it does —
but it cannot prevent silently discarding a parameter, which is the failure mode this repo
keeps rediscovering.

Corroborating evidence, and it was visible before any re-run: **the two arms diverge at step
0** on 13 of 20 tasks. The gate only runs at the end. A terminal gate cannot influence step
0, so the divergence was never the gate's doing.

**Fixed**: the typed-arm factories now accept and forward `exemplars`, and
`test_alfworld_exemplars.py` pins that every react-family arm can receive them.

## Attempt 2 — with the confound removed

Prompts verified byte-identical (4236 chars both arms).

| arm | n | correct | delivered | 交付率 | 交付正确率 | excluded |
|---|---:|---:|---:|---:|---:|---:|
| `react` | 20 | 8 | 12 | 60% | 67% | 8 |
| `react-termination` | 20 | 10 | 14 | 70% | 71% | 5 (+1 blocked) |

**Run-to-run variance on the identical configuration is at least ±2.** `react` scored 10/20
before the fix and 8/20 after — same prompt, same seed, same model, temperature 0. The local
model is **not reproducible across runs**. With n=20, a 2-task gap is inside that noise.

So this batch does **not** show that the gate helps. It shows the two arms are
indistinguishable.

## The measurement bug this exposed

`gate_false_reject` read 0 and `gate_corrected` read 2. Both were wrong.

`_draft_was_correct` calls `bench.check()`. `AlfWorld.check()` **deliberately raises**
`NeedsTextWorld` — its own docstring says success lives in the environment, not the answer
string. The exception was swallowed, so `draft_correct` was structurally `False`, which made:

- `gate_false_reject` ≡ 0 — reading as "the gate never killed a good answer"
- `gate_corrected` collapse to `revise ∧ correct`

**The gate had rejected two tasks whose actions had already won, and the books recorded that
as "the gate corrected 2".** A false reject was booked as a save.

**Fixed**: on a `check()` exception the predicate now falls back to `score()` instead of
returning `False`. Since ALFWorld scores by replaying the trajectory, draft and final score
identically, and both fields return to their intended meaning.

Recomputed under the corrected predicate:

| gate behaviour | count |
|---|---:|
| false reject (rejected an already-winning task) | **2** |
| corrected | **0** |
| false deny (delivered a wrong answer) | 3 |

The gate rejected 2 winning tasks, fixed nothing, and let 3 wrong answers through.

## The structural result

**A terminal gate that only rewrites the final answer cannot move an action-scored metric.**

`AlfWorld.score()` replays `trajectory.steps` and reads `infos["won"]`. It never looks at the
final answer. A gate that changes only that text therefore cannot change the score — its
rejections are invisible to the metric, for good or ill.

That has three consequences:

1. **On ALFWorld, `react` vs `react-termination` native scores can only differ by generation
   noise.** The 8 vs 10 is exactly that.
2. **The only things this gate can move are delivery rate and the claim-side metrics** — the
   factorisation columns, not the task column.
3. **To move the task, the controller must be able to change *actions*, not words.** That is
   redirect. `react-termination` is structurally incapable of it: its own docstring says it
   has no prior action-selection path, so `_remedy` can only return `degrade`.

This is the same conclusion the four-way ternary comparison reached from the other
direction: a controller that only re-decides the text is not the contribution. The
contribution has to be a controller that re-enters the action loop.

## What to run next

`react-typed` — it has the prior path (`needsTool` / `pickTool` / `pickInput`), and after the
remedy-priority fix `_remedy` returns `redirect` when `deliverable` is low. That is the only
arm on this dataset that can turn a rejected stop into new actions and therefore into a
different `won`.

Two things to fix before spending on it:

- **Replication.** ±2 on n=20 means a single run per arm cannot distinguish anything. Either
  raise n or run repeats — and report the variance.
- **The local model's non-determinism.** temperature 0 is not reproducible here, so "same
  configuration, same result" cannot be assumed. Every paired comparison must run both arms,
  and the variance must be measured, not inferred.

## Artifacts

- void batch: `experiments/log/alfworld/{react,react-termination}/*seed20261003*` (first)
- fixed batch: same arms, later timestamps
- code fixes: `experiments/scripts/run.py` (exemplars forwarding),
  `experiments/core/runner.py` (`_draft_was_correct` fallback)
- tests: `experiments/tests/test_alfworld_exemplars.py`,
  `experiments/tests/test_pipeline.py`
