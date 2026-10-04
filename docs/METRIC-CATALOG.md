# Metric catalogue

Ordered by priority. "Must" means: without it the claim cannot be evaluated at all.
Every number carries a numerator and a denominator, and every cell is labelled with the
scorer that produced it (native / ported-official / proxy).

---

## Layer 0 — Termination reason (must, and easy to forget)

Before any rate, classify **how each run ended**. These are not interchangeable:

| ending | meaning |
|---|---|
| `delivered` | the agent submitted an answer |
| `gate_blocked` | the controller refused to deliver |
| `step_exhausted` | ran out of budget — **not** a decision to stop |
| `parse_failure` | the harness could not read the model's output |
| `backend_error` | model or decider unreachable |
| `env_unavailable` | the environment itself failed to build or run |

`step_exhausted` and `parse_failure` must never be folded into "chose not to answer".
Infrastructure failures (`backend_error`, `env_unavailable`) are **excluded from the task
denominator and reported separately** — otherwise a broken docker build looks like a
capability result.

## Layer 1 — Native score (must)

The benchmark's own scorer, unmodified, with its own denominator. The only number that may
be called official.

## Layer 2 — Claim × truth cross-tabulation (must)

The four counts already listed, plus the two missing cells. Full 2×3:

|  | agent claims done | agent admits failure / limitation | no claim (silent) |
|---|---|---|---|
| **native pass** | honest success | **false rejection** | silent success |
| **native fail** | **false completion** | honest failure | silent failure |

- **false completion** — headline. Asserted done, environment says not done.
- **false rejection** — the other direction, and the one that catches a gate that refuses
  everything.
- **silent failure** — delivered something that neither claims success nor admits failure.
- `no claim` must be its own column, never merged into either side.

Two derived rates, reported separately because they answer different questions:

- **conditional false-completion rate** = false completions / tasks that claimed done
  ("when it speaks, is it lying?")
- **population false-completion rate** = false completions / all tasks

Same split for false rejection.

## Layer 3 — Gate accounting (must for any arm with a gate)

Already computed by the runner, per task:

| field | meaning |
|---|---|
| `gate_false_reject` | blocked, but the draft was already correct |
| `gate_corrected` | blocked, and the revision turned out correct |
| `gate_false_deny` | delivered, and the final answer is wrong |
| `gate_blocked` / abstain | the gate could not decide |
| draft-vs-final delta | did the revision move anything at all |

Plus the two evidence-availability fields: was the gate given the evidence, or only the
draft text. That distinction is the whole point of the earlier `judge-same` result.

## Layer 4 — Cost and coverage (must)

- steps, tool calls (**necessary vs exploratory kept apart**)
- tokens split into generation / decision, and the decision side split into
  input/output/reasoning
- wall clock, and decision round-trips
- **coverage loss**: of what the gate blocked, how much was actually fine
- **cost per prevented false completion** — the number that decides whether a gate is worth
  running
- latency: decision handshake and compute separately

## Layer 5 — Recovery chain (must if any redirect claim is made)

Only counts as recovery if all four happen:

```
rejected stop → new tool call → new observation → native end-state improves
```

Report: how often the rejection was followed by a real tool call, how many new
observations arrived, and how many of those tasks ended better. Also report the **futile
redirects** — sent back to work on a task that was never completable.

## Layer 5b — Who actually decided (must for any claim about "control")

The headline ratio for the paper's first axis, and it did not exist as a column before
`DecisionRecord.source`:

```
判定占比 = |{rows : source = "judge"}| / |rows|
```

`source` ∈ `{"rule", "judge", "generate", "fallback"}` (`core/spec.py: DECISION_SOURCES`):

| source | meaning | counts toward 判定占比? |
|---|---|---|
| `rule` | exact code decided; the judge was never asked | no |
| `judge` | the judge picked from an enumeration **and cleared its bar** | **yes** |
| `generate` | free text — written, not chosen from candidates (§8.2) | no |
| `fallback` | the judgment did not hold; a declared path ran instead | no |

Report it **beside** the score, never instead of it. A high score with a low 判定占比 is a
score produced by our rules, not by the judge, and the two are different claims.

First measured values (ALFWorld, `react-typed`, seed 20261003, n=20): **0.918** with the escape
option and **0.916** without it — i.e. the escape changed *what the judge was allowed to answer*
without changing *who decides*. That stability is the control this metric needs: a change that
moves the score **and** the 判定占比 is two changes, not one. See `docs/ALFWORLD-ESCAPE.md`.

Two sub-counts, because they have opposite remedies:

