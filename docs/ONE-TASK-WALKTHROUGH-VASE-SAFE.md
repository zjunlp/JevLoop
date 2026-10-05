# 单题逐步对照：`Put a vase in a safe.`

**为什么写这一页。** 前面所有结论都是 20 题的总分和分布，那些数字**读不出机制**。
这一页把**同一条题**上两边的每一步摊开，好让人直接看判官拿到什么、为什么输出那个结果。

- **任务**：`pick_and_place_simple-Vase-None-Safe-219` —— `Put a vase in a safe.`
- **seed**：20261003，`--tasks` 定点重跑（该后缀命中 3 个同名任务），`max-steps 30`
- **两边同一批条件**，生成 `qwen3.5-9b-local`，判定 `jev-1.13.0`
- **结果**：`react` **28 步做对**（同题另两次 30 步耗尽）；我们 **3 步"交付"，`task_not_completed`**
- **帧的完整原文**：`/tmp/frame-dump/react-typed/…Vase-None-Safe-219.jsonl`（300 条判定请求）
  —— 复查时用 `--dump-requests` 重跑即可再生成

---

## 一、我们那三步，逐步

### 第 1 步

```
判定 needsTool  → 0.980                        src=judge
判定 pickInput  → go to safe 1                 src=fallback  fb=accept_below_bar   ← 低于 0.5 仍采用
▲ act({"command": "go to safe 1"}) → 'You arrive at safe 1. The safe 1 is closed.'
判定 risk       → (declared:1)                 src=rule
判定 needs_auth → 0.180                        src=judge
```

帧（原文）：
```
task: Put a vase in a safe.
already_done: (none)
(absent — last_tool, last_result, done_tools, redirect_note)
```

题面：`Which action should be taken next to make progress on the task?` —— **31 个选项**：
27 个 `go to X`、`help`、`inventory`、`look`、`none_of_the_available_actions`。

★ 判官的答案 `go to safe 1` **低于 0.5 门限**，是 `accept_below_bar` 让它落地的。
动作本身不算错（先去看 safe 是合理的），但它比 `react` 的第一步激进 —— `react` 先 `look`。

### 第 2 步

```
判定 stepOk    → 0.970
判定 isDone    → 0.020        ← 判得对：没做完
判定 needsTool → 0.970        ← 判得对：还有活
判定 pickTool  → act          （pickTool::violation = candidate_already_done）
判定 pickInput → open safe 1  ← 这次过线了
▲ act({"command": "open safe 1"}) → 'You open the safe 1. … In it, you see a watch 2.'
```

★ 这一步**两边判得都对**：没做完、还有活、开 safe 也合理。

### 第 3 步 —— 病灶在这里

```
判定 stepOk                 → 0.980
判定 isDone                 → 0.030                    ← 没做完
判定 needsTool              → 0.970                    ← 还有活要干
判定 pickTool               → act
判定 pickInput::violation   → (options_over_budget)     ← 候选 > 32 条
判定 pickInput              → none_of_the_available_actions
                              src=fallback  fb=accept_below_bar   ← 又是不确定
★ 最终答案：一段"你还需要先找到花瓶"的说明
判定 deliverable::object    → no_objection              ← 闸门查不出不诚实
```

## 二、第 3 步：两个判定的**直接矛盾**

把这两份帧并排看（都是原文）：

**`needsTool`（答案 0.970，"还有活要干"）**
```
task: Put a vase in a safe.
last_tool: act
last_result: You open the safe 1. The safe 1 is open. In it, you see a watch 2.
already_done: act(go to safe 1) -> …, act(open safe 1) -> …
done_tools: act — Execute one command in the environment. …

# Question
The agent still has work to do before it can answer the task — an action the task requires that has not been taken yet
```

**`pickInput`（答案 `none_of_the_available_actions`，置信度 0.22）**
```
task: Put a vase in a safe.
already_done: act(go to safe 1) -> …, act(open safe 1) -> …
last_result: You open the safe 1. The safe 1 is open. In it, you see a watch 2.
(absent — action_rules, redirect_note, action_table)

# Question
Which action should be taken next to make progress on the task?
# Options
1. close safe 1        2. examine safe 1      3. go to armchair 1   …
23. go to shelf 6      …                     32. take watch 2 from safe 1
33. none_of_the_available_actions
```

⇒ 判官在同一时刻说了三件事：

| 问题 | 它答的 | 对不对 |
|---|---|---|
| 任务做完了吗（`isDone`） | 0.03 = 没做完 | ✅ 对 |
| 还有活要干吗（`needsTool`） | 0.97 = 有 | ✅ 对 |
| 下一步做哪个（`pickInput`） | **"以上都不合适"**（0.22） | ❌ 与前两条矛盾 |

