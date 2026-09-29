# Does a decision contract gate better than `if`/`else`? A measurement

> The falsification test that [`POSITIONING-spec-vs-hook.md`](POSITIONING-spec-vs-hook.md)
> asks for, run headlessly and reproducibly. **The answer is no** — and the negative
> result is more useful than the claim it replaces.
>
> Reproduce: `node --experimental-strip-types bench/gate-compare.ts`
> Pinned by: `tests/gate-compare.test.ts` (11 tests)

## The question

The positioning document states the condition under which this project is more than a
nicer way to write a gate:

> Take a hook-based authorization and termination gate implemented as plain `if`/`else`
> and the same gate driven by a decision contract. If **unsupported completion** — a claim
> of completion that external evidence does not support — does not differ measurably
> between them, then the contract's value collapses to "a more legible way to write the
> gate".

This is that test, on the `can_deliver` node — the delivery gate, whose `unsupported`
question is *literally* "the answer states something that the tool output does not
support".

## What could possibly differ

Before running anything, one thing is decidable and it constrains the whole experiment.
`can_deliver`'s policy is:

```text
prob:unsupported >= 0.5  → revise
prob:deliverable >= 0.6  → deliver
else                     → revise
```

Given the same answer probabilities, that **is** an `if`/`else` chain. So the policy layer
cannot be where a difference lives, and any reading of the form "the contract judges more
accurately" is impossible by construction. A difference can only come from **how the frame
is built and validated**, and from **whether the judgement reads the same frame**.

So the experiment varies exactly that, and holds the policy fixed: the hand-written arm
uses thresholds copied character-for-character from `DECISION.md`. If the two arms had
slightly different thresholds, the measured difference would be an artefact of my typing.

## Setup

**Four arms.** The pairing is the design, not a result:

| Arm | What it is |
|---|---|
| `contract` | the gate as the **reference runtime actually behaves**: the frame is compiled by `frameArtifact`, a missing cell is recorded in `unfilled` — and then **nobody reads it**; the policy runs anyway |
| `contract-strict` | the same, plus refuse when `unfilled` is non-empty — **this is the Codex adapter's discipline**, not the contract's |
| `ifelse-best` | a hand-written gate written **as well as possible**, including a guard for "the host gave no evidence" — the fair opponent |
| `ifelse-naive` | the same hand-written gate with **no** guard |

**Six scenarios**, three supported and three unsupported. Two are not invented: they are
the real incidents recorded in `DECISION.md`'s `can_deliver` section — the answer that
honestly reports a limitation (must be delivered) and the answer that proposes content
never written to disk (must be revised). Two more (`S5`/`S6`) are **word-for-word identical
answers with opposite verdicts**, differing only in whether the evidence actually contains
the file that was read. That pair is the needle that punctures a "when in doubt, reject"
gate, because such a gate looks perfect on false-accepts alone.

**Six perturbations.** Every one has provenance; none was invented to break the `if`/`else`
arm. A perturbation set designed after deciding who should win measures the author.

| Id | Drift | Where it comes from |
|---|---|---|
| `P0` | none | the baseline |
| `P1` | the `history` key is **absent** | observed: the first live Codex run lost `base_risk` exactly this way — a tool-name mismatch, so the lookup missed and the cell never entered the frame |
| `P2` | `history` is an **empty array** | observed: the transcript reader's failure shape — the key is there, the value is empty. Must be separate from `P1`: `undefined` and `[]` are different things in JS, and the refusal logic need not treat them alike |
| `P3a` / `P3b` | a value is an **array, not a string** | a real, already-fixed bug in this repo: `canDeliver`'s `evidence` projection returned an array, so the declared `chars: 600` bound had never once applied |
| `P4` | history is **well-formed but unrelated** | observed: the live run read `task` as `<environment_context>` — perfect format, entirely wrong content |
| `P5` | **only cells the frame excludes** | ★ the negative control. Any difference here means the differences elsewhere are not attributable to the declared frame |

**A deterministic judge, not a model.** The judge checks each factual claim in the answer
for a keyword in the evidence it is handed. It is deliberately a **proxy**: substring
matching is not semantics, and a real judge would accept paraphrases. Its purpose is to make
the `frame → verdict` step readable, recomputable and random-free — so that when the frame
breaks, the verdict breaks *for a reason I can point at*. It is shared by all four arms, so
it favours none of them. The semantic judge is the second arm (a hand-written LLM gate) and
needs a real backend; that is not this round.

**The oracle is hand-authored**, and this is the weakest part of the experiment, so it is
stated rather than buried. Each scenario's expected verdict was decided by a human reading
the evidence, and the `why` field records the reasoning so a reviewer can disagree with a
specific case. Calling a hand-labelled oracle "automatic" is the most common lie in this
kind of measurement, and it is exactly what makes the numbers look harder than they are.

## Result

Totals over 6 scenarios × 6 perturbations = 36 runs per arm:

