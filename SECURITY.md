# Security and deployment model

This file is the explicit decision §8 of [`TODO.md`](TODO.md) asks for. It is
short on purpose: the honest statement of what this loop does *not* protect
against is more useful than a list of partial mitigations that reads like a
guarantee.

## What this is

A **single-tenant, loopback-only research harness**. It is meant to be run by one
person, on their own machine, against a working directory they own.

## The decision: no authentication, and that is deliberate

`npm run serve` binds to **loopback only** and has **no authentication**. That is
not an unfinished feature — it is the deployment model, and it will stay that way.

The consequence, stated plainly:

> `HOST=0.0.0.0` makes it possible for **anyone on that network** to run tasks on
> this machine, with this loop's tool access. The server prints a warning when it
> starts; the warning is the whole mitigation.

If you need it reachable from elsewhere, put it behind something that
authenticates — do not add a password prompt to `src/server.ts`.

## What is not provided

None of these exist today. Do not assume any of them.

```text
authentication or authorisation        no
per-user isolation                     no — one process, one tenant
a ceiling on CPU, memory or disk       no
a ceiling on wall clock or spend       per run only, and opt-in: maxWallMs /
                                       maxModelCalls / maxTokens on runAgent,
                                       which halt the loop between steps
per-call tool limits                   yes — enforced in the contract, see below
a container, namespace or VM           no
path-escape sandboxing                 yes — and that is all it is
tool-output trust boundary             partial — string channels are marked
                                       untrusted; list-valued channels are not
```

Read the last two together with §7 of [`TODO.md`](TODO.md): a tool result is
untrusted input, and a decision model does not follow instructions, so the
relevant attack is **displacement** — untrusted text nudging a probability across
a threshold. String-valued channels carry an explicit marker now. That is a
mitigation, not a proof, and the measurement that would say how much it helps has
not been run.

### Per-call tool limits

Three limits live in `src/act.ts`, not in a provider — so a different tool backend
cannot drop them:

| Limit | Value | When it applies |
|---|---|---|
| Input ceiling | declared per tool (`write_file` 64 KB, `delete_file` 4 KB) | checked **before** `run()`, so an oversized call has no side effect at all |
| Timeout | declared per tool, **read-only tools only** (5 s) | the call is abandoned, not cancelled |
| Output ceiling | 8000 chars, every tool | truncated **and labelled** with how much was dropped |

Two honest caveats:

- **A timeout is giving up on observing, not on executing.** JavaScript cannot
  cancel a promise already in flight, so a timed-out call may still be running.
  That is why `write_file` and `delete_file` deliberately do **not** declare one:
  reporting "timed out" for a write that actually succeeded would let the loop
  continue on the basis of something that did not happen.
- **The output ceiling bounds what comes back, not what a tool did.** It stops a
  provider from flooding the context; it does not bound disk or memory.

## The tools

The loop can only call tools in `src/act-local.ts`'s registry, and the name the
model returns is checked against that table before anything runs. What the tools
can touch is bounded by the working directory:

| Tool | Risk | What it does |
|---|---:|---|
| `list_dir` | 0 | lists the working directory |
| `read_file` | 0 | reads a file |
| `write_file` | 1 | writes or overwrites a file, up to 64 KB of input |
| `delete_file` | 3 | deletes a file or an **empty** directory; never recurses |
| `done` | 0 | no-op |

Two gates matter more than the table:

- **Mutation is opt-in.** `write_file` only enters the candidate set when the
  caller supplies an input source; `delete_file` needs `allowDelete` **in
  addition**, because writing and deleting are not the same trust level.
- **Risk 2 and above requires authorisation.** `DECISION.md`'s
  `score:risk >= 2 → ask_human` is a hard rule, not a threshold, and a decision
  model's own confidence cannot bypass it. Without an `onAskHuman` handler the
  answer is **deny**, so the loop stops rather than proceeding.

⚠️ **Threshold overrides can raise those bars.** `--gate grade_risk.risk=4`
moves the authorisation threshold above the top of the ladder, which means
destructive calls stop asking. The override is recorded in `run:start` and in
every affected rule's reason, but it is your decision and it is not reversible
after the fact.

## Shell and git are deliberately absent

A tool that starts a process would widen a boundary that is known not to be
hardened — no resource limits, no isolation. The order is: provide the limits,
then add the tools. [`TODO.md`](TODO.md) §1 records this as a condition rather
than a checkbox that is merely unchecked.

## Reporting

Open an issue with the command and its output. If you believe something here is
wrong — a claim in this file that the code does not honour — that is a bug, and
it is the kind we most want to hear about.
