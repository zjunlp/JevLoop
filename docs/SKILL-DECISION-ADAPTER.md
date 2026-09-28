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

---

## What this skill was missing

Written after applying it to a host we do not own — Codex, via its lifecycle hooks. The
worked scope is [`ADAPTER-CODEX-SCOPE.md`](ADAPTER-CODEX-SCOPE.md); what follows is what
that exercise found missing here. Each entry is a step that cost real time to work out
because the guidance was not there.

### 1. Find the seam before inventorying anything

Step 1 says to record the host's graph; it never says **where to look**. For a host you
do not own, look for a documented extension point — hooks, plugins, event buses,
lifecycle callbacks — and do not fork. Codex's hook mechanism turned out to be the whole
answer: an external command that receives one JSON event and returns one JSON verdict.

Add to Step 1: **find the extension point first, and only then inventory.** If the host
offers only a log to read, the best you can do is Steps 6 and 8, and you should say so
rather than attempting 2 through 5.

### 2. `hostReach` per position, and partial adoption as a legitimate outcome

Step 1 says that where a position has no branch, "stop and add the branch before claiming
support". **For a host you do not own you cannot add a branch.** The instruction is fine
for your own runtime and impossible for `codex`, `opencode`, or anything you install.

Replace it with a declared reach per position:

```text
full         the host gives a real veto, and every action in the contract's position
             is expressible
partial      a veto exists but the verdict vocabulary is coarser (see item 3)
unreachable  no interception point exists — record it and move on
```

Two of six positions were unreachable for Codex for **structural** reasons: there is no
hook before the model turn, and `PreToolUse` fires after the tool has been chosen. A
partial adapter that says this is more useful than a claim of support that cannot hold.

### 3. Translate the action vocabulary, and declare the loss

The Skill's Step 5 says an unhandled action is an adapter failure. True — but the harder
case is an action the host can only express **approximately**. Codex accepts four
verdicts (silence, `allow`+rewrite, `deny`+reason, `block`+reason) against the contract's
fourteen actions.

So add: for each contract action, record the host verdict **and, when the mapping is
lossy, which way it fails**:

```text
action            host verdict            loss
auto              silence                 none
use               allow + updatedInput    none
escalate          deny + reason           none
ask_human         deny + reason           ★ the host cannot ask; this fails CLOSED
```

`ask_human` is the usual casualty, because a host hook is a program and a program cannot
suspend for a human. Fail-closed is the defensible default for a contract whose premise
is "do not proceed quietly" — but the point is that it is **declared**, per action, rather
than discovered in production.

### 4. The adapter is an external process with its own obligations

Steps 2 through 5 read as though the adapter lives inside the host, next to its state.
For a foreign host it does not: it is a command the host spawns, and it inherits four
jobs the reference loop performed itself:

```text
state the host does not keep     Codex does not track which files were read — the
                                 adapter must, and its copy can be wrong in ways the
                                 contract cannot see
reading and bounding its inputs  history comes from a transcript file, which is
                                 unbounded by construction; the declared bounds must be
                                 applied by the adapter or the frame grows silently
the audit channel                auto_audit's "leaves a trace" becomes the adapter's
                                 own obligation; the host has nowhere to put it
computing the digests            see item 5
```

Call this out in Step 2, and make it a checklist item in Step 8's report.

### 5. For a foreign host, records are derived — expect `unverifiable`

Step 6 says "at every decision, record …". A host you do not own will not record what you
want; it records what it already records. Codex writes JSONL transcripts, and no hook can
add frame digests to them.

So a derived record will verify as `unverifiable` unless the **adapter** computes and
stores `sentFrameDigest` and `sentQuestions` itself. That is the expected result, not a
failure — but it must appear in the report as such. Add to Step 6: distinguish
**host-emitted** records (may verify) from **adapter-derived** ones (verify only if the
adapter supplies the digest inputs).

### 6. Adopt in the order the value is

The Skill lists positions but not which to take first when only some are reachable. From
the Codex exercise the order is:

```text
1. before-call     the authorization gate — a real veto, and a safety property
2. after-generate / is_done   the termination gate — where quiet completion lives
3. after-tool      step success
4. input-choice    rewriting an argument (needs the host to allow a rewrite)
```

Positions 1 and 2 are where a host hook has a veto and where this project's claims are
concentrated. A host that offers only observation gets **zero** of them, and the honest
report is that the runtime is not adoptable yet rather than that the adapter is partial.

### 7. Verdict schemas are strict; read the host's parser, not just its schema

Codex rejects unknown fields, rejects `permissionDecision: allow` unless it accompanies
an `updatedInput`, and rejects `permissionDecision: deny` without a non-empty reason. A
schema alone would not have told us the second rule; the parser did. When integrating,
read the code that validates your output — the schema is the shape, the parser is the
contract.
