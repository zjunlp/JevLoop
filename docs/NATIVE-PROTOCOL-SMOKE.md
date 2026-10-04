# Native atomic-claim protocol smoke run

## CI report

The reported Claim.empty and unused claimOf errors belong to earlier source state. Current HEAD 455c428 already declares Claim.empty and only imports Claim as a type. GitHub API reports CI success for HEAD: https://github.com/zjunlp/JevLoop/actions/runs/36683380745 . Local check (141 files), typecheck, build and 676 TypeScript tests passed. No redundant TypeScript fix was made.

## Executed protocol

`experiments/scripts/ternary_native_run.py` loads byte-verified original retrieval, generation prompts, binary/ternary judges, certificate rules and run_config from the pinned upstream archive. Only its chat interface is bridged to our model client. Raw requests/responses are logged, atomized claims and actual upstream verdicts persisted, then `ternary_native_eval` invokes unchanged original grading and metrics.

The direct/binary/ternary rows are upstream protocol smoke runs, not a JevLoop/Jev performance comparison. A `jev` configuration is now available: it generates the same atomic claims, sends only question/claim/documents to pinned Jev over HTTP, and records the typed decision plus raw response. It rejects degraded/missing answers with no Mock fallback. Its four-choice mapping is our decision policy, **not** the author's quote-certified ternary judge; both only share the unchanged upstream claim gold_check and metrics. The current paired development run uses local qwen3.5-9b-local for generation and real Jev for commit decisions, q001 and q061, max_tokens4096. No paid generation API calls. Generation is separate across configurations rather than cached-candidate paired. Dirty workspace and n=2 make these debugging demonstrations, not paper effects.

## Results

| Original config | Completed | Moves | FalseFollowRate | Coverage | Tokens | CostPerCorrectAnswer |
|---|---|---:|---:|---:|---:|---:|
| direct | Yes | 2 | 0.5 | 1.0 | 516 | 516 |
| binary | No | — | — | — | — | — |
| ternary | Yes | 2 | 0.5 | 1.0 | 1258 | 1258 |

These are original claim-move metrics, not two-question answer accuracy. CostPerCorrectAnswer is the author's token/valid-FOLLOW-claim quantity, not dollar cost. One supported claim is valid; one committed single revenue figure on a conflicting question is invalid. The original ternary certificate rule does not by itself detect every conflicting-source case; this local outcome is retained, not corrected by adapter code.

Binary failed because its model response was Markdown-fenced JSON. Upstream directly applies json.loads; adapter did not strip fences or rerun with an altered prompt. The failure and raw response remain available. The incomplete mixed-config run is not aggregated as a completed comparison.

## Artifacts

- `experiments/result/_external/ternary-native-direct-2026-10-02/`: claims.jsonl, requests.jsonl, tokens.json, native_report.json, meta.json, exit.json.
- `experiments/result/_external/ternary-native-ternary-2026-10-02/`: same completed artifacts.
- `experiments/result/_external/ternary-native-smoke-2026-10-02/`: failed mixed run, raw binary response retained, exit.completed=false.
- `experiments/tests/test_ternary_native_run.py`: exact prompt/response bridge and failure propagation tests.
- New direct-versus-Jev development artifacts: `experiments/result/_external/ternary-native-direct-vs-jev-dev-2026-10-02/`. direct commits both claims (FFR0.5/Coverage1), Jev commits supported claim and returns UNDECIDED on conflicting revenue claim (FFR0/Coverage0.5). This is only an n=2 mechanism check, not a superiority claim.
- The original four-type shared-candidate run (`ternary-native-shared-four-types-dev-2026-10-02/`) generated one common claim set, then stopped on a real HTTP read timeout; it remains a preserved failed attempt. The resume run reused those exact candidates with a 180s Jev timeout and completed all four question types (`ternary-native-jev-resume-four-types-dev-2026-10-02/`). The paired direct report reused the same claims (`ternary-native-direct-cached-four-types-dev-2026-10-02/`). `summarize_ternary_shared_dev.py` verifies ordered `(q_id, q_type, claim)` equality before writing the paired report.
- Paired development result: 5 claims, direct FFR 0.40/Coverage 1.00, Jev FFR 0.25/Coverage 0.80. Jev reduced one conflict claim to UNDECIDED but still committed one unanswerable claim; this is a diagnostic n=4-question result, not a superiority claim. Shared generation costs 1050 tokens; Jev decision usage adds 3520 tokens (total Jev 4570). This is an expected backend failure artifact, not a benchmark score.
- Combined native adapter tests: 10 passed; full Python suite: 431 passed.

