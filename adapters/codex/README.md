# Codex → `DECISION.md` adapter

Status: **experimental, and deliberately partial**. Read
[`docs/ADAPTER-CODEX-SCOPE.md`](../../docs/ADAPTER-CODEX-SCOPE.md) first — it is the
reason this adapter covers three of the seven reference nodes and not the other four.

There is no fork here. Codex's own lifecycle hooks are the seam: a hook is an external
command, Codex writes one JSON event to its stdin and reads one JSON verdict from its
stdout.

## What it does

| Codex hook | Contract block | Position | The veto it gives |
|---|---|---|---|
| `PreToolUse` | `grade_risk` | `before-call` | `deny` stops the tool call |
| `PostToolUse` | `step_ok` | `after-tool` | `block` sends a reason back to the model |
| `Stop` | `is_done` | `after-tool` | `block` means **do not finish** |

Those are the three places Codex offers a real decision rather than an observation. The
`Stop` one is the termination gate — where a quiet, unsupported "done" would otherwise
pass through unchecked.

## What it does not do

- **`pick_tool` and `needs_tool` are not adoptable here.** `PreToolUse` fires *after* the
  model has chosen a tool, and no hook fires before each model turn. Both positions are
  structurally unreachable; wiring them would be pretending.
- **`ask_human` is mapped to `deny`.** Codex puts `permissionDecision: ask` on the wire
  and its parser rejects it, so "ask a human" cannot be expressed. The adapter fails
  **closed** and says so in the verdict, because silently proceeding is the failure this
  whole project is about. If you want fail-open instead, that is a deliberate edit, not a
  configuration flag.
- **Frames are thin today.** `task` and `history` come from Codex's `transcript_path`, and
  this entry deliberately does not read it yet (see Roadmap). Missing cells make the
  adapter **deny**, not proceed. So the out-of-the-box behaviour is "refuse", which is the
  safe half of incomplete.

## Install

Add the hooks to `~/.codex/hooks.json` (shape verified against
`codex-rs/config/src/hooks_tests.rs`):

```json
{
  "description": "JevLoop DECISION.md adapter",
  "hooks": {
    "PreToolUse": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "node --experimental-strip-types /path/to/JevLoop/adapters/codex/hook.ts",
            "timeout": 10
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "hooks": [
          { "type": "command", "command": "node --experimental-strip-types /path/to/JevLoop/adapters/codex/hook.ts", "timeout": 10 }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          { "type": "command", "command": "node --experimental-strip-types /path/to/JevLoop/adapters/codex/hook.ts", "timeout": 10 }
        ]
      }
    ]
  }
}
```

Omit the `matcher` field entirely to run on every tool. Codex may ask you to trust a hook
the first time it runs. To roll back, delete the three groups whose `command` ends in
`adapters/codex/hook.ts`.

### Environment

```text
JEVLOOP_DECISION_MD    the contract file. Default: DECISION.md in this repository
JEVLOOP_JEV_URL        decision backend base URL, e.g. https://api.typesafe.ai
TYPESAFE_API_KEY       sent as a bearer token when set
JEVLOOP_STUB=1         deterministic stub backend — self-check only, NOT a judgement
JEVLOOP_RECORDS        append decision records here as JSONL
```

**With no backend configured the adapter denies.** A gate that fails open when it is not
wired up is worse than no gate, because you believe it is there.

### Self-check, and verifying the records

```bash
# one event in, one verdict out — no backend, no network
echo '{"hook_event_name":"PreToolUse","tool_name":"read_file","tool_input":{"path":"a.ts"}}' \
  | JEVLOOP_STUB=1 JEVLOOP_RECORDS=/tmp/rec.jsonl \
    node --experimental-strip-types adapters/codex/hook.ts

# then verify what it recorded, with the reference verifier
npm run replay -- /tmp/rec.jsonl
```

That second command is the point of the record format: decisions taken by **a host we do
not own** verify under **our** verifier. Run against this adapter it reports
`3 verified · 0 mismatch · 0 unverifiable` — the digests exist only because the adapter
computes them, since Codex will never write them.

## Reading the transcript

`task`, `history`, `lastResult` and `readFiles` come from the `transcript_path` Codex
puts in every hook event — an adapter cannot ask Codex for them, because Codex does not
keep them.

Two things about that are worth knowing before you rely on it:

- **It is an internal format.** Codex's own `RolloutLine` says readers "must use
  codex_rollout's canonical parser", which lives inside Codex. So the reader here is
  defensive by design: unknown line types are skipped silently (formats grow), malformed
  lines are skipped **and counted, and reported**, and anything it cannot find stays
  `undefined` so the decision is **refused** rather than made on a half-empty frame.
  Format drift makes this adapter louder, not quieter.
- **A transcript has no size bound**, so the reader takes two windows — 64 KB from the head
  for the first user message, 256 KB from the tail for recent steps — and says so in its
  notes when it does. Reading a whole session into memory to answer one question is the
  unbounded operation this project keeps finding elsewhere.

`files` and `readFiles` are **approximations**: they are recognised from the path
arguments of read-style tool calls. A guessed `readFiles` would make `is_done`'s
`already_read` column lie, and that column is the criterion for "were the two files the
task named actually read" — so the reader recognises instead of guessing, and labels the
result as approximate.

## The self-check stub is deliberately conservative

`JEVLOOP_STUB=1` is not a judgement, and it **cannot allow a destructive call**: it reports
high risk for `shell` / `apply_patch` / `write_file` and friends, which routes through
`ask_human` and therefore to `deny`. Reads pass. An earlier version answered "everything
is fine" to every question, which meant the stub would happily allow `rm -rf /` — a stub
left in the environment would have quietly removed the gate it was demonstrating.

## Roadmap, in the order that matters

1. ~~Read the transcript~~ — **done** (see above).
2. **Persist `files` / `readFiles` across hook invocations** instead of re-deriving them
   from the tail window. The current values are approximations and they get thinner the
   further back the reads are.
3. **Write the audit line** for `auto_audit`. The verdict already carries the flag; nothing
   consumes it yet.
4. **A `PreToolUse`-driven `pick_input`.** Codex accepts `updatedInput` alongside
   `permissionDecision: allow`, which is exactly the shape a "which file" answer needs —
   but the candidate set has to come from the adapter's own state first.

## What this adapter does not claim

It does not make Codex safe, does not verify tool output, and does not make the *decision*
correct — only whether the contract was consumed and recorded. The wording above is
deliberately the one from the adapter Skill:

> This runtime has a `DECISION.md` adapter for the listed positions and actions. It does
> not claim universal Decision Contract compatibility.
