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
a ceiling on CPU, memory or disk       not by the harness. A container gives you
                                       one; see below — that is where these live
a ceiling on wall clock or spend       per run only, and opt-in: maxWallMs /
                                       maxModelCalls / maxTokens on runAgent,
                                       which halt the loop between steps
per-call tool limits                   yes — enforced in the contract, see below
a container, namespace or VM           you supply it. We do not ship one, and the
                                       reason is below; the invocation is verified
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

## Running it in a container

**The decision: we do not ship a container image, and you should run this inside
one.** Those are one sentence because they are one decision — an image we build
would be a build artifact to maintain for a project whose whole shape is "no build
step, no dependencies", while the thing you actually need is the *bounds*, and
those come from the runtime flags rather than from us.

This invocation was **run and verified**, not written from memory:

```bash
WORK=/path/to/a/working/directory
docker run --rm \
  --network none \
  --cpus 1 --memory 1g --pids-limit 256 \
  --read-only --tmpfs /tmp:rw,size=64m \
  --cap-drop ALL --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  -v "$PWD":/src:ro \
  -v "$WORK":/work:rw \
  -e HOME=/tmp -w /work \
  -e JEVLOOP_ISOLATED=1 \
  node:22-slim \
  node --experimental-strip-types /src/examples/demo.ts --rule
```

What each part is for, and what was checked:

| flag | why | checked |
|---|---|---|
| `--network none` | the loop needs no network for an offline run, so it should not have one | the demo ran to completion with no network |
| `--cpus` / `--memory` / `--pids-limit` | the CPU and memory ceilings this file says the harness does not have | a runaway allocator inside `--memory 128m` was killed (exit 137) |
| `--read-only` + `--tmpfs /tmp:size=64m` | the disk ceiling, and no writable root | a 100 MB write got `ENOSPC`; writing to `/` got `EROFS` |
| `--cap-drop ALL` + `no-new-privileges` | no capability to escalate with | see the `--user` note below |
| `-v "$PWD":/src:ro` | the source is **read-only**; the loop never needs to write to itself | verified — the whole run works from a read-only mount |
| `-v "$WORK":/work:rw` | the only writable place is the directory you chose | the work directory was untouched by the demo, which runs in `/tmp` |

⚠️ **`--user "$(id -u):$(id -g)"` is not optional if you drop capabilities.**
`--cap-drop ALL` removes `DAC_OVERRIDE`, so container-root can no longer read files
it does not own — and a source checkout is often mode `600`. Without `--user` the
first run fails with `EACCES` on the entry file. Found by running it; running as the
file owner is the better practice anyway.

⚠️ **`--network none` also means no hosted decision backend.** Use the offline
judge (`--rule`), a local model, or drop `--network none` deliberately and accept
that the loop can reach whatever the network allows. Inside a container,
`HOST=0.0.0.0` plus a published port exposes it to your network — the loopback
decision above is about the default, not a guarantee the flags cannot undo.

**What this does not fix.** A container bounds the *process*; it does not make the
decision layer correct, does not verify tool output, and does not stop a run from
deleting files inside the work directory you mounted. It changes what a mistake
costs, not whether one happens.

### Per-call tool limits

Three limits live in `src/act.ts`, not in a provider — so a different tool backend
cannot drop them:

| Limit | Value | When it applies |
|---|---|---|
| Input ceiling | declared per tool (`write_file` 64 KB, `delete_file` / `move_file` 4 KB) | checked **before** `run()`, so an oversized call has no side effect at all |
| Timeout | declared per tool, **read-only tools only** (5 s) | the call is abandoned, not cancelled |
| Output ceiling | 8000 chars, every tool | truncated **and labelled** with how much was dropped |

Two honest caveats:

- **A timeout is giving up on observing, not on executing.** JavaScript cannot
  cancel a promise already in flight, so a timed-out call may still be running.
  That is why `write_file`, `delete_file` and `move_file` deliberately do **not**
  declare one: reporting "timed out" for a write that actually succeeded would let
  the loop continue on the basis of something that did not happen. For a move it is
  worse than for the others — the source may already be gone.
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
| `move_file` | 2 | moves or renames a file/directory; **refuses to overwrite** an existing target, and does not create parent directories |
| `delete_file` | 3 | deletes a file or an **empty** directory; never recurses |
| `done` | 0 | no-op |

Two gates matter more than the table:

- **Mutation is opt-in.** `write_file` only enters the candidate set when the
  caller supplies an input source; `delete_file` needs `allowDelete` **in
  addition**, because writing and deleting are not the same trust level.
  `move_file` needs **both** gates: it creates a destination (write) and makes the
  source path stop existing (delete), so granting only one would widen a boundary
  on the other side. Its risk is 2 rather than 3 precisely because it refuses to
  overwrite — nothing is lost, only the old path.
- **Risk 2 and above requires authorisation.** `DECISION.md`'s
  `score:risk >= 2 → ask_human` is a hard rule, not a threshold, and a decision
  model's own confidence cannot bypass it. Without an `onAskHuman` handler the
  answer is **deny**, so the loop stops rather than proceeding.

⚠️ **Threshold overrides can raise those bars.** `--gate grade_risk.risk=4`
moves the authorisation threshold above the top of the ladder, which means
destructive calls stop asking. The override is recorded in `run:start` and in
every affected rule's reason, but it is your decision and it is not reversible
after the fact.

## Process-spawning tools: gated, not promised

A tool that starts a process would widen a boundary that is known not to be
hardened. [`TODO.md`](TODO.md) §1 recorded that as a condition rather than a
checkbox that was merely unchecked, and §8 owned the condition. It is now closed —
**by making the deployment answer a machine question, not by writing a promise.**

The harness can bound exactly three things, and only for one call: input size,
output size, wall clock. It **cannot** bound CPU, memory, disk or network — those
need a kernel, a cgroup or a network namespace, and that belongs to the
deployment rather than to this loop. A process-spawning tool can therefore
legitimately exhaust memory, fill the disk, or talk to the network, and no amount
of care inside the loop changes that.

So a tool now declares it: `Tool.requiresIsolation`. When a tool declares it,
`callTool` refuses **before `run()`** unless the run was explicitly told it is
isolated:

```text
错误：<tool> 需要在**隔离环境**里运行，而这一次运行没有确认隔离 —— 这一调**没有执行**。
```

The acknowledgement is `AgentOptions.assumeIsolated`, and the application layer
sets it from `JEVLOOP_ISOLATED=1` — the same variable the container recipe above
uses. **The kernel does not read the environment**; only the application knows
what the deployment looks like, and a hidden env read inside the loop would make
"who is responsible for CPU and memory" unanswerable.

Two consequences worth stating plainly:

- **The container is the supported deployment for these tools.** That is the
  choice §8 existed to make. Elsewhere, an isolation-requiring tool is not
  "discouraged" — it does not execute, and the refusal says why and points here.
- **`--network none` is what makes the isolation claim real, and it also rules
  out a hosted decision backend.** That trade-off was recorded when the recipe
  was tested, and it still holds. If you need a hosted backend and a shell tool
  at the same time, you need a narrower network policy than `none`, and you
  should write down which one you chose.

What this gate is **not**: it is not a sandbox. It does not create namespaces, it
does not limit a process after it starts, and it cannot detect an isolated-looking
environment that is not actually isolated. It converts one specific silence — "a
process tool ran somewhere without the bounds it assumes" — into a refusal. The
rest is the container's job, and the container section above is the recipe.

## Reporting

Open an issue with the command and its output. If you believe something here is
wrong — a claim in this file that the code does not honour — that is a bug, and
it is the kind we most want to hear about.
