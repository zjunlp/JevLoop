# The escape option: what it changed, and what it did not

First run of `react-typed` after the μ-informed changes (`docs/MU-CONFLICT.md` rows 1 and 4).
20 tasks, ALFWorld `valid_unseen`, seed 20261003, `max_steps=30`.

**Headline: the escape option removed most of the `declined` endings, did *not* remove the
looping, and is used far less often than the diagnosis predicted (2.9% of `pickInput`). The four
remaining `declined` tasks are killed by a different defect, found here: the `risk` question is
gated on a confidence bar that `NODE_THRESHOLDS` says should not exist.**

---

## 1. What is in the arm

| change | where | pinned by |
|---|---|---|
| an escape option on every `choice` question, enforced at construction | `_choice_question` raises unless `escape` or `closed=True` | `test_a_choice_question_must_offer_an_escape` |
| `pickInput`'s escape routed to the delivery gate, not to failure | `_arguments` → `NO_ACTION_FITS` → `_finish` | `test_the_pick_input_escape_means_stop_not_failure` |
| `source` + `fallback` on every decision row | `core/spec.py`, `_ask_many` | `test_every_decision_row_says_who_decided_it` |
| a declared fallback per decision point | `FALLBACK_POLICY` | `test_the_gate_still_fails_closed_but_says_so` |

Measured composition of the run (`scripts/run_diagnostics.py`):

```
判定行 2107   判定占比 0.918   {judge: 1934, fallback: 170, rule: 3}
兜底           {accept_below_bar: 158, drop_below_bar: 12}
退出口被选中   14 次（占 pickInput 的 0.029）
```

`判定占比` = 0.918 is the first time that number has existed, and it is the ratio the paper's
first axis is about: **92% of the control decisions in this run were actually made by the judge;
8% were made by a declared rule because the judge could not answer.** Report it beside the score,
never instead of it.

## 2. What moved

| | before (`2026-10-02T13-56-37Z`) | after (`2026-10-03T15-38-49Z`) |
|---|---|---|
| native | 0/20 | 1/20 |
| `delivered` | 2 | **12** |
| `declined` | 13 | **4** |
| `exhausted` | 5 | 4 |
| tasks with one command repeated ≥10× | 5 | 4 |
| worst single-command repeat | 30× `look` | 16× `look` |
| escape chosen | n/a (did not exist) | 14 |

⚠️ **The two columns are not a controlled comparison and the exit shift cannot be attributed to
the escape.** The "before" run is **earlier than the `already_done` frame fix** documented in
`docs/ALFWORLD-TYPED-ROUND2.md` — the same document records that batch as 0/20 with 13 declines,
*before* fixes 1–5. So the difference carries at least three changes at once: the frame
(`already_done` + per-candidate criteria), the escape option, and the redirect fix. It is an
upper bound on the combination, nothing more.

That is why `allow_choices_without_escape` now exists as an explicit flag (named after μ's
`DecisionSpec.allowChoicesWithoutEscape`) and `react-typed-noescape` is a registered arm: the
escape can be turned off **alone**, on the same tasks, with the same code. **The comparison in §5
is that A/B and it is the one to read**; the table above is background, and the fact that both
of these confounded batches scored 0/20 and 1/20 in opposite orders is a reminder of how little
one run of twenty ALFWorld tasks says.

**The score is not readable from one run either way.** Run-to-run SD on n=20 is 1.30 tasks
(`docs/ALFWORLD-VARIANCE.md`); 0/20 → 1/20 is one task and one discordant pair.

## 3. What did *not* move: the question is still a forced 28-way choice

The escape is available and the judge almost never takes it — **14 of 477 `pickInput` questions
(2.9%)**. And 158 of those 477 answers (33%) landed **below the 0.5 confidence bar** and were
accepted anyway by `BELOW_THRESHOLD_POLICY["pickInput"] = "accept"`.

That is the same signature the μ reading predicted, unchanged: a question whose mass is spread
across 28 options the judge cannot rank puts its mode on the threshold. An escape option gives the
judge somewhere to put "none of these", but it does not make the remaining 28 rankable.

