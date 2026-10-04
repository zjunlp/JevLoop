# Two ways to ask which action to take, and the measurement that picked one

**Question.** `pickInput` chooses the value of the first argument of the tool that
`pickTool` just picked. There are two ways to ask it, and they are two different methods:

- **comparative** — one question, all candidates in one option table, the judge compares
  them against each other.
- **admission** — one question per candidate, asked in a single round trip, each answered
  yes/no on its own. The escape is then *derived*: it is "no candidate cleared the bar".

I changed the default to admission on 2026-10-04, on the strength of a design lesson read
off μ and `browser-use/jev-ultrafast`: *the N-way argmax is the disease, one question per
candidate is the cure*. Then I measured it.

**Method.** Seed 20261003, temperature 0, 20 tasks, `max-steps` 8 (TERNARY) / 30
(ALFWorld), same generator (`qwen3.5-9b-local`), same judge (`jev-1.13.0`, no degraded
answers except where noted). Both arms share `run_loop`, the tool set, and the frame; they
differ in one field. Every run was made on a clean tree, and no run was made while another
was in flight.

The runs span three commits, none of which changed the frame or the policy thresholds:

- `778ae42` — `typed-9`. Candidate source fixed (`read_doc` offers what the search
  reported, not all 40 documents); shape still chosen by the controller default only.
- `7d577a3` — `typed-9`. `Tool.candidate_shape` added; TERNARY's `read_doc` declares
  `comparative`.
- `b9d7df1` / `1fe533f` — `typed-10`. Default shape flipped to comparative;
  `react-typed-admission` added; docs.

Because the default flipped, the arm carrying each shape changes its name partway through.
Both shapes are present under every spec version, so the contrast is read within a version,
never across one.

## Result

Every run below is reported; nothing is averaged away. All ten comparative runs and all six
admission runs are on TERNARY, seed 20261003, 20 tasks.

| code | spec | how the shape was chosen | comparative | admission |
|---|---|---|---|---|
| `778ae42` | typed-9 | controller default = admission; comparative forced by the arm | 15, 12, 12, 12 | 8, 8, 9, 9 |
| `7d577a3` | typed-9 | `read_doc` declares comparative; arm override did not yet exist | 11, 12, 10, 12 | — |
| `b9d7df1` | typed-10 | default = comparative; admission forced by the arm | 11, 11 | 9, 9 |
| **all runs** | | | **mean 11.8, n = 10** | **mean 8.6, n = 6** |

`7d577a3` has no admission cell for a reason worth recording: that commit made the tool
declaration outrank the arm, so both arms silently ran the declared (comparative) shape. Its
two `react-typed-singlechoice` runs are comparative runs, and they are listed as such.

ALFWorld, on the same tasks, both shapes present under each spec version:

| code | spec | comparative | admission |
|---|---|---|---|
| `7d577a3` | typed-9 | 3/20 | 0/20 |
| `1fe533f` | typed-10 | 2/20 | 0/20 |

The second admission run has one degraded judge answer, which its batch's `stop_reason`
records. The number carries that note rather than hiding it.

