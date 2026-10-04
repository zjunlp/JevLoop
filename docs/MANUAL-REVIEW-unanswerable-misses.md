# Manual review: the two "unanswerable" misses on the 20-question development subset

Scope: the four `unanswerable` claims in the fixed-seed 20-question development subset
(seed 20261002), reviewed against the original question, the retrieved documents, the
whole 40-document corpus, and the pinned upstream scorer. No code, prompt, threshold,
verdict or score was changed. Upstream `gold_check`/`metrics` remain the primary numbers.

## What I previously reported, and why it was wrong

The earlier summary said Jev "still followed 2 fabricated claims". Manual reading shows
neither of those two claims is a fabrication. The corrected statement is below.

## The four claims, one by one

| q_id | claim | Jev verdict (probabilities) | upstream `gold_check` | manual reading |
|---|---|---|---|---|
| q109 | "Garnet BioWorks does not have a chief technology officer listed in the provided documents." | `FOLLOW` (.86) | `False` | **true absence statement**, mis-scored |
| q094 | "Dovre Analytics does not have a chief technology officer listed in the provided documents." | `FOLLOW` (.86) | `False` | **true absence statement**, mis-scored |
| q099 | "Ister Materials' chief executive officer is D. Horvat." | `OMIT` (.70) | `None` (not FOLLOW) | **Jev correct**, direct wrong |
| q104 | "S. Kowal is the chief executive officer of Brevia Dynamics." | `OMIT` (.64) | `None` (not FOLLOW) | **Jev correct**, direct wrong |

Question for all four is the same shape: *"Who is the chief technology officer of X?"*,
with gold `NOT_FOLLOW` / `value="absent"`.

## q099 and q104: Jev was right

The generator answered a **CTO** question with the **CEO** fact. The claim is true
(d009/d002 state it) but does not answer what was asked. `OMIT` is upstream's exact label
for "the claim may be true but is inessential to the question".

Jev returned `OMIT` with FOLLOW probability only 0.15 on both. direct committed both and
was scored wrong. These two are Jev successes, and my per-type table already counted them
that way — they were never part of the "misses".

## q109 and q094: true statements scored as fabrications

The claim asserts an absence, scoped to "the provided documents". Verified:

- the three retrieved documents (d007/d001/d002 and d004/d001/d002) list only a CEO;
- **the whole 40-document corpus contains no occurrence of "chief technology officer" or "CTO" at all**.

So both claims are true. They are the honest, safe partial answer to a question whose
gold is "absent".

Why does upstream score them `False`? The author wrote `pipeline.is_absence_claim` to
*exclude* absence claims from the false-follow rate and count them separately:

```
_ABSENCE = r"do(es)? not (state|mention|specify|provide|contain)|no information|not (stated|mentioned|specified|provided|documented)"
```

"does not **have** ... listed" is not in that alternation. Measured on the pinned code:

```
'Documents do not state the founding year.'   -> True
'Documents do not mention a CTO.'             -> True
'The document does not contain the CTO name.' -> True
'Does not specify a CTO.'                     -> True
'No information about the CTO.'               -> True
'X does not have a CTO listed.'               -> False   <-- our generator's phrasing
```

So `gold_check` falls through to the `q["type"] in ("contradiction","unanswerable")`
branch and returns `False`. Under the author's own documented intent these two should be
`None` (abstain_follows), excluded from the false-follow rate.

A full scan of all 25 claims found exactly two absence-phrased claims — these two — and
they are exactly the two Jev is scored as failing.

## But this is not only a metric artifact

Jev also has a genuine limitation here, of a different kind from fabrication: it has no
way to express "this sentence reports missing data rather than answering the question".
Upstream's certificate rule can never return FOLLOW without a document quote certifying
the claim, and an absence cannot be certified by a quote. Jev assigned `FOLLOW` at 0.86 to
a sentence that only describes what the documents lack. That is a real behaviour worth
fixing on our side, independent of how upstream scores it.

So both readings hold and neither cancels the other: **the claims are not fabrications,
and Jev still mishandles absence statements.**

## Corrected numbers

Primary (unchanged upstream code, as published by the author):

| | direct | Jev |
|---|---:|---:|
| FOLLOW verdicts | 25 | 17 |
| false FOLLOWs | 10 | 2 |
| FalseFollowRate | 40.0% | 11.76% |

Secondary (manual classification applying the author's documented absence exclusion):

| | direct | Jev |
|---|---:|---:|
| FOLLOW verdicts | 23 | 15 |
| false FOLLOWs | 8 | 0 |
| FalseFollowRate | 34.8% | 0% |

**Jev committed zero fabricated values on this subset.** All of its remaining
"false follows" were true absence statements.

I am not reporting the secondary row as *the* result. The primary row is what the pinned
upstream code computes; the secondary row is a manually verified annotation explaining
what the two cells actually contain. Fixing the upstream regex is not our call.

## What this changes

- The n=20 headline is **not** "Jev missed 2 fabricated claims". It is "Jev fabricated
  nothing here, but mislabels absence statements as FOLLOW, and upstream's absence
  detector does not catch our generator's phrasing".
- Jev's FFR of 11.76% is inflated by that mismatch of phrasing, not by lying.
- 0/15 valid claims rejected still has a descriptive 95% Wilson upper bound of about
  20.4%. A zero count on 15 claims is not evidence of a zero rate.
- Anything I do next must not be tuned on these 20 questions. A phrasing fix that makes
  absence claims come out UNDECIDED is a method change and needs fresh questions.

## Artifacts

- Raw Jev requests/responses: `experiments/result/_external/ternary-native-jev-cached-20-dev-2026-10-02/jev-decisions.jsonl`
- Shared candidates: `experiments/result/_external/ternary-native-shared-20-dev-2026-10-02/candidates.json`
- Comparison summary: `experiments/result/_external/ternary-native-20-dev-comparison.json`
