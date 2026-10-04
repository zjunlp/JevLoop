# Grounding, step 2: the pointer becomes a first-class part of a question

Generalises what fixed the ternary case (`docs/UNDECIDED-DIAGNOSIS.md`) into a mechanism any
node can use, and applies it to the delivery gate.

## The mechanism

```python
@dataclass(frozen=True)
class Pointer:
    ask: str                              # "which recorded step contains every number…"
    options: tuple[str, ...]              # ★ a CLOSED set of things that may be pointed at
    validate: Callable[[str], bool]       # ★★ runs OUTSIDE the model
    none_option: str = ""                 # "I cannot point at anything"
```

`Question` gains `pointer: Pointer | None = None`.

Three properties, each deliberate:

**The validator runs outside the model.** If the model also judged the citation, we would
have added another opinion rather than a check. This is the whole point — a probability
cannot be shown wrong; a citation can.

**The options are a closed set.** That is what a decision model is good at: exhaustive
enumeration. "Which of these recorded steps?" is a shape it answers reliably; "quote the
supporting span" is not (Jev cannot emit free text at all).

**The caller builds the pointer with the evidence already bound into the closure.** So
`_ask_many` needs to know nothing about documents, steps or drafts — it only asks, validates,
and downgrades.

## The rule

**A verdict that has a pointer and asserts something must produce a citation that validates.
If it does not, the assertion does not hold** — recorded as `举证未通过` with what was cited.

Only the **affirmative** side is constrained: denying a claim needs no citation;
"I confirm this holds" does. And the failing verdict is **downgraded, not retried** — pointing
at nothing means the evidence is not there, and re-asking an identical request cannot
conjure it (`docs/RETRY-DOES-NOT-HELP.md`).

Cost: none in round trips. The judge answers multiple questions in one forward pass, so the
pointer rides along in the same request — that is why grounding is affordable here.

## Applied to `canDeliver`

`deliverable` now carries a pointer: **"which recorded step's tool output contains every
number stated in the answer?"**, with options being the recorded steps plus
`none_of_the_recorded_steps`, and a validator that checks every number in the draft appears
in the cited step's observation.

Numbers because they are the sharpest falsifiable content — a fabricated number is the most
common false claim we have measured — and because the thousands-separator lesson
(`1,284` splitting into `1` and `284`) is already learned and handled.

**Honest limit, stated in the code and here:** this check governs **numbers, not prose**. The
ALFWorld false completion — "placed the microwaved apple in the fridge" against the
observation "The fridge 1 is closed." — shares enough tokens that no lexical check catches
it. So the mechanism's strength varies with what the evidence contains, exactly like the
postcondition-tier table: documents with explicit values can be grounded sharply; free-form
prose cannot. **That tier must be reported alongside any number derived from it.**

When there is nothing to point at — no recorded steps with results, or a draft with no
numbers — the pointer is `None` and **no citation is demanded**. Demanding an impossible
citation would make the gate fire on every claim, and a permanently-true warning is one
nobody reads (`candidate_already_done` died exactly that way).

## A bug this found in its own wiring

The pointer question was added to the local `Request` — used for validation, rendering and
the digest — but the payload actually sent to the backend was built from the **original
argument list**:

```python
questions={q.node: _wire(q) for q in questions}      # ← the pointer never left the process
```

So the citation was never asked for, and the downgrade branch was unreachable. Fixed to
iterate `req.all_questions`. This is the §8.15 shape again: **a requirement written in one
place that does not take effect in another.** The integration test now asserts the pointer id
actually appears on the wire, not merely that `_evidence_pointer` returns something.

## Verification

446 Python tests pass; `check` and `typecheck` clean. New tests cover: an affirmative verdict
with a failed pointer is downgraded with a recorded reason; a valid pointer leaves the verdict
alone; no pointer means no extra question; the number-grounding validator accepts real numbers,
rejects fabricated ones and rejects unknown steps; and the end-to-end path sends
`deliverable::pointer` when the draft has numbers and omits it when it does not.

**Not yet exercised on a real tool-using benchmark.** The FTA run used to check this makes
zero tool calls (single-shot tasks with the failure pre-staged in the prompt), so there is
nothing to point at and the pointer is correctly `None`. ALFWorld and Terminal-Bench are the
datasets that would exercise it, and the typed arm is not operational on ALFWorld
(`docs/ALFWORLD-TYPED-ROUND2.md`). That gap is real and should be closed before any number
from this mechanism is quoted.

## What remains

| node | pointer | deterministic check |
|---|---|---|
| `stepOk` | which observation shows the step succeeded | look for the claimed effect in it |
| `isDone` | which requirement is unmet | check it against the task |
| `needsTool` | which action has not happened | look for it in the history |

All three take the same shape: a question, a closed set of artifacts, and a validator outside
the model.

## Artifacts

- `experiments/core/frame.py` — `Pointer`, `Question.pointer`
- `experiments/jloop/typed.py` — asking, validating, downgrading, recording;
  `_evidence_pointer`, `_numbers_in`
- tests: `experiments/tests/test_typed_controller.py` (55 in that file)
