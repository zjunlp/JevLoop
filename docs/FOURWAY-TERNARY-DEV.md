# Four-way comparison on the identical candidate set (development)

20 questions, 25 atomic claims, fixed seed 20261002. All four configurations receive the
**same generated claims and the same retrieval context**; the script asserts the ordered
`(q_id, claim)` tuples are identical before reporting. Scoring is the pinned, unchanged
upstream `gold_check` / `metrics`. Working tree dirty, method not frozen: development
numbers, not citable.

## Result

| config | who | follows | false follows | FalseFollowRate | Coverage | tokens |
|---|---|---:|---:|---:|---:|---:|
| `direct` | upstream, no judge | 25 | 10 | 0.4000 | 1.00 | 5,046 |
| `binary` | upstream, LLM binary judge | 24 | 9 | 0.3750 | 1.00 | 25,394 |
| `ternary` | **upstream, author's method** | 15 | **0** | **0.0000** | 0.84 | 96,136 |
| `jev` | **ours** | 17 | 2 | 0.1176 | 0.76 | 22,194 |

**Our method does not show an advantage here. The author's ternary judge wins on this
subset** — zero false follows at higher coverage than ours.

## The one place our arm looks defensible

Our two false follows are the true absence statements already reviewed in
`docs/MANUAL-REVIEW-unanswerable-misses.md` ("the documents do not have a CTO listed",
while the whole corpus contains no CTO). Upstream's `is_absence_claim` misses that
phrasing. Excluding them, our arm reaches 0/15 as well. **This is an annotation, not the
primary number, and it is not a win** — it is at best a tie, on claims we did not choose.

## By task type

| type | direct | binary | ternary | jev |
|---|---|---|---|---|
| supported (5) | 5 FOLLOW, 0 bad | 5 FOLLOW, 0 bad | 5 FOLLOW, 0 bad | 5 FOLLOW, 0 bad |
| contradiction (6) | 6 FOLLOW, **6 bad** | 5 FOLLOW, **5 bad** + 1 NULL | 4 NULL + 2 UNDECIDED, **0 bad** | 6 UNDECIDED, 0 bad |
| unanswerable (4) | 4 FOLLOW, **4 bad** | 4 FOLLOW, **4 bad** | 2 OMIT + 2 UNDECIDED, **0 bad** | 2 OMIT + 2 FOLLOW, **2 bad** |
| redundancy (10) | 10 FOLLOW, 0 bad | 10 FOLLOW, 0 bad | 10 FOLLOW, 0 bad | 10 FOLLOW, 0 bad |

Two observations that survive the small n:

- **The binary judge is almost worthless here** (37.5% vs 40% for no judge at all) while
  the ternary judge is perfect, both using the *same* judge model. The form of the check
  matters far more than having a check.
- **Nothing separates the arms on `supported` or `redundancy`.** No `supported` claim was
  ever rejected by anything, so this subset gives no evidence about false rejection. All
  the separation lives in the 10 `contradiction`/`unanswerable` claims.

## Confounds that block any superiority claim

1. **Judge model asymmetry.** The author's baselines were run with `deepseek-flash` as
   judge, because the local 9B cannot emit the bare JSON their `json.loads` requires — it
   failed on every attempt. Our arm uses the pinned small decision model `jev-1.13.0`. So
   this compares a frontier LLM judge against a small dedicated decision model, which is
   not a like-for-like judge comparison.
2. **Cost is not matched.** `ternary` spends about **4.3×** our arm's tokens. If the claim
   is cost-efficiency, this is the number that matters and it needs a cost-matched design.
3. **n = 20 questions, 10 discriminative claims.** One claim moves FalseFollowRate by
   ~0.04–0.07. No interval should be read as precise.
4. **Redundancy is untested.** All 10 redundancy claims were valid under upstream scoring,
   so OMIT handling was never exercised in a way we can read.

## Operational findings worth keeping

- The author's `binary`/`ternary` judges **crash on a judge that wraps JSON in markdown
  fences**; the local 9B does this consistently. This is a property of the judge model, so
  the judge was changed rather than the parsing. Recorded as `--judge-*` flags.
- `ternary` additionally failed with an **empty response** at `max_tokens=2048`: the model
  spent 4,426 tokens and 9,480 characters on hidden reasoning and emitted no visible JSON.
  Raised to 8192 and it completed. Any reasoning-model judge needs a generous budget here.
- `binary`'s own run crashed inside `ternary` before writing a report, so its numbers were
  re-scored from its already-written 25 claims with the same pinned evaluator.

## What this changes

The honest next step is **not** to tune our arm on these 20 questions. Either:

- run the author's baselines with a judge comparable to ours, and/or match token budget, so
  the comparison is interpretable; or
- accept that the author's ternary method is the stronger claim-level verifier and position
  our contribution elsewhere (harness-level control and recovery), which is what the
  earlier claim analysis suggested anyway.

## Artifacts

- Combined table: `experiments/result/_external/ternary-native-fourway-20-dev.json`
- Per-config reports: `ternary-native-shared-20-dev-2026-10-02/`,
  `ternary-native-authorjudges-20-dev-2026-10-02c/`,
  `ternary-native-ternaryjudge-20-dev-2026-10-02d/`,
  `ternary-native-jev-cached-20-dev-2026-10-02/`
