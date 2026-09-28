# Skill: Adapt an Agent Host to `DECISION.md`

Use this skill when adding `DECISION.md` support to an existing Agent runtime.

## Goal

Make the host consume a decision contract without silently dropping a field,
policy, action, or evidence requirement.

The skill produces two things:

1. a host adapter that maps the portable contract to the runtime;
2. a conformance test that proves the adapter rejects incomplete mappings.

The skill is not a runtime substitute and does not make an arbitrary host safe by
itself. Hard permissions, filesystem isolation, and tool execution remain owned
by the host.

## Step 1: Inventory the host loop and graph

Do not assume that the host follows the reference sequence
`needs_tool → pick_tool → step_ok → is_done`. Record the host's actual graph:

```text
node or phase id
entry conditions
state cells read
possible actions
next node for each action
retry and escalation edges
terminal states
```

The host may have dozens of nodes, nested loops, branches, retries, or
parallel subloops. Keep the graph in the host adapter; the Decision contract
specifies each node's local judgement, not a universal control-flow shape.

Record the exact locations where the host:

```text
starts a step
chooses whether to use a tool
chooses a tool
chooses tool input
checks authorization
receives tool output
checks step success
checks task completion
generates an answer
releases an answer
```

Map each location to one `DECISION.md` position. If a position has no host
branch for an action, stop and add the branch before claiming support.

## Step 2: Define host state cells

Create a closed registry of state cells. For every cell, document:

```text
name
type
source
whether it is trusted
whether it may be projected into each decision
maximum size
```

Do not treat an unknown field as an empty string. A missing mapping must be an
adapter error, because an empty value can change a policy decision.

## Step 3: Register projections

For every `frame` field with a projection name:

1. register exactly one projection provider;
2. specify its input state cells;
3. specify its output type;
4. apply the declared bound;
5. record unfilled, absent, and truncated values;
6. include the projection name and output in the frame audit record.

Reject unknown projection names. Never fall back to raw state silently.

## Step 4: Register dynamic candidates

For every `dynamic:` declaration, define a host provider with an explicit
input/output shape. The provider must return the actual candidate set used by
the decision request, not only a description of the candidate set.

The declaration is already parsed — read the fields, do not re-split the line:

```text
block.dynamic.provider   the name to look up in your registry
block.dynamic.output     the shape it must return (`candidates` today)
block.dynamic.why        why it must be rebuilt every step
```

Provider names come from the host's own closed table. A name the host has not
registered is an adapter failure, not a reason to fall back to the defaults
listed in the file.

At minimum record:

```text
provider name
candidate ids
candidate descriptions
state version
```

A fixed default list must not replace a dynamic candidate provider.

## Step 5: Compile and execute policy

Compile questions and policy before running the host. Reject:

```text
unknown predicate
unknown action
missing fallback
fallback before the final rule
position/action mismatch
```

Evaluate rules in document order. Record the selected rule, action, reason and
all policy warnings. An unhandled action is an adapter failure, not an
instruction to continue.

## Step 6: Add evidence and replay

At every decision, record:

```text
decision id
position
frame digest
request digest
frame fields
explicit exclusions and reasons
questions and options
answers
selected action
selected policy rule
provider/model
latency and cost
```

A host is not conforming until it can replay one recorded decision using the
same contract version and report whether the frame and request digests match.

The reference format is `decision-record/v1` (see §5 of
[`DECISION-CONTRACT.md`](DECISION-CONTRACT.md)) and the reference verifier is
`verifyRecord()`, exported from `jevloop/contract`. Two of its fields exist only
because of the merged case — `sentFrameDigest` and `sentQuestions` — and a record
that omits them is `unverifiable`, not `verified`. Note also what replay does not
establish: it is not reproducibility and it is not correctness.

## Step 7: Write conformance tests

Start with these fixtures:

```text
valid contract
unknown projection
missing exclusion reason
unhandled action
position/action mismatch
missing dynamic provider
missing state cell
truncated evidence
```

The valid fixture must execute the host's declared graph. The small reference
fixture uses:

```text
needs_tool → pick_tool → step_ok → is_done
```

A host with additional nodes must add a graph fixture that visits every
supported node and at least one branch, retry, escalation, and terminal edge.
The negative fixtures must fail loudly before an unsafe action is dispatched.

## Step 8: Report the integration boundary

Publish an adapter report with:

```text
supported schema version
supported positions
supported actions
registered projections
registered dynamic providers
unsupported fields
known evidence limitations
replay status
```

Use this wording until the host passes the full checklist:

> This runtime has a `DECISION.md` adapter for the listed positions and actions.
> It does not claim universal Decision Contract compatibility.

## What this skill does not permit

Do not claim that the adapter:

- prevents sandbox escape;
- validates external truth without an external verifier;
- makes every Agent reliable;
- replaces Workflow;
- supports a field merely because the parser accepts its name.