| Arm | agrees | false-accept | false-reject | refused | error |
|---|---|---|---|---|---|
| `contract` | 33 | 0 | 9 | 0 | 0 |
| `contract-strict` | 30 | 0 | 6 | 6 | 0 |
| `ifelse-best` | 30 | 0 | 6 | 6 | 0 |
| `ifelse-naive` | 33 | 0 | 9 | 0 | 0 |

And cell-by-cell, across **every** perturbation:

- `contract` ≡ `ifelse-naive` — identical in all 36 runs
- `contract-strict` ≡ `ifelse-best` — identical in all 36 runs
- `contract` vs `ifelse-best` — differ only under `P1`, in all six scenarios

The negative control passed for all four arms: changing only excluded cells changed nothing,
so the `P1` difference is attributable to the missing cell and not to the manipulation
machinery.

### What this says

**1. The falsification condition holds.** On this node, with this judge, contract-driven
gating shows no measurable advantage over an equivalent hand-written gate. The policy layer
is translatable by construction, and the measured behaviour bears that out rather than
contradicting it.

**2. The refusal is a choice, not a property of the contract.** In the reference runtime,
losing a declared cell does **not** stop the decision: `unfilled` is recorded and nothing
consumes it. The arm that behaves like the contract as shipped is indistinguishable from a
hand-written gate that never thought about drift.

The refusal that exists lives in `adapters/codex/core.ts`, and the best-practice
hand-written gate implements the identical guard with the identical result. So "declarative
frames refuse under drift" is currently **an adapter property, not a contract property** —
and any document that says otherwise is describing the adapter while crediting the
contract.

**3. The zero is not safety.** Under `P1`, `contract` scores zero false-accepts — and that
deserves to be read with suspicion. Empty evidence makes *every* claim unsupported, so the
gate rejects everything: three false-rejects and three coincidentally-right rejections. It
is not judging better; it has stopped working. A gate that rejects everything is perfect on
the false-accept axis, which is why every table here reports both axes.

### A hole this found

`history: []` — the key present, the value empty — is refused by **nothing**, including the
`contract-strict` arm. `unfilled` detects that a key was never supplied; it cannot detect
that a supplied value is empty. The frame's own vocabulary already separates `unfilled`
("the harness forgot to feed this") from `absent` ("not applicable today"), and an empty
array projects to an empty string that is neither.

This matters because it is the *reader's failure shape*, not a hypothetical: the Codex
adapter produces exactly this when a transcript cannot be read. And it is the same class of
defect as the two the live run found — a condition that is recorded nowhere and therefore
concluded silently. It is now pinned by a test that fails if any arm starts refusing, so
fixing it will force this document to be updated rather than quietly invalidated.

## Two manipulations that failed

`P3a` and `P3b` were intended to show that a type drift (an array where a string is
declared) corrupts the frame invisibly. **They changed no verdict in any arm.** The
projections coerce, `String(['abc']) === 'abc'`, and the declared `chars` bound is applied
by *element count* to arrays, so a one-element array is not even over budget.

They are reported as failures rather than deleted. Deleting them would leave a report
saying "all perturbations agree", which would record an experiment that did not happen as a
conclusion that did. What they do show is narrower and still worth having: the frame carried
an array where its projection declares `string`, and `unfilled` / `absent` / `truncated`
said nothing about it. A verdict can be unaffected while the frame is wrong.

## Limits

- **One node.** `can_deliver`. The claim is about the gate tested here, not about all
  fourteen decisions.
- **A proxy judge**, as above. This experiment cannot speak to whether a contract improves
  a *model's* judgement; that is the LLM arm.
- **Six scenarios and a hand-authored oracle.** Enough to exhibit the mechanism, not enough
  for a rate with an error bar. The tables are counts over a curated set, not estimates.
- **The reference frame compiler is used** (`buildDecisions().canDeliver.frameArtifact`).
  `jevloop/contract` exports no generic frame compiler, so the portable path would need one;
  that asymmetry is itself worth noting.
- **A negative result about the verdict is not a negative result about everything.** This
  says the contract does not *judge* better. It does not test legibility, or whether a
  third party can audit the result — the two benefits the positioning document already
  identifies as conditional on a second consumer.

## What follows

The contract's remaining defensible claim is narrower than "better decisions" and more
specific than "a nicer way to write the gate": **a declared frame makes the drift check
derivable, so it cannot be forgotten one cell at a time.** In this experiment that claim is
not yet measured — it is structural. The contract computes `unfilled` *from the `frame:`
declarations*, so a cell added to the contract is covered automatically; a hand-written gate
covers exactly the cells its author remembered. `ifelse-best` matched `contract-strict`
because a human wrote one guard for one cell in a six-line gate.

That is testable — mutate the frame declaration and measure which arm stays covered — and
it is the version of the claim worth running next, because it is the only one this round did
not falsify.
