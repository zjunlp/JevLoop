# Grounding, step 1: a declared tool risk is looked up, not judged

First step of generalising "a verdict must be able to point at something"
(`docs/UNDECIDED-DIAGNOSIS.md`). Chosen first because it needs no new mechanism — it stops
asking the model to guess a constant that is already known.

## The hole

`gradeRisk`'s first gate is `score:risk >= 2 → ask_human`, and `DECISION.md` says it is a
**hard rule that does not accept being bypassed by a probability**. But its input has always
been a probability — the model's `risk` score. So "hard" rested entirely on evaluation order:
if the model scored the risk low, the rule never fired.

That file's own comment admits it:

> "把风险阈值从 2 提到 3 试图绕开第一条时，第二条 `needs_auth=0.95` 兜住了"

**What caught it was the other model judgement.** Both gates were probabilities; neither was
grounded.

And risk is a property of the tool. `delete_file` is destructive regardless of its arguments
or context. Asking a model to guess a known constant is the same shape as the finding that
"what the frame does not contain, the judge cannot produce".

## What changed

`Tool.base_risk: int | None = None` — declared by the benchmark, which owns the tool
definitions:

| value | meaning |
|---|---|
| `0` | read-only |
| `1` | reversible write |
| `2` | irreversible |
| `3` | destructive |
| **`None`** | **the tool cannot say** |

`_grade_risk` now branches:

- **declared** → the score is looked up, the model is **not** asked for `risk`, and one
  `needs_auth` question is asked instead;
- **`None`** → both questions are asked, exactly as before.

**`None` is deliberately not `0`.** `0` means "I declare this read-only"; `None` means "this
tool cannot say". General-purpose tools are the latter: Terminal-Bench's `exec` runs arbitrary
shell, ALFWorld's `act` runs any admissible command — whether a particular call is dangerous
depends on that call's content, not on the tool. Defaulting to `0` would silently classify
every general tool as read-only, which is the failure this whole line of work is trying to
prevent.

Declared so far — the genuinely read-only tools: ternary-judge `search` / `read_doc`,
gsm8k `calculate`, toy `lookup_capital`. Left undeclared: `exec`, `act`, BFCL's functions.

## Two effects

**1. The hard rule is now structurally hard.** For a tool that declares `2` or `3`, no
probability can pull the risk score down, because no model produces it. The bypass the
comment described is no longer available.

**2. Read-only tools stop being audited by accident.** Previously a model that scored
`lookup_capital` as risk 1 produced `auto_audit`. Now it is a table lookup of 0 and lands on
`auto`. This is a **behaviour change for existing benchmarks** and it will move their numbers;
the declaration is the deliberate part, not a side effect.

## Provenance is recorded

A looked-up risk still writes a decision row — `answer="(declared:0)"`, note naming the tool
and field — following the existing `answer="(generated)"` convention for "this step was not a
judgement". Without it the account would show only a `needs_auth` question and "who decided
the risk" would be unanswerable.

Verified end to end: a real `act-typed` run writes

```
(declared:0)  lookup_capital.base_risk=0（工具声明，未问模型）；read-only
```

and makes no model call for `risk`.

## Verification

442 Python tests pass; `check` clean. Four existing tests were repointed at a tool with
`base_risk=None`, because they test the model-judged path and that path now only exists for
undeclared tools — with a comment saying so. A new test pins both halves: declared ⇒ no
`risk` question and a `(declared:N)` row; undeclared ⇒ the question is asked.

## What remains

This was step 1 of three. Still to do:

| step | node | pointer | deterministic check |
|---|---|---|---|
| 2 | `canDeliver` | which evidence span supports the draft | span/overlap check — currently only prototyped in the ternary runner |
| 3 | `stepOk` / `isDone` / `needsTool` | which observation shows success / which requirement is unmet / which action has not happened | look it up in the cited artifact |

The generic shape for those is a `pointer` field on `Question`: a question, a closed set of
things that may be pointed at, and a **validator that runs outside the model**. A verdict
whose pointer fails validation is downgraded, not retried — retry is only for evidence
shortfalls.

## Artifacts

- `experiments/core/types.py` — `Tool.base_risk`
- `experiments/jloop/typed.py` — `_grade_risk` branch, `(declared:N)` recording
- declarations: `experiments/benchmark/{ternary_judge,gsm8k,toy}/`
- tests: `experiments/tests/test_typed_controller.py`
