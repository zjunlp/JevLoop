# Native evaluation and baseline status

## Non-negotiable boundary

Benchmark task grades come from the pinned upstream evaluation protocol. Our observation layer records behavior; it must not replace labels, denominators, extraction rules or official aggregation. Legacy proxy scores remain debugging artifacts, not official benchmark scores.

## Completed first adapter: Ternary claim-level evaluation

`experiments/scripts/ternary_native_eval.py` loads byte-verified upstream sources and data from `mvp-ternary-judge@1f1e19a7e466cb9bb6b7e8993a1a75ea3f29fb42`.

- Calls unchanged `pipeline.gold_check`, `run_experiment.metrics`, and `by_type`.
- Keeps original atomic claims and real FOLLOW / OMIT / NULL / UNDECIDED decisions.
- Preserves True / False / None, exact-span boundaries, ambiguity checks and absence handling.
- Coverage is upstream move-level non-UNDECIDED fraction, including OMIT. CostPerCorrectAnswer is tokens per valid FOLLOW claim despite its name. Neither definition is corrected by us.
- Requires measured token totals for each configuration; no missing-cost-to-zero conversion.
- Rejects old final-answer prose logs instead of inventing atomic claims or verdicts.
- Six tests pass, including independent differential evaluation of all 636 archived moves and source-tampering rejection. Token totals in that differential test are explicit test fixtures, not reported experiment costs.
- Upstream module import creates a results directory only inside an isolated temporary directory; no paid clients or original generation/judging are invoked.

This is **an original-scorer adapter**, not a complete upstream-pipeline reproduction or a completed JevLoop model comparison. The live method runner still needs to produce original-format atomic claims and actual decisions. Original generation/retrieval policies must be retained when claiming full reproduction; scorer output must never be fed into a tested controller.

Example:

```sh
python3 -m experiments.scripts.ternary_native_eval native_claim_moves.jsonl \
  --tokens measured_config_tokens.json --output native_report.json
```

## Remaining benchmark work

| Benchmark | Current gap | Strict next step |
|---|---|---|
| FTA | Current detector is a custom proxy; README says published model-judge estimates, not 3,600 human labels. Public response/label result bundle is absent locally. | Obtain/check pinned release assets; use original blinded six-label judge, exact evidence-span validation, original analysis and clustered intervals. Preserve judge identity and distinguish model-only estimates from human validation. |
| BFCL v3 selected categories | Historical official evaluator pin is now available at `experiments/dataset/_candidates/bfcl-official/v3-full/` (commit `c15b2a151662cac9839c96d7dfb1493b5329c975`, package version `2025.06.08`). It is statically compiled but dependencies/data/model handlers are not installed or run. Current loader remains function-name proxy. | Build an isolated official runner using the full v3 source and preserve original schemas, dialogue, complete acceptable-argument gold and raw response. Invoke official grading/aggregation. Missing live-simple data remains missing, not zero score. |
| BullshitBench / DRACO | Local regex is not original semantic panel/content rubric. | Reproduce upstream judging and reporting; annotate current detector output as proxy only. |
| ALFWorld | Native won replay exists, but local custom exemplars were tuned on viewed examples; additional completion-claim audit is absent. | Freeze upstream evaluation conditions, remove or separately declare custom prompts; observe final claims and actual recovery actions without changing native won. Low won alone is not evidence that overclaim cannot be measured. |
| Terminal-Bench | Container/test implementation exists; scarce runs include infrastructure failures. | Per-task environment preflight; preserve pinned tests and separate task failure, agent error and environment unavailability. Perturbed tools are separate robustness conditions, not original leaderboard conditions. |
| tau2 | Enumerates tasks only; tools/scoring raise NeedsSimulator. | Use pinned official simulator, domain environment and DB/communication/assertion evaluators. Do not put hidden user scenarios in agent input. |
| BeforeDone / shobench | Candidate sources inspected, no JevLoop runnable adaptation. | Keep as related artifacts until exact upstream runtimes and evaluation inputs are wired. |

## Baselines: two distinct comparisons

### Controlled loop ablation

Hold generator, task input, tools, budgets and native evaluator fixed:

1. Standard ReAct control.
2. Terminal validation with text-only recovery.
3. Terminal validation with real return to tool actions.
4. Full explicit JevLoop control, with node-specific ablations rather than assuming seven nodes are optimal.

A terminal-only controller **can in principle resume its ordinary generator-driven action loop**; lacking independent action-selection judges does not inherently prevent redirect. Our current terminal controller implementation degrades text instead, so its existing runs cannot establish redirect effectiveness. A redirect result requires recorded rejected-stop, later tool execution, new observation and native end-state improvement.

Use real Jev as the initial fixed decision backend. Mock belongs only in plumbing tests. HTTP fallback must not silently turn an API evaluation into a mock evaluation; actual provider/fallback evidence must be audited, and a formal strict API mode still needs to be implemented.

### External harness comparison

Start with OpenHands (mature) and pi (minimal), where the chosen benchmark supports them. Pin harness versions and use the same generator when supported. Keep benchmark evaluator and task conditions identical; disclose unavoidable tool/prompt/context differences. Claude Code/Codex with different backbones are full-system references, not clean harness-effect evidence.

CLM/Jev/prompted-LLM comparisons are decision-backend experiments, a separate axis from harness comparison. Do not simultaneously change backend, evidence input and recovery strategy then attribute the result to one factor.

## Observations, not replacement grades

Collect native raw output, initial draft, verdict/reason, termination reason, tool calls/observations, final output, token counts and timing. Derived false-completion labels need independently validated claim annotation. Do not score intermediate states with a final-only evaluator unless upstream supports that use. If intermediate draft grading is unavailable, keep it unavailable rather than coercing it to False.

## Verification scope

This milestone completes one byte-preserving native scorer adapter and its differential tests, plus a documented gap/baseline plan. It does **not** claim all registered datasets are officially adapted, previously reported proxy percentages are validated, or live control/recovery superiority is established. Existing uncommitted changes remain uncommitted; no historical results were overwritten.
