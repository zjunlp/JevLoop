# Run-to-run variance on ALFWorld, and what sample size we actually need

Small replication study, run before spending on the arm ladder. Same arm (`react`), same 20
tasks, same seed, same budget, `temperature=0`, local `qwen3.5-9b-local`. Five independent
batches.

## Result

| batch | correct |
|---|---:|
| 1 | 10/20 |
| 2 | 8/20 |
| 3 | 11/20 |
| 4 | 11/20 |
| 5 | 11/20 |

mean 10.2, range 8–11, **SD 1.30 tasks = 6.5 percentage points**.

Per-task stability across the five runs:

| passed | tasks |
|---:|---:|
| 0 / 5 | 8 |
| 1 / 5 | 1 |
| 3 / 5 | 2 |
| 4 / 5 | 1 |
| 5 / 5 | 8 |

**4 of 20 tasks are unstable (20%)**; the rest are perfectly stable. Pairwise, any two runs
share identical action sequences on 14–19 of the 20 tasks.

## Why temperature 0 is not reproducible here

Investigated directly, because "same seed, same model" was supposed to mean same result.

**An isolated probe is deterministic.** Sending one prompt 8 times in a row, both a short
prompt and the real 4236-character ALFWorld prompt, gave 8/8 identical outputs.

**Inside a real run it is not.** For one task, comparing two batches call by call:

```
call #0:  prompt identical -> output identical
call #1:  prompt identical -> output DIFFERENT
             A: "...listed in the available actions..."
             B: "...listed in the allowed actions..."
call #2+: prompts differ (because #1 differed)
```

`available` versus `allowed` is a near-tie. **vLLM serves requests under continuous
batching, and batch composition perturbs the numerics enough to flip a near-tie token.**
From there the difference cascades: the Thought enters the scratchpad, the next prompt
differs, and the trajectory diverges — sometimes all the way to a different `won`.

So the non-determinism is a **serving artefact**, not sampling temperature. It cannot be
fixed by setting temperature to 0, and it is invisible to a single-request probe.

## What this costs the experiment

On n=20, two independent arms differ by SD ≈ 1.84 tasks. Every comparison at this size so
far has been inside that band:

- the void batch's 10 vs 3 — a real confound, but also beyond anything this design could
  measure cleanly;
- the fixed batch's 8 vs 10 — **1.1 SD, not a result**.

Rough sample sizes needed for a 2σ detection, at this flip rate:

| effect to detect | n per arm |
|---:|---:|
| 20 pp | ~17 |
| 10 pp | ~68 |
| 5 pp | ~272 |

These are **independent-arm** numbers. Paired analysis (McNemar on the same tasks, which is
what we have) is substantially more sensitive, because the 16 stable tasks contribute
nothing to the variance and only the ~20% flaky ones carry information. That is the design
to use.

## Consequences

1. **Never compare two single runs again.** Every arm runs at least K repeats; report mean
   and spread, not one number.
2. **Use the paired per-task structure.** Same tasks for every arm; analyse with McNemar and
   report the discordant counts, not two percentages.
3. **Budget for repeats.** Either ~70 tasks per arm, or fewer tasks with 3+ repeats each and
   an averaged per-task outcome.
4. **The 20% flaky tasks are the noise floor.** Any claimed effect smaller than what those
   tasks can plausibly move should not be reported.
5. **Record the batch composition problem.** It is a property of the local serving stack; a
   hosted API may behave differently, and the variance must be re-measured per backend
   rather than assumed.

## What to run next

The `react-typed` ladder, with repeats, on the same tasks — it is the only arm that can
change *actions* rather than wording, and therefore the only one that can move `won` (see
`docs/ALFWORLD-PAIRED-RUN.md`). Design: same 20 tasks, 3 repeats per arm, report per-task
outcome counts and a McNemar-style comparison.

## Artifacts

- five batches: `experiments/log/alfworld/react/*seed20261003*`
- related: `docs/ALFWORLD-PAIRED-RUN.md`
