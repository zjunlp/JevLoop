# Gates: rules filter first, the judge only confirms

Decision by the user, 2026-10-04: 「我们的闸门也改成"规则先筛、判官只确认"」. This is the
architecture, its two invariants, what it fixed, and what it costs.

Read `docs/MU-CONFLICT.md` §4 first: that is the conflict this resolves. The short version is that
μ's structure (a declared fallback, provenance per decision) was adoptable and μ's *default*
(fail open) was not, because fail-open at a gate leaves the agent correct and the measurement
unfalsifiable. This document is the third option: **keep failing closed, but move the closed
decision from the judge to a rule — and let the judge only make things stricter.**

```
                    BEFORE                                 AFTER
   judge answers deliverable/unsupported        rules produce ALLOW or BLOCK + a reason
   judge answers score:risk  ─────────────►     judge CONFIRMS the rule, or objects to it
   verdict = what the judge said                verdict = stricter(rule, judge)
   judge unsure  ⇒ blocked ⇒ decline            judge unsure ⇒ the rule stands
```

## 0. This is μ's own shape, not a borrowing we invented

Checked against their README on 2026-10-04. μ's `tool.risk` is *"A command **the rules flag**: did
you ask for it?"* with the effect *"**Unsure means asking you**"*, and `tool.approval` is *"Only
what it is sure of runs; the rest asks you."* Their summary line is the design in one sentence:
*"Rules are the floor: a dangerous-looking command is caught by rules first, and the judge only
vouches that you asked for it."*

So for the risk and authorization gates, rules-first is **the same architecture μ uses**, including
"unsure ⇒ ask a human". They also run each decision point in `active` / `shadow` / `off`, and route
each one to its own judge. The one place we deliberately differ is the *delivery* gate: see §5.4.

## 1. The two invariants

**① Monotonicity.** The judge may only make a gate stricter, never looser.

**② Uncertainty never produces a refusal.** Refusal is the rule's job, and a rule refuses only when
it holds a certificate. So `unjudgeable ⇒ blocked` — the path that killed 4 of 20 ALFWorld tasks
(`docs/ALFWORLD-ESCAPE.md` §4) — **does not exist in this version.**

Invariant ② is why the judge is a confirmer and not an advisor. An advisor's "I'm not sure" has to
be interpreted, and every interpretation we tried ended up either ignoring the answer (waste) or
turning it into a refusal (the bug).

## 2. The rule layer: certificates only

A rule may **unilaterally** refuse delivery only if its trigger is a *certificate* — a check that
runs on the artifact and returns a result with no model judgement anywhere inside it. The criterion
in one line: **only what can be falsified qualifies as a rule.**

`DELIVERY_CERTIFICATES` (three, and the list is the whole set):

| id | certificate | check |
|---|---|---|
| `empty_draft` | there is nothing to deliver | `draft.strip() == ""` |
| `ungrounded_number` | the draft asserts a number no tool output contains | set difference |
| `no_evidence` | every tool call returned empty output | all observations blank |

`RISK_PATTERNS` + `UNKNOWN_TOOL_BAND` play the same role for `gradeRisk`: they produce the risk
**band** so the band is never a model output, and therefore never subject to a confidence
threshold. That threshold is exactly what broke (§4 of the escape document: the judge answered
`risk=1` correctly every time, at confidence 0.39, and a default `Question.threshold = 0.5`
discarded it — 4 of 20 tasks died without a single tool call).

### The two checks that look like rules and are not

| check | why it is not a certificate |
|---|---|
| `tool_error_ignored` — the environment reported a failure and the draft claims success | needs a **claim detector** ("is this sentence a success claim?"), which does not exist |
| `goal_signal_absent` — the environment never signalled success and the draft claims completion | same |

Under monotonicity a crude detector is **worse** than no rule: a false positive becomes a permanent
refusal that the judge is forbidden to relax. So both are **downgraded to material for the judge's
objection question** (the tightening direction, where the judge is free), and they are recorded as
`NOT_YET_CERTIFICATES` with that reason.

**This is the design's known ceiling, and it belongs in the report:** ALFWorld's characteristic
failure — a completion report for a task that was not completed — is *not* caught by any rule here.
Only the judge catches it, and only because it is allowed to object. When Layer 7's detector has a
measured false-positive rate, those two can be promoted.

## 3. The judge layer: confirm, or object

Exactly one question per gate, and its form depends on what the rule said.

**The rule refused** — `deliverable::confirm` / `risk_confirm`:

```
A deterministic check refused to deliver this answer, for the reason above.
Judge only whether that reason holds for this answer — do not decide whether
the answer should be delivered.
   holds / does_not_hold / unsure
```