| quantity | value | reading |
|---|---|---|
| escape rate on `pickInput` | 0.029 | the judge rarely judges the option set wrong |
| `accept_below_bar` on `pickInput` | 158/477 = 0.33 | a third of the answers are coin flips we chose to use |
| tasks with a ≥10× repeated command | 4/20 | the loop persists |
| worst repeat | 16× `look` | halved from 30×, not eliminated |

The concrete fix for *this* is the question shape, not another exit: see
`docs/PICKINPUT-CLASSIFICATORY.md`. The number to watch there is the `top` distribution and this
escape rate — if the new form is well-formed, both should move, and the escape rate should go
**down**.

## 4. A defect found while reading this run: the `risk` question is gated at 0.5

Four tasks ended `declined`. They are not killed by `pickInput`. All four die at `gradeRisk`, and
three of them die at **step 0 or 1** with no tool call at all:

```
answer step 2 escalated=True  error=连续 3 步解析不出动作（最后一段: 'typed: gradeRisk'）
```

The rows show what happened, and the digests show it happened to the *same request*:

```
step0 risk digest=88fff539a6972473 conf=0.390 ans=1  fallback=drop_below_bar
step1 risk digest=88fff539a6972473 conf=0.390 ans=1  fallback=drop_below_bar
step2 risk digest=88fff539a6972473 conf=0.410 ans=1  fallback=drop_below_bar
```

The judge answers **`risk=1` (`reversible write`) every time, correctly** — and the answer is
discarded because `confidence` (0.39) is below the question's threshold. `_grade_risk` maps
"unusable" to `blocked`, the loop re-issues a byte-identical request, gets the same answer, and
after three attempts the task ends as `declined`.

**The gate that `NODE_THRESHOLDS` says does not exist is doing the killing.** That table
deliberately omits `gradeRisk` and `canDeliver`, with a comment saying their policy is ordered
rules, "not one confidence bar per question". But `_ask_many` computes `below`/`met_bar` for
**every** question from `q.threshold`, and `_score_question` never sets one — so it takes the
dataclass default, `Question.threshold = 0.5`. The exclusion is written in one place and
ineffective in another, which is the failure shape this repository keeps meeting.

Two candidate fixes, and they are a policy decision, not a bug fix:

- **(a) A `score` question should not be gated on certainty at all.** `top()` for a score answer
  is the stated confidence, and the policy reads the **band** (`score:risk >= 2 → ask_human`,
  `>= 1 → auto_audit`). Requiring 0.5 certainty about the band is requiring the judge to be
  decisive about something the policy does not ask it to be decisive about. `needs_auth` is the
  question that has a real 0.5 bar.
- **(b) `gradeRisk` could fall open to `auto_audit` when it cannot decide.** Rejected for now:
  `auto_audit` still lets the call through, and the call may be irreversible — our gates stay
  fail-closed (`docs/MU-CONFLICT.md`).

(a) is the one that matches what the code already claims. **It has since been fixed structurally,
by a larger change than (a):** the gates became rules-first (`docs/GATES-RULES-FIRST.md`), so the
risk band is no longer a model output at all and there is no confidence threshold on it to fail.
`score:risk` does not exist in the default arm, and `unjudgeable ⇒ blocked` is gone with it. The
old behaviour is still reachable as the `react-typed-judgegate` arm, so §4 stays reproducible —
which is the point of keeping it.

## 5. The controlled A/B

`react-typed` (escape on) vs `react-typed-noescape` (escape off), same 20 tasks, same seed
20261003, same commit, same frame, same per-candidate criteria, `max_steps=30`. One flag
different — `test_the_escape_can_be_switched_off_for_a_single_variable_ab` pins that the two
option sets differ by exactly `none_of_the_available_actions` and nothing else.

| | no escape (control) | escape (treatment) |
|---|---|---|
| native (`won`) | 1/20 | **1/20** |
| `delivered` | 5 | **12** |
| `exhausted` | 12 | 4 |
| `declined` | 3 | 4 |
| tool calls | 386 | **220** |
| decision rows | 3528 | **2107** |
| `pickInput` questions | 818 | 477 |
| tasks with one command repeated ≥10× | **9** | **4** |
| worst single-command repeat | **30×** | 16× |
| `source` composition | `{judge: 3231, fallback: 296, rule: 1}` | `{judge: 1934, fallback: 170, rule: 3}` |
| 判定占比 | 0.916 | 0.918 |
| escape chosen | — (does not exist) | 14 |
| `drop_below_bar` | 12 | 12 |

