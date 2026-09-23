"""我们把 JevLoop 这条臂。**一个 `decide()` = 一次节点序列。**

## 这个文件是论文那张表的第一个格子

`docs/PLAN-*.md` 的 Table 2 按两根轴切臂:**（一）谁来决定**、**（二）历史怎么到达下一步**。
这个文件动的是第一根轴 —— 循环还是 ReAct 那个循环（`common.run_loop`）,
**换掉的只有控制器**。

所以 `react × typed` 和 `react × llm` 的差**只可能来自决策者**。这不是声明,是构造:
两个臂共用同一个 `run_loop`、同一个 `build_prompt`、同一批工具。

## 逐步是什么 —— **七个节点全在**（2026-09-23）

```
decide() 每一步被调用一次
  │
  ├─ ① 上一步是工具调用吗？（`view.history` 的最后一步）
  │     ├─ ② stepOk      prob:ok   >=0.6 → continue / else → stop
  │     └─ 过了          → ③ isDone  prob:done >=0.6 → finish / else → keep_going
  │
  ├─ ④ needsTool     prob:needs_tool >= 0.5 → use_tool / else → answer
  ├─ ⑤ pickTool      top >= 0.6 → call / else → escalate
  │     └─ 真要调工具之前 → ⑥ gradeRisk
  │           score:risk >= 2      → ask_human
  │           prob:needs_auth>=0.5 → ask_human
  │           score:risk >= 1      → auto_audit   ★ **真的留痕**（`Session.record_audit`）
  │           else                 → auto
  ├─ ⑦ pickInput      top >= 0.5 → use / else → escalate
  │
  └─ 要生成答案时 → `_finish()` → ⑧ canDeliver
        prob:unsupported >= 0.5 → revise（**真的重写一次**,上限 1 次）
        prob:deliverable >= 0.6 → deliver
        else                    → revise
```

★★ **最容易出错的地方,以及这里是怎么处理的**:`stepOk` / `isDone` / `canDeliver`
都是**事后**判定,而 `decide()` 只在**事前**被调用。所以:

- `stepOk` / `isDone` 在**下一次 `decide()` 的开头**补跑（看 `view.history` 的最后一步）;
- `canDeliver` 在**生成之后、交出去之前**跑 —— 它判的对象就是刚生成的那份 draft,
  放到下一次 `decide()` 里去判是判不到的（那时答案已经交出去了）。

★ **批 = 一次 HTTP 往返。** 同一次请求里可以带**多道题**（`_ask_many`）——
`gradeRisk` 的两问（`risk` + `needs_auth`)和 `canDeliver` 的两问
（`deliverable` + `unsupported`)各自合并成一次;而
`needsTool` / `pickTool` / `pickInput` / `stepOk` / `isDone` 各占一次。

⚠️ **合并的判据不是「能塞多少塞多少」,是「共享同一份帧 + 彼此独立」。**
   合并不了的那两处都因为有**顺序或帧**的约束:

   - `needsTool` 与 `pickTool` —— `candidates()` 在「工具都做过了」时返回
     `[DONE]`,那是**代码按精确规则**判出来的收尾（§8.1 第三行),那时
     `pickTool` 压根不该被问;合并是**先发后看**的,会白问一路没有意义的题。
   - `stepOk` 与 `isDone` —— `stepOk` 的帧**故意没有 `task`**（那是修出来的,
     见 `NODE_FRAMES["stepOk"].excluded`),而 `isDone` **必须有**。
     **两份帧合不成一份**,所以这两道题只能分两次问。

## 三分法的落点（§8.1）

| 这一步是 | 交给谁 | 在这里 |
|---|---|---|
| 生成文本 | LLM | `_answer_text()` —— 只有这一处（修订也是它,带理由）|
| 挑选 / 打分 / 是否 | Jev | `_ask()` —— 一次请求判一批 |
| 遵循精确规则 | 代码 | 候选重建、预算校验、`Request.check()`、`gradeRisk` 的分级 |
| 人的授权 | **人** | `Decision(kind="ask")` —— 循环停下并 `escalated` |

## ★ 两个从事故里长出来的约束,在这里**是构造性的**

**候选每步重建**（§8.4）:`_candidates()` 每次都从 `view.tools` 减去 `ctx.records()`
里做过的动作。固定候选会让模型去选一个已经不适用的动作 —— 实测写完文件后
`write_file` 还在候选里,模型会**再选它**。

**违规必须有人接**（第 10 轮 R2/R5）:`_ask()` 里的 `Request.check()` 不是装饰,
`fatal` 会让这一步**发不出去**,并退回一个 `unparsed` + 原因。
那条失效链是「选项超限 → 校验发现 → **无人接收** → 请求照发 → 判定静默掉点」——
断在第三步还是第四步,区别就是这里有没有人接。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from experiments.core.agent import Session
from experiments.core.controller import Decision, DecisionView
from experiments.core.deciding import Answer, DecideRequest, DecisionClient
from experiments.core.frame import (
    AgentCtx,
    Question,
    Request,
    candidate_provider,
    compile_frame,
    ctx_from_steps,
    frame_for,
)
from experiments.core.models import Message
from experiments.core.types import is_tool_call

# ★ `DEFAULT_YES` / `DEFAULT_TOP` 两个全局常量**已删** —— 见下面的
#   `NODE_THRESHOLDS`:`DECISION.md` 里 `pick_tool` 是 0.6 而 `pick_input` 是 0.5,
#   用一个全局值会把其中一个改错,而**两边都还是「看起来在卡门限」**。

# ★★★ `ANSWER_FORMAT` **已删** —— 它违了我们自己定的分工。
#
#   原来 `_answer_text` 拼的是:
#
#       Reply with the final answer only. Do not emit an action.   ← 我们加的
#       # Task
#       <题目>
#       Give the final answer as a single number on its own line.  ← benchmark 的契约
#
#   ⇒ **两条输出契约并存**,而 `core/bench.py` 的分工表写着:
#     「任务陈述 + **输出契约** → **benchmark**;交互协议 → baseline。
#      **baseline 不许改任务陈述,只能加自己的协议块。**」
#     我们加的那条**不是交互协议,是第二条输出契约**。
#
#   ★ 实测代价(GSM8K × 100,单 commit)`react-typed` **63%**、平均 **9.8** 个输出
#     token;而同一个模型的 `direct` 是 **97%**、**131.7** 个 token。
#     **第一条契约把推理一起禁掉了** —— 模型老老实实只吐一个数。
#
#   ★ 这正是已经记过的那条教训:「两条输出契约并存时,从 prompt 上看不出
#     模型听了哪条」。教训记过了,我又犯了一次 —— 所以这次留注释在代码里。
#
#   ⇒ 生成那一步**就是生成**,用 benchmark 给的 `task_prompt`,一个字都不加。


# ═══════════════════════════════════════════════════════════
# ★★★ 问题和门限 —— **逐字抄 `DECISION.md`,不许自己写**
#
# 为什么这么重:第一版我按自己的理解给这三个节点写了措辞,结果
# **`needsTool` 那一句正好是 `DECISION.md` 里记着的那次事故的写法**。
#
# `DECISION.md` 的原文（`## needs_tool`）:
#
#   ★ 判据是「任务还有没有没做的动作」,不是「还有没有没拿到的信息」。
#   这两个在只读任务上恰好一致,而在**写任务**上分道扬镳 ——
#   实测:任务「把 alpha.ts 里的 totalOf 抄到一个新文件 summary.ts 里」,
#   读完 alpha.ts 之后这个节点判了 `answer`(0.36),于是 loop 直接去生成回答,
#   **文件从没被写出来**。
#
# 我写的是 `"Does this task still require a tool call before it can be answered?"`
# —— 问的是**工具调用**,而事故的教训正是「要问**任务要求的动作**」。
# 「写一个文件」在这个问法下又一次落在问题之外。
#
# ★ 而且 `vocab.ts` 说「**问题 ID 不会到达模型**」—— 所以措辞是模型能看到的全部,
#   写错了没有任何别的东西兜得住。**这是照抄比回忆准的第三个例子**（前两个:
#   `top()` 的语义、`.env` 的变量名）。
#
# 门限也一起抄。★ `pickTool` 是 **0.6**、`pickInput` 是 **0.5** —— 两个不一样,
# 而我第一版只有一个全局 `top`。
# ═══════════════════════════════════════════════════════════

#: `needs_tool`:`prob:needs_tool >= 0.5 → use_tool`（`DECISION.md`）
NEEDS_TOOL_ASK = (
    "The agent still has work to do before it can answer the task — "
    "an action the task requires that has not been taken yet"
)
#: ★ 判据**必须给**:`vocab.ts` 说 noul 的 `criteria` 「显著提升判定质量」,
#: 而且它正是上面那次事故的修法 —— 把「写」明确写进 true 那一侧。
NEEDS_TOOL_CRITERIA = {
    "true": ("the task still requires an action that has not happened: "
             "reading something, listing something, writing something, running something"),
    "false": ("every action the task asks for has already been taken, "
              "and there is enough information to answer"),
}

PICK_TOOL_ASK = "Which tool should the agent call next?"
PICK_INPUT_ASK = "Which file should this tool call target?"

# ═══════════════════════════════════════════════════════════
# ★★★ 另外四个节点的措辞 —— 同样**逐字抄 `DECISION.md`**
#
# 「照抄比回忆准」的前三个例子是 `top()` 的语义、`.env` 的变量名、
# `needsTool` 的问法。这里是第四个、第五个、第六个、第七个 —— 而且这一批
# 抄错的代价更大:这四个节点里有两个是**闸门**（`gradeRisk` / `canDeliver`),
# 措辞一松,闸门就变成 fail open 的 —— **它拦不住任何东西,而账上看起来在拦。**
# ═══════════════════════════════════════════════════════════

#: `step_ok`:`prob:ok >= 0.6 → continue`（`DECISION.md`）
#:
#: ★★ 措辞里**必须**有那句「Judge only this call」:这条判定出过的事故是
#: 被拉到任务级（帧带着 `task`、问题写着 "for the task"、判据写着
#: "what the task needed",三处一起拉)。帧那一侧已经**故意没有 `task`**
#: （见 `NODE_FRAMES["stepOk"].excluded`),措辞这一侧就是另一半 ——
#: **两处缺一处,那次事故就会回来。**
STEP_OK_ASK = (
    "This tool call itself completed and returned output this step can use. "
    "Judge only this call; whether the whole task is finished is a different "
    "question, decided elsewhere."
)
STEP_OK_CRITERIA = {
    "true": ("the tool ran and returned content — no error, no empty result, "
             "and the target it names is the one that was requested"),
    "false": ("the call did not work: an error, an empty result, a missing file, "
              "or output that clearly did not come from this tool"),
}

#: `is_done`:`prob:done >= 0.6 → finish`（`DECISION.md`）
IS_DONE_ASK = ("The agent has done everything the task requires — "
               "no further tool call is needed to answer it")
IS_DONE_CRITERIA = {
    "true": ("the goal stated in the task has been reached, and the answer can be "
             "written from what has already been gathered"),
    "false": "something the task still asks for is missing",
}

#: `grade_risk`:**一次判定问两件事**（`DECISION.md` 里 kind 是 `mixed`）。
GRADE_RISK_ASK = "How risky is this tool call?"
#: ★ `score` 的判据是一个**从低到高的档位表**（`vocab.ts` 的形状）。
#: 顺序有意义:判定模型给的是**分**,而分靠这张表才有含义。
RISK_LEGEND: tuple[str, ...] = (
    "read-only",
    "reversible write",
    "irreversible",
    "destructive",
)
NEEDS_AUTH_ASK = ("This call must be explicitly authorised by a human before it runs")
NEEDS_AUTH_CRITERIA = {
    "true": "it can destroy data, spend money, or leave the machine",
    "false": "it only reads or writes inside the working directory",
}

#: `can_deliver`:**也是一次判定问两件事**（`DECISION.md` 的 kind 是 `mixed`）。
DELIVERABLE_ASK = ("The answer carries out what the task asked for, "
                   "and reports it accurately")
DELIVERABLE_CRITERIA = {
    "true": ("the task's request has been carried out and the answer describes it "
             "consistently with what the tools returned"),
    "false": ("the task's request has not been carried out, or the answer "
              "misreports what happened"),
}
#: ★★ **这一条是 ALFWorld 那题的判据。**
#: 实测:任务要「把**加热过的**苹果放进冰箱」,agent 只走到冰箱门口
#: （冰箱还关着）就交了「I placed the microwaved apple in the fridge.」——
#: 工具输出里**没有任何东西支持这句话**,而这条判据问的正是这个。
UNSUPPORTED_ASK = "The answer states something that the tool output does not support"
UNSUPPORTED_CRITERIA = {
    "true": "it claims a fact, file or result that was never observed",
    "false": "everything it says traces back to a tool result",
}

#: 每个节点的门限,**逐条注明出处**。
#:
#: ⚠️ 两个 `choice` 的门限**不一样**（0.6 vs 0.5）—— 这不是笔误,
#: 是 `DECISION.md` 里就写着两个数。用一个全局常量会把其中一个改错,
#: 而**两边都还是「看起来在卡门限」**。
NODE_THRESHOLDS: dict[str, float] = {
    # prob:needs_tool >= 0.5 → use_tool   （probGte 语义:P(true)）
    "needsTool": 0.5,
    # top >= 0.6 → call / else → escalate （topGte 语义:果断程度）
    "pickTool": 0.6,
    # top >= 0.5 → use  / else → escalate （topGte 语义:果断程度）
    "pickInput": 0.5,
    # prob:ok >= 0.6 → continue（probGte 语义）
    #
    # ★★★ **0.6 不是 0.5,这条有讲究**（`DECISION.md` 的 `step_ok` 一节）:
    #   `noul` 的 0.5 是**最不确定**的取值,而这道门限是闭区间 `>=` ——
    #   一个等于「毫无信息」的值不该能放行任何事。`stepOk` 又是七个判定点里
    #   唯一一个「放行 = 当没事发生」的门:**它放行的意思是「这一步成功了」,
    #   于是失败被吞掉。** Mock 恒 0.5,门限 0.5 时它会判 `continue`,
    #   把「完全不确定」读成了「成功」。
    "stepOk": 0.6,
    # prob:done >= 0.6 → finish
    "isDone": 0.6,
    # ⚠️ `gradeRisk` / `canDeliver` **故意不在这里** —— 它们的策略是
    #   `DECISION.md` 里那几条**顺序求值**的规则（`score:risk >= 2` 先于
    #   `prob:needs_auth`,等等),不是一道题一个果断度门限。
    #   把 0.5 塞进来会让「`score:risk >= 2` 这条硬规则」看起来也能被
    #   概率绕过 —— 而 §8.5 的原话是「**授权闸门不接受概率绕过**」。
}


def _noul_question(node: str, ask: str, *, threshold: float,
                   criteria: dict[str, str] | None = None,
                   frame: str = "") -> Question:
    return Question(node=node, kind="noul", ask=ask, threshold=threshold,
                    criteria=criteria or {}, frame=frame)


def _score_question(node: str, ask: str, legend: tuple[str, ...], *,
                    frame: str = "") -> Question:
    """`score` 的判据是**档位表**（`vocab.ts`:`criteria: [档位, 从低到高]`）。

    ★ `_wire` 那一边把它摊成 `list(criteria.values())` —— 所以这里传进去的
    字典**键就是档位本身**,顺序由元组定。抄错顺序等于把「不可逆」当成「只读」,
    而风险分是靠位置读的。
    """
    return Question(node=node, kind="score", ask=ask,
                    criteria={label: label for label in legend}, frame=frame)


def _choice_question(node: str, ask: str, options: list[str],
                     *, threshold: float,
                     criteria: dict[str, str] | None = None,
                     frame: str = "") -> Question:
    """★★★ **候选必须带说明。**

    实测（2026-09-22,`bfcl-v3-multiple × react-typed`）:候选只传了**工具名**,
    描述是空字符串 —— 于是判定模型只能**光看名字猜**。
    结果 **82/100 是 `wrong_tool`**,而置信度经常是 **1.000**(判得很果断,只是错了)。

    ★ 这正是 §8.2 那个形状:**帧里没有的,它判不出来**。
      而且它和 `canDeliver` 那次一样 —— **看起来像判定错,其实是喂少了**。

    `vocab.ts` 对 `choice` 的 `criteria` 的定义就是「键是选项本身,
    值是**什么条件下该选它**」—— 而 `DECISION.md` 的原文里,
    每个选项后面都跟着一句说明（`read_file — 需要文件内容才能继续…`）。
    我们只传了键,没传值。
    """
    return Question(node=node, kind="choice", ask=ask, options=tuple(options),
                    threshold=threshold, criteria=dict(criteria or {}), frame=frame)


#: ★★★ `pickTool` 候选里的**终止项** —— `DECISION.md` 的 `pick_tool` 原文里就有它:
#:
#:     - done — 已有足够证据回答任务,工具循环可以结束了
#:
#: **实测没实现它的代价**(2026-09-22,`bfcl-v3-multiple × react-typed`):
#: 判定**选对了工具**(82 → 25 条 `wrong_tool` 里,剩下的都是这一类),
#: 但调完之后下一步 `needsTool` 仍说「还要动作」——
#: 而候选里**已经把做过的删掉了**(§8.4),于是**只剩错的工具可选**。
#: 结果 `sorted(called) != sorted(gold)` → 判 `wrong_tool`。
#:
#: ⇒ **把做过的删掉,就必须同时给一个「不做了」的出口。**
#:   否则候选集在第一次调对之后**只剩错的选项** —— 这不是模型选错,是我们没给对的选项。
#:   这是我实现 §8.4 时漏掉的另一半。
DONE = "__done__"


def candidates(session: Session, ctx: AgentCtx) -> list[str]:
    """**这一步**能选的工具。§8.4 的落点。

    ★ 做过的动作**在这里删掉,不是在帧里提示一句** —— 提示是可以被无视的,
    而候选列表是模型唯一能选的东西。

    ★★ **删掉之后必须补一个 `DONE`** —— 见上面那段。少了它,
      第一次调对之后候选里**只剩错的选项**,而模型没有别的可挑。

    ⚠️ 注意这只是**工具级**的去重。同一个工具做两次常常是合理的
    （读两个不同的文件）,所以删的是**已经做过的那一次动作**,
    而 `pickInput` 会在参数那一层再算一次候选。
    """
    done = {r.tool for r in ctx.records()}
    left = [t.name for t in session.tools if t.name not in done]
    # ★ 只要**已经做过什么**,就给出口。一次都没做时不给 ——
    #   那时「不做了」应当由 `needsTool` 回答,而它的帧正是为那个问题准备的。
    return (left + [DONE]) if done else left


@dataclass
class TypedController:
    """判定与生成分开的控制器。

    `client` 是判定后端（`core/deciding.py`）;生成仍然走 `session.call_model`。

    ★★ **一个 `decide()` 会发若干次判定请求,一次请求 = 一批。**
    `session.next_batch()` 在每个**请求点**开批,按批计时,不按条
    （同一次请求判多路时按条求和会多算几倍,实测过）。
    哪几个节点合并进同一次请求,由「证据形状是否相同」决定 —— 见模块头。
    """

    client: DecisionClient
    #: 「还要不要动作」的门限（`probGte` 语义）。
    #: ★ 默认值取自 `NODE_THRESHOLDS`,**不是另一个常量** ——
    #:   两处各写一个数,改了其中一个就是「配了没生效」那个坑。
    yes: float = NODE_THRESHOLDS["needsTool"]
    name: str = "typed"
    #: 每一步的判定轨迹（节点 / 答案 / 置信度）。**进日志用,不是给 policy 读的。**
    trace: list[dict] = field(default_factory=list)

    # —— 对外 ────────────────────────────────────────────────

    def decide(self, session: Session, view: DecisionView) -> Decision:
        ctx = ctx_from_steps(view.task_prompt, list(view.history))
        # ★★★ **每步重算「还剩哪些动作」并放进帧。**
        #   `needsTool` 问「还有没有没做的动作」—— 而它的帧必须**装着动作**,
        #   否则模型只能从「做过什么」反推（§8.2:帧里没有的,它判不出来）。
        #   和 `candidates()` 同一个来源,所以两处不会分叉。
        #   ⚠️ **`DONE` 不算动作** —— 它是「没有动作了」的出口,不是一件事。
        #   `pickTool` 需要它当**选项**（选项键),`needsTool` 需要的是
        #   「还剩哪些**事**」,两者差这一个哨兵。混进来会让一个已经做完的
        #   任务在帧里显示成「还剩 `__done__` 可做」。
        ctx.remaining = tuple(a for a in candidates(session, ctx) if a != DONE)
        # ★★ **调过的工具带上它们的说明。**
        #   `needsTool` 判的是「任务要求的事做完没有」,而工具**名字**答不了这个 ——
        #   `library.search_books` 得配上「Search for a book in a given library」
        #   才判得出「找一本历史小说」覆盖了没有。
        #   `pickTool` 一直有描述（`criteria` 的值）,`needsTool` 这边漏了。
        called = {r.tool for r in ctx.records()}
        docs = {t.name: t.description for t in session.tools}
        ctx.done_tools = "\n".join(f"{n} — {docs.get(n, '')}" for n in sorted(called))
        self.trace = []

        # ★★★ **① 事后判定 —— 补跑上一次 `decide()` 之后发生的那一步。**
        #
        #   `stepOk` / `isDone` 判的都是「刚刚那一步」,而 `decide()` 只在
        #   **事前**被调用 —— 所以它们只能在**下一次进来的时候**补跑。
        #   位置必须在一切之前:上一次的工具调用失败了,就不该再往下走
        #   （那时的 `needsTool` 看到的是一个成功的历史,它会判得"没错"——
        #   错的是我们没告诉它上一步塌了）。
        #
        #   ★ 它返回 None = 那一步没事,继续往下。
        post = self._review_last_step(session, view, ctx)
        if post is not None:
            return post

        if not view.tools:
            # ★ 没有工具的任务（GSM8K 那种）**一次判定都不该发**,两个理由:
            #
            #   ① 「要不要用工具」的答案恒为否,问它只是白花一次判定;
            #   ② `canDeliver` 判的是「回答有没有超出**工具输出**的支持」——
            #      没有工具就没有工具输出,那道闸门**没有可核对的材料**。
            #      发出去会得到一个凭空的答案,而日志上它和一次正常判定一样（§8.10）。
            #
            #   ★ 所以这条路上**刻意不过闸门**,而且这件事要说明 ——
            #     不然它看起来像「我们忘了跑 canDeliver」。
            return self._finish(session, view, ctx, why="这个任务没有工具",
                                deliver=False)

        # ② 还要不要动作
        #
        # ⚠️ **它和 `pickTool` 不合并** —— 试过了,合起来会埋掉一条出口:
        #   `candidates()` 在「工具都做过了」时返回 `[DONE]`,而 `DONE` 是
        #   **代码按精确规则**判出来的收尾（§8.1 第三行),那时 `pickTool`
        #   压根不该被问。合并是**先发后看**的,于是这一批里会白问一路
        #   「挑哪个工具」—— 而它唯一的候选是 `__done__`（那不是一个工具名）。
        #   ★ 而「能由精确规则定的不交给判定模型」正是 §8.1 那条,
        #     所以这里**顺序是真的**:先问要不要,再问挑哪个。
        batch = session.next_batch()
        asked = self._ask(session, batch, ctx, view.step,
                          _noul_question("needsTool", NEEDS_TOOL_ASK,
                                         criteria=NEEDS_TOOL_CRITERIA,
                                         threshold=NODE_THRESHOLDS["needsTool"]))
        if "needsTool" not in asked:
            return self._blocked(session, view, "needsTool")
        need = asked["needsTool"]

        if need.prob_true() < self.yes:  # noqa: SIM201 —— 刻意留成可覆盖的
            # ★ 用 `prob_true()`（「是」的概率）,不是 `top()`（果断程度）——
            #   这里问的是「还要不要动作」,答案本身是「是/否」。
            #   一个**果断的「否」**（noul=0.05）在 `top()` 上是 0.95,
            #   拿它来比就会得出「很确定还要工具」—— 正好反了。
            return self._finish(session, view, ctx, why=f"needsTool={need.noul:.3f}",
                                batch=batch)

        # ②′ 挑哪个工具 —— **候选在这一步重建**（§8.4）
        options = candidates(session, ctx)
        if not options:
            # 候选空了:做过的都做过了,那就是可以答了。
            # ★ 但 `needsTool` 刚说「还要一个动作」—— 这两句是**矛盾的**,
            #   矛盾本身要记下来,否则它看起来像一次顺利的收尾。
            self.trace.append({"step": view.step, "node": "pickTool",
                               "violation": "no_candidate_left", "fatal": False,
                               "detail": (f"needsTool={need.noul:.3f} 说还要动作,"
                                          f"但候选已空（做过的都做过了）")})
            # ★ 收尾不是「模型判的」,是**代码按精确规则判的**（§8.1 第三行）——
            #   所以要说明来源,不能让日志看起来像一次判定。
            return self._finish(session, view, ctx, why="候选已空（做过的都做过了）",
                                batch=batch)

        # ★★★ **`DONE` 必须在「唯一候选」捷径之前处理。**
        #
        #   实测（2026-09-22）:加 `DONE` 出口之后 `bfcl-v3-simple × react-typed`
        #   **从 97/100 掉到 0/100** —— 因为那个子集只有 **1 个工具**,
        #   工具做完之后 `candidates()` 返回 `[DONE]`,而捷径把 `DONE`
        #   当成了**工具名**去 `view.tools` 里找。
        #
        #   ★ 这是**加出口时引入的回归**,而且只打在「工具数 = 1」的子集上 ——
        #     另一个子集（2–4 个工具）走的是 `else` 分支,完全没受影响。
        #     **同一处改动在两个子集上一好一坏,是「只在有工具的数据集上测」
        #     这条纪律的又一个例子 —— 但还得再加一条:两个子集都要测。**
        if options == [DONE]:
            self.trace.append({"step": view.step, "node": "pickTool",
                               "answer": DONE, "top": 1.0, "provider": "typed"})
            return self._finish(session, view, ctx,
                                why="候选只剩 done（工具都做过了）", batch=batch)

        if len(options) == 1:
            # ★ 只有一个候选就**不问** —— 「要不要用工具」刚由 `needsTool` 判过,
            #   再问「要哪一个（而只有一个）」是白花一次判定。
            #   这正是 §8.1 第三行:能由精确规则定的,不交给判定模型。
            picked_choice = options[0]
            tool = next(t for t in view.tools if t.name == picked_choice)
        else:
            # ★★ 候选**带描述** —— 光给名字等于让判定模型猜（见 `_choice_question`）。
            #   `Task.tools` 里就有 description,而它此前**根本没进过问题**。
            picked_asked = self._ask(session, session.next_batch(), ctx, view.step,
                                     _choice_question(
                                         "pickTool", PICK_TOOL_ASK, options,
                                         threshold=NODE_THRESHOLDS["pickTool"],
                                         criteria={
                                             o: (docs.get(o) or "there is enough "
                                                 "evidence to answer; stop calling tools")
                                             for o in options}))
            if "pickTool" not in picked_asked:
                return self._blocked(session, view, "pickTool")
            picked = picked_asked["pickTool"]
            picked_choice = picked.choice
            if picked_choice == DONE:
                # ★ 判定模型说「够了」—— 去生成答案,不再调工具。
                #   这条出口是 `DECISION.md` 里就有的（`done`）,不是我加的。
                self.trace.append({"step": view.step, "node": "pickTool",
                                   "answer": DONE, "top": picked.top(),
                                   "provider": "typed"})
                return self._finish(session, view, ctx,
                                    why="pickTool 判了 done（证据够了）", batch=batch)
            tool = next((t for t in view.tools if t.name == picked_choice), None)
            if tool is None:
                # 判定模型选了一个**不在候选里**的工具 —— 那是它的错,
                # 但必须能被看见,不能悄悄退回一个默认值。
                return self._blocked(session, view,
                                     f"pickTool 选了候选外的 {picked_choice!r}",
                                     answer=picked)

        # ③ 参数
        arguments, err = self._arguments(session, ctx, view, tool)
        if err is not None:
            return self._blocked(session, view, err)

        # ④ 真要调工具之前 —— 风险与授权
        #
        # ★ 位置在**参数之后**:`gradeRisk` 判的是**这一调**的风险,
        #   而「这一调」= 工具 + 参数（`target`）。参数还没定就问风险,
        #   问的是另一件事 —— 而它会照答,答案是凭空生成的（§8.10）。
        #
        # ★★ 硬闸门与概率闸门是**两条独立的**（`DECISION.md` 的 `grade_risk`）:
        #   `score:risk >= 2` 不接受概率绕过（§8.5);`needs_auth` 才是模型判断。
        #   顺序也是判据:`score:risk >= 2` 先于 `prob:needs_auth >= 0.5`。
        risk = self._grade_risk(session, ctx, view, tool, arguments)
        if risk == "ask_human":
            reason = f"gradeRisk: {tool.name}"
            return Decision(kind="ask", syntax="typed",
                            raw=f"typed: 授权闸门拦下 {reason} —— "
                                f"{self.trace[-1].get('detail', '')}",
                            thought=reason)
        if risk == "blocked":
            return self._blocked(session, view, "gradeRisk")

        return Decision(kind="tool", tool=tool.name, arguments=arguments,
                        syntax="typed", raw=f"picked={picked_choice}")

    # —— 节点 ────────────────────────────────────────────────

    def _arguments(self, session: Session, ctx: AgentCtx,
                   view: DecisionView, tool) -> tuple[dict, str | None]:
        """参数从哪来。**能枚举的就判,不能枚举的只能生成** —— 而且要说明是哪一种。

        ★ 这是 §8.2 那条硬约束的落点:判定模型只能从枚举里挑
        （实测 77 个候选时选中概率掉到 0.425）。所以一个参数**自由文本**的工具
        （`search[query]` 那种）**不能被 `pickInput` 选中** ——
        把它做成 `choice` 是在骗自己,它只能靠猜。

        那种情况走「生成提候选、判定排序」里的**前半段**:让 LLM 生成。
        ★ 于是**哪一步是判的、哪一步是生成的**必须记清楚 ——
        那正是论文第一根轴要量的东西,含糊过去这个臂就没有意义了。

        ★ `pickInput` **独占一次请求**:它的候选依赖**刚选中的那个工具**
        （`for_options(ctx)` 的形状),和 `needsTool`/`pickTool` 不共享证据。
        """
        provider = candidate_provider(tool)
        params = list((tool.parameters.get("properties") or {}).keys())

        if not params:
            return {}, None

        first = params[0]
        if provider is None:
            # 不可枚举 → 生成。**记下来 —— 这一步不是判定。**
            session.record_decision(step=view.step, node=f"pickInput:{first}",
                                    answer="(generated)", confidence=0.0,
                                    correct=True, latency_ms=0.0,
                                    batch=session.next_batch())
            return {first: self._generate_argument(session, view, tool, first)}, None

        options = [o for o in provider(ctx)]
        if not options:
            return {}, None
        if len(options) == 1:
            # 只有一个候选 —— 问它是在浪费一次判定,而且答案必然是它。
            return {first: options[0]}, None

        asked = self._ask(session, session.next_batch(), ctx, view.step,
                          _choice_question("pickInput", PICK_INPUT_ASK, options,
                                           threshold=NODE_THRESHOLDS["pickInput"]))
        if "pickInput" not in asked:
            return {}, "pickInput"
        picked = asked["pickInput"]
        if picked.choice not in options:
            return {}, f"pickInput 选了候选外的 {picked.choice!r}"
        return {first: picked.choice}, None

    def _grade_risk(self, session: Session, ctx: AgentCtx, view: DecisionView,
                    tool, arguments: dict) -> str:
        """`gradeRisk` —— 「这一调多危险」,以及要不要人批。

        返回 `auto` / `auto_audit` / `ask_human` / `blocked`。

        ★★ **这一调 = 工具 + 参数**,所以 `target` 在这里才存在 —— 这也是
        它必须排在 `pickInput` **之后**的原因（见调用点）。

        ★★★ **两条闸门是独立的,顺序也是判据**（`DECISION.md` 的 `policy`）::

            score:risk >= 2      → ask_human     ← 硬规则,**不接受概率绕过**（§8.5）
            prob:needs_auth>=0.5 → ask_human     ← 模型判断
            score:risk >= 1      → auto_audit
            else                 → auto

        `resolvePolicy` 是**顺序求值、第一条命中就返回**。所以把
        `score:risk >= 2` 提到 `prob:needs_auth` 前面不是风格问题 ——
        反过来的话,一个「风险 3 但模型说不用授权」的调用会被放过去,
        而那正是 §8.5 明说不许发生的事。
        """
        # ★★ **`target` = 这一调的参数,所以参数的来源在帧上要说清。**
        #   `gradeRisk` 的帧声明写的是 `FrameField("last_input", 200, "target")`
        #   —— 也就是「`AgentCtx.last_input` 就是这一调的目标」。
        #   而 `ctx` 是从**已完成的历史**拼出来的:第 0 步时它是空的,
        #   于是「刚要调的那个工具」在帧里不存在 —— 闸门会对着一片空白判风险。
        #   （实测:第一版没写这一行,`target` 一直是上一步的输入,
        #   而第 0 步干脆缺席 → 请求被 `field_missing` 拦下,整条臂动不了。）
        #   ★ 它只在**这一调**的判断里生效:ctx 是 `decide()` 里现拼的,
        #     下一次进来会从 `view.history` 重新拼一份。
        ctx.last_input = str(next(iter(arguments.values()), "") or "")
        batch = session.next_batch()
        asked = self._ask(session, batch, ctx, view.step, [
            _score_question("risk", GRADE_RISK_ASK, RISK_LEGEND, frame="gradeRisk"),
            _noul_question("needs_auth", NEEDS_AUTH_ASK,
                           criteria=NEEDS_AUTH_CRITERIA, threshold=0.5,
                           frame="gradeRisk"),
        ])
        if not {"risk", "needs_auth"} <= set(asked):
            # ★ 两问缺一**不作数**:拿 `risk=0` 或 `needs_auth=0` 顶上,等于
            #   让一道授权闸门在「不知道」的时候**默认放行** —— 那是 fail open,
            #   而 §8.5 的原话是「授权闸门不接受概率绕过」。
            return "blocked"
        risk, auth = asked["risk"], asked["needs_auth"]

        action = _risk_action(risk.score, auth.prob_true())
        detail = (f"risk={risk.score}（{RISK_LEGEND[risk.score] if 0 <= risk.score < len(RISK_LEGEND) else '未知档位'}）"
                  f" needs_auth={auth.prob_true():.3f} → {action}")
        self.trace.append({"step": view.step, "node": "gradeRisk", "answer": action,
                           "top": auth.top(), "provider": "typed",
                           "detail": detail})

        if action == "auto_audit":
            # ★★★ **承诺了留痕就必须真的留痕。**
            #
            #   `DECISION.md` 的原话:「`auto_audit` 承诺了留痕就必须真的留痕。
            #   以前这条分支和 `auto` 完全一样,只多打一行 trace。」
            #   ★ 而「只多打一行 trace」在证据上等于没留 —— `trace` 是内存里的
            #     调试列表,跑完就没了。这条痕必须进**事件流**（`events.jsonl`）,
            #     那里是跑完之后还读得到的唯一地方。
            #     （和 `_ask` 里那条「违规写进内存里一个 list 不算有人接收」同一个形状。）
            session.record_audit(
                step=view.step, tool=tool.name,
                # 目标照 TS 的 `AuditRecord` 截到 200 字符 —— 留痕要能读,
                # 而一整篇写入内容不该把审计行撑爆。
                target=(str(arguments.get(next(iter(arguments), ""), "")) or "")[:200],
                reason=(f"score:risk={risk.score} >= 1 → auto_audit;"
                        f" prob:needs_auth={auth.prob_true():.3f}"),
                risk=risk.score,
            )
        return action

    def _review_last_step(self, session: Session, view: DecisionView,
                          ctx: AgentCtx) -> Decision | None:
        """★★ `stepOk` + `isDone` —— **事后**判定,在下一次 `decide()` 的开头补跑。

        返回 `None` = 那一步过了,继续往下走。

        ★ 为什么必须在这里:两个节点判的都是「**刚刚**那一步」,而 `decide()`
        只在事前被调用 —— 工具还没跑,没有东西可判。放到下一次进来补,
        是唯一说得通的位置（`view.history` 的最后一步就是它）。

        ★★ `stepOk` 过了才问 `isDone` **这条顺序不能反**:
        「这一步成没成」和「整个任务完没完」是两层。上一步失败了却去问
        「做完了吗」,`isDone` 会在一个**塌了的历史**上判 —— 而它判得"没错"
        （历史里确实有那些动作),错的是我们没告诉它上一步没成。
        `DECISION.md` 明写:「两者判错了层就会互相打架」。

        ★ 两个节点合并成**一次请求**:证据形状相同（都看刚刚那一步),
        而且彼此独立 —— 合并的判据就是这个,不是「能塞多少塞多少」。
        """
        if not view.history:
            return None
        last = view.history[-1]
        if not is_tool_call(last.action):
            # 上一步不是工具调用（生成/解析错误）—— 没有「这一步成没成」可判。
            # ★ `__parse_error__` 那种伪步骤也在这一支:它不产生 `ToolCallEvent`,
            #   拿它去问 `stepOk` 是在对一个从未发生的调用判成败（见 `is_tool_call`）。
            return None

        asked = self._ask(session, session.next_batch(), ctx, view.step,
                          _noul_question("stepOk", STEP_OK_ASK,
                                         criteria=STEP_OK_CRITERIA,
                                         threshold=NODE_THRESHOLDS["stepOk"]))
        if "stepOk" not in asked:
            return self._blocked(session, view, "stepOk")

        ok = asked["stepOk"]
        if ok.prob_true() < NODE_THRESHOLDS["stepOk"]:
            # ★ 门限是 0.6 而不是 0.5,理由见 `NODE_THRESHOLDS["stepOk"]`:
            #   这一格是七个判定点里唯一一个「放行 = 当没事发生」的门,
            #   放行意味着**失败被吞掉**。所以它比别处严。
            #
            # ★ `stop` **不重试**:重试需要一个错误分类策略,而那个策略不存在 ——
            #   所以动作名只承诺实际发生的事（它以前叫 `retry_or_stop`,
            #   名字承诺了做不到的事,`DECISION.md` 里有这段）。
            self.trace.append({
                "step": view.step, "node": "stepOk", "answer": "stop",
                "detail": f"上一步没成立（ok={ok.prob_true():.3f}）—— 不再往下走",
            })
            return Decision(kind="unparsed", syntax="typed",
                            raw=(f"typed: stepOk 判了 stop（ok={ok.prob_true():.3f} < "
                                 f"{NODE_THRESHOLDS['stepOk']}）—— 上一步的工具调用没有成:"
                                 f"{ctx.last_tool}({ctx.last_input}) -> {ctx.last_result[:200]}"))

        # ★ `isDone` **单独一次请求**:它的帧里必须有 `task`,而 `stepOk` 的帧
        #   **故意没有**（`NODE_FRAMES["stepOk"].excluded` 里写着为什么)——
        #   两者共享不了一份帧,所以合并不成立。**「彼此独立」是合并的判据,
        #   而「帧一样」是它的前提。**
        asked = self._ask(session, session.next_batch(), ctx, view.step,
                          _noul_question("isDone", IS_DONE_ASK,
                                         criteria=IS_DONE_CRITERIA,
                                         threshold=NODE_THRESHOLDS["isDone"]))
        if "isDone" not in asked:
            return self._blocked(session, view, "isDone")
        done = asked["isDone"]
        if done.prob_true() >= NODE_THRESHOLDS["isDone"]:
            # ★ **finish 是判定模型说的,不是步数用完** —— 语义早停。
            return self._finish(session, view, ctx,
                                why=f"isDone={done.prob_true():.3f}")
        return None

    def _finish(self, session: Session, view: DecisionView, ctx: AgentCtx,
                *, why: str, batch: int = 0, deliver: bool = True) -> Decision:
        """生成答案,**并过交付闸门**（`canDeliver`）。

        ★★ 为什么闸门在这里而不是在下一次 `decide()`:它判的对象是
        **刚生成的那份 draft**。等到下一次 `decide()` 时答案已经交出去了
        （`run_loop` 收到 `answer` 就返回）—— 那样闸门只是个装饰。
        TS 侧也是这个位置（`ctx.draft = gen.text` 之后紧跟 `ask(specs.canDeliver, ctx)`)。

        ★★ **`revise` 承诺了修订,那修订就必须真的发生。**
        `DECISION.md` 的 `can_deliver` 一节写着「交付闸门」,而 TS 侧的原话是
        「以前它只是被拼进 halt 字符串,草稿原样返回」。
        **上限 1 次**:第二次还不合格就如实交出去并说明 ——
        不无限重试,那会变成一个收费循环。
        """
        del batch  # 只为了和 `_ask` 的调用形状一致;这里不记账
        draft = self._answer_text(session, view)
        ctx.draft = draft

        if not deliver:
            # ★ 没有工具 → 闸门**没有可核对的材料**（见 `decide()` 里那条)。
            #   这里记一行,好让「为什么没跑 canDeliver」在轨迹里有答案 ——
            #   沉默地跳过会让它和「忘了接」长得一样。
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": "(skipped)", "detail": why})
            return Decision(kind="answer", answer=ctx.draft,
                            thought=f"生成答案（{why}）", syntax="generated")

        verdict, feedback = self._can_deliver(session, view, ctx)
        if verdict == "revise":
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": "revise", "detail": feedback})
            ctx.draft = self._answer_text(session, view, revise=feedback)
            verdict, feedback = self._can_deliver(session, view, ctx)
            if verdict == "revise":
                # ★ 第二次仍然不合格 —— **如实交出去,并说明**（§8.10:不假装成功）。
                #   这里不再重写第二遍:上限 1 次是刻意的（TS 侧同一条）。
                self.trace.append({"step": view.step, "node": "canDeliver",
                                   "answer": "revise(again)",
                                   "detail": f"修订一次后仍未过闸门:{feedback}"})
        if verdict == "blocked":
            # 闸门发不出去（帧缺判定依据 / 超预算）→ 这一步**不成立**,
            # 交给 `_blocked` 退回 `unparsed`,循环去看得见的地方弃答。
            return self._blocked(session, view, "canDeliver")

        return Decision(kind="answer", answer=ctx.draft,
                        thought=f"生成答案（{why}）", syntax="generated")

    def _can_deliver(self, session: Session, view: DecisionView,
                     ctx: AgentCtx) -> tuple[str, str]:
        """`canDeliver` —— 交付闸门。返回 `("deliver"|"revise"|"blocked", 说明)`。

        ★★ 策略**逐字**来自 `DECISION.md`,而且顺序是判据::

            prob:unsupported >= 0.5 → revise
            prob:deliverable >= 0.6 → deliver
            else                    → revise

        `unsupported` 排在前面不是随手写的:「一个完整但凭空编了事实的回答,
        比一个不完整的回答更该被打回」。ALFWorld 那题编的完成报告正是这一类。

        ★ 两条合并成一次请求:都看**同一份 draft 和同一份证据**。
        """
        batch = session.next_batch()
        asked = self._ask(session, batch, ctx, view.step, [
            _noul_question("deliverable", DELIVERABLE_ASK,
                           criteria=DELIVERABLE_CRITERIA, threshold=0.6,
                           frame="canDeliver"),
            _noul_question("unsupported", UNSUPPORTED_ASK,
                           criteria=UNSUPPORTED_CRITERIA, threshold=0.5,
                           frame="canDeliver"),
        ])
        if not {"unsupported", "deliverable"} <= set(asked):
            return "blocked", ""

        unsupported, deliverable = asked["unsupported"], asked["deliverable"]
        if unsupported.prob_true() >= 0.5:
            return "revise", (f"回答里有工具输出不支持的内容"
                              f"（unsupported={unsupported.prob_true():.3f}）—— "
                              f"只写证据支持得了的话")
        if deliverable.prob_true() >= 0.6:
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": "deliver",
                               "top": deliverable.top(), "provider": "typed"})
            return "deliver", ""
        return "revise", (f"回答没有把任务要求的事做完或如实报告"
                          f"（deliverable={deliverable.prob_true():.3f}）")

    def _answer_text(self, session: Session, view: DecisionView,
                     *, revise: str = "") -> str:
        """生成最终答案。**一个字都不加** —— 见上面 `ANSWER_FORMAT` 那段。

        ★ `view.task_prompt` **已经包含 benchmark 的输出契约**
          （GSM8K 的 `ANSWER_CONTRACT` 就拼在题目后面）。我们再补一条
          就是第二条契约,而两条并存时模型听哪条从 prompt 上看不出来。

        ★ 「这做过什么」那一行留着:它是**上下文**,不是契约 ——
          多步任务里模型需要知道已经查过什么。

        ★★ `revise` 是**交付闸门打回时**才有的那一段:它必须带上闸门给的理由
          （否则第二次生成是在同一个盲区里重写一遍,而那是白花钱）。
          它**不是**第二条输出契约 —— 它是"这一份不行,原因是 X"这一个事实。
        """
        parts = []
        if revise:
            parts += [f"# Revision required\nA previous answer was rejected: {revise}. "
                      f"Rewrite it so that the problem is fixed; do not repeat the same claim.", ""]
        parts.append(view.task_prompt)
        done = "; ".join(f"{s.action.name or s.action.kind}" for s in view.history)
        if done:
            parts += ["", "# What was done", done]
        return session.call_model([Message(role="user", content="\n".join(parts))]).text

    def _generate_argument(self, session: Session, view: DecisionView, tool, name: str) -> str:
        prompt = "\n".join([
            f"Give only the value for `{name}` — nothing else, no quotes, no label.",
            "",
            "# Task",
            view.task_prompt,
            f"# Tool\n{tool.name}: {tool.description}",
        ])
        return session.call_model([Message(role="user", content=prompt)]).text.strip()

    # —— 判定本身 ────────────────────────────────────────────

    def _ask_many(self, session: Session, batch: int, ctx: AgentCtx, step: int,
                  questions: list[Question]) -> dict[str, Answer]:
        """**一次请求,一批题。** 返回 `节点 → 答案`;**空字典 = 这一步发不出去**。

        ★★ 这里是「有人接收」那一步（第 10 轮 R2/R5）。

        那条失效链是:**选项超限 → 校验发现 → 无人接收 → 请求照发 → 判定静默掉点**。
        断在第三步和断在第四步,对这个函数来说就是 `return {}` 和 `continue` 的区别。

        两种违规分开处理:
        - **fatal**（缺判定依据 / 超预算 / 题太多）→ **不发**。发出去只会得到一个
          凭空生成的答案,而日志上它和一次正常判定长得一样（§8.10）。
        - **非 fatal**（候选里有做过的动作）→ 发,但记下来 ——
          §8.4 那条不变量要有人**看见**,不是有人拦住。

        ★★ **合并只省往返,不省判定。** 三道题一次请求 = 一次前向对所有问题
        并行打分（`core/deciding.py` 的模块头）—— 所以
        `questions_in_batch` 记 3、`requests_in_batch` 记 1。
        这两个数**分开记**正是为了这件事:合成一个就永远看不出有没有合并。
        """
        node = questions[0].node if len(questions) == 1 else "+".join(q.node for q in questions)
        # ★ 帧按**节点**取,不是按问题 id —— `grade_risk` 的两道题是
        #   `risk` / `needs_auth`,而它们的帧叫 `gradeRisk`（见 `Question.frame`）。
        frame = compile_frame(frame_for(questions[0].frame or questions[0].node), ctx)
        req = Request(frame=frame, questions=tuple(questions))
        t0 = time.perf_counter()

        for v in req.check(ctx):
            self.trace.append({"step": step, "node": node, "violation": v.code,
                               "fatal": v.fatal, "detail": v.detail})
            # ★★ **违规必须落到事件流里,否则不算有人接收。**
            #
            #   第 10 轮那条失效链是「校验发现 → **无人接收** → 请求照发 → 静默掉点」。
            #   写进内存里一个 list 仍然不是接收 —— 跑完之后没人读得到它,
            #   于是下一个人重建现场时,看到的是「这里怎么少了一次判定」。
            #   所以按「一次没成立的判定」记账:`correct=False` + 说明原因。
            session.record_decision(
                step=step, node=node, answer=f"({v.code})", confidence=0.0,
                correct=False, latency_ms=0.0, batch=batch,
                frame_digest=req.frame.digest(),
                request_digest=req.digest(), request_text=req.render(),
                note=v.detail,
            )
            if not v.fatal:
                continue
            # ★ 不发。为什么发不出去已经记在账上了 —— 否则调用方只知道「没判定」。
            return {}

        t_req = time.perf_counter()
        resp = self.client.decide(DecideRequest(
            state={"frame": req.frame.render()},
            questions={q.node: _wire(q) for q in questions},
        ))
        # ★ 把**这一次请求**的墙钟报给 session —— 批次耗时按请求累加。
        #   不报的话 `decision_ms` 会退化成「两次开批之间」,把那之间的
        #   生成调用和工具执行一起算进来（实测把框架时间减成了负数）。
        session.note_decision_request((time.perf_counter() - t_req) * 1000)

        # ★★★ **先算「成立了没有」,再决定这一批里哪些答案算数。**
        #
        #   于是下面那段记账可以**一道题一行**,而不是一段代码重复三遍 ——
        #   一条判定只记一行,这一条在七个节点上同样成立。
        asked = {q.node: resp.answers.get(q.node) for q in questions}
        decided = {q.node: (a is not None and a.top() >= q.threshold)
                   for q, a in ((q, asked[q.node]) for q in questions)}

        for q in questions:
            answer = asked[q.node]
            if answer is None:
                # 后端没给 / 给了畸形的 —— §8.10:报出来,不假装
                detail = f"dropped={resp.dropped} missing={resp.missing} {resp.warnings}"
                self.trace.append({"step": step, "node": q.node,
                                   "violation": "answer_unusable",
                                   "fatal": True, "detail": detail})
                session.record_decision(
                    step=step, node=q.node, answer="(answer_unusable)", confidence=0.0,
                    correct=False, latency_ms=(time.perf_counter() - t0) * 1000, batch=batch,
                    frame_digest=req.frame.digest(), request_digest=req.digest(),
                    request_text=req.render(), note=detail,
                )
                continue

            self.trace.append({
                "step": step, "node": q.node,
                "answer": answer.choice or answer.noul or f"score={answer.score}",
                "top": answer.top(), "provider": resp.provider,
                "frame_digest": req.frame.digest(),
                "truncations": dict(req.frame.truncations),
                "missing": list(req.frame.missing),
            })

            # ★★ **果断程度不够就不许往下走。**
            #
            #   这是一个**被迫的选择**:选项是穷尽的,判定模型必须挑一个 ——
            #   所以「挑了一个」不等于「挑得对」。`top()` 判的正是这件事
            #   （`choice` 看被选中那项的概率;`noul` 看 `max(p,1-p)`）。
            #
            #   §8.6 要求 Mock 必须让 policy **自己走到 `escalate`** ——
            #   而 Mock 给的是平均分布（8 个选项时每项 0.125）。
            #   没有这道门,`_arguments` 会照拿第一个候选,
            #   于是「不确定就别猜」在代码里**从来没有被走到过**。
            #
            #   ★ 多题时**逐题各判各的**:一批里有一道不果断,
            #     不该把同批里果断的那几道一起废掉（它们各自独立,
            #     合并只是为了省一次往返 —— 见 `_ask_many` 的说明)。
            session.record_decision(
                step=step, node=q.node,
                answer=str(answer.choice or f"{answer.noul:.3f}"
                           if answer.kind != "score" else answer.score),
                confidence=answer.top(),
                # ★ 帧的指纹进日志（§8.14）—— 两次运行帧不一样而没人发现,
                #   「同一个方法」这句话就不成立。
                frame_digest=req.frame.digest(),
                # ★★★ **请求的指纹也进**（§8.17）—— 判「两次跑的是不是同一个判定」
                #   要比的是这个,不是 `frame_digest`:那个只覆盖帧,
                #   而 `choice` 的**选项不在帧里**,换了候选帧指纹一动不动。
                request_digest=req.digest(),
                # ★ `correct` 是「这次判定**成立**吗」,不是「护身符」。
                #   全填 True 的话,`correct` 那一列恒为真,
                #   于是「置信度和正确性同现」这句话**在账面上永远成立** —— 而它本该被检验。
                correct=decided[q.node],
                # ★★ **一条判定只记一行。**
                #
                #   第一版这里在「不果断」时**又记了一条** —— 于是同一次判定在账上出现两遍,
                #   而**判定次数正是论文的头条指标之一**。这和 §8.10「按批计时、按记录求和
                #   会多算几倍」是同一类错:账目上的一个数被数了两遍,而账面上看不出来。
                #
                #   所以原因写在**同一行的 `note` 里**,不是另起一行。
                note="" if decided[q.node] else f"top={answer.top():.3f} < {q.threshold}",
                latency_ms=(time.perf_counter() - t0) * 1000, batch=batch,
                # ★★ **正文落在这里,不是 `trace` 里** —— `trace` 是内存里的调试列表,
                #   而落盘在 `record_decision`。第一次接的时候接到了 `trace` 上,
                #   于是 `--dump-requests` 静默地一个文件都不写（跑完才发现目录不存在）。
                #   和 §8.15 那条「要求写在文档里、没写在代码里」是同一个病。
                # ★★★ **`req.render()` 不是线上的东西** —— 它的 `# Options` 只有选项名,
                #   而真正发出去的 `questions[node].criteria` 是**选项 → 判据**的映射。
                #   「给 Jev 看的 choice 是什么」问的正是后者,所以两段都落。
                #   ★ 多题时落的是**整份请求的正文 + 整份线上 questions** ——
                #     一题一行会写三遍同一段帧,而「它实际看到了什么」只有一份。
                request_text=(req.render() + "\n\n# 线上的 questions（真正发出去的那一份）\n"
                              + json.dumps({x.node: _wire(x) for x in questions},
                                           ensure_ascii=False, indent=1)),
            )
            if not decided[q.node]:
                self.trace.append({
                    "step": step, "node": q.node, "violation": "below_threshold",
                    "fatal": True,
                    "detail": (f"{q.node}: top={answer.top():.3f} < {q.threshold}"
                               f"（答得不果断,不许拿它往下走）"),
                })

        return {n: a for n, a in asked.items() if a is not None and decided[n]}

    def _ask(self, session: Session, batch: int, ctx: AgentCtx, step: int,
             question: Question | list[Question]) -> dict[str, Answer]:
        """一道题的形状（`_ask_many` 的薄壳）：`_ask(..., q)["节点"]`。

        ★ 留着它是因为大多数调用点只问一件事,而写成
          `_ask_many(..., [q])["节点"]` 会让「这一步要的是哪一个答案」
          淹没在样板里。**多题和单题走的是同一条路径** ——
          薄壳不许有自己的校验或记账,否则两条路会分叉。
        """
        return self._ask_many(session, batch, ctx, step,
                              [*question] if isinstance(question, list) else [question])

    def _blocked(self, session: Session, view: DecisionView, why: str,
                 *, answer: Answer | None = None) -> Decision:
        """这一步发不出去 / 判定不成立。

        ★ 返回 `unparsed` 而不是硬凑一个动作 —— `unparsed` 的措辞是
        **「没答出来」不是「答错了」**（`core/controller.py`）。循环会重试,
        重试用完就 `escalate`,而 `escalate` 是一种**能被看见**的结果。

        ⚠️ 弃答的**原因**放进 `raw`,而且开头就写明是 `typed:` ——
        不写的话,日志上它和「模型格式错了」长得一样,而那是完全不同的事。
        """
        detail = ""
        if answer is None and self.trace:
            detail = self.trace[-1].get("detail", "")
        return Decision(kind="unparsed", syntax="typed",
                        raw=f"typed: {why}{' — ' + detail if detail else ''}")


def _wire(question: Question) -> dict:
    """`Question` → 线协议的问题形状。**逐字抄 `src/vocab.ts`。**

    ★★ 第一版这三个字段名**全是我猜的**（`kind` / `ask` / `options`）,
    而正本是 **`type` / `instructions` / `criteria`**。这和 `top()` 那次是同一个毛病:
    **猜一份已经写在隔壁的协议,而不去读它。**

    形状（`vocab.ts`）::

        noul   {type, instructions, criteria?: {true, false}}
        choice {type, instructions, criteria: {选项: "什么条件下该选它"}}
        score  {type, instructions, criteria: [档位, 从低到高]}

    ★ `choice` 的 `criteria` 键**就是选项本身**（会原样回到 `answers[id].choice`）,
    不是选项列表 —— 我之前写成 `options` 一个 map。
    """
    if question.kind == "choice":
        return {"type": "choice", "instructions": question.ask,
                "criteria": {o: question.criteria.get(o, "") for o in question.options}}
    if question.kind == "score":
        return {"type": "score", "instructions": question.ask,
                "criteria": list(question.criteria.values())}
    wire = {"type": "noul", "instructions": question.ask}
    if question.criteria:
        wire["criteria"] = dict(question.criteria)
    return wire


def _risk_action(risk: int, needs_auth: float) -> str:
    """`grade_risk` 的 policy —— **逐字抄 `DECISION.md`,而且顺序是判据**。

    ```text
    score:risk >= 2      → ask_human
    prob:needs_auth>=0.5 → ask_human
    score:risk >= 1      → auto_audit
    else                 → auto
    ```

    ★★ 两条闸门**互相独立**（`DECISION.md` 原话）:
    「第一条是硬规则（风险分够高就必须授权,**不接受概率绕过**),第二条才是模型判断。
    实测有效 —— 把风险阈值从 2 提到 3 试图绕开第一条时,第二条 `needs_auth=0.95` 兜住了。」

    ★★ 所以这里的**求值顺序**就是那条硬规则本身:先看 `score:risk`,
    再看 `prob:needs_auth`。反过来写的话,一个「风险 3 但模型说不用授权」
    的调用会被放过去 —— 而 §8.5 明说不许发生。

    ★ 它是一个**纯函数**,不住在 `decide()` 里面:这条策略是**代码按精确规则**
    做的判断（§8.1 第三行),抽出来才能单独测、也才能在写错时看得出来。
    """
    if risk >= 2 or needs_auth >= 0.5:
        return "ask_human"
    if risk >= 1:
        return "auto_audit"
    return "auto"


__all__ = ["TypedController", "candidates", "DONE", "NODE_THRESHOLDS",
           "NEEDS_TOOL_ASK", "NEEDS_TOOL_CRITERIA", "PICK_TOOL_ASK",
           "PICK_INPUT_ASK", "STEP_OK_ASK", "STEP_OK_CRITERIA",
           "IS_DONE_ASK", "IS_DONE_CRITERIA", "GRADE_RISK_ASK", "RISK_LEGEND",
           "NEEDS_AUTH_ASK", "NEEDS_AUTH_CRITERIA", "DELIVERABLE_ASK",
           "DELIVERABLE_CRITERIA", "UNSUPPORTED_ASK", "UNSUPPORTED_CRITERIA"]
