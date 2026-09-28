# DECISION.md Contract

> Draft: portable-core boundary for external Agent hosts.
>
> `DECISION.md` is a declarative decision contract. JevLoop is the reference
> implementation, not the only intended consumer.

## 1. What a host must consume

A host reads a document as a set of decision blocks. The portable core is:

```text
block id
kind
position
questions
options and criteria
policy rules
frame fields and budgets
explicit exclusions and reasons
generator instructions
```

A host must reject a document when:

- a block, question, option, position, action, or policy predicate is malformed;
- a frame field has no bound or reason;
- an excluded field has no written reason;
- a frame field or exclusion cannot be mapped to host state;
- a policy action has no registered host handler;
- a position does not handle the policy action.

A host must not silently ignore an unknown declaration.

## 2. Portable core versus host adapter

The file describes **what** a decision asks and **which contract** governs it.
The host supplies the runtime-specific meanings.

### Portable core

These concepts belong in the file format:

```text
id
kind: choice | noul | score | mixed | rule
when: <position> —— <human-readable purpose>
dynamic: <provider>(ctx) → <output> —— <reason>     (optional)
ask
options
policy
frame:
  + <field> <bound> [<projection>] —— <reason>
  - <field> —— <reason>
generator
```

`when:` has two parts, and the parser splits them rather than leaving consumers
to reparse prose: the first token is the position identifier, and the text after
`——` is the purpose for humans and audit tools. Both are on the parsed block as
`position` and `purpose`. A position is **required** — a block without one is
refused, because an action nothing dispatches is worse than a parse error.

`dynamic:` also declares three things, not one:

```text
provider   the name the host must have registered
output     what shape it returns — currently always `candidates`
why        why the candidates must be rebuilt every step
```

The provider must be written `<name>(ctx)`: a dynamic provider exists to read the
current state, so a declaration that omits the context is not something a host can
implement correctly. `output` is a closed vocabulary with exactly one member —
adding a second is a deliberate change that also needs a host handling branch.

`when:`/`dynamic:` syntax lives in `src/decision-syntax.ts`; validation against
`POSITIONS` and the policy lives in `src/decisiondoc.ts`.

### Host adapter

Each host must register:

1. **State cells**: the names and types available to frame declarations;
2. **Projection providers**: implementations for names such as `earlierMaybe`;
3. **Dynamic candidate providers**: implementations for the providers named by
   `dynamic:` declarations, keyed by provider name and matching the declared
   output shape;
4. **Position handlers**: the actions that each position can execute;
5. **Action handlers**: the behavior of `use_tool`, `call`, `ask_human`,
   `finish`, `deliver`, and any host-specific actions;
6. **Evidence providers**: the facts used by completion and delivery checks;
7. **Event sink**: a record containing the decision id, position, frame digest,
   request digest, answer, action, policy, and evidence.

The host adapter is the only place where these names acquire runtime behavior.
A portable file must not assume JevLoop's `AgentCtx`, local filesystem tools, or
JevLoop's loop branches.

### Provenance: which frame values came from a tool

A frame field is only as trustworthy as the cell it reads. Cells carrying bytes
returned by a tool call — a file body, a directory listing, a step record — are
**untrusted input**, the same way the tool name the model returns is. A decision
model does not follow instructions, so the classic injection attack does not
apply the way it does to an LLM; what applies is **displacement**, untrusted text
moving a probability across a threshold.

So a conforming adapter should:

- derive the trust of each frame field from its source cell, **not** from a
  per-field flag anyone can forget to set;
- mark untrusted values so the decision model can discount them by provenance;
- keep the marker inside the frame digest, so a replay can tell whether a frame
  was marked at all;
- record which fields were untrusted on the frame artifact, so a trace can be
  audited after the fact;
- **not** silently rewrite the bytes: stripping imperative-looking sentences is
  not obviously correct for a classifier, since a log that genuinely says "the
  test failed" is both evidence and an imperative.

The reference implementation wraps untrusted *string* channels. List-valued
channels are unlabelled and that is a known gap, recorded in `TODO.md` §7 with
the reason: putting a label inside a value breaks consumers that read it as data.