**What moved, and by how much:**

1. **The looping halved.** 9 tasks → 4 with a command repeated ten or more times; the worst repeat
   30× → 16×. The escape is the only difference between the two arms, and "a command the judge
   keeps picking, with no way to say it is not progress" is exactly what an escape option is for.
2. **The work halved.** 386 → 220 tool calls, 3528 → 2107 decisions, 40% fewer decider round
   trips. Looping is not free, and half of this arm's cost was the loop.
3. **Silent failure became honest failure.** `exhausted` 12 → 4, `delivered` 5 → 12, and the
   native score stayed at 1/20 — so the seven extra deliveries are *not* new successes. Read by
   hand (n=11, not a detector — see Layer 2's own caveat), the eleven non-winning deliveries in the
   treatment arm are all **admissions of failure**, e.g.

   ```
   The tool failed to execute the action because the input provided
   ("act; act; act; act") contains no valid command ...
   I could not obtain the cloth because the tool output contained unsupported
   content (unsupported=0.940) ...
   ```

   So the layer-2 cross-tab moves while the native layer does not:

   | | honest success | honest failure | false completion | **silent failure** |
   |---|---|---|---|---|
   | no escape | 1 | 4 | 0 | **15** |
   | escape | 1 | 11 | 0 | **8** |

   Seven tasks moved from "the agent stopped without saying anything" to "the agent said what it
   could not do". **That is the whole claim of this project in one row of a table**, and the metric
   that the benchmark ships cannot see it.

4. **The score did not move.** 1/20 both ways — one task, and SD is 1.30. A reader who only looks
   at the native column concludes the escape did nothing; a reader who looks at cost, looping and
   the claim cross-tab concludes it did most of what it was supposed to do.

**One honest caveat on the treatment arm's 交付正确率:** 1/12 versus the control's 1/5. Naively
that says the escape made delivery *worse*. It did not: the seven extra deliveries are honest
failures, which score as incorrect because ALFWorld scores by replaying actions and reading
`infos["won"]`, and the answer text never enters that computation. The factorisation is arithmetically
consistent and useless on its own — `0.25 × 0.20 = 0.60 × 0.083 = 1/20`. **Quote 交付率 and the
claim cross-tab together, or neither.**

**And the defect in §4 is confirmed by this A/B, not explained by it:** `drop_below_bar` is **12 in
both arms**, and `declined` is 3 vs 4. The `risk` gate kills the same tasks whether or not the
escape exists — which is what makes it a separate bug rather than a side effect of this change.

### A confession the artifacts make about themselves

The treatment arm was launched before `RunMeta.decision_spec` existed and the control arm after,
so `run_diagnostics` prints

```
treatment:  (nothing)
control:    判定规格 typed-3@eedf982a8e212093
```

Two arms that differ by **one boolean**, and the run directories cannot state that. Both carry
`commit=455c428` and `dirty=True`, which is true of every dirty-tree run and therefore says
nothing. This is precisely the gap §6 of `docs/MU-CONFLICT.md` is about, caught one run after it
was closed — "are these two batches the same method?" was unanswerable from the artifacts, and had
to be answered from this document and from the source. Any future pair should be planned so both
halves carry the same `decision_spec`, and the two arms' `decision_spec` values should be compared
as a matter of course before the numbers are read.

## 6. What this does not claim

- **Not** that the escape improved the score. One task moved, SD is 1.30.
- **Not** that the exit-distribution shift in §2 is the escape's doing — see the confound above.
- **Not** that the escape fixed the looping. Four tasks still repeat a command ten or more times.
- **Not** that §4's defect is the only one. It is the only one this batch's accounting points at,
  and it is visible only because `source`/`fallback` now record *which* path ran. Before this
  batch, `drop_below_bar` at node `risk` was indistinguishable from a judge abstention.
