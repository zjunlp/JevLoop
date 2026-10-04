# The universal metric: exit accuracy

## The reviewer problem this solves

An earlier proposal was "verdict replay consistency": a pinned decision model returns the
same verdict for the same request, and a generative loop cannot report an equivalent
number. That metric is **not usable**, for exactly the reason a reviewer would give: it is
fillable only by our architecture, so it reads as a metric designed to favour the method.

A traditional loop *can* be made deterministic (temperature 0), so the contrast would also
collapse under a fair decoding setting.

We need a metric where **both arms can always fill a value**, and where the mechanism we
built should move that value.

## The metric

> **退出正确率 (exit accuracy) = 停下且任务真做成 / 所有停下的题**

`停下` is a harness-level event, not a claim. Any loop has it: a traditional ReAct loop
stops the moment it emits a final answer, exactly as our controller stops when a
termination decision is accepted. No completion-claim detector is needed — which also
removes the weakest component in the whole measurement chain.

Report it with its denominator, and pair it with one guard column:

| metric | definition | direction |
|---|---|---|
| **退出正确率** | stopped ∧ native pass / stopped | ↑ |
| **交付率** | stopped / all tasks | ↑ |

The pair is necessary. **交付率 alone** can be won by never stopping; **退出正确率 alone**
can be won by stopping only on the trivially easy tasks and burning the budget on
everything else. Together they cannot be gamed: an arm that never stops has no exit
decisions at all, and its 交付率 exposes it.

## Why it is not "invented for our method"

It is the ordinary error rate of a loop's exit decision. Any agent loop terminates somehow;
saying how often that termination was correct is a plain question about the loop, not a
bespoke construct. The traditional loop is free to lower it — better prompting,
self-consistency, its own stop-verifier. That is precisely the comparison we want.

## Measured discrimination

ALFWorld, native `won`, from two existing runs (unpaired, dirty tree, n=10 — feasibility
evidence, not a result):

| arm | n | stopped | **退出正确率** | 交付率 |
|---|---:|---:|---:|---:|
| `react` (no gate) | 10 | 8 | **2/8 = 25%** | 80% |
| `react-termination` | 10 | 9 | **5/9 = 56%** | 90% |

The metric separates the arms on the dimension the architecture targets, and both arms
report both numbers.

## Honest limit: it degenerates on single-step tasks

On a one-step task, "stopping" *is* "answering", so exit accuracy equals plain accuracy.
Verified on the sweep logs:

| dataset | exit accuracy | error rate | agree? |
|---|---:|---:|---|
| gsm8k | 67% | 2/3 wrong | ✓ |
| strategyqa | 100% | 0/3 wrong | ✓ |
| fever | 67% | 1/3 wrong | ✓ |
| triviaqa | 67% | 1/3 wrong | ✓ |
| bfcl-v3-simple | 100% | 0/2 wrong | ✓ |

This is a **feature, not a failure**: the number stays well defined and fillable by both
arms on every dataset, and on single-step tasks it is honestly identical to accuracy. It is
also a reminder that those datasets cannot say anything about control — there, control has
nothing to control.

## Where it stands relative to the other metrics

| metric | both arms fill? | every dataset? | needs claim detector? | isolates lying? |
|---|---|---|---|---|
| 原生成功 | yes | yes | no | no |
| 成本 | yes | yes | no | no |
| **退出正确率** | **yes** | **yes** (degenerates on 1-step) | **no** | **no** |
| 交付率 | yes | yes | no | no |
| 假完成率 | yes | no | **yes** | yes |
| 误拒率 | yes | no | **yes** | yes |
| 裁决重放一致率 | nominally | yes | no | no — **unusable, architecture-specific** |

Exit accuracy does **not** isolate lying. It measures whether the loop's exit decision was
right, which is broader: it counts an honest give-up as an incorrect exit just as it counts
a false success. To separate those you still need the claim detector, and that separation
belongs in the appendix, not the main table.

## Revised main table

| dataset | arm | n | 原生成功 | **退出正确率** | 交付率 | tokens/题 |
|---|---|--:|--:|--:|--:|--:|

Four columns, every one fillable by every arm on every dataset. No claim detector, no
architecture-specific metric, no blank cells.

The appendix then carries the finer decomposition where the structure exists:

- 退出正确率 broken into **假完成 / 诚实放弃 / 无声明**
- 误拒
- 闸门账
- 恢复链

## What still has to be true for the paper

Exit accuracy being higher for our arm is a **raw** comparison. The paper claim needs it
paired (same tasks, same seed, same budget, McNemar) and alongside cost. And it must hold
on `alfworld` and `terminal-bench`, the two datasets where stopping is a real decision
rather than a synonym for answering.