## Official resource status

FTA v0.3.0's published six-model bundle is now present under `experiments/dataset/_candidates/fta-release/`, with zip SHA256 `9924904c89240f18bfff28a78aed82496f5cd8bfc46e5af73cba1c8e6f04a5ff`. It contains 3,600 responses and GPT-5.6-Luna model labels (1,800 confirmatory plus 1,800 extension), explicitly not human-validated. A read-only audit found 3,600 unique response IDs, all rows carrying model labels, six models × three conditions with 200 rows per cell, and zero non-null human-consensus labels; see `experiments/result/_external/fta-release-audit.json`. The publication bundle is merged `labeled_results.jsonl`, not directly the original analysis's separate raw/labels input. We did not invent status fields or reconstruct provider errors, so no new FTA `run_analysis` claim is made.

BFCL historical v3 source is now present under `experiments/dataset/_candidates/bfcl-official/v3-full/`, pinned to `c15b2a151662cac9839c96d7dfb1493b5329c975`, package version `2025.06.08`, archive SHA256 `1525d6a3f19495c51f8aeefb9fac8c3eb638509529cbae0ae83cd988a433f194`. The source compiles without installing dependencies. It is not yet an executable official adapter: the original model handlers, complete v3 data/possible answers and dependencies have not been installed or run. The current JevLoop BFCL function-name scorer remains non-official.

## Remaining work

The development runner now exports atomic proposals and genuine strict-HTTP Jev decisions. It is a claim-controller experiment, not a full seven-node JevLoop comparison.

A fixed-seed 20-question development subset (5 per type, 25 atomic claims; seed 20261002) now has a same-candidate paired report: `experiments/result/_external/ternary-native-20-dev-comparison.json`. Direct had 10 false-follow claims and Jev did not follow 8/10 of them, preserving all 15 valid claims in this subset. Original move metrics were direct FFR .40/Coverage 1.00 and Jev FFR .1176/Coverage .76. These are descriptive development observations: claimwise Wilson intervals are shown, no question-clustered inference or final-method claim is made. One selected question produced no atomic claim, and the upstream scorer correctly adds no placeholder move.

Manual review of the four `unanswerable` claims (`docs/MANUAL-REVIEW-unanswerable-misses.md`) corrected an earlier mischaracterisation: Jev's two remaining "false follows" are **true absence statements** ("the documents do not have a CTO listed"), and the entire 40-document corpus contains no CTO mention at all. Upstream's `is_absence_claim` does not match "does not have ... listed", so `gold_check` returns False instead of the author's intended None. Jev committed **zero fabricated values** on this subset. A secondary annotation excluding those two absence claims gives direct FFR .3478 (8/23) and Jev 0/15, but that is an annotation, not a replacement for the primary pinned-upstream numbers. Jev does retain a real, different limitation here: it labels a claim that reports *missing* data as FOLLOW, which upstream's quote-certificate rule could never do. On the other two questions Jev was correct (`OMIT` for a true-but-inessential CEO claim) where direct committed.

Next freeze a larger balanced development subset only after reviewing the unanswerable misses; do not tune a global threshold on this same subset and call it final evidence. Any phrasing or policy fix for absence statements must be validated on fresh questions. Then build isolated official FTA/BFCL runners and compare only original evaluation outputs. Keep proxy scores in separate debugging reports. New FTA model responses still require the original blinded six-label judge protocol; public labels for other models cannot label our new responses.