## 3. Action semantics

`DECISION.md` declares **which actions a position may produce** (`POSITIONS`).
That is only half of what a host needs: an action name says nothing about what
happens *after* the decision. Those meanings used to live only in JevLoop's loop,
which is precisely what a portable contract is supposed to remove — a second
implementer would have to read our control flow and copy it.

So each action declares its meaning. A host can write one `switch` over `next`
and be done:

| action | `next` | ends the loop | more model calls | needs evidence | retries |
|---|---|---|---|---|---|
| `use_tool` | `pick_tool` | no | yes | no | 0 |
| `answer` | `generate` | **yes** | yes | no | 0 |
| `call` | `run_tool` | no | yes | no | 0 |
| `use` | `run_tool` | no | yes | no | 0 |
| `auto` | `run_tool` | no | yes | no | 0 |
| `auto_audit` | `run_tool` | no | yes | no | 0 |
| `ask_human` | `human` | on refusal | yes | no | 0 |
| `continue` | `next_step` | no | yes | no | 0 |
| `stop` | `generate` | **yes** | yes | no | 0 |
| `finish` | `generate` | **yes** | yes | no | 0 |
| `keep_going` | `next_step` | no | yes | no | 0 |
| `deliver` | `end` | yes | **no** | **yes** | 0 |
| `revise` | `regenerate` | yes | yes | **yes** | **1** |
| `escalate` | `end` | **yes** | yes | no | 0 |

Three things this table exists to say out loud, because guessing them wrong is
easy:

- **"Ends the loop" is not "the run is over."** `answer`, `stop`, `finish` and
  `escalate` all stop the *tool loop*, and the run then **generates a final answer
  anyway** — including after `stop`, where that answer is an honest report of
  failure. Only `deliver` ends the run. Collapsing these into one `terminal` flag
  would produce a host that silently drops the last generation.
- **Only the delivery gate needs evidence.** `deliver` and `revise` are the two
  actions whose correctness depends on checking a draft against evidence; that is
  why the gate exists.
- **Only `revise` retries, and exactly once.** Retrying costs money, so it is
  declared rather than implied.

The table is a **description, not an executor**: JevLoop's loop still implements
these semantics with branches, because what an action means *at a position* is
known only to that position's code. So the table is checked **against the
runtime** — `tests/action-semantics.test.ts` drives the loop once per action and
asserts the observed behaviour matches. A semantics table nobody checks is just
another declaration that can lie.

## 4. Projection declarations

A `frame:` field can name a projection (`+ task 400 earlierMaybe`). A Markdown
file cannot hold a function, so the host supplies the implementation — but until
this declaration existed the host only got the **name**. "How does `lastOrNone`
differ from `resultMaybe`?" was answerable only by reading JevLoop's code, and the
difference *is part of the criterion*: one sends `（还没有做过任何动作）` when there
is no result, the other sends an empty string, and a classifier cannot tell "no
result yet" from "the result was empty" unless the projection says so.

Each projection therefore declares what it reads, what shape it returns, and what
it promises on a missing value:

| projection | reads | returns | promise when the value is missing |
|---|---|---|---|
| `earlierMaybe` | `earlier` | string | empty string |
| `filesMaybe` | `files` | list | empty list |
| `readMaybe` | `readFiles` | list | empty list |
| `resultMaybe` | `lastResult` | string | empty string |
| `draftMaybe` | `draft` | string | empty string |
| `toolOrEmpty` | `lastTool` | string | empty string |
| `lastOrNone` | `lastResult` | string | **`（还没有做过任何动作）` — not empty** |
| `toolOrUnknown` | `lastTool` | string | **`unknown` — not empty** |
| `describeDone` | `history` | string | a one-line summary, never a raw array |
| `lastInput` | `history` | string | — |
| `readCount` | `readFiles` | count | 0 |
| `recentSteps` | `history` | list | empty list |
| `writeEvidence` | `history` | string | — |
| `localToolRisk` | `lastTool` | count | **omitted entirely** (`absent`), never 0 |

