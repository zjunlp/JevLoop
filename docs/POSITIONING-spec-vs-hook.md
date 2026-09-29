# A specification, or a hook? What this project actually is

> Written after building a real adapter for a host we do not own
> ([Codex](ADAPTER-CODEX-SCOPE.md), [`adapters/codex/`](../adapters/codex/README.md)).
> The exercise made two things clear that the other documents only imply: what a
> decision contract is worth, and **under what condition** it is worth anything.

## The question

There are two readings of this project, and a reader will arrive at one of them within
five minutes:

```text
reading A   a specification for the judgement layer of an agent
reading B   a hook you install into somebody else's agent
```

They are not alternatives — but they are not the same product either, and the difference
decides what work is worth doing next.

## First, what the specification is not

`DECISION.md` is **not an agent-design specification**. It does not say how to build an
agent, what phases it has, how its sub-agents are organised, or how they communicate. It
governs **one layer**: the judgements. For each judgement it declares where it sits in the
loop, what it asks, which options exist, how answers become actions, **what context it is
allowed to see, and what it deliberately does not see**. It is a contract about
judgements, not a blueprint for agents.

## What the specification is

Not a format for listing decisions. A format is a container; this is a set of
**invariants a program can refuse**. Four layers, plus a mutation suite that exists to
prove the layers are not vacuous:

```text
parse     grammar, kind, closed action list, closed positions, every field bounded
policy    every predicate must compile — one that does not is a gate that never fires
frame     every state cell is either read by some judgement or excluded WITH A REASON.
          There is no third state.
schema    a missing or unrecognised version is refused, not guessed at
```

## What it is worth, and when

The honest version separates the part that holds for one consumer from the part that only
materialises with several.

| What it buys | Evidence in this repository | Holds when |
|---|---|---|
| **Legible judgements** — inputs and exclusions are declarations, not code buried in a branch | delete the `- cwd —— …` line and four layers plus 61 tests stayed green; the cell simply vanished from the declaration. The frame-completeness check now fails it by name | someone reads or audits the layer |
| **Refusal at load time** | 15 mutations caught, 4 negative controls unharmed (`npm run conformance`) | always |
| **Action meanings are defined, not inferred** | all 14 actions declare `next` / `endsLoop` / `moreModelCalls` / `needsEvidence` / `retries`, each **checked against the running loop** | a host reads them |
| **Consumable without the reference runtime** | from a packed tarball, installed into an empty project, `jevloop/contract` works **with our own `DECISION.md` deleted** | always |
| **Auditable across hosts** | records from a real Codex session verify under our verifier (`npm run replay`: `verified`, no mismatches) — the digests exist only because the adapter computes them | there is a second host, or a third-party auditor |

**The first four rows are roughly what a careful engineer gets from a YAML file plus a
validator.** What the contract adds beyond that is **consistency across hosts** and
**third-party auditability** — and neither is worth much with one consumer. We have one.

So the defensible claim is conditional:

> A decision contract buys **legibility and refusability** for the judgement layer. Its
> price is paid immediately; its value arrives with the second consumer.

That is why `TODO.md` §12 lists **one real adopter** as a load-bearing item rather than a
nice-to-have, and why writing another format feature is currently worth less than running
this thing inside one real agent loop.

## The adapter path, and what it cannot do

A hook is how the contract reaches a host that is not ours. Seven limits are **structural**
— more effort does not remove them:

1. **Only interceptable judgements are adaptable.** Codex offers three of six positions.
   `pick_tool` — routing *which tool* — is the reference loop's most-cited node and it is
   **unreachable** there, because `PreToolUse` fires after the model has already chosen.
   Which judgements you can adapt is decided by the host's extension surface, not by which
   ones matter.
2. **Host verdict vocabularies are coarser than the contract's.** Codex accepts four
   verdicts against fourteen actions, and `ask_human` **cannot be expressed at all** — its
   parser rejects `ask`. Every adapter therefore declares a lossy mapping, and **the same
   contract behaves differently on different hosts**. That directly weakens the
   "one contract, one behaviour" premise.
