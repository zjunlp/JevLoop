# `react-typed` on ALFWorld: 0/20, and why it is a controller gap, not a capability result

One run, same 20 tasks and seed as the paired comparison, `--max-steps 30`, real Jev (no
fallback). Result: **0/20** against `react`'s 8–11/20.

The number is not the interesting part. The mechanism is.

## What actually happened

| stop_reason | tasks |
|---|---:|
| `declined` (chose not to answer) | 13 |
| `exhausted` | 5 |
| `delivered` | 2 |

Step counts: mostly 2–10. The arm gives up almost immediately.

The decision trace of one task:

```
isDone     -> 0.020 ... 0.040 ... 0.030      correctly says "not done"
pickInput  -> examine cabinet 1   conf=0.54  accepted, executed
pickInput  -> examine cabinet 1   conf=0.53  accepted
pickInput  -> examine cabinet 1   conf=0.50  accepted
pickInput  -> examine cabinet 1   conf=0.46  REJECTED (below 0.5)
pickInput  -> examine cabinet 1   conf=0.53  accepted
... three consecutive rejections -> escalate -> declined
```

Two things compound:

1. **Jev loops on a non-productive command.** `examine cabinet 1` returns information and
   changes nothing, and the controller keeps re-choosing it. Across the run `examine safe 1`
   appears 56 times, `look` 60 times.
2. **The `pickInput` confidence threshold sits exactly at Jev's confidence mode.** Measured
   over the run: 217 `pickInput` decisions, median `top` 0.63, but the repeated-command
   states cluster at 0.41–0.54 — straddling the 0.5 threshold. So the same state alternates
   between "accepted" and "rejected", and three consecutive rejections terminate the task.

15% of all `pickInput` decisions fall below 0.5. That is not a huge rate on its own — the
damage comes from those rejections **clustering on one sticky state**, where the retry is
deterministic (same frame → same answer → same confidence) so the loop cannot escape.

## Two structural gaps, both in the controller

**Gap 1 — candidates are not deduplicated by (tool, argument).**

`candidates()` currently deduplicates by **tool name**, and I previously removed
deduplication entirely for tools carrying `live_candidates` — because ALFWorld has one tool
(`act`) whose *arguments* are the real action space, and tool-level dedup would end the loop
after one step (`docs/...`; the fix is in `typed.py`). That fix was right about tool names
and wrong about arguments: it left **nothing** preventing the same command from being offered
again.

The frame's own rule already states the intent — `candidate_already_done` fires 187 times per
run complaining that `act` is in the candidate set, which is now expected and therefore a
**stale check**. The correct rule is: exclude **(tool, argument)** pairs already executed,
not tool names, and not nothing.

**Gap 2 — the confidence threshold is uncalibrated for a large live-candidate space.**

`pickInput`'s threshold is 0.5 (`NODE_THRESHOLDS`, copied from `DECISION.md`). That value was
chosen where the candidate set is small. ALFWorld offers ~28 admissible commands per step,
the decision is inherently higher-entropy, and the confidence distribution now has its mode
right at the threshold.

**This must not be tuned on this batch.** Adjusting 0.5 until ALFWorld passes would be fitting
to the evaluation set. It needs a separate calibration set, and the repo already has the
vocabulary for this — the earlier finding that "the decision sits right on the threshold
because the frame's evidence is too thin" is the same disease.

## What this does and does not show

**Does not show** that independent control fails on long-horizon tasks. The arm never got to
run: 13 of 20 tasks terminated in under 10 steps for a reason internal to the controller.

**Does show** that the current typed controller is **not operational** on a large
live-candidate action space, and that this is where the work is. It also shows the arm is not
"the same generator with a different controller": on ALFWorld it produced **zero generation
calls** — Jev chooses every action — so it is better described as *Jev driving the loop*.

## Next steps, in order

1. **Fix candidate dedup to (tool, argument)** — principled, matches the documented intent,
   and directly attacks the observed loop. Then retire or rewrite the stale
   `candidate_already_done` check.
2. **Calibrate the `pickInput` threshold on data that is not this batch.** Report the
   confidence distribution and the threshold's position, not just the resulting score.
3. **Then** re-run the ladder with repeats, using the paired design from
   `docs/ALFWORLD-VARIANCE.md`.

Until 1 and 2 are done, `react-typed` numbers on ALFWorld measure the controller's plumbing,
not the idea.

## Artifacts

- run: `experiments/log/alfworld/react-typed/*seed20261003*`
- variance and sample-size context: `docs/ALFWORLD-VARIANCE.md`
- the paired `react` vs `react-termination` result: `docs/ALFWORLD-PAIRED-RUN.md`
