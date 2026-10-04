# Typed controller round: three real bugs fixed, and what remains

Continuing `docs/ALFWORLD-TYPED-ZERO.md`. Three defects were found and fixed; the arm still
does not work on ALFWorld, and the reason is now clearly not plumbing.

## Fixed

**1. `pickInput`'s frame excluded `history`.** Jev was asked "what next?" with no record of
what it had already tried, and looped on `examine cabinet 1`. The frame now carries
`already_done` (300 chars, list-clipped), matching the pattern `needsTool` and `isDone`
already used.

**2. `candidate_already_done` fired on every step.** It compared **tool names**, and
ALFWorld has one tool (`act`) — so after the first step the warning was permanently true
(187 reports in one run). A permanently-true warning is not a warning, and this is exactly
the "nobody looks at this invariant" disease it was written to prevent. It now compares
argument values and non-dynamic tool names.

**3. Below-threshold `pickInput` dropped the answer, and the retry was a lottery.**
Measured: the same `request_digest` asked repeatedly returned different confidences in
**19 of 20 groups** (0.44 / 0.40 / 0.46). Retrying an identical request cannot be error
recovery. `BELOW_THRESHOLD_POLICY` now distinguishes nodes whose failure the loop can
observe and correct (`pickInput` → accept the best candidate, flagged) from nodes where it
cannot (`canDeliver` — its product is the answer being delivered; `gradeRisk` — irreversible
actions). The recorded `correct` still means "did it meet its bar", so the account does not
lose the fact that a decision was a coin flip.

**4. `PICK_INPUT_ASK` said "Which file should this tool call target?"** There are no files in
ALFWorld; the tool is `act` and the candidates are `go to safe 1`, `take mug 1 from fridge 1`.
The phrasing came from the file-operation origin and names a concept that does not exist in
the domain. Changed to a task-relative question.

**5. `pickInput` passed no `criteria`.** `_choice_question`'s own docstring documents the
cost of empty criteria: options with names only, the model guesses from the name, and on
`bfcl-v3-multiple` that produced **82/100 `wrong_tool` at confidence 1.000** — "looks like a
wrong judgement, is actually underfeeding". Criteria are now derived from each command's verb
(uniform across tasks, not per-task hints), with a generic fallback for unknown verbs.

## Result after the fixes

6 fresh tasks, seed 20261004, same settings: **1/6**, up from 0/20.

| stop_reason | tasks |
|---|---:|
| `delivered` | 3 |
| `exhausted` | 2 |
| `declined` | 1 |

Steps now reach the budget (2, 7, 7, 19, 30, 30), so the premature-death failure is gone.
But the action distribution is still wrong:

```
go 28   examine 25   look 21   inventory 8   take 3   open 2   move 2
```

and two of six tasks repeat a single command 12 and 20 times.

## What remains, stated plainly

**Jev, asked to pick among ~28 free-form ALFWorld commands, does not choose task-progressing
actions.** It prefers inspection and navigation over the take/open/place sequence the task
requires. Fixing the frame, the warning, the retry policy, the question, and the criteria
were all real repairs — the arm went from dying at step 2 to running its full budget — and
none of them made the selection good.

That is a **capability boundary on the prior/action-selection use of a small decision
model**, and it is worth separating from its other use:

| use | evidence |
|---|---|
| **posterior** — judging a claim given evidence | ternary-judge: 0 false follows, matched the author's ternary baseline at ~4× lower token cost (`docs/FOURWAY-TERNARY-DEV.md`) |
| **prior** — choosing an action with no evidence yet | ALFWorld: loops on non-productive commands; does not complete tasks |

Those are the two halves of the prospective/retrospective distinction the project drew
early. The current evidence says the decision model is useful in one and not the other on
this task family.

## Consequences for the plan

- **Do not read the typed ALFWorld number as evidence about the architecture.** The
  architecture's question is what an *explicit control layer* buys; this arm's score is
  dominated by action-selection quality.
- **The `react` vs `react-termination` comparison remains the informative one on ALFWorld**,
  with the caveat already recorded: a terminal gate that only rewrites text cannot move an
  action-scored metric (`docs/ALFWORLD-PAIRED-RUN.md`).
- **Sample size before any claim.** The measured run-to-run SD is 1.30 on n=20
  (`docs/ALFWORLD-VARIANCE.md`); every arm needs repeats and a paired analysis.
- **If the typed arm is to be pursued on ALFWorld**, the next question is whether
  action-selection quality is a calibration/interface problem (fewer candidates, forced
  choice among task-relevant verbs) or a genuine model limit. That is a separate
  investigation, and it must not be run on the tasks already used for any reported number.

## Verification

438 Python tests pass; the three changed expectations are updated with their reasons
(the old `pickInput` frame-digest assertion pinned the behaviour that was the bug).
