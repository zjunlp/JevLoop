# How to explain this project to me

The user asked for this on 2026-10-04, pointing at
[Karpathy's post](https://x.com/karpathy/status/2105819303471976479): give the model the
**ASD-STE100** treatment — the controlled English that aircraft maintenance manuals use, so that
every sentence has exactly one reading. "80% of ASD-STE100" is enough.

This file is about **talking to the user**. It says nothing about how to think or how to write
code. The code keeps its own habits: long rationale comments, the incident that produced each
rule, the alternatives that were rejected.

## The rules

1. **Short sentences.** One idea per sentence. Aim for 20 words or fewer.
2. **One name per thing, forever.** Never rotate synonyms to sound varied. If it is 闸门, it is
   always 闸门 — not gate, not 检查, not 把关, not 护栏. Synonym rotation is the single largest
   source of confusion in a project with this many moving parts.
3. **Active voice. Name who does what.** "规则给出档位" — not "档位被给出".
4. **Define a term the first time, in one line, with no other undefined terms.**
5. **Concrete beats abstract.** Give a real example from a real run: a task id, a number, a line
   from the log. "20 题里 4 题这样死" is worth more than "会有较高的失败率".
6. **Prefer a table or a diagram to prose.** Two columns answer "what changed" faster than a
   paragraph. Karpathy's second suggestion is to generate the artifact, not the description.
7. **No hype, no hedging.** Say "不知道" when we do not know. Do not write "显著提升" without a
   numerator and a denominator.
8. **State the cost.** Every design decision here has one. A recommendation without its cost is
   not a recommendation.

## Why this matters here specifically

This project has invented a private vocabulary: 帧, 证书, 兜底, 单调性, 判定占比, 交付率,
静默失败. Each term is load-bearing — they are not decoration. But they are also not
self-explanatory, and the user has to hold all of them at once to follow a status update.

The fix is not to drop the terms. The fix is to use **one** name for each, define it once, and
never make the reader re-derive which of three near-synonyms is meant.

## What the user asked for, in their words

> 我这里主要是不太懂你说的这么多的名词是什么意思，你后续可以从稍微易懂的角度解释给我，
> 然后你再给我梳理一遍我们这里是怎么做的

So: terms first, in plain language; then the whole pipeline, end to end.
