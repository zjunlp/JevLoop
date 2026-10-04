# Paired ladder result: `react` vs `react-termination` on ALFWorld

Step 3 of the typed-controller goal. Same 20 tasks (seed 20261003), same budget, both arms
repeated, void batches excluded by checking the prompt actually carried the benchmark's
exemplars.

## Runs

| arm | repeats | scores | mean | SD |
|---|---|---:|---:|---:|
| `react` | 5 | 10, 8, 11, 11, 11 | 10.20 | 1.30 |
| `react-termination` | 4 | 10, 10, 11, 10 | 10.25 | 0.50 |

One `react-termination` batch (`12-28-31Z`, 3/20) is **excluded**: it ran before the exemplar
forwarding fix and its prompt was missing the benchmark's exemplars. Detected by checking the
first model request for the exemplar text, not by its score.

**Difference: +0.05 tasks, +0.3 percentage points.**

## Paired analysis

Per-task majority across each arm's repeats, then McNemar:

| | count |
|---|---:|
| both arms correct | 10 |
| both arms wrong | 9 |
| only `react-termination` correct | 0 |
| only `react` correct | 1 |

**Exact McNemar p = 1.000.** Nine of twenty tasks are never solved by either arm; ten are
solved by both. Essentially nothing moves.

## What this means

The terminal gate is **invisible to this metric**, which is what the structural analysis in
`docs/ALFWORLD-PAIRED-RUN.md` predicted: `AlfWorld.score()` replays actions and reads
`infos["won"]`, and a gate that only rewrites the final answer cannot change either. The
arms differ in wording, not in what the agent does.

So the ALFWorld result is **not** evidence that explicit control fails. It is evidence that
**this comparison cannot test the question** on this dataset. The gate did do things — 2 false
rejects and 3 missed false answers were measured by hand — but the native metric cannot see
any of it.

## Where the claim can actually be tested

Three options, in increasing cost:

1. **Report the factorisation, not the task score.** On ALFWorld the only quantities a
   terminal gate can move are 交付率 and 交付正确率 (`docs/UNIVERSAL-METRIC.md`). Those are
   measurable here and were not the target of this run.
2. **Use an arm that can change actions.** `react-typed` can, but its action selection is
   currently poor on ALFWorld (1/6 after the fixes in `docs/ALFWORLD-TYPED-ROUND2.md`) and
   that would dominate any comparison.
3. **Use a dataset where the terminal decision is load-bearing** — where the answer *is* the
   deliverable and the task state is judged from it. `ternary-judge` is that dataset, and it
   already produced a clean four-way comparison.

## Standing constraints from this batch of runs

- Run-to-run SD on n=20 is 1.30 tasks; a single run per arm cannot distinguish anything
  (`docs/ALFWORLD-VARIANCE.md`).
- The generator and the decision backend are both non-deterministic per call
  (`docs/DECIDER-JITTER.md`); repeats are mandatory, not optional.
- Every reported batch must be checked for the exemplar forwarding, since a silent drop
  invalidated one batch here.
