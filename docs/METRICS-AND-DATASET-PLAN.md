# Beyond success rate: what to measure, and on which datasets

Written after the four-way ternary comparison showed our arm does **not** beat the author's
ternary judge, and after a manual cross-tabulation of ALFWorld showed that the metric —
not the dataset — was what made us drop it.

## 1. Success rate alone is not enough, and we already have proof

ALFWorld `react`, 10 tasks, native `won`:

```
won = 2/10
```

Read alone, that says "the honest arm barely works here, the event rate is too low, drop
the dataset". That was my earlier conclusion. **It was wrong.**

The same 10 runs, cross-tabulated against what the agent actually claimed:

| truth (`won`) | agent claimed done | agent reported failure | no claim |
|---|---:|---:|---:|
| pass (2) | 2 | 0 | 0 |
| fail (8) | **5** | 1 | 2 |

**5 of 10 tasks are false completions** — the agent asserted it had finished a task the
environment says it did not finish. Of the 7 tasks where it claimed completion, 5 were
false. The event is abundant; the metric was the problem.

Success rate cannot distinguish:

- "tried, failed, and said so" from "tried, failed, and claimed success";
- a gate that improves outcomes from a gate that just refuses everything;
- a cheap arm from an expensive one.

## 2. The metric set

Five layers. Report **all five**, per dataset, with denominators.

### A. Native task score

The benchmark's own scorer, unmodified. The only number that may be called official.
Everything else here is an observation.

### B. Cost

Steps, tool calls, tokens, wall clock. Without this, a gate that refuses everything looks
free and a gate that improves things looks expensive.

### C. The claim × truth cross-tabulation — the headline

|  | native pass | native fail |
|---|---|---|
| **agent claims done** | honest success | **false completion** |
| **agent claims not-done** | **false rejection** | honest failure |

Two error rates, both directions, plus the "no claim" bucket reported separately rather
than folded into either. A one-sided rate can be gamed by a degenerate policy.

### D. Coverage loss

Of everything the controller blocked, how much was actually fine? A gate that blocks a lot
to catch a little is not a win, and coverage loss does not show up in the native score.

### E. Recovery-chain evidence

For any "go back and do it" claim: rejected stop → new tool call → new observation →
native end-state improvement. A request that is rejected and then merely rewritten proves
honesty, not recovery.

## 3. Which datasets can actually support layer C

Layer C needs **two independent per-task signals**: objective truth, and a machine-readable
claim. Many of our datasets have only the first.

| dataset | objective truth | claim channel | C computable? |
|---|---|---|---|
| `alfworld` | native `won` replay | final answer text (needs a detector) | **yes** |
| `terminal-bench` | official pytest | final answer text (needs a detector) | **yes**, for the 79/86 Dockerfile tasks |
| `ternary-judge` | native claim gold | the controller's own verdict | **yes**, already done |
| `bfcl-v3-*` | gold function calls | did it call, and did it claim to? | partial; needs official scorer first |
| `gsm8k`, `hotpotqa`, `triviaqa`, `fever`, `sotuqa`, `strategyqa`, `sportsunderstanding`, `physicsquestions`, `toy` | answer match | **none — there is no completion claim, only an answer** | **no** |
| `fta` | six-label judge | — | blocked: needs the original judge |
| `bullshitbench`, `draco` | premise challenge | the answer itself | proxy scorer only |
| `tau2-bench` | DB state hash | — | blocked: needs the user simulator |

**The nine QA datasets cannot carry our claim.** They have no notion of "I finished the
task" that could be false. They stay as capability and cost regression checks, not as
evidence about control.

## 4. The missing piece

**There is no completion-claim detector on the Python side.** The only one is
`src/claim-lexicon.ts`, and its own header records four separate false-positive incidents,
all landing on the honest side.

That is the blocker for layer C everywhere except ternary-judge. Two consequences:

- The ALFWorld numbers in §1 came from a three-line heuristic I used to read the logs by
  hand. **They are a manual reading, not a measurement.** The story is worth pursuing;
  those exact numbers are not evidence.
- A ported detector must ship with a **differential test against the TypeScript original**
  (this repo's existing parity discipline) and must report **its own error rate** next to
  every derived metric. A lexical proxy sitting underneath a headline number is exactly the
  failure mode this project keeps catching in others.

## 5. Run plan

**Step 1 — claim detector with a measured error floor.** Port `claim-lexicon.ts` to Python,
add a differential test, and hand-label a sample to report its false-positive and
false-negative rates. Without this, layer C is not reportable.

**Step 2 — ALFWorld arm ladder, paired this time.** `react` vs `react-termination` vs
`react-typed`, same tasks, same seed, same budget, frozen tree. Report layers A–E. This is
the cheapest dataset with layer C support and the event is already known to be common.

**Step 3 — Terminal-Bench**, restricted to the 79 Dockerfile tasks or after adding compose
support. Slower; do it once step 2's pipeline is settled.

**Step 4 — BFCL**, only after the official evaluator is wired. Until then its numbers are
function-name proxies and cannot enter a table.

**Not now:** the nine QA datasets (no claim channel), FTA (judge blocked), tau2 (simulator
blocked), and any further tuning of our arm on the ternary development subset.

## 6. What would change the paper's story

The four-way result says our claim-level controller is not the contribution — the author's
ternary judge is better at that job. The ALFWorld cross-tabulation points somewhere else:
**the harness-level control layer changed both task success and false-completion rate on
the same tasks.** Whether that survives a paired, frozen, adequately powered run is the
question worth answering now.

## Artifacts

- Four-way comparison: `docs/FOURWAY-TERNARY-DEV.md`
- Cross-dataset sweep: `docs/SWEEP-2026-10-02.md`
- Manual absence-claim review: `docs/MANUAL-REVIEW-unanswerable-misses.md`
