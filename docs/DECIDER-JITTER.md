# The decision backend is not deterministic, and the threshold sits inside its jitter

Found while fixing the ALFWorld `pickInput` loop. This is the most important measurement
in the typed-controller investigation so far, because it undercuts an assumption the
project has been stating rather than measuring.

## Measurement 1 — the backend jitters on identical requests

Same `DecideRequest`, sent 8 times, `jev-1.13.0` pinned, no fallback:

```
#1 top=0.580   #2 0.560   #3 0.580   #4 0.540
#5 0.560       #6 0.550   #7 0.570   #8 0.560
```

**Five distinct values for one request.** The chosen option was stable here, the
probability was not.

Jitter scales with the number of options:

| options | observed `top` across 8–12 identical calls |
|---|---|
| 2 | 0.97, 0.98 — spread 0.01, choice stable 12/12 |
| 28 | 0.54–0.58 — spread 0.04, choice stable |

So the noise floor is roughly **0.01–0.03**, and it grows with the candidate set — consistent
with the same serving-side effect already measured on the generator
(`docs/ALFWORLD-VARIANCE.md`).

## Measurement 2 — real runs show the same thing

In the `react-typed` ALFWorld run, decision records carry a `request_digest` covering frame
+ question + options. Grouping by that digest:

- **20 groups had the same request asked more than once**
- **19 of those 20 produced different confidences**

Example, one task, one identical request:

```
digest=b496f00cd7da91de   go to countertop 1   conf=0.44
digest=b496f00cd7da91de   go to countertop 1   conf=0.40
digest=b496f00cd7da91de   go to countertop 1   conf=0.46
```

Byte-identical request, three different confidences. One of those crossed 0.5; the others did
not.

## Why this broke the typed arm

`pickInput`'s threshold is 0.5. Measured over that run: 217 decisions, **median `top` 0.63**,
and the sticky repeated-command states clustered at **0.41–0.54**.

The threshold is *inside* the jitter band of exactly the decisions that matter. So:

1. A decision at 0.46 fails, is not recorded as a step, and the frame is unchanged.
2. The loop retries — with an **identical request**.
3. Because the answer is a fresh draw, the retry sometimes succeeds by luck (0.53) and
   sometimes fails again.
4. Three consecutive failures escalate, and the task ends as `declined`.

**Retrying an identical request is a stochastic retry, not error recovery.** The observed
0/20 is this, compounded with Jev repeatedly choosing a non-productive `examine X` — which
the frame gave it no way to know it had already tried (fixed separately, see below).

## What this costs the claim

The project has been asserting, and this session has been repeating, that a decision layer
is **deterministic and therefore auditable and replayable** — that this is the structural
advantage over a generative loop. **As measured on the hosted backend, that is false.** The
same request returns different probabilities.

It remains true that the decision is *separable* and *loggable* — which is the actual
architectural claim — but **"reproducible" must be replaced by "measurable noise floor"**.
Any report that says otherwise is overstating what we have.

Neither claim survives without this number: a threshold whose margin is smaller than the
backend's jitter is not a decision, it is a coin flip.

## What to do about it — principled fixes, not tuning

1. **Never retry an identical request expecting a different answer.** On a below-threshold
   answer the controller must either accept the best available candidate (recording that it
   was below threshold) or change the frame so the retry is a genuinely different question.
   Repeating it is a lottery.
2. **Report the margin, not just the verdict.** For every threshold decision, record
   `top - threshold` and the measured jitter. Decisions whose margin is inside the jitter
   band should be **flagged as coin flips** rather than counted as decisions.
3. **Do not move the threshold to fix ALFWorld.** Moving 0.5 only relocates which states are
   coin flips; it would also be fitting to the evaluation batch. The threshold needs a
   calibration set that is not this one.
4. **Re-measure per backend.** This is a serving property. A different provider may have a
   different noise floor, and it must be measured rather than assumed.

## Also fixed in this pass

The `pickInput` frame previously **excluded `history`**, so Jev was asked "what next?" with
no record of what it had already tried. It looped on `examine cabinet 1` (56 times in one
run). The frame now carries `already_done` (300 chars, list-clipped), matching the pattern
already used by `needsTool` and `isDone`. The `candidate_already_done` check was also
rewritten: it compared **tool names**, which on ALFWorld (one tool, `act`) fired 187 times
per run and was therefore ignored — a permanently-true warning is not a warning.

## Artifacts

- this document; probe scripts were run inline and their outputs quoted above
- run under analysis: `experiments/log/alfworld/react-typed/*seed20261003*`
- related: `docs/ALFWORLD-TYPED-ZERO.md`, `docs/ALFWORLD-VARIANCE.md`