| answer | outcome |
|---|---|
| `holds` | refuse (rule and judge agree) |
| `unsure` | **refuse** — the rule stands; invariant ② |
| `does_not_hold` | **refuse** — the rule stands; recorded as `judge_disagrees_with_rule` |

`does_not_hold` never releases the draft. That is the hard edge of "rules are the floor", and it is
the easiest thing to get wrong by following intuition: writing "the judge disagreed, so let it
through" hands the verdict back to the judge and the whole change is undone. The disagreement is
valuable **in the ledger**, not in the outcome — it is evidence that a rule may be wrong, and
`run_diagnostics` counts it.

For risk the same shape, with the band: `correct` / `too_low` / `too_high` / `unsure`. `too_low`
raises by `RAISE_STEP`; `too_high` and `unsure` leave the band alone. **Only up.**

**The rule passed** — `deliverable::object`:

```
No deterministic check found a falsifiable problem with this answer.
Can you point at one that a check cannot see?
   no_objection / overclaim / incomplete / unsure
```

| answer | outcome |
|---|---|
| `no_objection`, `unsure` | deliver |
| `overclaim` | revise, reason `overclaim` → `_remedy` **degrades** |
| `incomplete` | revise, reason `incomplete` → `_remedy` **redirects** |

This is the judge's only power that changes anything, and note what it is: it **names a disease**
(`_remedy` needs the name to choose the remedy) — it does not produce the verdict. Naming a
disease is classification; deciding whether to deliver is a verdict. Only the second one was taken
away.

### Confidence does not enter the verdict

All three confirm/object questions are asked with `threshold=0.0`, and the code reads their
**content** only. The rationale is not laziness: a confidence bar on a *report* is what broke —
and "the judge was not decisive" is not a reason for anything. `top()` is still recorded on every
row, so "do hesitant objections help?" remains an offline question instead of a hidden threshold.

The one place a threshold survives is `needs_auth` (a `noul`, `≥ 0.5` → ask a human). For a `noul`
answer `top() = max(p, 1−p) ≥ 0.5` always, so that bar has never been able to drop anything; it is
kept because it is `DECISION.md`'s policy, not because it does work.

## 4. One judgement, one row

The judge's answer is recorded **once**, on the question's own row (`_ask_many`), with its `top`,
`confidence`, `correct` and `source`. The derived interpretation (which certificate fired, whether
the judge disagreed, whether the band was raised) goes to `trace` and, for anything that must
survive the run, is recovered by **joining rows at the same `(task_id, step)`**.

That is not a stylistic preference. The first implementation gave each stance its own extra row
(`answer="(stance:...)"`, `source="judge"`), and the first real run showed it: **15 calls produced
30 `risk_confirm` rows**. The consequences were two broken numbers, not one extra line — node counts
doubled, and `判定占比` had both numerator and denominator inflated. This is the same defect the
`record_decision` docstring records from an earlier round ("one judgement was written twice and the
judgement count was inflated"), which is why it is written down again here rather than only fixed.

`scripts/run_diagnostics.py` performs the join and reports:

```
规则证书 N 次 {cert_id: count}           what the rules refused, and why
  判官确认 {stance: count}   其中否定规则 K 次
  判官反驳（规则放行时）{overclaim/incomplete: count}
  风险档位确认 {stance: count}           too_low raises, too_high does not lower
```

These four counts are new capabilities of the ledger: before this change there was no way to ask
"are our rules right?" separately from "is the judge right?".

## 5. What this costs, stated plainly

1. **A false rule block is permanent.** The judge can flag it but cannot release it. Mitigation is
   that only three certificates can block, all of them set differences or emptiness; and the
   disagreement count is reported so a bad rule becomes visible rather than silently expensive.
2. **Pattern coverage is the weakest link.** `RISK_PATTERNS` is textual, so it cannot tell code
   from data — a read-only tool whose *argument* contains `rm` gets raised (safe direction, wasted
   question), and a destructive command outside the pattern vocabulary (`python -c "...rmtree..."`)
   is **not** caught. `base_risk` is the mitigation, which makes the declaration load-bearing.
3. **`base_risk` changed meaning: it is now a floor, not an override.** A declared read-only tool
   whose arguments redirect into `/etc` is still raised. The reverse is forbidden — patterns can
   never lower a declaration. This inverts `docs/GROUNDING-STEP1-DECLARED-RISK.md`.
4. **Undeclared tools with unmatched arguments ask a human.** `UNKNOWN_TOOL_BAND = 2`
   (`irreversible`), because "the rule cannot tell" is not "safe". In a benchmark, `ask_human` ends
   the task, so **a benchmark must now declare `base_risk` for its general-purpose tool.**
   ALFWorld's `act` declares `1` with the reason written at the declaration; Terminal-Bench's
   `exec` still does not, and that is an open item, not an oversight.

## 6. First real run (`react-typed`, ALFWorld, 2 tasks, `max_steps=12`)

The plumbing works: `typed-4@35d6333e989ec0b3`, `判定占比 0.818` over 132 rows, `rule: 14`
(the risk bands), one row per judgement.

Two findings worth carrying forward, both from a run of two tasks and therefore **indicative, not
established**:

- **`risk_confirm` came back `unsure` 14 times out of 14.** Asked to *originate* a band, the same
  judge produced one every time (hesitantly: `risk=1`, confidence 0.32–0.41). Asked to *confirm*
  the identical band, it declines to confirm. Either the confirm question is underfed (the frame
  carries the command and the band, nothing else) or the judge has no basis to second-guess a
  declared grade — and both readings point the same way: **do not ask for confirmation where the
  rule is already certified.** Our own rule says a `base_risk` declaration is authoritative; asking
  the judge to confirm it is exactly the "问一个已经写在纸上的答案" this repository already
  rejected for `base_risk` and for the environment's success signals. The `too_low` raise path is
  therefore currently **dead on ALFWorld (0/14)** while still costing one question per step.
  ⇒ Next step: ask the risk question **only when the band came from a pattern or from
  `UNKNOWN_TOOL_BAND`**, not when it came from a declaration.
- **The judge's objection path fired and was load-bearing**: 2 objections (`overclaim`,
  `incomplete`) on 2 gate evaluations. With no certificate firing, those are precisely the
  catch that the rule layer cannot make, which is the division of labour this design claims.