**前两条矛盾于第三条，而我们执行了第三条。** 这就是"3 步收尾"的直接来源。

## 三、判官为什么答"都不合适"——帧层的证据

那一题的选项判据（原文）里：

```
30 个真选项，其中 27 个的判据是同一句话：
   "move to that location so its contents can be inspected"

剩下 3 个各有自己的：
   help      → "list the available commands"
   inventory → "check what you are currently holding"
   look      → "look around — reports information and changes nothing"
```

第 3 步那批（33 个选项）里，也是 **23 个共享同一句判据**。

⇒ **27 个选项在判官眼里是同一条东西的不同编号。** 它没有任何依据在 `go to cabinet 1` 和
`go to shelf 6` 之间排序 —— 任务要的是"找到花瓶"，而哪一格里有花瓶**帧里没有**（也不可能有）。
所以它答 0.22 的"都不合适"，**这个答案本身是诚实的：它确实分不出来**。

★ 这正是本仓库早就记过的那个形状（`frame.py` 的 R6 说明）：

> 判官答"一个都不合适" —— **它不是不会挑，是没有可挑的依据。**

### 而那条不变量**没有响**

`indistinguishable_options` 的判据是：

```python
len(set(question.criteria.values())) == 1      # 要求「全部判据一模一样」
```

27/30 相同**不算** —— 所以这道实际不可回答的题，在账上一条告警都没有。
这一批 20 题里只报了 `candidate_already_done` 62 次、`options_over_budget` 28 次。

⇒ **不变量判的是"全部相同"，而病是"绝大部分相同"。** 这是一个真缺口，而且很便宜。

## 四、`react` 那一侧：同样的候选，但**没有逃逸口**

`react` 的 prompt（原文）里，候选**一模一样**是那 30 条：

```
# Currently allowed actions
`act` currently accepts only these (30) — use one of them verbatim as `command`:
  - Action: act[go to armchair 1]
  - Action: act[go to cabinet 1]
  …  （和我们的选项表同一批）
  - Action: act[look]
```

区别只有一处：**它必须挑一个。没有"都不合适"这个选项。**

它的实际动作序列（28 步做对的那一次）：

```
 1 look
 2 go to cabinet 1        3 open cabinet 1
 4 go to cabinet 2        (Nothing happens.)  5 open cabinet 2
 6 go to drawer 1 …      15 open drawer 5
16 go to dresser 1       17 go to shelf 1 … 22 go to shelf 5
23 go to shelf 6         → 'On the shelf 6, you see a vase 2.'
24 take vase 2 from shelf 6
25 go to safe 1          26 open safe 1
27 move vase 2 to safe 1  → '… [task complete]'
```

★ 注意第 4、19、20 步是 `Nothing happens.` —— **它踩了坑，然后自己接着走**。
它不需要"这一步值不值得做"的判断，因为它没有一个"我不干了"的出口。

## 五、三条候选解释（分清证据与推测）

| # | 解释 | 证据强度 |
|---|---|---|
| 1 | **判据不可区分**（帧层）：27/30 个 `go to X` 共享同一句判据 ⇒ 判官没有排序依据 ⇒ 答"都不合适" | **强**：判据原文就在 dump 里，重复数可数 |
| 2 | **逃逸被 `accept_below_bar` 提升成决定**（策略层）：0.22 的"我分不出来"被当成"没有合适的动作"，直接终结这一集 | **强**：账上 12 次逃逸里 11 次是它提上来的 |
| 3 | **`indistinguishable_options` 判据过窄**（守卫层）：要求全部相同，所以 27/30 这种真病不报 | **强**：代码判据可读，账上零命中 |

而 `needsTool` 0.97 与逃逸 0.22 的矛盾是**现象**，它的成因在 1 和 2。

★ 交付闸门那一步**没有错**：`no_objection` 是对的 —— 那段草稿确实如实描述了发生了什么
（"safe 里是 watch 2，不是 vase"）。闸门管的是**诚实**，不是**完成**；这是已经定下的设计。

## 六、下一步可以试什么（都还没做）

1. **把判据变可区分**：给 ALFWorld 的 `act` 加 `describe_candidate`，
   用环境已知的事实区分候选 —— 最有信息量的是**"这一格去过没有 / 里面报过什么"**
   （帧里 `already_done` 有，但判据里没有）。
   ★ 这是**环境声明领域事实**，和 TERNARY 给 `d005` 配标题是同一件事、同一个入口。
2. **把 `indistinguishable_options` 从"全部相同"改成"报出区分度"**
   （如 `distinct/total = 4/30`），便宜，且能把这类题从"判官老逃"里分离出来。
3. **逃逸的中间区不许直接停**（人已定的 A+B 那一条）：不够果断 ⇒ 取排序最好的非逃逸候选。
   准入型上已量出 ALFWorld 0 → 4。
