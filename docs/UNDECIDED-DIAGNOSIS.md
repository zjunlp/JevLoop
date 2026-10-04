# The undecidable verdict: diagnosis, and a fix that removes both false follows

Follow-up to `docs/RETRY-DOES-NOT-HELP.md`. Two user instructions drove this:

1. **Retry/gather-more-evidence is only for evidence shortfalls.** Recorded as a rule below.
2. **Investigate the `UNDECIDED` verdict — it looks off.** It was.

## The rule, recorded

`UNDECIDED` and "evidence insufficient" are different failures and must not share a remedy:

| verdict means | remedy |
|---|---|
| evidence is **missing** — could be fetched | go get it (retry with expanded retrieval) |
| evidence is **conflicting or absent by construction** | nothing to fetch; decide differently |

The measured evidence for this: of 9 retries in the previous experiment, **7 were spent trying
to rescue claims that were correctly rejected**, and all 9 returned `UNDECIDED` again at
95–98% confidence. Retrieval cannot fix a conflict that exists in the corpus.

## Diagnosis

All 27 claims of the fresh subset, with their first-pass distributions:

| type | claims | Jev | correct? |
|---|---:|---|---|
| `supported` | 6 | `FOLLOW` ×4, `UNDECIDED` ×2 | 2 misses |
| `contradiction` | 7 | `UNDECIDED` ×7 (P 0.67–0.98) | **all 7 correct** |
| `unanswerable` | 4 | `FOLLOW` ×2, `OMIT` ×2 | **2 wrong** |
| `redundancy` | 10 | `FOLLOW` ×10 (P 0.94–1.00) | all correct |

The two errors are both `unanswerable`, and both committed a claim of this shape:

```
"Garnet BioWorks does not have a chief technology officer listed in the provided documents."
"Aldermont Systems does not have a chief technology officer mentioned in the provided documents."
```

Verified against the pinned upstream code:

| claim | `is_absence_claim` | `gold_check` |
|---|---|---|
| q109 absence claim | `False` | `False` → counted as a false follow |
| q091 absence claim | `False` | `False` → counted as a false follow |
| q014 "revenue of 87 million USD" | `False` | `True` → Jev's `UNDECIDED` is a genuine miss |

So the claims are **true statements about missing data** — the corpus contains no CTO at all —
and upstream's absence regex does not match the phrasing `does not have`. This is the same
pattern already documented in `docs/MANUAL-REVIEW-unanswerable-misses.md` from a **different**
subset: the generator reaches for this phrasing repeatedly.

**But the interesting part is not the regex. It is that the author's method cannot make this
mistake at all.** `pipeline.fixed_rule`:

```python
if v in ("FOLLOW", "NULL"):
    if not q or len(q) < 12:          return "UNDECIDED", "NO_CERTIFICATE"
    if not any(q in d["text"] for d in docs): return "UNDECIDED", "CERTIFICATE_NOT_GROUNDED"
```

A `FOLLOW` must carry a **verbatim document span**. An absence cannot be quoted, so it is
downgraded automatically. **Our judge had no counterpart to that step.** The gap is not the
judge — it is the decision procedure: we ask "is this supported?" and never "by what?".

## The fix

Give our arm the same obligation, expressed for a choice-only interface (Jev cannot emit
free text): a second question —

> "Which single provided document, if any, states this claim verbatim or with an explicit
> number/name that certifies it?"  — options are the doc ids plus `none_of_the_provided_documents`

`FOLLOW` with `none` is downgraded to `UNDECIDED`, recorded as `no_certificate` — the same
disposition as the author's `fixed_rule`.

## Result

Same 20 questions, same 27 shared claims, same native scorer.

| arm | committed | false follows | FFR | Coverage | tokens |
|---|---:|---:|---:|---:|---:|
| `direct` (no judge) | 27 | 12 | 44.4% | 1.00 | 4,891 |
| `ternary` (author) | 16 | 1 | 6.25% | 0.81 | 90,555 |
| `jev` (no grounding) | 16 | 2 | 12.5% | 0.67 | 23,169 |
| **`jev` + grounding** | 14 | **0** | **0%** | 0.59 | 33,459 |

The grounding question was asked **16 times** (once per `FOLLOW`) and answered
`none_of_the_provided_documents` **exactly twice** — q091 and q109. Those two were downgraded;
**nothing else changed.** No valid claim was lost: `supported` still commits 4,
`redundancy` still commits all 10.

So in this batch our arm goes from 2 false follows to none, while the author's method has one —
at roughly **2.7× lower token cost** (33k vs 91k).

## What this is evidence for

The mechanism that fixed it is not a better judge, a better prompt, or more evidence. It is a
**requirement on what a verdict must be able to point at**. That is the same lesson as the
earlier finding that a decoupled-but-text-reading judge behaves like no judge at all
(`docs/MEASUREMENT-gate-equivalence.md`): **what a decision is allowed to be based on
determines whether it tracks the truth.**

It also explains the two error modes with one cause:

- committing an absence claim — no certificate exists, and none was demanded;
- declining a supported claim in the face of conflicting documents (q014) — a separate
  caution issue, not addressed here.

## Caveats — these are development numbers

- **20 questions, 27 claims.** One claim moves FFR by ~0.06.
- **The author's 1/16 is not a settled rate** either; at this n the difference between 0 and
  1 is not a result.
- **Coverage of 0.59 is not a straight loss**: the 2 downgrades were genuinely uncommittable,
  and as noted in `docs/RETRY-DOES-NOT-HELP.md`, upstream `Coverage` counts the author's
  `NULL` as covered while `UNDECIDED` is not, so cross-arm coverage comparison is partly a
  labelling artefact. Report "committed vs not" alongside it.
- **The grounding question costs an extra decision call per `FOLLOW`** — included in the
  token figures above.
- **Do not tune on this subset.** The question's wording and the downgrade threshold were
  written from the diagnosis, and must be validated on fresh questions.

## Artifacts

- `experiments/result/_external/ternary-grounded-jev-20-2026-10-05b/` — the grounded run
- `experiments/result/_external/ternary-retry-jev-20-2026-10-05/` — the ungrounded comparison
- `JevClaimController(grounded=True)` + `_ask_grounding` in
  `experiments/scripts/ternary_native_run.py`; 8 tests including that `grounded=False` walks
  no extra step
