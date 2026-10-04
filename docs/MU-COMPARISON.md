# What μ does differently, and where our frame design is wrong

Read at the user's suggestion: [qybaihe/mu](https://github.com/qybaihe/mu) — *"a coding agent
with a judgment kernel… a small, fast model that answers one bounded question at a time, at 35
decision points in every turn."* Built on [pi](https://github.com/earendil-works/pi), with Jev
as the judge. Sources read: `packages/kyrn-judge/src/decision.ts`, `src/policy.ts`,
`src/decisions/tool-admission.ts`.

**Verdict up front: one of their constraints is a rule we violate, and it is the direct cause
of the symptom we have been treating with workarounds.**

> **Status (later).** §1 (escape option) is **implemented** and pinned by tests. §4 is **not a
> borrowing decision** — it is a genuine conflict, resolved by recording provenance rather than by
> picking a side; §5 (`shadow`) and §6 (spec versioning) are also built. See
> **`docs/MU-CONFLICT.md`** for the decision record, which supersedes §4 below.
>
> **§4's conflict has since been resolved structurally**, not merely recorded: our gates now
> produce their verdict from **rules** and let the judge only make them stricter
> (`docs/GATES-RULES-FIRST.md`). That is neither their fail-open default nor our original
> judge-originates design.
>
> **§2 and §3 are the ones still open**, and they are not plumbing: they change the *shape* of the
> `pickInput` question. The design, its cost (28 candidates × 2 questions against
> `MAX_QUESTIONS = 3`), its falsifiers and the order to test it in are written up in
> **`docs/PICKINPUT-CLASSIFICATORY.md`** — read that rather than implementing from §2–§3 below,
> which are the reading, not the plan. This file stays as the reading that produced the list.

---

## 1. A choice question must have an escape option — and they enforce it at definition time

`packages/kyrn-judge/src/policy.ts`:

```ts
/**
 * Option names that mean "nothing fits". A choice question without one is
 * forced to pick a real option even for off-topic input, and does so at full
 * confidence, so specs must include one unless the option set is truly closed.
 */
export const ESCAPE_OPTIONS = ["none", "other", "unclear", "unknown"] as const;

export function hasEscapeOption(question: ChoiceQuestion): boolean {
  return Object.keys(question.criteria).some(isEscapeOption);
}
```

And `defineDecision` (`decision.ts`) **throws** when a choice question lacks one:

```ts
if (!spec.allowChoicesWithoutEscape) {
  for (const [questionId, question] of Object.entries(spec.questions)) {
    if (question.type === "choice" && !hasEscapeOption(question)) {
      throw new TypeError(
        `Choice question "${questionId}" in decision "${spec.id}" has no escape option`);
    }
  }
}
```

**Our `pickInput` has no escape option.** It is a 28-way forced choice among ALFWorld's
admissible commands. The judge cannot answer "none of these is the next thing to do", so it must
pick one, and its probability mass is spread across 28 plausible options.

Every symptom we have been chasing follows from that:

| what we observed | what it actually is |
|---|---|
| `top` = 0.44–0.55 on ALFWorld `pickInput` | 28-way forced choice; the mass has nowhere to go |
| the 0.5 confidence threshold sitting *exactly* at the observed mode | a workaround for a badly-formed question |
| `examine cabinet 1` picked 56 times in a run | the judge had no way to say "this is not progress" — only to pick another real option |
| the repo's own measurement: 77 options → `top` 0.425 | the same disease, worse, and it was recorded as a backend property |
| `BELOW_THRESHOLD_POLICY["pickInput"] = "accept"` | we then *removed our own guard* because the guard was unrunnable |

We added `none_of_the_recorded_steps` to the **grounding** question, so we already understood the
pattern — we just never applied it to the action question itself.

## 2. They ask a classificatory question; we ask a relational one

`decisions/tool-admission.ts`:

> The question asks **what a chunk IS**, not whether it is relevant to the agent's intent.
> Measured on the local judge: **the relational form called every chunk relevant, noise
> included**, while this classification put 4 of 4 noise chunks and 3 of 3 errors in the right
> class.

Their question:

```
What kind of output is `c1`?
  error / result / progress / warning / passing / other
```

Ours:

```
Which action should be taken next to make progress on the task?
```

Ours is **relational**: it asks the judge to model the task's goal, the agent's intent and the
future, then compare 28 candidates against that. Theirs is **classificatory**: it is answerable
from the artifact alone.

This is the same distinction our own grounding work arrived at from the other side — a verdict
that can point at something is checkable; one that cannot is an opinion. **A relational question
cannot be grounded in the artifact, because the artifact does not contain the relation.**

## 3. One question per candidate, one state — not one choice over N

`decision.ts`:

> `questionsFor`: Questions built from the input, **one per candidate** (a skill, a memory, a
> file path), for decisions over a list whose length is only known at run time. **Carrying the
> candidate in the question keeps one state for all of them**, which a large-window judge
> answers in a single request.