Two of those rows are the reason the table is worth publishing:

- **The non-empty fallbacks are criteria, not cosmetics.** `lastOrNone` and
  `toolOrUnknown` exist precisely because an empty string would let a judgement
  confuse *absent* with *empty*, or *unknown tool* with *no tool*.
- **`localToolRisk` returns no field at all for an unrecognised tool.** `0` means
  "read-only", so it cannot stand in for "unknown" — the field is dropped and
  recorded in `Frame.absent`.

The name list and each `from` have **one source of truth**
(`src/frame-projections.ts`); JevLoop's implementation supplies only function
bodies, and the key type makes a missing or extra implementation a compile error.
`tests/frame-projections.test.ts` additionally checks that every declared `from` is
a real state cell, that every declared `returns` matches what the implementation
actually returns, that no projection is declared without being used, and that the
external host fixture's capability list matches the declaration exactly.

## 5. Adapter conformance checklist

An adapter is conforming only if it can demonstrate all of the following:

- It parses the same file without dropping blocks or fields;
- It reports every parse and compile problem with a source location;
- It maps every `+` field to exactly one state cell or projection;
- It records every `-` field and its reason;
- It rejects an unknown projection instead of treating it as raw state;
- It rejects an unhandled action instead of logging and continuing;
- It evaluates policy rules in document order with an explicit fallback;
- It can replay one decision from the recorded frame and request;
- It emits a conformance report for both a valid file and deliberately invalid files.

The minimum integration test should run one host loop through:

```text
needs_tool → pick_tool → step_ok → is_done
```

The test does not need a language model. A deterministic mock decision provider
is sufficient; the purpose is to prove that the host consumes the contract and
executes its actions.

## 6. Extending beyond the reference loop

The reference JevLoop loop currently has seven named decision blocks and six
closed positions. That is a property of the reference host, not a limit that a
portable Decision contract should impose.

A different host may declare ten, thirty, or more decision nodes. For example,
a coding host might add:

```text
classify_issue
select_repository
identify_owner
choose_search_strategy
check_dependency_change
plan_patch
select_test_scope
interpret_test_failure
check_scope
request_review
prepare_candidate_patch
```

This is supported only if the host supplies the corresponding adapter pieces.
Adding a block to the file does not automatically add behavior to a runtime.

### 4.1 Node declaration versus loop graph

A decision contract declares a node's local contract:

```text
node id
position or host phase
questions and options
frame and exclusions
policy and actions
completion/evidence requirements
```

The host owns the control-flow graph:

```text
current phase + state + action → next phase
```

This separation is intentional. A portable file should not assume that every
Agent loop is a linear sequence such as:

```text
needs_tool → pick_tool → step_ok → is_done
```

A host may run a graph, a state machine, a planner/executor loop, or several
nested loops. It can invoke the same decision node more than once with a new
state version, provided the event records identify the invocation and the
resulting transition.

### 4.2 Adding a node

To add a node, an adapter must:

1. declare a unique node id;
2. assign it to an existing portable position or a namespaced host phase;
3. register every projection used by its frame;
4. register its dynamic candidates, if any;
5. register every policy action and the action's next-state behavior;
6. define the states in which the node may be invoked;
7. define the evidence required for its outputs;
8. add a valid fixture and at least one negative fixture;
9. record the node in the adapter capability report.

A node must not be considered supported merely because the parser accepts its
id. An uninvoked node, an unhandled action, or a transition with no consumer is
an adapter conformance failure.

### 4.3 Three extension levels

Hosts should report which level they implement:

```text
Level 0 — static declarations
  Parse and inspect any number of blocks.

Level 1 — local decision execution
  Execute a block with host state, projections, questions, policy and actions.

Level 2 — graph execution
  Define and execute transitions between many nodes, including loops,
  branches, retries, escalation and terminal states.
```

JevLoop's current reference loop is a Level 2 host for its own seven-node graph.
It is not yet a generic graph runtime for arbitrary host-defined graphs.

