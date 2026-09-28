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
ask
options
policy
frame:
  + <field> <bound> [<projection>] —— <reason>
  - <field> —— <reason>
generator
```

`when:` has two parts: the first token is the position identifier; the text after
`——` explains the purpose for humans and audit tools. A host should expose both
parts structurally rather than making consumers reparse prose.

### Host adapter

Each host must register:

1. **State cells**: the names and types available to frame declarations;
2. **Projection providers**: implementations for names such as `earlierMaybe`;
3. **Dynamic candidate providers**: implementations for declarations such as
   `toolsFor(ctx)` or `unreadFiles(ctx)`;
4. **Position handlers**: the actions that each position can execute;
5. **Action handlers**: the behavior of `use_tool`, `call`, `ask_human`,
   `finish`, `deliver`, and any host-specific actions;
6. **Evidence providers**: the facts used by completion and delivery checks;
7. **Event sink**: a record containing the decision id, position, frame digest,
   request digest, answer, action, policy, and evidence.

The host adapter is the only place where these names acquire runtime behavior.
A portable file must not assume JevLoop's `AgentCtx`, local filesystem tools, or
JevLoop's loop branches.

## 3. Adapter conformance checklist

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

## 4. Extending beyond the reference loop

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

## 5. Compatibility boundary

The current JevLoop document contains some reference-host details:

- `FRAME_PROJECTIONS` names are registered by JevLoop code;
- `dynamic:` is currently a provider name plus prose, not a portable callable;
- policy predicates use JevLoop's closed vocabulary;
- action names are checked against JevLoop's action set;
- positions are checked against JevLoop's loop positions.

These are intentional adapter seams, not yet an industry-wide ABI. Before
claiming broad interoperability, a future schema version should publish:

```text
schemaVersion
structured position and purpose
projection capability declarations
dynamic provider input/output shapes
action semantics
evidence schema
event and replay schema
```

Until then, the honest claim is:

> `DECISION.md` has a portable declarative core and a JevLoop reference adapter.

It is not yet correct to claim that any Agent runtime can execute the file
without an adapter.

## 5. Reference implementation

The reference adapter currently consists of:

```text
src/decisiondoc.ts       parse the document
src/decision-compile.ts  compile questions and policies
src/decisions.ts         map frames and JevLoop nodes
scripts/conformance.ts   validate the reference contract
examples/external-host.ts  minimal non-loop host
```

The external host example deliberately does not import `agent.ts`, `decisions.ts`,
or `AgentCtx`. It proves the structural boundary, while the adapter checklist
records the work still required for full execution interoperability.
