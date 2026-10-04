# `pickInput`: from one relational 28-way choice to per-candidate classification

Design proposal. **Not implemented.** Status of the μ comparison: rows 1 (escape), 4
(declared fallback + provenance) and 5 (`shadow`) are in code; this is rows 2 and 3, and it
is the one change that attacks the quality of the question rather than its plumbing.

Read `docs/MU-COMPARISON.md` §2–§3 and `docs/MU-CONFLICT.md` first. The short version:

> Their question asks **what a chunk IS**. Ours asks **which of 28 strings is the next thing to
> do**. A relational question cannot be grounded in the artifact, because the artifact does not
> contain the relation.

## What our question actually is today

`_PICK_INPUT_ASK` = *"Which action should be taken next to make progress on the task?"*, and each
option carries a relational criterion (`jloop/typed.py::_PICK_INPUT_CRITERIA`):

```
go to safe 1      → "move to that location so its contents can be inspected"
examine safe 1    → "inspect that object — reports information and changes nothing"
```

So the judge is asked to model the task's goal, the agent's state and the future, then rank ~28
candidates against that. Three measured consequences:

| observation | reading |
|---|---|
| `top` sits at 0.44–0.55, i.e. **on** the 0.5 threshold | the mass has nowhere to go: 28 plausible options, each criterion true of *some* plan |
| `examine cabinet 1` chosen 56× in one run; 30× in a task | the question admits "this is a legitimate step", never "this is not progress" |
| 13/20 tasks ended `declined` before the escape option existed | the judge could not answer "none of these"; it could only pick another real option |

The escape option (row 1) removed the third consequence. It does **not** address the first two: a
question that is answerable only by modelling the future still gets a spread distribution, and the
threshold is still sitting on the mode.

## The proposal

**Ask two classificatory questions per candidate, in one request, and let our rules select.**

For each candidate `c` in the admissible-command list:

```
Q1(c): What does `go to safe 1` change?
         nothing — it only reports information
         where I am
         whether a container is open
         what I am holding
         the state of an object (clean / heated / cooled)
         other

Q2(c): Is the thing `go to safe 1` acts on named or implied by the task?
         yes / no / not applicable / other
```

Both are answerable from **the command alone** (Q1) or from **the command plus the task text**
(Q2). Neither requires the judge to model the agent's plan. Each carries `other`, which is μ's
escape requirement, and each is a `choice` question whose options are *classes*, so the escape is
a real answer rather than a 29th string.

Then selection is **ours and deterministic**, in this order:

1. drop candidates already tried, when a strictly-untried alternative exists in the same class
   (this is `ctx.already_done`, already in the frame — it becomes a rule instead of a hint);
2. drop candidates whose Q1 class is `nothing` (inspection) when the last action in history was
   also `nothing` — this is the `examine`/`look` loop, killed by rule rather than by a threshold;
3. rank the rest by Q2 = `yes` first, then by the class the task currently needs
   (`where I am` before `whether a container is open` before `what I am holding` before
   `the state of an object`, for ALFWorld's pick-and-place family);
4. if the ranking is empty or every Q1 is `other`, take the declared fallback
   (`FALLBACK_POLICY["pickInput"] = "no_action_fits"` → try to finish, gate decides).

Step 3's class order is a **declared table**, so it is reviewable and bumpable — and any change to
it changes `decision_spec_digest()`, so it cannot be changed silently.

## Why this is the same claim as the paper

It splits the decision at the seam the paper is about:

- **classification** (what is this thing) — the judge does it, and it is *checkable against the
  artifact*, which is `docs/GROUNDING-STEP2-POINTER.md`'s "a verdict must be able to point at
  something";
- **selection** (what to do about it) — our rules do it, in a table anyone can read.

Today's `pickInput` has the judge doing both, and the second half is the half it is worst at
(it has no state, no plan and no memory of what failed). **Moving selection into a rule is not a
concession; it is the claim.**

## Cost, stated honestly

- **N candidates × 2 questions in one request.** μ measured 16 chunks in 0.44 s / 7.6k tokens
  against 1.4 s / 11.6k for 16 separate requests — *"the state is billed once"*. Our wire format
  already batches (`Request(questions=...)`), so this is a payload change, not a protocol change.
  ⚠️ `MAX_QUESTIONS = 3` and `MAX_OPTIONS = 32` apply **per request**; 28 candidates × 2 questions
  is 56 questions. So this needs either a raised, declared budget or chunking into batches of
  candidates. **That is the main engineering unknown and it must be measured before anything else.**
- **Step 3's class order is domain knowledge.** For ALFWorld it is inferable from the task text
  family (`pick_and_place_simple`, `pick_clean_then_place_in_recep`, `look_at_obj_in_light`, …).
  For a general agent it is not, and the fallback (step 4) does the work. So this design is
  **best-case for ALFWorld and honest-but-weaker elsewhere** — say so rather than generalising it.
- **It is a new arm, not a fix.** The two forms are different controllers and must be separate
  rows in the table (`DECISION_SPEC_VERSION` bump).

## How it will be judged, and what would falsify it

Run both forms on the same tasks with repeats, and compare **paired**, not on totals:

| quantity | why it is the right one |
|---|---|
| `top` distribution on `pickInput` (median distance from the threshold) | the diagnosis is "the mass has nowhere to go"; this is that quantity directly. Cheaper and far less noisy than the task score — `scripts/frame_ab.py` already establishes this method. |
| the escape rate (`none_of_the_available_actions`) | if the new question is well-formed, the escape should become *rare*; a high escape rate means the classification is wrong, not that the judge is bad |
| max repeat of one command within a task | the `examine` loop, measured by rule (`scripts/run_diagnostics.py`) |
| native score | last, with repeats and a majority vote — run-to-run SD is 1.30 tasks on n=20 (`docs/ALFWORLD-VARIANCE.md`), so a single pair of runs cannot settle it |

**Falsifiers, written before the run:**

- `top` does not move off the threshold ⇒ the problem was not the question's relational form, and
  §2 of `MU-COMPARISON.md` is wrong for this domain. That is a publishable negative result about
  borrowing a constraint from a different setting.
- The escape rate *rises* ⇒ the classification vocabulary is wrong (`other` absorbing everything).
- Native score rises but `top` does not ⇒ **distrust it**: the score moved for a reason other than
  the one claimed, and with SD 1.30 that is the likelier explanation.

Before implementation, measure only the budget question: build the 56-question request and see
whether the backend accepts it and what `top` looks like on the 28 candidates of one real
ALFWorld step. If the request is rejected or the state is billed per question, the design changes
and the rest of this document is moot.

## Related

- `docs/MU-COMPARISON.md` §2, §3 — the reading that produced this
- `docs/MU-CONFLICT.md` — what was a conflict and what was just missing
- `docs/FRAME-ASSEMBLY-PICKINPUT.md` — what the current frame carries
- `docs/ALFWORLD-TYPED-ROUND2.md` — the measurements behind the three consequences table
