# Verification: can every dataset report exit accuracy?

Question asked: does exit accuracy work on all datasets, single-step and multi-step alike?

**Answer: every dataset that runs can fill a value, but on most of them that value is
*numerically identical to accuracy*, so it carries no extra information. It only becomes a
distinct quantity on multi-step tasks.**

Verified against existing logs, one batch per benchmark.

## The measurement

For each benchmark: `stopped` = tasks with a non-empty answer event; exit accuracy =
(stopped ∧ native pass) / stopped; compared against plain accuracy.

| benchmark | n | delivered | accuracy | exit accuracy | differs? |
|---|---:|---:|---:|---:|---|
| gsm8k | 3 | 3 | 0.33 | 0.33 | **same** |
| strategyqa | 3 | 3 | 1.00 | 1.00 | **same** |
| fever | 3 | 3 | 0.67 | 0.67 | **same** |
| triviaqa | 3 | 3 | 0.67 | 0.67 | **same** |
| hotpotqa | 3 | 2 | 0.00 | 0.00 | **same** |
| sotuqa | 3 | 3 | 0.33 | 0.33 | **same** |
| sportsunderstanding | 3 | 3 | 0.33 | 0.33 | **same** |
| physicsquestions | 3 | 3 | 0.33 | 0.33 | **same** |
| toy | 3 | 3 | 1.00 | 1.00 | **same** |
| ternary-judge | 20 | 20 | 0.75 | 0.75 | **same** |
| fta | 100 | 100 | 0.53 | 0.53 | **same** |
| bullshitbench | 3 | 3 | 0.33 | 0.33 | **same** |
| bfcl-v3-simple | 100 | 100 | 0.98 | 0.98 | **same** |
| draco | 3 | 2 | 0.67 | 1.00 | differs (n=3, noise) |
| bfcl-v3-multiple | 16 | 13 | 0.38 | 0.46 | differs |
| **alfworld** | 10 | 5 | 0.20 | **0.40** | **differs 2×** |

## The metric is a factorisation, not a new metric

```
准确率 = 交付率 × 交付正确率
```

where 交付率 = delivered / n and 交付正确率 = (correct ∧ delivered) / delivered.

Verified exactly on the data: alfworld `react` gives 0.8 × 0.25 = 0.20, and the control arm
0.9 × 5/9 = 0.50 — both equal the reported accuracy.

This matters for the reviewer objection. The metric is not something invented for our
method; it is the existing accuracy **split into its two factors**. The reason it is worth
reporting separately is that the product hides which factor moved: an arm can lose accuracy
by never stopping, or by stopping wrongly, and those call for opposite fixes.

On one-shot tasks 交付率 ≈ 1, so the factorisation carries no information. There, report
accuracy and say so.

## What this means

**13 of 16 benchmarks give a number identical to accuracy.** The reason is structural, not
statistical: on a one-shot task the agent produces exactly one answer, so "the loop stopped"
and "the loop answered" are the same event. `ternary-judge` and `fta` are in this group even
though they are whole papers — they are single-shot, with no tools and no steps.

Exit accuracy is a **different cut from accuracy only where there is a process**: `alfworld`
(20% → 40%), `bfcl-v3-multiple` (38% → 46%), `terminal-bench` (no stopped run yet).

So the metric solves the reviewer objection — both arms fill it everywhere, on every
dataset — but it does **not** make the one-shot datasets informative about control. Nothing
will. On a task with one step there is no control decision to be right or wrong about.

## Coverage: which benchmarks have logs at all

| status | benchmarks |
|---|---|
| enough logs, metric computable | alfworld, bfcl-v3-simple, bfcl-v3-multiple, bfcl-v3-irrelevance, bfcl-v3-live-simple, bullshitbench, draco, fever, fta, gsm8k, hotpotqa, physicsquestions, sotuqa, sportsunderstanding, strategyqa, ternary-judge, toy, triviaqa |
| **not computable yet** | **terminal-bench** — its single logged run delivered nothing (empty answer), so stopped = 0 and the value is undefined, not zero |
| **not computable at all** | **tau2-bench** — raises `NeedsSimulator`; never runs |

`terminal-bench` is a budget/agent issue, not a structural one: answer events exist and the
native `pytest` truth exists. It needs runs where the agent actually reaches a finish.

## Two gaps this verification exposed

**1. "Stopped" was not a first-class field — now fixed.**

`Result` had no delivered/stopped column, so the value had to be reconstructed from
`answer` events. Reconstructing it **proved to be wrong**, not merely awkward: `Result` does
not carry `outcome.error`, so one `agent_error` row was rebuilt as `exhausted` — "it threw"
read as "it ran out of budget", and those two differ on whether the task belongs in the
denominator at all.

`Result.stop_reason` is now written by the runner with six values — `delivered`, `declined`,
`blocked`, `exhausted`, `error`, and (reserved) `parse_failure`. It is deliberately **not**
added to `REQUIRED_RESULT_FIELDS`, so historical batches still load; old rows read as the
empty string, meaning "not recorded", not "delivered nothing".

Implementing it surfaced a second, older conflation worth recording: `escalated=True` is set
in **three** different places in `baseline/common.py` — the gate blocked, the controller
asked for a human, and **the step budget ran out**. That file's own comment already noted
they "look identical in the books". `_stop_reason` therefore classifies structurally
(`len(steps) >= max_steps`) rather than trusting the flag, and pins each case in
`test_pipeline.py`. Correcting it changed the reading of the alfworld empty answers: they are
**budget exhaustion**, not the agent declining to answer.

**2. Empty is still ambiguous inside a run.** Empty final answers are common — alfworld
50/121, bullshitbench 100/205, fta 141/1015, bfcl-v3-multiple 333/2860, gsm8k 12/2889 — and
the reasons differ: exhaustion, parse failure, blocked, error. `stop_reason` now separates
these **at the outcome level**, but a parse failure inside the generator's loop is not yet
its own code path everywhere. Until it is, an arm with a weaker parser will show fewer
deliveries, which the paired 交付率 column exposes but does not explain.

## Consequence for the plan

- The main table keeps **退出正确率 + 交付率** as the two universally fillable columns.
- **The claim's weight has to sit on the multi-step datasets** — `alfworld`,
  `terminal-bench`, the BFCL multi-turn subsets — because those are the only ones where the
  metric says anything accuracy does not.
- The one-shot datasets stay in the table as regression and cost checks, honestly labelled
  as producing the same number as accuracy.
- Before any of it: put `stopped` and the termination reason into `Result`, so every
  downstream number has a stable definition.
