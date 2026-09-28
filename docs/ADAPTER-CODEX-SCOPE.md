# Applying the adapter Skill to Codex — a worked scope

> **What this file is.** The output of following
> [`SKILL-DECISION-ADAPTER.md`](SKILL-DECISION-ADAPTER.md) against a real host we do
> not own ([`openai/codex`](https://github.com/openai/codex), read at revision
> `e72da2b`). It is Step 1 (inventory) and Step 2 (state cells) done for real, plus the
> verdict on what is and is not reachable.
>
> **What it is not.** A working adapter. Nothing here has been run against Codex; every
> host fact below was read out of its source, with the path cited, so you can check it.

## The seam: Codex hooks, not a fork

Codex exposes a documented lifecycle-hook mechanism. A hook is an **external command**:
Codex writes one JSON event to its stdin, reads one JSON verdict from its stdout.

That is the whole reason an adapter is possible without touching Codex: the adapter is
a separate process, and the host's own control flow is untouched. Had Codex offered only
a transcript to read, the adapter would be limited to Step 6 (records) and nothing else.

The events that carry a verdict (not just information) are:

| Codex hook | What it may return | Source |
|---|---|---|
| `PreToolUse` | `permissionDecision: allow \| ask \| deny`, `permissionDecisionReason`, `updatedInput`, `additionalContext` | `codex-rs/hooks/src/schema.rs:244-255` |
| `PostToolUse` | `decision: block`, `reason` | `codex-rs/hooks/src/schema.rs:145-155` |
| `Stop` | `decision: block`, `reason` | `codex-rs/hooks/src/schema.rs:454-461` |
| `UserPromptSubmit` | `decision: block`, `additionalContext` | `codex-rs/hooks/src/schema.rs:429-433` |
| `SessionStart`, `SubagentStop`, `PreCompact`, `Interrupt` | context / lifecycle only | `codex-rs/hooks/src/schema.rs` |

## Step 1, for real: position reachability

The Skill asks to map each host location to one `DECISION.md` position. For Codex the
honest answer is a **partial** map, and the three verdicts are different enough to need
separate names:

| Position | Codex hook | Reach | Why |
|---|---|---|---|
| `before-call` | `PreToolUse` | **full** | a real veto: `deny` stops the call |
| `input-choice` | `PreToolUse` | **full** | `updatedInput` (with `permissionDecision: allow`) rewrites the arguments before they run |
| `after-tool` | `PostToolUse` | **partial** | can `block` with a reason (feeding it back to the model), but cannot distinguish "step failed, stop" from "step failed, retry" |
| `after-generate` / `is_done` | `Stop` | **partial** | `block` means *do not finish*. This is the termination gate — the one the quiet-completion problem lives at — but the verdict vocabulary is one bit |
| `step-start` | — | **unreachable** | `UserPromptSubmit` fires **once per user prompt**, not once per step, and it cannot say "act now" — it can only block or add context. The per-turn question "do I need a tool yet?" is decided inside the model turn, with nothing to intercept |
| `tool-choice` | — | **unreachable** | `PreToolUse` fires *after* the model has chosen the tool. The choice is a model output, not an interception point |

So **two of six positions are out of reach for structural reasons**, not for lack of
effort. `pick_tool` — routing "which tool" to a decision model — is the reference
implementation's most-cited node and it cannot be adopted here at all.

## The action vocabulary is coarser, and the mapping is lossy

`DECISION.md` names 14 actions. Codex's hooks accept, in effect, four verdicts:
*silence* (proceed), `allow` + `updatedInput`, `deny` + reason, and `block` + reason.
The translation is therefore not one-to-one, and the surprising parts are worth stating:

| Contract action | Codex verdict | Note |
|---|---|---|
| `auto` | *silence* | a plain `allow` is **not** accepted by Codex unless `updatedInput` is present (`output_parser.rs:453-457`) — the "allow" spelling exists only as the companion of a rewrite |
| `auto_audit` | *silence* + adapter records the audit | Codex has no audit channel; the "leaves a trace" promise becomes the adapter's own obligation |
| `ask_human` | **not expressible** | `permissionDecision: ask` is on the wire but Codex's parser rejects it as unsupported (`output_parser.rs:458-459`). The adapter must choose `deny` (fail closed) or silence (fail open) |
| `deny`-shaped outcomes (`escalate`) | `deny` **with a non-empty reason** | enforced: `deny` without a reason is rejected (`output_parser.rs:510`) |
| `use` (input choice) | `allow` + `updatedInput` | fits exactly, including the "allow requires updatedInput" rule |
| `keep_going` (at `Stop`) | `block` + reason | this is the quiet-completion gate |
| `finish` | *silence* | |

**`ask_human` is the casualty**, and it is not a detail: it is the action the reference
contract uses for its authorization ladder. A Codex adapter must declare which way it
fails. For a contract whose premise is "do not proceed quietly", the defensible mapping
is `deny` with a reason — fail closed — and that choice has to be written down, because
the host will not make it for you.

## Step 2, for real: the state cells Codex gives you

`PreToolUse` hands the adapter (`codex-rs/hooks/src/schema.rs:277-296`):

```text
session_id, turn_id, agent_id, agent_type
transcript_path          ← a JSONL transcript the adapter may read
cwd
hook_event_name, model, permission_mode
tool_name, tool_input, tool_use_id
```

Which covers, in `DECISION.md` terms:

| Frame cell | Available from | Verdict |
|---|---|---|
| `tool` | `tool_name` | **given** |
| `target` / `input` | `tool_input` | **given** |
| `cwd` | `cwd` | **given**, and it is the sandbox root |
| `history`, `lastResult` | read `transcript_path` | **derivable** — one file read per decision, and it must be bounded |
| `task` | first user message in the transcript, or cached from `UserPromptSubmit` | **derivable** |
| `files`, `readFiles` | the adapter's own bookkeeping | **the adapter's** — Codex does not track "which files were read" |
| `canWrite`, `canDelete` | `permission_mode` is the nearest signal | **mapped, with a caveat**: Codex's modes are not the same axis as "may this run mutate" |

Two consequences the Skill does not currently mention:

- **`files` / `readFiles` are the adapter's job.** In the reference implementation the
  loop maintains them. A foreign host will not, so the adapter is now a *stateful*
  component with its own persistence — and its state can be wrong in a way the contract
  cannot see.
- **Every frame is rebuilt from a file read.** The transcript is unbounded by
  construction; the adapter must apply the declared bounds itself, or the frame silently
  grows past what the decision model was measured on.

## Step 6 for a host you do not own: records are *derived*

Codex already writes JSONL transcripts. It does not write frame digests, and no hook can
make it. So a `decision-record/v1` record derived from Codex's transcript will carry
`sentFrameDigest` / `sentQuestions` **only if the adapter computes and stores them
itself**; otherwise `verifyRecord()` correctly returns `unverifiable` for every record.

That is the expected outcome, not a failure — but it has to be *reported* as such. The
Skill's Step 8 asks for a "replay status" field, and for this host the honest value is
"derived records, digests only if the adapter writes them, otherwise unverifiable".

## Verdict on the exercise

An adapter for Codex is **possible and worth building, at roughly half the contract**:

- **Adoptable now:** `before-call` (authorization — with `ask_human` mapped fail-closed),
  `input-choice`, and the `Stop` termination gate. Those are the three places a real veto
  exists, and two of them are exactly where the project's safety and quiet-completion
  claims live.
- **Not adoptable:** `step-start` and `tool-choice` — no interception point exists.
- **New obligations the adapter takes on:** an audit channel, `files` / `readFiles`
  bookkeeping, transcript reading and bounding, and computing the digests if records are
  ever to verify.

The Skill, as written, does not prepare you for any of the last three. What it was
missing is recorded at the end of [`SKILL-DECISION-ADAPTER.md`](SKILL-DECISION-ADAPTER.md).