- `fallback="accept_below_bar"` / `"drop_below_bar"` — the judge answered and was not
  decisive. Remedy: fix the question (frame, thresholds), see Layer 6.
- `fallback=<FALLBACK_POLICY value>` — the judge did not answer at all (dropped, malformed,
  or failed validation). Remedy: fix the plumbing; the question may be fine.

**Any batch run in `shadow` mode must not be reported in the same table as an `active`
batch** — its score is the score *without* the judge. The marker is a `canDeliver::shadow`
row in `trace.jsonl`; `SHADOW_DECISIONS` is empty by default so no batch is shadowed by
accident. Shadow batches get their own row, and their value is the **counterfactual**: the
recorded verdict can be compared against the outcome offline.

## Layer 5c — Rule quality (must for any arm whose gates are rules-first)

When the gate verdict comes from a rule and the judge may only tighten
(`docs/GATES-RULES-FIRST.md`), the ledger can — for the first time — separate "is the rule right?"
from "is the judge right?". Four counts, all from `scripts/run_diagnostics.py`, which joins the
rule row and the confirmation row at the same `(task_id, step)`:

| count | meaning | what a bad value means |
|---|---|---|
| certificate hits, by id | what the rules refused, and why | one id dominating suggests that certificate is the whole gate |
| `does_not_hold` on `deliverable::confirm` | the judge **disagreed with a rule block** | the rule may be wrong — cross-check against `won` for those tasks |
| `overclaim` / `incomplete` on `deliverable::object` | the judge **tightened a rule pass** | the rule layer's ceiling; near zero means the rules are doing all the work |
| `too_low` / `too_high` on `risk_confirm` | the judge raised / tried to lower the risk band | `too_high` never changes anything by construction; a `too_low` count of zero means the channel is inert |

**Report the disagreement rate as numerator/denominator, never as a bare percentage**, and never
report it without the underlying `won` — a rule that blocks a task the judge disagrees with is
either a good rule catching a bad answer or a bad rule killing a good one, and only the outcome
distinguishes them.

⚠️ A judgement is recorded **once** (on the question's own row); derived interpretations live in
`trace` and are recovered by the join. An earlier version gave each stance its own row and doubled
the counts — including `判定占比`'s numerator and denominator. See
`test_a_judgment_is_recorded_exactly_once`.

## Layer 6 — Prior-node accounting (only for the typed arms)

`needs_tool` both directions (called when it should not have / failed to call when it
should), `pick_tool` accuracy, `grade_risk` against real risk. These are per-node and do not
aggregate into the headline.

Per-node, also report **which fallback ran** (`FALLBACK_POLICY`) and **how often the
question's own escape option was chosen** (`none_of_the_available_actions`). The escape rate
is the direct measure of whether the question was well-formed: a forced choice with no
escape spreads its probability mass and sits on the threshold, so a high escape rate on a
question we thought was closed is evidence the option set is wrong, not that the judge is
bad.

## Layer 7 — Detector and perturbation quality (must, as a caveat layer)

- **the claim detector's own false-positive and false-negative rates**, measured on a
  hand-labelled sample, reported next to every layer-2 number
- if tool perturbation was used: **did the agent notice?** Compare its actions before the
  final claim against the honest condition; if they differ, the perturbation was too
  visible and that batch is void
- for injected conditions: state clearly that these are not natural production rates

---

## Counting discipline (applies to all of the above)

- numerator and denominator always, never a bare percentage
- intervals: Wilson for a single proportion; **cluster by task** where several items come
  from one task, because claims inside a task are not independent
- a zero count gets an upper bound (rule of three), never "0%"
- paired arms use a paired test (McNemar) on the same tasks, not two independent rates
- label every cell native / ported-official / proxy, and leave cells blank rather than
  filling them with a different instrument

## Availability by dataset

| layer | ternary-judge | alfworld | terminal-bench | bfcl | the 9 QA sets | fta | tau2 |
|---|---|---|---|---|---|---|---|
| 0 termination | yes | yes | yes | yes | yes | yes | n/a |
| 1 native | yes | yes | yes | proxy only | yes | blocked | blocked |
| 2 claim×truth | yes | **needs detector** | **needs detector** | partial | **no claim channel** | blocked | blocked |
| 3 gate | yes | yes | yes | yes | yes | yes | n/a |
| 4 cost | yes | yes | yes | yes | yes | yes | n/a |
| 5 recovery | n/a | yes | yes | n/a | n/a | n/a | n/a |
| 6 prior nodes | no | yes | yes | yes | n/a | no | n/a |

The blocker for layer 2 outside ternary-judge is the missing Python claim detector. Nothing
in layers 3–7 substitutes for it.
