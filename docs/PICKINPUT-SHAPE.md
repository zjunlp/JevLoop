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
answers). Both arms share `run_loop`, the tool set, and the frame; they differ in one
field. The batch that produced the numbers below ran on a clean tree at `b9d7df1`
(`DECISION_SPEC_VERSION = typed-10`).

## Result

Every run below is reported; nothing is averaged away. All ten comparative runs and all six
admission runs are on TERNARY, seed 20261003, 20 tasks.

| code | how the shape was chosen | comparative | admission |
|---|---|---|---|
| `778ae42` | controller default = admission; comparative forced by the arm | 15, 12, 12, 12 | 8, 8, 9, 9 |
| `7d577a3` | `read_doc` declares comparative; arm override did not yet exist | 11, 12, 10, 12 | — |
| `b9d7df1` | default = comparative; admission forced by the arm | 11, 11 | 9, 9 |
| **all runs** | | **mean 11.8, n = 10** | **mean 8.6, n = 6** |

`7d577a3` has no admission cell for a reason worth recording: that commit made the tool
declaration outrank the arm, so both arms silently ran the declared (comparative) shape. Its
two `react-typed-singlechoice` runs are comparative runs, and they are listed as such.

ALFWorld, one run per arm at `b9d7df1`: comparative **3/20**, admission **0/20**.

Paired, on the same 20 tasks: admission's correct set is a **subset** of comparative's.
Three separate batches, and in each one admission won **zero** tasks that comparative lost
(0 / 0 / 0, against comparative's 4 / 2 / 2). Admission is not differently right; it is
strictly less right.

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

- **ALFWorld is one run per arm.** The run-to-run standard deviation at n=20 is 1.30 tasks
  (`docs/ALFWORLD-VARIANCE.md`), so 3 against 0 is about 2.3 σ and is suggestive, not
  established. Both typed arms are far below plain `react` on ALFWorld (10.2/20) and that
  gap is the larger and more important one; this experiment did not address it.
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
confirm the prediction (3 against 0 the other way). A second heterogeneous dataset, with
repeats, is what would settle it. Until then the honest statement is narrower: **on TERNARY,
with a retrieval candidate set, comparative wins and the mechanism is understood; on
ALFWorld, admission also lost, for reasons not yet separated.**