### 4.4 Namespaces and host extensions

The portable core should keep a small, stable vocabulary. Host-specific nodes,
positions and actions should use an explicit namespace rather than silently
reusing a core name:

```text
position: host:repository-selection
action: host:request_review
projection: host:dependency-summary
```

The adapter must either implement a namespaced extension or reject it with a
source-located error. It must never reinterpret an unknown extension as a
portable action.

## 7. Compatibility boundary

The current JevLoop document contains some reference-host details:

- `FRAME_PROJECTIONS` names are registered by JevLoop code;
- `dynamic:` is currently a provider name plus prose, not a portable callable;
- policy predicates use JevLoop's closed vocabulary;
- action names are checked against JevLoop's action set;
- positions are checked against JevLoop's loop positions.

These are intentional adapter seams, not yet an industry-wide ABI. A future
schema version should still publish:

```text
dynamic provider input declarations (which state cells it reads)
evidence schema
event and replay schema
```

Two items have left this list. **Action semantics** (§3) are declared, exported
through `jevloop/contract`, and checked against the runtime, so a host no longer
has to read JevLoop's loop to learn what `stop` or `deliver` does. **Projection
declarations** (§4) now say what each of the fourteen names reads, returns, and
promises on a missing value, with one source of truth for the names.

`DECISION.md` now declares its schema version, and a missing or unrecognised one
is refused — by `schemaProblems()`, surfaced as the `schema` layer of
`npm run conformance` and of `jevloop spec`. The version is deliberately a
separate layer rather than part of `problems`, because the two mean different
things: `problems` says *this file is malformed*; the schema layer says *I cannot
read the semantics this file claims*. A file written for a future version is the
second case, not the first.

Positions, dynamic providers, actions and projections are now structured rather
than re-parsed or inferred by each consumer. What is still missing: a `dynamic:`
declaration says only that the provider takes the context, not which state cells
it reads.

Until the remaining items land, the honest claim is:

> `DECISION.md` has a portable declarative core, a declared schema version, and a
> JevLoop reference adapter.

It is not yet correct to claim that any Agent runtime can execute the file
without an adapter.

## 8. Consuming the contract without the runtime

A host that wants only the checker must not have to install — or satisfy —
JevLoop's own runtime. Two entry points:

```ts
import { … } from 'jevloop'           // the package root: the whole reference runtime
import { … } from 'jevloop/contract'  // parse, compile, policy, adapter checks only
```

`jevloop/contract` deliberately excludes `decisions.ts`, `agent.ts` and
`frame.ts`. That exclusion is enforced, not documented: `contract.ts` is
registered at layer L3 in `scripts/check.ts`, and a dependency may only point at
a lower-numbered layer, so importing the runtime from it fails `npm run check`.

Verified end-to-end from a packed tarball installed into an empty project:

```text
jevloop/contract   works with DECISION.md removed from the package
jevloop            fails without it — the module-load assertion needs our contract
```

That is the difference between "portable" and "install us first".

## 9. Reference implementation

The reference adapter currently consists of:

```text
src/decisiondoc.ts         parse the document and check its schema
src/decision-syntax.ts     the `when:` / `dynamic:` grammar, in one place
src/decision-compile.ts    compile questions and policies
src/adapter.ts             check a host's declared capabilities
src/contract.ts            the portable entry point (jevloop/contract)
src/decisions.ts           map frames and JevLoop nodes
scripts/conformance.ts     validate the reference contract
scripts/adapter-report.ts  check the published capability report against the code
examples/external-host.ts  minimal non-loop host with its own graph
```

The external host example consumes `src/contract.ts` and nothing else. It proves
the structural boundary, while the adapter checklist records the work still
required for full execution interoperability.

Its published capability report (`examples/external-host.capabilities.json`) is
checked against the code by `npm run adapter-report`, and
`tests/adapter-report.test.ts` runs the same check inside `npm test` — so an
incomplete or stale report fails the suite rather than being discovered later.
State-cell names are deliberately not listed in the report, because they are
internal to the host.