And the measured batch (`tool-admission.ts`): 16 chunks in **0.44 s / 7.6k tokens** versus
**1.4 s / 11.6k** as 16 separate requests — *"the state is billed once"*.

So the cost argument for batching works in both designs, but the **question shape** is
different, and theirs does not degrade as the candidate list grows: 16 independent
classifications, each with its own probability and its own escape option, versus one 28-way
choice.

## 4. Fail-open with a declared fallback; ours fails closed

`decision.ts`:

> Runs decisions fail-open: **`decide` never rejects because of the judge.** Timeouts, outages,
> invalid answers and abstentions all yield the spec's `fallback`.

Every spec declares it:

```ts
fallback(): AdmissionOutcome { return { kind: "unknown", drop: false }; }
```

The fallback is *"equal to the host's behavior without a judge"* — the decision point's absence
is a defined behaviour, not an error.

Ours returns `blocked` and the task ends as `declined`. That is why 13 of 20 ALFWorld tasks died
the moment the judge was unsure, and why a `TimeoutError` and "the judge had no opinion" both
look like the arm refusing to work.

> ⚠️ **Superseded — see `docs/MU-CONFLICT.md`.** This is the one genuine conflict, and the
> resolution is *not* to adopt their default. A gate that fails open still leaves the **agent**
> correct and makes the **measurement** unfalsifiable ("how many deliveries did we let through
> unvouched?" is not recoverable from the outcome). We therefore keep failing closed at the gates
> and adopt their *structure* instead: `FALLBACK_POLICY` declares each node's absent-behaviour,
> and every row records `source` + the fallback's name. `pickInput` is the single fail-open, and
> it is safe because what follows it is another check (`canDeliver`), not a delivery.

## 5. `shadow` mode — a decision point you can evaluate without changing behaviour

> `off`: the judge is not called; the fallback is returned.
> `shadow`: **the judge is called and recorded, but the fallback is returned.**
>   *New decision points start here until their verdicts have been compared with outcomes.*
> `active`: the judged outcome is returned unless the policy abstains or the call fails.

We have no such mode. A node in our controller is either wired in or not, so **we cannot measure
whether a decision point helps without changing the agent's behaviour.** Every comparison we
have run is therefore a comparison of two different agents, and the question "would this
judgment have been right?" is unanswerable from our logs.

This is the same problem as the reviewer objection to a bespoke metric, seen from the other
side: they ship the metric and the rollout mechanism together.

## 6. Smaller things worth copying

| μ | us |
|---|---|
| `version: 2` on the spec — *"Bump whenever question wording or policy changes, so ledger records stay comparable"* | `commit` + `dirty`; a wording change is indistinguishable from a code change |
| `cacheImpact: "none" \| "append-only" \| "prefix-mutating"` per decision | nothing; we do not know which judgments could be reordered or deduped |
| `latency: "inline" \| "parallel" \| "background"` per decision | nothing |
| `policy(answers, input): Out \| Abstain` — a pure function, separate from `buildState` and from the ask | policy embedded in `_can_deliver`, mixed with asking and bookkeeping |
| dropped content **archived behind a one-line pointer** — *"keeps a wrong verdict recoverable"* | the gate blocks and the arm rewrites; the dropped content is gone |
| `buildState` puts the long field **last**, because a bounded window cuts the tail | we clip each field independently with `clip="tail"` |

---

## What I would do, in order

1. **Give every choice question an escape option, and enforce it at construction.** This is
   theirs, it is a one-line structural rule, and it targets the root of the ALFWorld failure.
   For `pickInput`: add `none_of_the_available_actions`; when it is chosen, the controller must
   do something other than act (ask, or stop).
2. **Split `pickInput` into per-candidate questions** over one state, each classificatory
   ("is this the kind of action the task requires next?") rather than one relational 28-way
   choice. Measure whether `top` and the observed `examine`-loop improve.
3. **Introduce `shadow` mode** so a decision point can be logged and compared against outcomes
   before it is allowed to change behaviour. Without it we cannot evaluate any of this.

None of the three is a rewrite; all three change results and would need fresh batches.

**One caveat, stated plainly:** μ is a shipped coding agent, not a research harness. Its
constraints are tuned to "the agent must keep working"; ours are tuned to "the measurement must
be clean". Where they conflict — fail-open versus fail-closed, above all — the choice is a
research decision, not a borrowing decision, and it should be made deliberately and written
down.

## Sources

- [qybaihe/mu](https://github.com/qybaihe/mu) — README (decision-point catalogue, judges)
- `packages/kyrn-judge/src/decision.ts` — `DecisionSpec`, modes, fail-open contract
- `packages/kyrn-judge/src/policy.ts` — `hasEscapeOption`, `pickChoice`
- `packages/kyrn-judge/src/decisions/tool-admission.ts` — classificatory question, batching, fallback