3. **Granularity mismatches are fatal.** `Stop` gives one bit for termination;
   `step-start` has no point at all; `UserPromptSubmit` fires once per prompt, which is
   the wrong frequency for a per-step position.
4. **The adapter cannot see what the host does not record.** `files` / `readFiles` become
   the adapter's job — approximate, and thinner the further back the reads are.
5. **A hook adds a process boundary to every decision.** Codex's own example config uses
   `timeout: 10` seconds. We measured a hosted decision round trip at ~390 ms of which
   ~254 ms is handshake (`TODO.md` §8.11). **The hook model eats a large part of the
   "decisions are cheap" argument**, and on a hosted backend it makes round-trip cost
   worse. The reference loop at least pays that cost in-process.
6. **You are asking a user to install something that can refuse their agent's actions.**
   The host may require explicit trust, and an adapter that fails open silently removes
   the gate it was demonstrating. (Ours fails closed — but that is our choice, not a
   property of hooks.)
7. **Internal formats drift.** The transcript reader consumes a format whose own
   documentation says readers "must use codex_rollout's canonical parser", which lives
   inside Codex. No compatibility promise exists.

Five further gaps were **ours, and fixable** — the first is now closed, and it was the one
that mattered most:

1. ~~The adapter has never run inside a live Codex session.~~ **It now has** (Codex
   0.158.0, `codex exec`, a stub model) — and the live run found two bugs the offline suite
   could not: the risk table was keyed on the *model-facing* tool name while hooks deliver
   the host's canonical one (so `base_risk` went silently `absent`), and "the first user
   message" is a synthetic `<environment_context>` turn, so `task` came out **wrong** while
   every other signal looked perfect. Both are fixed and covered by tests. What is still
   unverified is **repetition and independence**: one session, one Codex version, and the
   adapter was edited in response to what that session showed, so the live evidence is not
   yet independent of the fixes it produced.
2. Frames are thin in practice: `files` / `readFiles` are approximations.
3. `auto_audit`'s trace obligation has no consumer yet.
4. **Nothing measures whether any of this reduces unsupported completion.** There is no
   number behind the reliability claim.
5. **Replay cannot catch a self-consistent wrong frame — observed, not hypothetical.** In
   the first live session the adapter judged against a wrong `task`; `npm run replay`
   reported every record `verified`, `0 mismatch`. The raw context is deliberately not
   recorded, so there is nothing to check the projection against. Records prove a decision
   was made under *some* frame, not the right one.

## The falsification condition

If the specification is to be more than a nicer way to write a gate, this must come out
the other way:

> Take a hook-based authorization and termination gate implemented as plain `if`/`else`
> and the same gate driven by a decision contract. If **unsupported completion** — a
> claim of completion that external evidence does not support — does not differ measurably
> between them, then the contract's value collapses to "a more legible way to write the
> gate". That is a much smaller claim, and it should be stated as such.

If a difference does exist, it has to come from something only the contract provides:
**declarative bounds and exclusions** (which decide what a judgement can see), **closed
position/action checking** (which prevents a gate that does not exist), **refusal at load
time**, and **records an outside party can audit**. None of those are reachable with a
plain branch — and none of them have been measured.

## What follows for priorities

```text
not next    another format feature. The checklist in §12 of TODO.md is empty of them.
done        run the adapter inside a live Codex session. It found two silently-wrong reads
            (see the gaps above); both are fixed and the fixes are pinned by tests.
next        the measurement: contract-driven gate versus an equivalent if/else gate, on
            unsupported completion. It is the positive form of the falsification
            condition, and it is the same experiment the paper needs.
```

The uncomfortable summary: **the specification is the more interesting artifact and the
adapter is the one that runs.** A contract with no second consumer is a well-checked
document; a hook with no contract is a hundred lines of `if`. The project becomes real at
the point where both exist and someone else's runtime is the thing being governed.