Paired, on the same 20 tasks: admission's correct set is a **subset** of comparative's.
Three separate batches, and in each one admission won **zero** tasks that comparative lost
(0 / 0 / 0, against comparative's 4 / 2 / 2). Admission is not differently right; it is
strictly less right.

## Why ALFWorld's admission arm also loses — the loop folds

The TERNARY mechanism does not explain ALFWorld, where the candidates are heterogeneous
commands. The ledger gives a different and blunter reason: **the admission arm stops after
about one action per task.**

| | comparative | admission |
|---|---:|---:|
| tool calls, all 20 tasks | 200 | **23** |
| `needsTool` questions | 193 | 40 |
| `isDone` questions | 174 | 23 |
| `pickInput` ledger rows | 192 | 1298 |
| exits | 16 delivered, 3 exhausted, 1 declined | **20 delivered** |
| tasks won | 2 | 0 |

Admission asks 1298 candidate questions and makes 23 tool calls. With hundreds of
admissible commands rated one at a time, the judge gives every one of them a low absolute
probability, so "no candidate cleared the bar" holds almost always; the derived escape
fires, the loop goes to finish, and the task is delivered one step in. The comparative arm
spends its 192 questions on a single option table per step and actually acts 200 times.

This also shows why the *derived* escape is the dangerous half of the admission design: an
absolute bar on a per-candidate yes/no probability is not the same quantity as the top of a
comparative distribution, and reusing `NODE_THRESHOLDS["pickInput"] = 0.5` for both means
"the judge is not fully certain" collapses into "there is nothing to do". μ's own advice,
recorded in `docs/ACTION-SELECTION-LESSONS.md`, is to make the no-information case a **flat
prior** rather than a refusal — this measurement is what happens when it is a refusal.

## Why — the candidate structure, not the shape

The mechanism is visible in the ledger rather than inferred. On TERNARY the search reports
one to three documents, and the controller now offers exactly those (`Tool.live_candidates`).
They are **three documents about the same company**:

| # | title | contains the founding year? |
|---|---|---|
| [1] | `Halvar Logistics — company profile` | **yes** |
| [2] | `Halvar Logistics — market news` | no |
| [3] | `Sector commentary #8` | no |

The question is "when was Halvar Logistics established". Comparative picked `d008` — the
profile — for q020, `d003` for q051, `d007` for q139: **correct in all three**. Admission
scored the three `0.31 / 0.29 / …`, ranked `[2]` first, and picked `d020`: market news,
which does not contain the year.

So the judge *can* tell these apart, from the titles, and it does when it has to compare
them. Asked one at a time it answers "plausibly, yes" to each and the ranking is worse. The
candidates are **homogeneous** — instances of one kind that are only distinguishable
against each other — and a comparative question is the only form that supports that.

The condition the design lesson was actually about is the opposite one: candidates that are
**heterogeneous** and can each independently be true or false, such as ALFWorld's admissible
commands. There, an N-way question spreads probability mass across every command that
"could make sense" and the mode sits pinned to the threshold — that observation was real
and it is why admission was built. It just does not apply to a retrieval result.

## What this does not show

- **ALFWorld is one run per arm** (two, for the final pair). The run-to-run standard
  deviation at n=20 is 1.30 tasks (`docs/ALFWORLD-VARIANCE.md`), so 3 and 2 against 0 and 0
  is suggestive, not established. What *is* established there is the loop-fold above, which
  is a structural difference of 200 tool calls against 23 and is not a small-sample effect.
- **Both typed arms are far below plain `react` on ALFWorld** (10.2/20), and that gap is
  larger and more important than the gap between the two shapes. This experiment did not
  address it; the diagnostics above are the starting point for it.
- **TERNARY's absolute numbers moved between batches** (comparative 15 → 10 across the
  day) while both arms were measured in every batch. Only the *within-batch* contrast is
  read here, which is why every batch is reported rather than a mean.
- **The cost side is not reported here.** Admission asks more questions per decision (N
  instead of 1: 80 `pickInput` ledger rows against 15 on TERNARY) and takes fewer round
  trips overall (209 against 217). Both are counted across all 20 tasks by
  `run_diagnostics`; neither is part of the claim above.

## What was changed as a result

- Default `PICK_INPUT_SHAPE = "comparative"` (`DECISION_SPEC_VERSION` → `typed-10`).
- `Tool.candidate_shape` lets an environment declare which structure its candidates have.
  Precedence is **explicit arm > environment declaration > global default**, so a contrast
  arm is never silently overridden — an earlier ordering got this backwards and made the
  `react-typed-singlechoice` arm run the declared shape, scoring 10 and 12 against
  `react-typed`'s 11 and 12 while its name claimed otherwise.
- `react-typed-admission` stays registered so the negative result is reproducible.
- `docs/ACTION-SELECTION-LESSONS.md` §七 item 2 is annotated with this measurement; the
  lesson as originally written was half wrong.

## Falsifiers

If the rule "shape follows candidate structure" is right, then on a dataset whose
candidates are genuinely heterogeneous — independent, individually admissible — the
admission shape should win. ALFWorld was the candidate for that test and it did not
confirm the prediction: 0 and 0 against 3 and 2 the other way. The reason is now visible
(the derived escape fires almost always on a long candidate list, folding the loop), so the
prediction is not merely unsupported but has a competing explanation.

What would settle it: an admission rule whose no-information case is a flat prior rather
than a refusal, measured on the same ALFWorld tasks. If admission then matches comparative,
the fault was the bar, not the shape, and the shape-follows-structure rule survives. If it
still folds, the rule is wrong and heterogeneous candidates do not want per-candidate
scoring either. Until that runs, the honest statement is the narrow one: **on TERNARY, with
a retrieval candidate set, comparative wins and the mechanism is understood; on ALFWorld
admission also lost, and the reason is the bar rather than the candidate structure.**
