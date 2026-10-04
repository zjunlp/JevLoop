# Where μ and we actually disagree

Read: [qybaihe/mu](https://github.com/qybaihe/mu) `packages/kyrn-judge/src/{decision,policy}.ts`,
`src/decisions/tool-admission.ts`. The catalogue of what they do differently is in
`docs/MU-COMPARISON.md`; **this file is only about conflict**, because "what should we copy" and
"what can we copy" are different questions and only the second one is a decision.

The short answer: **of the six things they do that we do not, exactly one is a real conflict.**
The other five are capabilities we lack, or things we already agreed we were wrong about. Writing
that down matters because a borrowed constraint and a *rejected* constraint look identical in a
diff, and only one of them is a research decision.

| # | their constraint | our practice | verdict |
|---|---|---|---|
| 1 | a choice question must offer an escape | `pickInput` was a forced 28-way choice | **we were wrong** — ✅ fixed, and measured (`docs/ALFWORLD-ESCAPE.md`) |
| 2 | ask classificatory questions, not relational ones | `pickInput` asks "what should be done next" | **we were wrong** — ⏳ not yet |
| 3 | one question per candidate, one state | one N-way choice over one state | **we were wrong** — ⏳ not yet |
| 4 | **fail open to a declared `fallback`** | `blocked` → the arm declines | **★ real conflict** — ✅ resolved structurally (`docs/GATES-RULES-FIRST.md`) |
| 5 | `shadow` mode | a node is wired or it is not | missing capability — ✅ built |
| 6 | version the spec, not the commit | `commit` + `dirty` | **we were wrong** — ✅ fixed, mechanically |

Only rows 2 and 3 are open. They are the ones that touch `pickInput`'s **question shape** —
the design, its cost and its falsifiers are in `docs/PICKINPUT-CLASSIFICATORY.md`, and they are
what should be measured next; row 5 is what makes them measurable without changing the agent.
**Do not read this table as a status report — read the ✅.**

---

## The real conflict, stated precisely

Their contract (`decision.ts`):

> Runs decisions fail-open: **`decide` never rejects because of the judge.** Timeouts, outages,
> invalid answers and abstentions all yield the spec's `fallback`.

The fallback is *"equal to the host's behavior without a judge"*, so **a decision point being
absent is a defined behaviour, not an error**.

> ⚠️ **Correction (2026-10-04), from their README.** An earlier version of this document read the
> contract above as "μ fails open everywhere". That is wrong, and the README's own catalogue shows
> why: **the fallback is per decision point, and for the safety points the host's behaviour is to
> ask the human.** Their `tool.risk` is described as *"A command **the rules flag**: did you ask for
> it?"* with the effect *"**Unsure means asking you**"*, and `tool.approval` as *"Only what it is
> sure of runs; the rest asks you."* So for risk and approval, μ is **rules first, judge confirms,
> unsure ⇒ the human** — which is exactly the architecture the user asked us to adopt on
> 2026-10-04 (`docs/GATES-RULES-FIRST.md`). And their README states the same principle in one line:
> *"Rules are the floor: a dangerous-looking command is caught by rules first, and the judge only
> vouches that you asked for it."*
>
> The conflict is therefore **narrower than first stated**, and it is now only about the *delivery*
> gate. For a context point like `tool.admission`, "the host's behaviour without a judge" is to keep
> the content — a mild default. For our delivery gate it is "hand in the draft" — and that is the
> one place where we keep a stricter default than the host's, because handing in an unvouched answer
> is not measurable after the fact.

Ours: when a judgment does not hold, `_ask_many` drops it, the caller calls `_blocked`, the loop
returns `unparsed` and retries; when retries run out the task ends as `escalated`. Measured on
ALFWorld: **13 of 20 tasks** died this way, and `TimeoutError` and "the judge had no opinion" are
indistinguishable in the log.

### Why we cannot simply adopt theirs

They are a **shipped coding agent**: the first goal of a fallback is *do not stall the user's
request*, so failing open is obviously right — the host keeps working.

We are a **research harness measuring control correctness**. Failing open at a gate means
**letting through a delivery that nothing vouches for**, and "how many times did we let one
through" is not recoverable from the outcome: the task either succeeded (so no one asks) or
failed for some other reason. An intervention that cannot be counted makes the measurement
unfalsifiable, which is the one thing a benchmark cannot afford.

So the honest statement of the conflict is not "fail-open vs fail-closed". It is:

> Their fallback is tuned so the *agent* stays correct. Ours has to be tuned so the *measurement*
> stays correct. When a gate fails open, the agent is still correct and the measurement is not.

### Resolution, first step: keep fail-closed at the gates, make every fallback record its name

Adopting their *structure* while rejecting their *default* is legitimate — but only if the
structure is what makes the default auditable. So:

1. `FALLBACK_POLICY` (`experiments/jloop/typed.py`) declares **per node** what happens when the
   judge does not answer. It is a table, not a control-flow path — reading it tells you every
   decision point's absent-behaviour in one screen.
2. Every `DecisionRecord` carries **`source` ∈ `{rule, judge, generate, fallback}`** and, when the
   source is `fallback`, a **`fallback`** field naming which path ran
   (`experiments/core/spec.py: DECISION_SOURCES`).
3. The gates declare `"reject"`. The action nodes declare `"retry"`. `pickInput` declares
   `"no_action_fits"`, and that is the **only** fail-open — see below.
4. We adopt their line verbatim in spirit: **the fallback must be declared, and it must never be
   silent.** What we add is that it must also be *counted*, because that count is a result:

   ```
   判定占比 = |{rows: source = "judge"}| / |rows|
   ```

   That ratio is the first axis of the paper ("control is not generation") and it did not exist
   as a column before this change. A fallback we cannot count is a fallback that changed our
   answer for free.

### The one place we do fail open, and why it is not a contradiction

`FALLBACK_POLICY["pickInput"] = "no_action_fits"`: when the action-parameter judgment does not
answer, we do **not** re-issue the request — we route to the delivery gate instead.

The reason is measured, not stylistic. Re-issuing produces a **byte-identical** request
(`request_digest` matches), and on the local judge **19 of 20 groups with an identical digest
came back with different confidence** (`0.44 / 0.40 / 0.46`). So "retry" there is not error
recovery, it is **re-drawing the sample**, and it is what killed 13/20 tasks.

Two things make this fail-open safe where a gate's would not be:

- it does not permit an action, it **asks the gate** — `canDeliver` still rejects, and the
  rejection carries its reason back into the frame (`MAX_REDIRECTS = 1`);
- it is **declared and recorded**, so the fallback rate for `pickInput` is a number we report,
  not a property of the run we discover later.

The distinction that decides every row of the table:

> Fail open is safe when the *next* thing that happens is another check that can say no.
> Fail open is not safe when the next thing that happens is irreversible — a delivery, a write.

`pickInput` is followed by `gradeRisk` and `canDeliver`. `canDeliver` is followed by the answer.

### Resolution, second step: the gates became rules-first

Recording provenance made the conflict **auditable**; it did not make it go away. The user then
took the architectural decision, on 2026-10-04: 「我们的闸门也改成"规则先筛、判官只确认"」. The
full design is `docs/GATES-RULES-FIRST.md`; the part that resolves *this* conflict is:

> The judge no longer produces the verdict. **Rules produce it** from certificates (set
> differences and emptiness — nothing with a model judgement inside), and the judge may only make
> the gate **stricter**. Uncertainty therefore never produces a refusal, and the specific path that
> was killing tasks (`judge unsure ⇒ blocked ⇒ decline`) **does not exist**.

So the resolution of the fail-open/fail-closed conflict is neither μ's default nor our original
one. It is: **keep failing closed, and move the closed decision from the judge to a rule that
holds a certificate.** μ's fail-open is still rejected for the gates, and μ's *structure* — a
declared fallback, provenance per decision — is what made it possible to see which of the two was
doing the refusing.

---

## Not conflicts: things we simply have not built

Called out separately so that "we did not build it" is never read as "we decided against it".

### `shadow` mode — ✅ built

Their three modes: `off` (fallback, judge not called), `shadow` (**judge called and recorded, the
fallback is still returned**), `active` (judged outcome returned unless it abstains or fails).

Without it, a decision point is wired in or it is not, so **the question "would this judgment
have been right?" is unanswerable from our logs**. Every comparison we have run is therefore a
comparison of two different agents. This is also the reviewer objection to a bespoke metric seen
from the other side: they ship the metric and the mechanism that lets you evaluate it together,
and we shipped the metric first.

**Built as `SHADOW_DECISIONS`** (`jloop/typed.py`), empty by default so no batch is shadowed by
accident. The unit is the *decision point*, not the question, because `gradeRisk`'s questions are
called `risk` / `needs_auth` and share no name with it — `DECISION_QUESTIONS` maps the one to the
others rather than guessing from a prefix.

"Off-mode behaviour" differs by decision point, and that difference is the interesting part:

| decision point | judge not consulted (`off`) / not obeyed (`shadow`) |
|---|---|
| `canDeliver` | **deliver the draft as written** — no gate means nothing rewrites it |
| action points | the declared `FALLBACK_POLICY` row (`retry`, `no_action_fits`) |

So a shadowed gate records `(shadow:revise/incomplete)` and then **delivers the unrevised
draft**. The counterfactual is now a join in the ledger: the gate's verdict and confidence are in
`trace.jsonl`, the outcome is in `results.jsonl`, and nothing in between changed the trajectory.

**Two things this design had to get right, both caught by running it:**

1. *The gate must still see its own answers.* The first implementation dropped the shadowed
   answers before `_can_deliver`, which then returned `blocked/unjudgeable` — and that became the
   recorded verdict. Shadow observed nothing while looking like it had. Hence
   `honor_shadow=False` at that one call site: **the answers are returned, and only the verdict
   is not applied.**
2. *`termination_only` must go through the same door.* That arm called `_can_deliver` directly,
   so any mode added to the gate would have silently applied to one arm and not the other. The
   gate now has a single entry point, `review_draft`, and the arm's test double had to implement
   it — which is how the interface gap became visible instead of silent.

### `judged`: deliberately not a column

Their `Decision` carries `judged: boolean` next to `source: "judge" | "fallback"`, to separate
"was the judge asked" from "whose outcome was returned". We fold that into `source` + the
fallback's **name**: `source ∈ {rule, generate}` already says the judge was never asked, and
`fallback="shadow"` says it was asked and not obeyed. A fifth column that is derivable from the
other two is a column that will drift out of agreement with them.

### Spec versioning — ✅ built, and made mechanical

They bump `version` on the spec *"whenever question wording or policy changes, so ledger records
stay comparable"*. We recorded `commit` + `dirty` + `prompt_hash`, and the gap was worse than it
looks: **`prompt_hash` covers only `benchmark:dataset_version:arm`**, so a reworded question, a
moved threshold and a changed fallback table all leave every recorded identifier untouched. "Are
these two batches the same method?" was unanswerable from the artifacts.

Their fix is discipline: remember to bump. Ours is mechanical, in two tests:

- `test_the_decision_spec_fingerprint_is_pinned` — `decision_spec_digest()` is a hash of the
  question wording, every criterion, the thresholds, the escape sentinel and the frame budgets.
  **Change any of them without bumping `DECISION_SPEC_VERSION` and the test is red**, with
  instructions in the failure message. Comments are deliberately excluded, so nobody learns to
  bump reflexively.
- `test_no_question_constant_escapes_the_fingerprint` — every uppercase constant in `typed.py`
  must be either in `DECISION_SPEC_PARTS` or in `DECISION_SPEC_IGNORED` **with a reason**. That
  closes the "added a new question and forgot to register it" hole, which would otherwise make the
  first test silently weaker exactly when it mattered.

Both the version and the digest go into the run metadata (`RunMeta.decision_spec` =
`"typed-3@eedf982a8e212093"`), for the arms that have typed decisions at all.

### `cacheImpact` / `latency` per decision

Nothing on our side. Worth noting only because `cacheImpact: "prefix-mutating"` is a warning that
a judgment's frame must be assembled *late* — which is exactly what our `redirect_note` does, by
accident rather than by declaration.

---

## What this changes in our own documents

- `docs/MU-COMPARISON.md` §4 ("fail-open with a declared fallback; ours fails closed") is
  **superseded** by the resolution above: we keep failing closed at the gates and now record
  which fallback ran.
- `docs/MU-COMPARISON.md` §1 ("a choice question must have an escape option") is **done**;
  §2 and §3 (classificatory, one question per candidate) are still open and are the intended
  content of the next ALFWorld batch.
- `BELOW_THRESHOLD_POLICY` and `FALLBACK_POLICY` are two tables on purpose. The first is *the
  judge answered and was not decisive*; the second is *the judge did not answer*. Collapsing them
  would put "0.44 confidence" and "the backend dropped it" in the same bucket, and those have
  opposite remedies.

## Enforcement

Pinned by tests, not by this document:

- `test_a_choice_question_must_offer_an_escape` — construction raises without one
- `test_every_decision_row_says_who_decided_it` — `source` is in the value domain
- `test_a_lookup_is_recorded_as_a_rule_not_as_a_judgment` — a table lookup is not a judgment
- `test_free_text_arguments_are_recorded_as_generated` — generation is not judgment
- `test_below_the_bar_the_row_names_the_fallback_that_ran` — the fallback has a name
- `test_the_gate_still_fails_closed_but_says_so` — `FALLBACK_POLICY[gate] == "reject"`
- `test_pick_input_keeps_the_retry_lottery_out_of_the_account` — the one fail-open routes to a gate
- `test_shadow_records_the_verdict_but_does_not_let_it_steer` — shadow is asked **and** harmless
- `test_shadow_rows_cannot_be_mistaken_for_a_judgment` — shadow rows are not judge rows
- `test_shadow_is_off_unless_asked_for` — no batch is shadowed by accident
- `test_the_pick_input_escape_does_not_leak_a_redirect_object` — the second redirect entry point

## Sources

- [qybaihe/mu](https://github.com/qybaihe/mu)
- `packages/kyrn-judge/src/decision.ts` — fail-open contract, modes, `version`, `cacheImpact`
- `packages/kyrn-judge/src/policy.ts` — `hasEscapeOption`, escape option list
- `packages/kyrn-judge/src/decisions/tool-admission.ts` — classificatory question, `fallback()`
