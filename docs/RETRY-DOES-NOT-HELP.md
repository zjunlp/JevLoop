# Does "go get more evidence" help? Tested, and no — with a reason

The user's question: can the controller improve itself ReAct-style by gathering more evidence
after a rejection?

Set up fairly for the first time. The author's `ternary_judge` **already contains this loop**:

```python
if verdict == "UNDECIDED":
    more = retrieve(question + " " + claim, all_docs, k=6)   # gather more
    raw2 = ternary_judge_raw(llm, claim, q, more)            # re-judge
```

Our `jev` arm had **one shot**. So the earlier four-way comparison gave the author's method a
retry mechanism and ours none. `JevClaimController` now has `retries` and uses **the upstream
`retrieve` unchanged**, so the only difference is who judges — not how documents are fetched.

## Setup

Fresh 20 questions, 5 per type, seed 20261005 — **disjoint from every earlier subset**.
27 atomic claims, generated once and shared by all arms. Native upstream `gold_check` /
`metrics` throughout.

## Result

| arm | committed | false follows | Coverage | tokens |
|---|---:|---:|---:|---:|
| `direct` (no judge) | 27 | 12 | 1.00 | 4,891 |
| `ternary` (author, own retry) | 16 | **1** | 0.81 | 90,555 |
| `jev` (no retry) | 16 | **2** | 0.67 | 23,169 |
| `jev` **+ retry** | 16 | **2** | 0.67 | 31,714 |

**The retry changed nothing: 0 of 27 verdicts differ from the no-retry arm**, at +8,545
tokens.

## Why it changed nothing — and this is the useful part

The retry fired on all 9 `UNDECIDED` claims. It did fetch more documents — 3 documents
became 6. And the verdict stayed `UNDECIDED` every time, with the backend **confident**:

```
q014  Brevia Dynamics reported revenue of 87 million USD   UNDECIDED P=0.95 → 0.94 → 0.96
q064  Dovre Analytics reported revenue of 233 million USD  UNDECIDED P=0.97 → 0.97 → 0.97
q090  Falken Optics reported revenue of 528 million USD    UNDECIDED P=0.98 → 0.98 → 0.98
```

**Jev's `UNDECIDED` is not "I need more evidence" — it is "this is undecidable", stated at
95–98% confidence.** More retrieval cannot fix a problem that is not about how much evidence
was fetched.

And the 9 rejections were mostly right:

| type | claims | what the gold wants | Jev's verdicts | correct? |
|---|---:|---|---|---|
| contradiction | 7 | do not commit a value | `UNDECIDED` ×7 | **all 7 correct** |
| unanswerable | 4 | do not commit a value | `FOLLOW` ×2, `OMIT` ×2 | 2 wrong |
| supported | 6 | commit the fact | `FOLLOW` ×4, `UNDECIDED` ×2 | 2 misses |
| redundancy | 10 | commit the useful fact | `FOLLOW` ×10 | all correct |

So 7 of the 9 retries were spent trying to rescue claims that were **correctly rejected**.
Re-fetching cannot help when the evidence is *conflicting* or *absent* — there is nothing
more to find. **"Gather more evidence" only helps when the rejection was caused by an
evidence shortfall, and here none were.**

## A metric artefact worth flagging

The apparent coverage gap — 0.81 for the author versus 0.67 for us — is **mostly a labelling
difference, not a behavioural one.**

Upstream `Coverage` = non-`UNDECIDED` / moves. So the author's `NULL` counts as covered
while Jev's `UNDECIDED` does not — even though **both mean "do not commit this claim"**, and
`gold_check` treats them identically (it only runs on `FOLLOW`).

| | committed | not committed |
|---|---:|---:|
| `ternary` | 16 | 11 |
| `jev` | 16 | 11 |

**Both arms commit exactly the same number of claims.** The real difference is one false
follow. Reporting "coverage 0.67 vs 0.81" as a deficit would be wrong, and this must be
stated wherever those numbers appear.

## What this means for the design

1. **Retry-on-rejection is not a capability lever here.** Adding it to our arm costs 37% more
   tokens and changes nothing. It is not the ReAct-style improvement it looks like.
2. **The undecidable case is where the real gap is.** `jev` still commits 2 of 4
   `unanswerable` claims; the author commits none. That is a judgement difference on the
   same evidence, and it is where to look next — not at retrieval.
3. **`UNDECIDED` and `NULL` are behaviourally equivalent but score differently.** Any future
   comparison must report "committed vs not" alongside upstream Coverage, or it will keep
   reading a label choice as a capability difference.

## Artifacts

- `experiments/result/_external/ternary-retry-shared-20-2026-10-05/` — shared candidates
- `experiments/result/_external/ternary-retry-ternary-20-2026-10-05/` — author's method
- `experiments/result/_external/ternary-retry-jev-20-2026-10-05/` — both Jev arms
- `JevClaimController.retries` + recovery records in
  `experiments/scripts/ternary_native_run.py`; tests in
  `experiments/tests/test_ternary_native_run.py` (7 pass, including that `retries=0` walks
  no extra step so the old batches stay comparable)