## 7. Falsifiers, written before the comparison

The A/B is `react-typed` (rules first, default) against `react-typed-judgegate`
(`gates_rules_first=False`, the judge-originates version). Same tasks, same seed, one flag.

- **Rule-block precision.** Of the gate refusals, how often does the judge disagree
  (`does_not_hold`)? Cross-checked against `won` for the underlying task. A rule whose blocks are
  mostly disagreed with **and** whose tasks would have won is a wrong rule, and this count is the
  only place that shows up.
- **The `decline` count must drop.** §4's mechanism is gone in the default arm; if `declined` does
  not fall, that mechanism was not what was killing those tasks and the diagnosis in
  `ALFWORLD-ESCAPE.md` §4 is wrong.
- **The score is not the criterion.** Run-to-run SD is 1.30 tasks on n=20
  (`docs/ALFWORLD-VARIANCE.md`). Read the exit distribution, the certificate counts and the
  claim×truth layer; use the score only with repeats and a majority vote.
- **If `too_low` never fires** (as in the smoke run), then the judge's only risk power is inert and
  the question should be dropped rather than kept as a ritual.
- **If objections never fire**, the judge contributes nothing to delivery and the honest conclusion
  is that the gate should be rules-only — which is a publishable result about this judge, not a
  failure of the architecture.

## 8. Enforcement

Pinned by `experiments/tests/test_gates_rules_first.py`:

| test | what it holds |
|---|---|
| `test_an_unsure_judge_never_refuses_a_delivery` | invariant ② |
| `test_no_answer_is_not_a_refusal` | `rule_stands`, not `reject` |
| `test_a_certificate_blocks_and_the_judge_only_confirms` | the confirm question replaces the verdict |
| `test_the_judge_disagreeing_with_a_rule_does_not_release_it` | invariant ①, hard edge |
| `test_the_judge_can_only_tighten_a_rule_that_passed` | the one power, and both remedies |
| `test_the_judge_can_raise_a_risk_band_but_never_lower_it` | monotonicity on the band |
| `test_the_risk_band_comes_from_rules_not_from_the_judge` | `score:risk` no longer exists |
| `test_the_delivery_certificates_are_only_the_checkable_three` | only falsifiable rules block |
| `test_an_undeclared_tool_with_no_matching_pattern_asks_a_human` | `UNKNOWN_TOOL_BAND = 2` |
| `test_a_declared_base_risk_is_a_floor_that_patterns_can_raise` | the semantic inversion |
| `test_the_risk_pattern_table_is_ordered_by_severity` | order is the table's correctness |
| `test_a_judgment_is_recorded_exactly_once` | the double-count defect |
| `test_the_two_gates_share_one_grounding_check` | one implementation of the sharpest certificate |
| `test_the_legacy_gate_still_asks_its_own_two_questions` | the comparison arm stays intact |

`DECISION_SPEC_VERSION` is now `typed-4`; `typed-3` and earlier are the judge-originates method and
**must not share a table with these rows**.
