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
  ├─ ⑥ pickInput     挑这一调的参数（候选由 `candidate_provider` 枚举）
  │     └─ 选了退出口 ⇒ **转去收尾**（不是失败）—— 见 `PICK_INPUT_ESCAPE`
  └─ ⑦ gradeRisk     ★ **它在 pickInput 之后不是笔误**:它判的是「**这一调**多危险」,
                       而「这一调」= 工具 + 参数（`target`）。参数还没定就问风险,
                       问的是另一件事,而判官会照答 —— 那个答案是凭空生成的（§8.10）。

  要生成答案时 → `_finish()` → ⑧ canDeliver（交付闸门）

⚠️ **上面这一段的策略（`score:risk >= 2 → ask_human` 那几行）是 `typed-3` 及以前那一版。**
   默认那一版（`typed-4`）是**规则先筛、判官只确认**，完整说明见
   `docs/GATES-RULES-FIRST.md`；结构上是：

     ⑦ gradeRisk   档位由**规则**给（工具声明 → 参数模式表 → 认不出就是 2 = 不可逆 ⇒ 问人）
                   判官只确认，而且**只准往上抬**（"太高"不降）
     ⑧ canDeliver  三条**证书**命中 ⇒ 拒绝，判官只确认那条理由（否定也**不放行**）
                   没有命中 ⇒ 放行，判官可以提出一个证书查不出的问题（**唯一能收紧的权力**）
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
import re
import time
from dataclasses import dataclass, field, replace

from experiments.core.agent import Session
from experiments.core.controller import Decision, DecisionView
from experiments.core.deciding import Answer, DecideRequest, DecisionClient
from experiments.core.frame import (
    AgentCtx,
    StepRecord,
    canonical_state,
    Pointer,
    Question,
    Request,
    candidate_provider,
    compile_frame,
    ctx_from_steps,
    frame_for,
    render_evidence,
    render_tool_input,
)
from experiments.core.models import Message
from experiments.core.types import is_harness_pseudo_step, is_tool_call

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
#: ★★★ **这句原来写的是「Which file should this tool call target?」—— 在该域里是错的。**
#:
#: 实测（2026-10-02，ALFWorld）：那里**根本没有文件**，工具是 `act`，
#: 候选是 `go to safe 1` / `take mug 1 from fridge 1` 这类命令。
#: Jev 于是被问「这一调该针对哪个**文件**」，而候选里一个文件也没有 ——
#: 它转头去挑 `examine safe 1`、`look`、`inventory`（只返回信息、不改变状态），
#: 30 步全烧在上面。**问题本身与任务目标无关，它只能按字面猜。**
#:
#: ★ 措辞是从文件操作那套沿用来的（`PICK_TOOL_ASK` 的兄弟），
#:   而 ALFWorld 不在那个域里。**这不是调措辞，是原来那句在这一域里说不通。**
PICK_INPUT_ASK = "Which action should be taken next to make progress on the task?"

#: `pickInput` 每个候选的**说明** —— 按命令的**动词**给。
#:
#: ★★ 为什么必须有：调用点原来**没传 `criteria`**，而 `_choice_question`
#:   自己的文档就写着这件事的代价 ——
#:   「候选只传了工具名,描述是空字符串 ⇒ 判定模型只能**光看名字猜** ⇒
#:     82/100 是 `wrong_tool`,而置信度经常是 1.000（判得很果断,只是错了）」。
#:   `vocab.ts` 对 `choice` 的判据定义就是「键是选项本身,值是**什么条件下该选它**」。
#:
#: ★ 这张表按**动词**分类，说的是**工具自己的语义**，对每道题一视同仁，
#:   不是按题目写死的提示。认不出来的动词给一句通用的，**不猜**。
_PICK_INPUT_CRITERIA: tuple[tuple[str, str], ...] = (
    ("go to", "move to that location so its contents can be inspected"),
    ("open", "open that container so what is inside becomes visible"),
    ("close", "close that container"),
    ("take", "pick that object up; you must be holding it to use it"),
    ("put", "place the object you are holding at that location"),
    ("move", "put the object into or onto that receptacle"),
    ("clean", "clean the held object with that appliance"),
    ("heat", "heat the held object with that appliance"),
    ("cool", "cool the held object with that appliance"),
    ("use", "use that object"),
    ("examine", "inspect that object — reports information and changes nothing"),
    ("look", "look around — reports information and changes nothing"),
    ("inventory", "check what you are currently holding"),
)
_PICK_INPUT_FALLBACK = "take this step if it is the next thing the task requires"
#: 退出口的说明 —— 让判官知道它**可以**这么答。
_PICK_INPUT_ESCAPE_CRITERION = (
    "select if NONE of the listed actions is the next thing the task requires "
    "(for example the task is already done, or every useful move has been made)")


def question_family(node: str) -> str:
    """**一道题的"族"** —— 去掉逐候选那一层编号。

    一候选一题（2026-10-04）让 `pickInput` 的题名变成 `pickInput::1`…`pickInput::N`,
    而策略表（`NODE_THRESHOLDS` / `BELOW_THRESHOLD_POLICY` / `FALLBACK_POLICY` /
    `DECISION_QUESTIONS`）是按**判定点**登记的。

    ★★ **这是一个我自己引入的静默失效**:`FALLBACK_POLICY.get("pickInput::5")`
      取不到东西 ⇒ 兜底退回默认值;shadow 也匹配不上 ⇒ **`shadow` 那个档位
      对动作选择悄悄不再生效**,而账上看起来一切正常。
      是 `test_shadowing_an_action_node_falls_back_instead` 把它抓出来的。

    ⚠️ **判据必须是"后缀是数字",不能只按 `::` 切。**
      `deliverable::confirm` / `deliverable::object` / `canDeliver::shadow`
      也是 `::`，而它们是**独立的判定点**,不是 `deliverable` 的成员。
      只有 `::<数字>` 才是逐候选。
    """
    head, sep, tail = node.rpartition("::")
    return head if sep and tail.isdigit() else node


def _candidate_criterion(tool, option: str) -> str:
    """一个候选项在问题里配的说明。**领域说明优先于动词表。**

    ★★★ 顺序是判据（2026-10-04 实测逼出来的）:

      ① **`tool.describe_candidate(option)`** —— 领域自己说这个候选是什么。
         它是**权威**:`read_doc` 的候选是 `d005`,只有那个数据集知道
         `d005` 是哪家公司。
      ② `_input_criterion(option)` —— 通用动词表（ALFWorld 的领域知识）。
         它认得出 `go to safe 1`,但认不出 `d005`。
      ③ 兜底那句「如果这是任务下一步要做的事就选它」。

    ⚠️ **为什么领域说明排在动词表前面**:动词表是**我们**对某个领域的猜测,
      而 `describe_candidate` 是**环境**说的事实。猜的东西不该盖过事实。
      实测代价:TERNARY 上 40 个候选全落到 ③,拿到**同一句话**,
      判官答"一个都不合适" **21/21** —— 它不是不会挑,是没有可挑的依据。
    """
    describer = getattr(tool, "describe_candidate", None)
    if describer is not None:
        try:
            got = str(describer(option) or "").strip()
        except Exception:                      # noqa: BLE001 —— 领域函数出错不该炸掉整个循环
            got = ""
        if got:
            return got
    return _input_criterion(option)


def _input_criterion(option: str) -> str:
    """一个候选命令的说明。**按动词匹配，认不出就不猜。**"""
    low = option.strip().lower()
    for verb, text in _PICK_INPUT_CRITERIA:
        if low.startswith(verb):
            return text
    return _PICK_INPUT_FALLBACK

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

# ═══════════════════════════════════════════════════════════
# ★★★ 规则先筛、判官只确认 —— 两道闸门的**新问法**
#
# 用户 2026-10-04 的决定：「我们的闸门也改成"规则先筛、判官只确认"。」
#
# 这不是「把判定换掉」，是**换掉裁决的来源**。以前：
#
#     canDeliver : 判官答两道 `noul`（deliverable / unsupported），**裁决由它产生**
#     gradeRisk  : 判官答 `score:risk`，**风险档位由它产生**，规则只是读那个数
#
# 现在：
#
#     规则层（只认**证书**，纯代码，不问模型）
#       有能力判 ⇒ 给出 ALLOW 或 BLOCK + 一条**具体的、可指认的理由**
#       没能力判 ⇒ **不作声**（不猜、不默认放行）
#     判官层（只**确认**，不产生）
#       规则说 BLOCK ⇒ 问「这条理由成立吗」   成立/不成立/说不好
#       规则说 ALLOW ⇒ 问「你能指出一个证书查不出的问题吗」
#
# ★★★ **单调性是这个设计的地基,而且它是可以写成一行断言的：**
#
#     判官只能把闸门**收紧**,永远不能放松。
#
#   于是"不确定"在任何一条路上都**不会**变成拒绝 —— 因为拒绝是规则的职权，
#   而规则**只在有证书的时候**才拒绝。这正是实测那个 bug 的根
#   （`docs/ALFWORLD-ESCAPE.md` §4：判官说"风险 1，置信度 0.39"，
#    而 0.5 的门限把这句话丢掉了 ⇒ 授权闸门不成立 ⇒ 整题 decline，
#    20 题里 4 题这样死。**那个 0.5 门限现在整个不存在了**）。
#
# ★★ 为什么这比"规则兜底、判官决定"更对：判官**没有状态、没有计划、没有记忆**，
#   它最不擅长的就是产生一个跨整条轨迹的裁决；它擅长的是**对着一份具体材料
#   回答一个具体问题**。而"这条理由成立吗"正是后一种形状。
#   顺带它把 `docs/GROUNDING-STEP2-POINTER.md` 那句要求（一条裁决必须能指向
#   什么东西）从**举证题**推广到了**闸门本身**：规则给出的理由就是它要指的东西。
# ═══════════════════════════════════════════════════════════

#: ★★★ **交付闸门的证书表** —— 只有这几条能**单方面**拒绝交付。
#:
#: 门槛写在这里：**触发条件必须是「在产物上跑一次就出结果」的检查**
#: （集合差、空串、字符串命中），**中间不许有模型判断**。
#: 有模型判断的地方一律进不了这张表 —— 那是判官层的活（它只能收紧）。
#: 判据一句话：**能被否证的才配当规则。**
DELIVERY_CERTIFICATES: tuple[tuple[str, str], ...] = (
    ("empty_draft",
     "草稿是空的 —— 没有东西可交付"),
    ("ungrounded_number",
     "草稿里出现了工具输出里没有的数字"),
    ("no_evidence",
     "每一次工具调用都返回了空输出，草稿没有可核对的材料"),
)

#: ★★★ **两个"看起来该是规则、其实当不了规则"的检查** —— 以及为什么。
#:
#:   `tool_error_ignored`  工具输出里有环境声明的失败信号，而草稿声称成功
#:   `goal_signal_absent`  环境从未给出达成信号，而草稿声称任务完成
#:
#: 两条都**不是证书**，因为它们的触发条件是「**草稿声称了某事**」——
#: 而"这段话是不是一个完成声明"需要**主张检测器**，那个东西**现在没有**
#: （`docs/METRIC-CATALOG.md` Layer 2 自己写着 "needs detector"）。
#:
#: ★ 在单调性下（判官只能收紧）把一条**粗检测器**做成规则是**更坏**的：
#:   检测器误报 ⇒ 规则永久拒绝交付,而判官**不允许**放松它。
#:   ⇒ 所以它们降级成**判官的反驳材料**：进帧（`env_signals`），
#:     由"你能指出一个证书查不出的问题吗"那道题使用 —— 那是**收紧**方向，
#:     判官在这里是自由的。
#:
#: ★ 这是这一版设计**已知的强度上限**，要写进报告：
#:   假完成（"I placed the microwaved apple in the fridge."）**规则抓不住**，
#:   只有判官能抓。等 `Layer 7` 的检测器有了自己的误报率,
#:   这两条才能升格成证书。
NOT_YET_CERTIFICATES: tuple[tuple[str, str], ...] = (
    ("tool_error_ignored",
     "需要主张检测器（草稿有没有声称成功）—— 检测器现在没有"),
    ("goal_signal_absent",
     "需要主张检测器（草稿有没有声称完成）—— 检测器现在没有"),
)

#: **规则说 BLOCK 之后的问法** —— 判官确认它的理由，不是重新裁决。
CONFIRM_BLOCK_ASK = (
    "A deterministic check refused to deliver this answer, for the reason above. "
    "Judge only whether that reason holds for this answer — do not decide whether "
    "the answer should be delivered."
)
CONFIRM_BLOCK_CRITERIA = {
    # ★ 这三个选项是**穷尽的**（对一条命题的三种立场），所以候选集是真的封闭 ——
    #   照 μ 的规则可以豁免退出口，但**豁免要写出来**（`closed=True`）。
    "holds": "the refusal's reason is correct for this answer",
    "does_not_hold": ("the refusal's reason is wrong — it misreads the answer, "
                      "or the evidence does state what the answer claims"),
    "unsure": "the material given is not enough to tell whether the reason holds",
}

#: **规则说 ALLOW 之后的问法** —— 两层意思要分开：**有没有问题**，以及**是哪一种**。
#:
#: ★ 为什么把"哪一种病"也交给判官：补救动作由病决定（`_remedy`：
#:   `overclaim` ⇒ 撤回，`incomplete` ⇒ 回去做）。判官在这里只**命名**，
#:   不产生裁决 —— 命名一个疾病是分类，产生"要不要交付"才是裁决。
OBJECT_ALLOW_ASK = (
    "No deterministic check found a falsifiable problem with this answer. "
    "Can you point at one that a check cannot see? "
    "(If the answer simply declines to commit because the evidence does not settle "
    "the question, that is `honest_refusal` — it is NOT a problem.)"
)
#: ★★★ **`honest_refusal` 是 2026-10-04 加的，而它是被实测逼出来的。**
#:
#: 在 TERNARY 上按金标分类看"打回时草稿本来就对"的那 8 题:金标类型是
#: `contradiction` / `unanswerable` —— **那两类的正确行为就是拒绝作答**。
#: 而拒绝作答**必然要说一句关于证据的话**（"语料里没有""文档互相矛盾"）。
#:
#: 旧的选项集只有 `no_objection / overclaim / incomplete / unsure` ⇒
#: **一句诚实的拒绝只能落进 `overclaim`** ⇒ 闸门打回它、`degrade` 它，
#: 而 q072 / q092 就这样从**对**变成了**错**。
#:
#: ⇒ 毛病不是"闸门太严"，是**它读不出「我没有作答」和「我编了一个事实」的区别**。
#:   而这正是我们已经量过的那个病:**关系型问题**（"它有没有夸大？"要建模答案的意图）
#:   而不是**分类问题**（"这份答案属于哪一类？"）。
#:
#: ★★ 措辞里那两句**必须同时成立**,否则这个类会变成一个逃生口:
#:   ① **"不作答"** —— 它没有对世界做任何断言;
#:   ② **"理由与证据一致"** —— 例:q001 的草稿声称"工具失败了",而证据显示
#:      `read_doc` **读成功了**。那**不是**诚实拒绝,那是一次 `overclaim`
#:      （它编了一个原因）。这两件事必须能分开,否则我们只是把判据放松了。
OBJECT_ALLOW_CRITERIA = {
    "no_objection": ("the answer commits to a value, and everything it says traces back "
                     "to what the tools returned"),
    "honest_refusal": ("it commits to NO value and says plainly that the evidence does not "
                       "settle the question (the documents are missing it, or they disagree), "
                       "**and the reason it gives is one the evidence supports**"),
    "overclaim": ("it states something the tool output does not support — a value that was "
                  "never observed, **OR a reason the evidence contradicts** "
                  "(for example it blames a tool failure while the evidence shows that call "
                  "succeeded)"),
    "incomplete": "a requirement stated in the task has not been carried out",
    "unsure": "cannot tell from the material given",
}

#: **`gradeRisk` 的确认题** —— 风险档位由规则给，判官只准**往上抬**。
RISK_CONFIRM_ASK = (
    "A deterministic rule graded this call as the risk band shown above. "
    "Judge only whether that grade is right for this specific call."
)
RISK_CONFIRM_CRITERIA = {
    "correct": "that band is right for this call",
    "too_low": ("this call is more dangerous than that band says "
                "— it can do something the band does not cover"),
    "too_high": "this call is safer than that band says",
    "unsure": "cannot tell from the material given",
}

#: ★★★ **交给「生成端」的证据预算** —— 和 `canDeliver` 的帧**不是同一个用途**。
#:
#: `canDeliver` 要**核对**一份草稿,所以它看最近几步就够;
#: 而**写答案的那一次调用要找到那个值**,看不到就等于没有。
#:
#: ★★★ 这是 2026-10-04 实测挖出来的一个**大洞**:`_answer_text` 的提示词里
#:   只有 `# What was done: search; read_doc` —— **工具名字,没有工具输出**,
#:   而 `call_model` 是**无状态**的(每次单条消息的全新补全)。
#:   ⇒ **写答案的模型看不见自己搜集到的证据。**
#:
#:   实测代价(TERNARY,9 道 `supported`):**8 道的答案就在工具输出里,而 0 道答出来了。**
#:   草稿里那句"工具失败了、没有可用证据"**不是编造,是一个盲眼的模型能得出的唯一结论**。
#:   而 `react-termination` 的内层是 `LLMController`(ReAct 的提示词带完整 scratchpad)
#:   ⇒ **它的生成端看得见证据** —— 那就是 8/20 与 14/20 之间的差距。
ANSWER_EVIDENCE_STEPS = 6
ANSWER_EVIDENCE_RESULT_CHARS = 1500

#: ★★★ **`risk_confirm` 什么时候问。** 它是一条**策略**,所以写在这里、进指纹。
#:
#: 实测（2026-10-04）:档位**来自工具声明**时,让判官"确认"它只会得到"说不好" ——
#: ALFWorld **287/291**、TERNARY **29/37**。而那两个数据集的档位都是声明的。
#: ⇒ 声明是常量,不值得问;模式表/认不出来时规则是猜的,才值得问。
#:
#: ⚠️ **这一类"什么时候问"的规则指纹原来盖不住** —— 静态的问题表只能表达
#:   "gradeRisk 问哪几道题",表达不了"其中一道有条件"。所以它必须作为常量登记,
#:   否则改了它而版本没变,**两批数会被当成同一个方法**。
RISK_CONFIRM_WHEN = "band is not declared（声明是常量；模式表/认不出来才问）"

#: 判官说"档位太低"时抬几档。**1 档**,而且**只抬不降**。
#:
#: ★ 为什么是 1：抬到顶（直接判 destructive）会让一次含糊的确认拥有最大的权力；
#:   抬 1 档是"判官发现规则低估了"，而它没有资格替规则定档。
RAISE_STEP = 1

#: ★★★ **工具没声明 `base_risk`、参数也匹配不上任何模式时的档位。**
#:
#: 取 **2 = irreversible ⇒ `ask_human`（fail-closed）**,不是 0。
#:
#: ★ 这一格是规则优先设计里**最危险的地方**,所以单独写出来：
#:   通用工具（`exec` / `act`）的危险取决于这一次的内容,规则**认不出来**
#:   不等于**安全**。默认成 0 就是把"不知道"静默读成"只读" ——
#:   而那正是这条设计要消灭的那类错。
#:   代价如实说：**认不出来的调用会去问人**。要看那些调用有多少,
#:   账上有 `risk_confirm` 那一行的 `source`（`rule:unknown`）。
#:
#: ★ 逐 benchmark 可覆盖（`AlfWorld` 那类全可逆的环境可以声明低一档）——
#:   但**覆盖要写在那个 benchmark 的文件里并给理由**,不许在这里放宽。
UNKNOWN_TOOL_BAND = 2

#: ★★★ **风险模式的声明表** —— 用来在**没有 `base_risk`** 时确定档位。
#:
#: 顺序是判据：**第一条命中就返回**，所以破坏性的模式必须排在前面。
#: 模式跑在 `render_tool_input(arguments)` + 工具名上（小写）。
#:
#: ⚠️ **这张表的覆盖度是这套设计最弱的一环**,如实说：它是领域知识,
#:   认不出的东西会落到 `UNKNOWN_TOOL_BAND`（问人，安全但贵）。
#:   它进 `decision_spec` 指纹 —— 改一个模式就是换了一个方法。
#:   ★ 而 `base_risk`（工具自己声明）**永远优先于这张表**。
RISK_PATTERNS: tuple[tuple[str, int], ...] = (
    # ③ destructive —— 删数据、动分区、关机
    (r"\b(rm|rmdir|shred|mkfs|fdisk|dd|shutdown|reboot|halt|poweroff)\b", 3),
    (r"\b(drop\s+table|truncate\s+table|delete\s+from)\b", 3),
    (r">>?\s*/(dev|etc|boot|sys|proc)\b", 3),
    # ② irreversible —— 离开这台机器、改全局环境、装东西
    (r"\b(git\s+push|git\s+reset\s+--hard|git\s+clean\s+-[a-z]*f)", 2),
    (r"\b(apt|apt-get|yum|dnf|brew|pip|pip3|npm|pnpm|yarn)\s+"
     r"(install|remove|uninstall|publish|upgrade)\b", 2),
    (r"\b(docker\s+(rm|rmi|kill|stop|run)|kubectl\s+(delete|apply))\b", 2),
    (r"\b(sudo|su)\b", 2),
    # ① reversible write —— 改工作目录里的东西
    (r"(?<![0-9])>>?\s*[A-Za-z0-9_./~]", 1),
    (r"\b(mv|cp|chmod|chown|ln|tee|touch|mkdir|rmdir-less)\b", 1),
    (r"\bsed\s+-i\b", 1),
    (r"\bgit\s+(commit|add|checkout|checkout\s+-b|merge|rebase|stash|tag)\b", 1),
    (r"\b(pip|npm|pnpm|yarn)\s+(test|run|build)\b", 1),
    # ① embodied（ALFWorld）：改状态但都可逆
    (r"\b(take|put|move|clean|heat|cool|use|toggle|turn\s+on|turn\s+off)\b", 1),
    # ⓪ read-only —— 看一眼就走
    (r"\b(go\s+to|look|examine|inventory|open|close)\b", 0),
    (r"\b(ls|cat|head|tail|grep|rg|find|wc|stat|file|du|df|pwd|which|type)\b", 0),
    (r"\b(env|printenv|date|whoami|uname|ps|top|diff|sort|uniq|cut|tr|jq)\b", 0),
    (r"\b(curl|wget)\b", 0),
    (r"\bgit\s+(status|log|diff|show|branch|remote)\b", 0),
)

#: 每个节点的门限,**逐条注明出处**。
#:
#: ⚠️ 两个 `choice` 的门限**不一样**（0.6 vs 0.5）—— 这不是笔误,
#: 是 `DECISION.md` 里就写着两个数。用一个全局常量会把其中一个改错,
#: 而**两边都还是「看起来在卡门限」**。
#: ★★ **闸门把"结束"改道回动作空间的上限。**
#:
#: 为什么是 1：和 `revise`/`degrade` 上限同样一条理由 —— 没有上限就是
#: "完不成 → 改道 → 又完不成 → 再改道"的收费循环。1 次够验证这条路通不通，
#: 而它是不是够用（还是该 2–3 次）**是个该由数据回答的问题，我们现在没有**。
MAX_REDIRECTS = 1

#: ★★★ **`pickInput` 的退出口。** 判官可以答"这些动作都不是下一步该做的"。
#:
#: 抄自 μ（`policy.ts`）：没有退出口的 choice 问题，判官**被迫挑一个真选项，
#: 而且挑得很果断**。我们量到的 28 选 1、`top` 贴在 0.5 门限上、
#: 一轮里 `examine cabinet 1` 挑 56 次 —— 都是这一条的下游（见 `Question.escape`）。
#:
#: ★ 选中它**不是出错**，是一个有意义的答案：下一步没有合适的动作了。
#: 处置是**转去尝试收尾**（让 `canDeliver` 判），而不是把这一步判成失败。
PICK_INPUT_ESCAPE = "none_of_the_available_actions"

#: ★★★ **一候选一题的题面**（`pickInput` 的新题形，2026-10-04）。
#:
#: 照 `browser-use/jev-ultrafast`（⭐21,934）与 μ 的 `files.locate`:
#: **每个候选一道有界的小题，候选写在状态里的编号表里，题里只引用编号。**
#:
#: ★ 为什么这才是修法:原来是一道 **N 选 1** 的题（ALFWorld 一步 ~28 个候选，
#: TERNARY 41 个），概率质量摊在 28–41 个都说得通的东西上，
#: 于是众数**贴在门限上**（`top` 0.44–0.55、`accept_below_bar` 188 行、
#: 一个命令重复 18 次）。
#:
#: ⚠️ **关系型不是病,N 选 1 才是。** `files.locate` 的题就是关系型的
#:   （`Is this file likely to contain query?`），而它明写 `capabilities: "relate"`。
#:   一候选一题把每个问题变回**有界、可独立回答**。
PICK_INPUT_CANDIDATE_ASK = (
    "Is `{ref}` an action this task needs next? "
    "Judge only this one action — the other candidates are judged separately, "
    "and `how_this_world_works` tells you what actions do in this world."
)
PICK_INPUT_CANDIDATE_SUFFICES_ASK = (
    "The task, current evidence, and actions already done remain in view regardless. "
    "Is `{ref}` still needed to make progress now? "
    "Judge only this one action — the other candidates are judged separately, "
    "and `how_this_world_works` tells you what actions do in this world."
)
PICK_INPUT_ADMISSION_UNCLEAR = "Cannot tell from the supplied evidence."
PICK_INPUT_CANDIDATE_CRITERIA = {
    "true": "doing this now is required by the task, or is a necessary step towards it",
    "false": ("it is not what the task needs next — already done, out of order, "
              "or irrelevant to the goal"),
}

#: ★★★ **`pickInput` 的题形。两种,而且它们是两个方法。**
#:
#:   `"admission"`    一候选一题 + 策略排序。每道题问「做这一个是不是下一步」,
#:                    逃逸是**推导出来的**（没有任何候选过线）。
#:   `"comparative"`  一道 N 选 1。判官在同一张选项表里**互相比较**。
#:
#: ★★★ **默认是 `"comparative"` —— 这是量出来的,不是选出来的。**
#:   我原来写下的结论是「N 选 1 的 argmax 是病,一候选一题是修法」
#:   （`docs/ACTION-SELECTION-LESSONS.md`,从 μ / `jev-ultrafast` 读出来的）。
#:   做完之后在**两个数据集上各量了一遍**,它**都是更差的那一个**:
#:
#:     ========== ========================= =========================
#:     数据集      admission（一候选一题）    comparative（N 选 1）
#:     ========== ========================= =========================
#:     TERNARY    8, 8, 9, 9 / 20           15, 12, 12, 12 / 20
#:     ALFWorld   0 / 20                     3 / 20
#:     ========== ========================= =========================
#:
#:   ⇒ 数字说话:默认回到比较型。准入型**留着**,而且有它自己的臂
#:     （`react-typed-admission`）—— 它是一个**已测的负结果**,不是一个被删掉的尝试。
#:
#: ★ 两个形状都留着还有第二个理由:**它们不能混进同一张表** ——
#:   所以它是契约的一部分、进指纹。
PICK_INPUT_SHAPE = "comparative"

#: `pick_input_shape` 的默认值 —— **"自动":让环境说。**
#:
#: ★★★ 为什么默认不是那两个值之一,而是 `"auto"`:两种问法**没有全局胜负**
#:   （见 `PICK_INPUT_SHAPE` 的数字）,胜负取决于**候选的结构**,而候选集是
#:   环境给的（`Tool.live_candidates`）—— 所以"该用哪种"这个事实**只有环境知道**。
#:   环境没说（`Tool.candidate_shape = None`）才落到上面那个全局默认。
#:
#: ★★ 为什么必须区分"自动"和"显式指定":对照臂靠 `pick_input_shape=…` 强制某一种。
#:   如果工具声明**永远**压过控制器,RUN 起来会是这样 ——
#:   `react-typed-singlechoice` 名义上"强制 N 选 1",实际跑的是工具声明的
#:   `comparative`,于是它在 TERNARY 上量出来的数和 `react-typed` 一模一样
#:   （实测 10/20、12/20 对 11/20、12/20）—— **臂名在说谎,而且不报错。**
#:   这正是这个仓库反复栽的那个形状（"配了没生效"）。
#:   ⇒ 优先级:**显式指定的臂 > 环境声明 > 全局默认**。
PICK_INPUT_SHAPE_AUTO = "auto"

#: ★ **改名不改语义** —— 旧拼法映射到新拼法。
#:
#:   `"single_choice"`  → `"comparative"`（同一个东西,当初叫"一道 N 选 1"）
#:   `"per_candidate"`  → `"admission"`  （同一个东西,当初叫"一候选一题"）
#:
#: ★ 为什么要留别名而不是直接改字面量:`react-typed-singlechoice` 这个**臂名**
#:   和它底下 6 个已落盘的 run 都在用旧拼法。直接改字面量会让那些 run 的臂名
#:   从"已知的臂"变成"未知的臂"（`scripts/check.py` ③ 会红）,于是要么改臂名
#:   （6 个目录跟着动）要么把它们挪进 `_superseded/`（丢掉可追溯性）。
#:   而**旧 run 跑的就是 comparative** —— 别名让它继续成立,一个字都不用搬。
#:
#: ⚠️ 只认这两个。拼错了**不是**静默落到默认,而是在下面当场抛错:
#:   一个拼错的形状名会让这个臂**悄悄变成另一个方法**,那正是要防的。
PICK_INPUT_SHAPE_ALIASES = {
    "single_choice": "comparative",
    "per_candidate": "admission",
}

#: `_arguments` 用这个哨兵告诉调用方「判官说没有动作合适」——和「出错了」分开。
NO_ACTION_FITS = "__no_action_fits__"

#: 指针题的 id 后缀 —— `canDeliver` 的两道题共用一份帧，名字不能撞。
_POINTER_SUFFIX = "::pointer"

#: ★★★ **低于门限时怎么办** —— 逐节点，不是一个全局开关。
#:
#:   `"drop"`（默认）= 丢掉这个答案 ⇒ 这一步不成立 ⇒ 循环重试。
#:   `"accept"`      = 照用最佳候选，但**在账上记明它低于门限**。
#:
#: ★ 为什么必须有 `"accept"` 这一档（实测，2026-10-02）：
#:
#:   `pickInput` 在 ALFWorld 上被丢掉之后，循环**重发同一个请求**。
#:   而那个请求是**逐字节相同**的（判定记录里 `request_digest` 一样）——
#:   于是「重试」不是错误恢复，是**重新抽一次**：
#:
#:       同一 digest 出现多次的 20 组里，**19 组的置信度不同**（0.44 / 0.40 / 0.46）
#:
#:   连撞 3 次就 `escalate`。实测 20 题里 **13 题**是这样死掉的，
#:   而不是因为 Jev 不会做那些题。
#:
#: ★★★ **2026-10-04 修正:上面那句「重试一个相同的请求是抽奖」说重了。**
#:   抖的是**置信度**,不是**决定**。按决定级重算同一个 20 题的账
#:   （`noul` 看 `prob_true() >= 门限`,`choice` 看选了哪个,`score` 看档位）:
#:
#:       stepOk    35/35 一致   risk 32/33   needs_auth 33/33   pickTool 34/34
#:       needsTool  7/7         isDone 5/5   deliverable 4/4    unsupported 4/4
#:       pickInput  4/6  ← **只有它真的会翻(2 个状态翻了)**
#:
#:   ⇒ 所以这一档**只对 `pickInput` 成立**,而且理由比原来写的窄得多:
#:     它是唯一一个"决定本身就是近似平局"的节点。
#:     ★ 而更值钱的那条结论是反过来的:**阈值型策略会把稳定的决定变成不稳定的**
#:     —— `risk` 的决定 32/33 稳定,却被一个读**置信度**的 0.5 门限丢掉了,
#:     20 题里 4 题因此死掉（`docs/ALFWORLD-ESCAPE.md` §4）。
#:     ⇒ **读决定,不要读置信度** —— 这正是 `typed-4` 那两道确认题门限取 0 的理由。
#:
#: ★ 判据是**这个节点的失败能不能被循环观测到并纠正**：
#:
#:   · `pickInput` / `pickTool` 选的是**动作** ⇒ 能。动作一执行就有新观测，
#:     走错了下一轮 `stepOk` / `isDone` 会看见。**行动换信息；弃答什么都换不到。**
#:   · `canDeliver` / `gradeRisk` **不可以**：前者的产物是**要交出去的答案**
#:     （放行一个不果断的答案 = 直接放走一次可能错误的交付），
#:     后者管的是**不可逆动作**（`DECISION.md` 的授权闸门）。
#:
#: ⚠️ 这一档**不调门限**。把 0.5 挪走只会换个位置抛硬币，而且会在评测集上过拟合。
#:   改的是**门限没过之后发生什么**，那件事不需要校准集。
#:   见 `docs/DECIDER-JITTER.md`。
BELOW_THRESHOLD_POLICY: dict[str, str] = {
    "pickInput": "accept",
}

#: ★★★ **判定压根没答出来时怎么办** —— 逐节点声明，**不许静默**。
#:
#: 抄 μ（`kyrn-judge`）:它的 `DecisionSpec` **必须**写一个 `fallback`,
#: 判定不出来就**照它执行,并把 `source` 记成 `"fallback"`**。
#: 它的理由不是"优雅",是**兜底可以发生,但不能没有名字**。
#:
#: ★ 它和 `BELOW_THRESHOLD_POLICY` 是**两件事**,所以是两张表:
#:
#:   · `BELOW_THRESHOLD_POLICY` = 模型**答了**,但不够果断（`top < threshold`);
#:   · `FALLBACK_POLICY`        = 模型**没答**（后端丢了 / 形状畸形 / 校验没过）。
#:
#: ⚠️ 名字写的是**动作**,不是好恶 —— 读到 `"retry"` 就知道这一步会
#: 原样重发,读到 `"no_action_fits"` 就知道它转去收尾。
#:
#: ★★★ **闸门那一档是我们和 μ 唯一的真冲突,而且是有意保留的。**
#:
#:   μ 是**生产判官库**:它兜底的第一目标是"别卡住用户的请求",
#:   所以它的 `fallback` 默认是 fail-open（照最保守的选项往下走）。
#:   我们是**评测**控制正确性:闸门 fail-open 的意思是
#:   **放走一次没有任何东西为它背书的交付**,而"放走了多少次"没法从结果里看出来
#:   —— 那会把评测变成不可证伪。
#:
#:   ⇒ 决议:**闸门保留 fail-closed**（`"reject"`）,但**必须记名**。
#:     于是「闸门拦截里有多少次其实是兜底而不是判断」变成一个可查的数,
#:     而不需要把闸门改成 fail-open。
#:     见 `docs/MU-CONFLICT.md`。
#:
#: ★★★ **一个判定点由哪几道题组成** —— `shadow` 一个判定点就 shadow 它全部子问题。
#:
#: 为什么要这张表:`shadow` 的单位是**判定点**（"交付闸门要不要信"），
#: 而 `_ask_many` 看到的是**题**（`deliverable` / `unsupported`）。
#: 靠命名前缀去猜（`q.node.startswith("canDeliver")`）在这种地方一定会漏 ——
#: `gradeRisk` 的两道题叫 `risk` / `needs_auth`,和判定点**一个字都不重**。
DECISION_QUESTIONS: dict[str, tuple[str, ...]] = {
    "needsTool": ("needsTool",),
    "pickTool": ("pickTool",),
    "pickInput": ("pickInput",),
    "stepOk": ("stepOk", "stepOk::environment"),
    "isDone": ("isDone", "isDone::environment"),
    "gradeRisk": ("risk", "needs_auth", "risk_confirm"),
    # ★ 规则优先那一版的两道确认题 —— 名字带前缀，和旧版**不会撞**。
    #   两版并存是为了能跑 A/B，不是为了兼容：`gates_rules_first` 一开，
    #   旧的两道题（`deliverable`/`unsupported`）**一次都不问**。
    "canDeliver": ("deliverable", "unsupported",
                   "deliverable::confirm", "deliverable::object"),
    "canDeliver::rules": ("deliverable::empty", "deliverable::grounding",
                          "deliverable::no_evidence",
                          "deliverable::confirm", "deliverable::object"),
}

#: ★★★ **只观察、不落地的判定点**（照 μ 的 `shadow` 模式）。
#:
#: μ 的三种模式（`decision.ts`）:
#:
#:   `off`    判定模型**不问**,直接返回 `fallback`（= 没有判官时宿主的行为）
#:   `shadow` **问了、也记了,但返回的仍然是 `fallback`** ——
#:            "新的判定点先停在这里,直到它的裁决和结果比对过"
#:   `active` 返回判定结果（除非弃答或调用失败）
#:
#: ★ 我们以前**没有这一档**:一个节点要么接着、要么没接。
#:   于是「这条判定要是有用吗」这个问题**从日志里答不出来** ——
#:   每一次对比都是**两个不同的 agent 在比**,而不是「同一条轨迹上的两种裁决」。
#:   这也是审稿人对"自定义指标"那条质疑的另一面:μ 把指标和**验证指标的手段**
#:   一起发了,而我们只发了指标。
#:
#: ⚠️ 默认空 —— **不许默认 shadow**,否则跑出来的分数是"没有判官"的分数,
#:   而它看起来和"接了判官"一模一样。
SHADOW_DECISIONS: frozenset[str] = frozenset()


#: ★ `pickInput` 的 `"no_action_fits"` 是**唯一一处 fail-open**,而且是有依据的:
#:   弃答之后重发**逐字节相同**的请求 = 重新抽一次
#:   （实测 20 组同 digest 里 19 组置信度不同）,实测 **13/20 题**是这样死的。
#:   fail-open 到退出口不是"放行动作",是**转去问闸门** —— 闸门仍然拦得住
#:   （它会把话说回来,理由进帧,`MAX_REDIRECTS=1`）。
FALLBACK_POLICY: dict[str, str] = {
    # 动作类 —— 弃答 ⇒ 循环重试（fail-closed:宁可不动,不可乱动）。
    "needsTool": "retry",
    "pickTool": "retry",
    "pickInput": "no_action_fits",
    # 事后判定类 —— 弃答 ⇒ 当"这一步没成 / 没做完"处理。
    "stepOk": "retry",
    "isDone": "retry",
    # 闸门类 —— 弃答 = 不放行。
    "canDeliver": "reject",
    "gradeRisk": "reject",
    "needs_auth": "reject",
    # ★★★ **规则优先那一版的两道确认题没有"放行/不放行"可言。**
    #   它们是**报告**，不是决定：缺答的意思只是"没听到判官的立场"，
    #   而裁决已经由规则那一层给出了。所以这里的名字是 `rule_stands` ——
    #   读到它就知道**这一次行为由规则决定，判官没说话**。
    #   ⚠️ 把它们写成 `"reject"` 会让「判官缺席」重新变成拒绝 ——
    #     那正是这次要消灭的东西（`docs/ALFWORLD-ESCAPE.md` §4）。
    "deliverable::confirm": "rule_stands",
    "deliverable::object": "rule_stands",
    "risk_confirm": "rule_stands",
}

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


# ═══════════════════════════════════════════════════════════
# ★★★ 判定规格的**版本 + 指纹** —— "同一个方法"这句话的可核对形式
# ═══════════════════════════════════════════════════════════
#
# 抄 μ 的 `DecisionSpec.version`：它的原话是
#
#   > Bump whenever question wording or policy changes, so ledger records stay comparable.
#
# ★ 我们的缺口比它小、但更难看:meta 里有 `commit` + `dirty` + `prompt_hash`,
#   而 **`prompt_hash` 只覆盖 `benchmark:dataset_version:arm`** ——
#   问法的字改了、门限挪了、兜底换了,这三样**一个都不动**。
#   于是"那两批是同一个方法吗"在盘上**答不出来**（`docs/MU-CONFLICT.md` 第 6 行）。
#
# ★★ μ 靠纪律（改了记得 bump）。我们把它做成**机械的**:
#   下面这张表列出所有参与指纹的常量,`test_the_decision_spec_fingerprint_is_pinned`
#   钉住摘要值 —— 改了字面量而没 bump 版本,测试就红。
#   还有第二条测试:模块里**任何一个大写常量没进这张表**也红,
#   所以不存在"新增了一个问法而忘了登记"这条路。
#
# ⚠️ 指纹**不覆盖注释**。注释改了不必 bump —— 否则大家会习惯性地 bump 而不去想。
#: ★ `typed-9` —— ★★★ **`pickInput` 改成一候选一题**（2026-10-04）。
#:   候选编号化进状态（`jev-ultrafast::action_space`）、N 道有界小题一次问完、
#:   而**逃逸从"一个选项"变成"没有任何候选过线"**。旧形状留在
#:   `pick_input_shape="single_choice"` 下当对照臂。
#: ★ `typed-8` —— **不可枚举参数的生成拿到"这一栏要什么形状"**（`Tool.argument_hints`）。
#:   在这之前 `search.query` 的提示只有「give only the value」,于是模型把**自己的结论**
#:   当搜索词发出去 —— `contradiction` 那 5 道全部死于"检索根本没发生"。
#: ★ `typed-7` —— ★★★ **生成端拿到工具输出了**（2026-10-04）。在那之前它只有工具**名字**,
#:   而无状态调用 ⇒ 写答案的模型看不见证据。**这是 9 道 `supported` 全灭的原因。**
#: ★ `typed-6` —— **交付闸门加了一类 `honest_refusal`**（2026-10-04）。
#:   旧选项集下"诚实的拒绝"只能落进 `overclaim` ⇒ 被打回 ⇒ `degrade` 它,
#:   而 `q072`/`q092` 就这样从对变成错。**闸门读不出「我没作答」和「我编了个事实」。**
#: ★ `typed-5` —— **证据预算按实测的窗口重设**(32K token，不是那句没出处的 512/1024)，
#: 并且 `pickInput` 补上了 `last_result`。帧的**内容**变了 ⇒ 与 typed-4 不可比。
#: ★ `typed-4` —— 闸门改成**规则先筛、判官只确认**（用户 2026-10-04 的决定）。
#: ★ `typed-3` 及以前 —— **判官产生裁决**。三批数字**不能进同一张表**。
DECISION_SPEC_VERSION = "typed-14"

#: `allow_choices_without_escape` 的**离线说明** —— 见那个字段的文档。
#: ★ 它是一份**声明**，不是一个可调的参数:打开它的批次是另一个方法。
ALLOW_CHOICES_WITHOUT_ESCAPE_DOC = (
    "允许 choice 问题没有退出口 —— 只用来做单变量对照,打开它的批次必须另列一张表"
)

#: `gates_rules_first` 的**离线说明**。
GATES_RULES_FIRST_DOC = (
    "闸门是规则先筛还是判官产生裁决 —— 两版是两个方法,批次必须分开列"
)

#: 参与指纹的常量名（`typed.py` 与 `frame.py` 两边）。**漏一个就有测试红。**
DECISION_SPEC_PARTS: tuple[str, ...] = (
    # 问法字面量 + 判据说明
    "NEEDS_TOOL_ASK", "NEEDS_TOOL_CRITERIA",
    "PICK_TOOL_ASK", "PICK_INPUT_ASK", "STEP_OK_ASK", "STEP_OK_CRITERIA",
    "IS_DONE_ASK", "IS_DONE_CRITERIA", "GRADE_RISK_ASK", "RISK_LEGEND",
    "NEEDS_AUTH_ASK", "NEEDS_AUTH_CRITERIA",
    "DELIVERABLE_ASK", "DELIVERABLE_CRITERIA",
    "UNSUPPORTED_ASK", "UNSUPPORTED_CRITERIA",
    # ★ 每个候选的说明文字**就是判据本身** —— 它改了就等于换了问法。
    "_PICK_INPUT_CRITERIA", "_PICK_INPUT_ESCAPE_CRITERION", "_PICK_INPUT_FALLBACK",
    # ★ 闸门的规则层 —— 证书表与风险模式表**就是方法本身**
    "DELIVERY_CERTIFICATES", "NOT_YET_CERTIFICATES", "RISK_PATTERNS",
    "UNKNOWN_TOOL_BAND", "RAISE_STEP", "RISK_CONFIRM_ASK", "RISK_CONFIRM_CRITERIA",
    "RISK_CONFIRM_WHEN", "ANSWER_EVIDENCE_STEPS", "ANSWER_EVIDENCE_RESULT_CHARS",
    "PICK_INPUT_CANDIDATE_ASK", "PICK_INPUT_CANDIDATE_CRITERIA", "PICK_INPUT_SHAPE",
    "PICK_INPUT_ADMISSION_UNCLEAR", "PICK_INPUT_CANDIDATE_SUFFICES_ASK",
    # ★ `PICK_INPUT_SHAPE_AUTO` 也进指纹:它不是"跑法",它决定
    #   `shape = 环境声明 or 全局默认` 这条解析规则 —— 拿掉它,
    #   `pick_input_shape` 的默认值就从"自动"变成"某一种",那是另一个方法。
    "PICK_INPUT_SHAPE_AUTO", "PICK_INPUT_SHAPE_ALIASES",
    "CONFIRM_BLOCK_ASK", "CONFIRM_BLOCK_CRITERIA",
    "OBJECT_ALLOW_ASK", "OBJECT_ALLOW_CRITERIA",
    # 出口与哨兵
    "DONE", "PICK_INPUT_ESCAPE", "NO_ACTION_FITS",
    # 策略与门限 —— **改一个数就是换了一个方法**
    "NODE_THRESHOLDS", "BELOW_THRESHOLD_POLICY", "FALLBACK_POLICY",
    "DECISION_QUESTIONS", "MAX_REDIRECTS",
    # 帧的装配（`frame.py`）
    "NODE_FRAMES", "MAX_OPTIONS", "MAX_REQUEST_CHARS", "MAX_LISTED_CANDIDATES",
    "MAX_QUESTIONS", "EVIDENCE_INPUT_CHARS", "EVIDENCE_WRITE_INPUT_CHARS",
)

#: 有意**不进**指纹的常量（写清楚为什么,免得下一个人以为是漏了）。
DECISION_SPEC_IGNORED: tuple[str, ...] = (
    "SHADOW_DECISIONS",   # 跑法,不是方法:shadow 的批次本来就另列一张表
    "DECISION_SPEC_PARTS", "DECISION_SPEC_IGNORED", "DECISION_SPEC_VERSION",
    # 题 id 的后缀（不是问法）—— 它只影响 `request_digest`
    "_POINTER_SUFFIX",
    # ★ 它改的是**方法**,但改法是"换一套方法",不是"微调当前这套" ——
    #   打开它的批次和默认批次**本来就该分开列**（`allow_choices_without_escape`）。
    #   把它塞进指纹会让两个 arm 共用一个规格版本号,那反而更糊涂。
    "ALLOW_CHOICES_WITHOUT_ESCAPE_DOC",
    # ★ 同上:`gates_rules_first` 也是"换一套闸门",两版各自的问法**都已经**
    #   在指纹表里（旧版的 `DELIVERABLE_ASK`… 和新版的 `CONFIRM_BLOCK_ASK`…），
    #   所以指纹覆盖的是"两套问法长什么样",而哪一个开关选哪一套由 arm 名记着。
    "GATES_RULES_FIRST_DOC",
    # 检索用的正则（数字落地的判据）—— 是**校验**规则,不是问法
    "_NUMBER", "_LIST_MARKER",
)


def decision_spec_digest() -> str:
    """问法 + 门限 + 兜底的指纹。**改任何一项它都会变。**

    ★ 用 `repr` 而不是 `str`:字典的顺序、`True/False`、元组和列表的差别
      都要在指纹里 —— 用 `str` 的话 `{"a":1}` 和 `{'a':1}` 看起来一样,
      而它们改的是同一份数据的两种写法（这里不该出现这种歧义）。
    """
    import hashlib
    import sys

    from experiments.core import frame as frame_mod

    # ★★★ **这里原来有一个 bug，而且它藏了很久（2026-10-04 才发现）:**
    #
    #   旧代码是 `holder = frame_mod if hasattr(...) else globals()`,
    #   然后 `getattr(holder, name, "<missing>")`。
    #   而 **`globals()` 返回的是 dict** —— `getattr` 在 dict 上取不到任何东西，
    #   于是 **`typed.py` 那 27 个常量全部被记成 `'<missing>'`**。
    #
    #   ⇒ 那个指纹其实**只覆盖了 `frame.py` 那 7 个**（帧字段、预算），
    #     而它声称覆盖的问法、判据、门限、兜底表 **一个都没进去**。
    #     `test_the_decision_spec_fingerprint_is_pinned` 一直「通过」，
    #     因为它比的是"version + 7 个帧常量 + 27 个 `<missing>`"。
    #
    #   ⚠️ **发现它的路径值得记下来**:给 `OBJECT_ALLOW_CRITERIA` 加了
    #     `honest_refusal` 一类（一个真的语义改动），指纹**一点没动**。
    #     如果那次改动没被别的东西挡住，这个 bug 会一直不被发现。
    #     ⇒ 所以下面加了一条守卫:**任何一个 part 取不到就红**。
    #
    #   `sys.modules[__name__]` 拿到的是**模块对象**，`getattr` 在它上面是好的。
    me = sys.modules[__name__]
    blob: list[str] = [f"version={DECISION_SPEC_VERSION}"]
    for name in DECISION_SPEC_PARTS:
        holder = frame_mod if hasattr(frame_mod, name) else me
        blob.append(f"{name}={getattr(holder, name, '<missing>')!r}")
    return hashlib.sha256("\n".join(blob).encode("utf-8")).hexdigest()[:16]


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
                     frame: str = "",
                     escape: str | None = None,
                     closed: bool = False) -> Question:
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
    # ★★★ **choice 必须有退出口** —— 照 μ 的 `defineDecision`：没有就不许注册。
    #
    #   理由见 `Question.escape`。这不是风格问题：一个 28 选 1 的强制选择会让
    #   判官**没法说"这些都不合适"**，而它的所有症状（top 贴在门限上、
    #   反复挑同一个不产出的动作）我们都已经量到了。
    if escape is None and not closed:
        raise ValueError(
            f"{node}: choice 问题没有退出口（escape）。"
            f"判官会在『一个都不合适』的时候被迫挑一个真选项 —— "
            f"而且挑得很果断（抄自 μ 的 `policy.ts`）。"
            f"要么给 escape=，要么显式声明 closed=True 并写明为什么这个选项集是封闭的。")
    if escape is not None and escape not in options:
        raise ValueError(f"{node}: escape={escape!r} 不在选项里")
    return Question(node=node, kind="choice", ask=ask, options=tuple(options),
                    threshold=threshold, criteria=dict(criteria or {}), frame=frame,
                    escape=escape or "", closed_choices=bool(closed))


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


def candidates(session: Session, ctx: AgentCtx, *, redirected: bool = False) -> list[str]:
    """**这一步**能选的工具。§8.4 的落点。

    ★ 做过的动作**在这里删掉,不是在帧里提示一句** —— 提示是可以被无视的,
    而候选列表是模型唯一能选的东西。

    ★★ **删掉之后必须补一个 `DONE`** —— 见上面那段。少了它,
      第一次调对之后候选里**只剩错的选项**,而模型没有别的可挑。

    ⚠️ 注意这只是**工具级**的去重。同一个工具做两次常常是合理的
    （读两个不同的文件）,所以删的是**已经做过的那一次动作**,
    而 `pickInput` 会在参数那一层再算一次候选。

    ★★★ **`redirected=True` 时上面两条都不适用**，因为正向路径和改道
    **问的不是同一个问题**：

        正向：还有什么事**没做过**？  —— 去过重，并给出口 `DONE`
        改道：缺的是哪一块？         —— **不去重、不给出口**

    两个理由，都是实的：

      · **去重的依据是工具名**，而"回去做"经常就是**换个参数再做一次** ——
        ALFWorld 那一类里 `go to X` → `go to Y` 是**同一个动词**，
        按名字去重会把唯一能补上缺口的那一步删掉。
      · **`DONE` 是刚刚被驳回的那个动作**。闸门刚判"没做完"，再把出口端上来
        是自相矛盾的；模型顺手再挑一次 `DONE` 就白跑一轮判定，然后撞上限退化。
        （和上面「一次都没做时不给 DONE」同源：出口要给得看时候。）
    """
    if redirected:
        return [t.name for t in session.tools]
    done = {r.tool for r in ctx.records()}
    left = [
        t.name for t in session.tools
        # ★★★ **带 `live_candidates` 的工具永远不去重。**
        #
        #   上面那句注释（"删的是**已经做过的那一次动作**"）说的是**动作级**去重，
        #   而代码一直是**工具级**的（`done` 收的是 `r.tool`）。两者在多工具数据集上
        #   重合（BFCL：一个工具一件事），在**单工具 + 参数化**的环境上差得离谱：
        #
        #       ALFWorld 只有**一个**工具 `act`，参数是命令原文，
        #       合法命令由环境**每步重建**（实测开局 28 条，走到 cabinet 1 之后全换）。
        #       ⇒ 按工具名去重的话，调一次 `act` 之后候选就只剩 `[DONE]`，
        #         **循环会在第一步就收尾** —— 那不是"做完了"，是"没得选了"。
        #
        #   ★ 判据是"**这个工具还能不能再做一次有意义的事**"：
        #     有 live_candidates ⇒ 能（换个参数就是另一步）；没有 ⇒ 按名字去重。
        if t.name not in done or t.live_candidates is not None
    ]
    # ★ 只要**已经做过什么**,就给出口。一次都没做时不给 ——
    #   那时「不做了」应当由 `needsTool` 回答,而它的帧正是为那个问题准备的。
    return (left + [DONE]) if done else left


@dataclass(frozen=True)
class Redirect:
    """闸门把"结束"改道回动作空间 —— **带上"为什么"**。

    ★★ 为什么不能只传一个 `None`：`_can_deliver` 明明算出了**缺什么**
      （它读了草稿和任务要求），而改道把控制流送回动作路径时，
      那条信息原来**被扔掉了** —— 于是 `pickTool` 看到的是和之前**一模一样**的帧。
      **那是盲改道**：它确实去调了工具（不是重写），但没有任何依据挑对那一个。
    """

    reason: str
    feedback: str


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
    #: ★★ **闸门把"结束"改道回动作空间**的次数（上限见 `MAX_REDIRECTS`）。
    #:
    #: 为什么需要它：闸门说"任务没做完"时，**光重写文本是错的补救** ——
    #: 实测（`fta × react-termination`）那 8 条编造的第一判全都是
    #: `deliverable` 低（0.12–0.31，即"没做完"），循环却只能再写一版，
    #: 于是改完 `unsupported` 冲到 0.86–0.99（"超出证据"）。
    #: 正确的补救是**回去把没做的事做掉**。所以改道必须有，而且必须有上限 ——
    #: 不然就是"完不成 → 改道 → 又完不成 → 再改道"的收费循环。
    redirects: int = 0
    #: ★★★ **闸门：规则先筛、判官只确认**（用户 2026-10-04 的决定）。
    #:
    #: `True`（默认）= 两道闸门的**裁决由规则产生**，判官只准**收紧**：
    #:
    #:   · `canDeliver` 规则层只有三条**证书**（`DELIVERY_CERTIFICATES`）；
    #:     有证书 ⇒ BLOCK，判官确认那条理由（否定也不放行）；
    #:     没证书 ⇒ ALLOW，判官可以提出一个证书查不出的问题（这是唯一能产生
    #:     结果的权力，而且它只**命名**疾病，不产生裁决）。
    #:   · `gradeRisk` 风险档位由**规则**给（`base_risk` → `RISK_PATTERNS`
    #:     → `UNKNOWN_TOOL_BAND`），判官只准**往上抬**。
    #:
    #: `False` = 旧的那一版：判官答 `deliverable`/`unsupported`/`score:risk`，
    #: **裁决由它产生**。★ 留着它是因为**它是这一批所有已测数字的那个方法** ——
    #: 两批不能进同一张表，`DECISION_SPEC_VERSION` 会随之 bump。
    #:
    #: ★★ 换掉的是**裁决的来源**，不是"要不要问模型"：两版都问，
    #:   区别是规则那一版把"不确定"从**拒绝**里彻底移除了。
    gates_rules_first: bool = True

    #: ★★★ **允许 choice 问题没有退出口** —— 名字照抄 μ 的
    #: `DecisionSpec.allowChoicesWithoutEscape`。
    #:
    #: 默认 `False`：`_choice_question` 会**抛错**（`policy.ts` 那条规则）。
    #: 打开它 = **声明这个候选集真的是封闭的**,而不是"忘了加退出口"。
    #:
    #: ★ 它存在的理由是**做对照**:退出口是这一批新加的结构,而
    #:   "它到底有没有用"只能靠**只改这一个开关**的 A/B 答。
    #:   没有这个开关,前后两批的差会同时带着帧改动、判据改动和别的修复 ——
    #:   实测就撞上了:13:56 那批（`declined` 13/20）**早于** `already_done`
    #:   进帧那一次修复,所以拿它当基线,量到的是"帧+判据+退出口"三件事的和。
    #:   ⚠️ 打开它的批次**必须和默认批次分开列**：它们是两个不同的方法。
    allow_choices_without_escape: bool = False

    #: ★★ `pickInput` 的题形。**默认 `"auto"` = 让环境说**
    #:   （`Tool.candidate_shape`,环境没说才落到 `PICK_INPUT_SHAPE`）。
    #:   显式写 `"comparative"` / `"admission"` = **压过环境声明** ——
    #:   对照臂靠这一条才成立,理由见 `PICK_INPUT_SHAPE_AUTO`。
    pick_input_shape: str = PICK_INPUT_SHAPE_AUTO
    # A1a changes only the answer type; keep the measured boolean control.
    admission_answer_kind: str = "noul"
    admission_question_form: str = "relational"
    # A2 changes only low-score routing, not missing-answer handling.
    admission_low_score_policy: str = "finish"

    #: ★★★ **只观察、不落地的判定点**（照 μ 的 `shadow` 模式）。
    #:
    #: 语义按判定点逐个定,统一的那一句是 μ 的原话:
    #: **判定模型被问了、也被记了,但返回的是"没有判官时宿主会返回的东西"。**
    #:
    #:   · `canDeliver`  ⇒ **照交**（没有闸门时宿主的行为就是交出去）。
    #:     裁决本身记成一行 `canDeliver::shadow`,于是
    #:     「闸门说 revise 的那些,草稿到底对不对」可以**离线**算出来 ——
    #:     这正是我们以前答不出"这条判定有没有用"的那一格。
    #:   · 动作类（`pickInput` 等）⇒ 走 `FALLBACK_POLICY` 里那一档,
    #:     也就是"判官没答"时的行为。
    #:
    #: ⚠️ **`shadow` 的批次不能和 `active` 的批次混进同一张表** ——
    #:   前者的分数是"没有判官"的分数。判据是 `canDeliver::shadow` 那一行在不在。
    shadow: frozenset[str] = SHADOW_DECISIONS

    @property
    def _shadowed_questions(self) -> frozenset[str]:
        """`shadow` 的**题**集合 —— 由 `DECISION_QUESTIONS` 展开,不靠名字猜。"""
        return frozenset(
            q for d in self.shadow for q in DECISION_QUESTIONS.get(d, ())
        )

    def gate_is_shadowed(self) -> bool:
        """交付闸门是不是"只观察"。`termination_only` 那一臂也要认这一档。"""
        return "canDeliver" in self.shadow

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

        # ★ 这一轮**是不是被闸门改道过来的** —— 决定候选集用哪一套（见 `candidates`）。
        redirected = False

        if need.prob_true() < self.yes:  # noqa: SIM201 —— 刻意留成可覆盖的
            # ★ 用 `prob_true()`（「是」的概率）,不是 `top()`（果断程度）——
            #   这里问的是「还要不要动作」,答案本身是「是/否」。
            #   一个**果断的「否」**（noul=0.05）在 `top()` 上是 0.95,
            #   拿它来比就会得出「很确定还要工具」—— 正好反了。
            d = self._finish(session, view, ctx, why=f"needsTool={need.noul:.3f}",
                             batch=batch, may_redirect=True)
            if isinstance(d, Redirect):
                # ★★★ **闸门把"结束"改道了，而且把"为什么"带了下来。**
                #   `needsTool` 说"不用动作了",而交付闸门判"任务没做完"——
                #   两句矛盾,而**以闸门为准**:判据读的是刚生成的那一份草稿和证据,
                #   比一个事先的猜测更有依据。
                #
                #   ★ 那条理由**必须进帧**（`redirect_note`），否则动作路径是盲的：
                #     它确实会去调工具,但没有任何依据挑对那一个。
                #     实测代价见 `Redirect` 的说明。
                ctx.redirect_note = (
                    f"A previous delivery was rejected ({d.reason}): {d.feedback}"
                )
                redirected = True
                self.trace.append({
                    "step": view.step, "node": "canDeliver",
                    "violation": "redirect_overrides_needsTool", "fatal": False,
                    "answer": f"revise/{d.reason}", "remedy": "redirect",
                    "detail": (f"needsTool={need.noul:.3f} 说「不用动作了」，"
                               f"而交付闸门判「没做完」⇒ 回到动作空间"
                               f"（第 {self.redirects}/{MAX_REDIRECTS} 次改道）；"
                               f"理由已进帧"),
                })
            else:
                return d
            # ★ 落到下面那一段**不是重新问一遍 `needsTool`** —— 是直接进
            #   `pickTool`,所以不会"改道 → 又问一次 → 又说不用 → 死循环"。

        # ②′ 挑哪个工具 —— **候选在这一步重建**（§8.4）
        # ★ 改道时用**另一套候选**：不去重、不给 `DONE`（理由见 `candidates`）。
        #
        # ★★★ **这一整段放在循环里，因为闸门有两条改道入口。**
        #
        #   ① `needsTool` 说"不用动作了"而闸门说"没做完" ⇒ 落到这里（上面那条路）；
        #   ② `pickInput` 选了退出口而闸门说"没做完" ⇒ **也必须落到这里**。
        #
        #   ⚠️ ② 以前是 `return self._finish(..., may_redirect=True)` —— 直接把
        #   `Redirect` 对象返回给 `run_loop` 了。实测（2026-10-03，ALFWorld seed20261020）
        #   当场炸：`AttributeError: 'Redirect' object has no attribute 'kind'`，
        #   整道题 `stop_reason="error"`、0 步。**`_finish` 的返回类型是联合类型，
        #   而只有一条调用点检查过它** —— 加第二条调用点时没人检查。
        #   ⇒ 两条路共用同一个处置：理由进帧 + 重进这里。
        #
        # ★ 不会死循环：`_finish` 里 `self.redirects += 1`，而 `_remedy` 见
        #   `self.redirects >= MAX_REDIRECTS` 就不再说 `redirect`。
        while True:
            options = candidates(session, ctx, redirected=redirected)
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
                                                 for o in options},
                                             # ★★★ **`pickTool` 的退出口是 `DONE`（做过事之后）
                                             #   或者上一步的 `needsTool`（一步都没做时）。**
                                             #
                                             #   照 μ 的规则：choice 必须能答"一个都不合适"。
                                             #   第 0 步时 `candidates()` 刻意不给 `DONE`
                                             #   （"不做了"该由 `needsTool` 回答），
                                             #   而 `needsTool` 就在这一步的**正前方**问过 ——
                                             #   那个问题**已经覆盖了**"没有动作可做"这一档。
                                             #   所以那一步的选项集是**真的封闭**，
                                             #   豁免要写在这里，不是默默放过。
                                             escape=(DONE if DONE in options else None),
                                             closed=(DONE not in options)))
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
            if err == NO_ACTION_FITS:
                # ★ 判官说没有动作合适 ⇒ **尝试收尾**，不是把这一步判成失败。
                finished = self._finish(session, view, ctx,
                                        why="pickInput 说没有动作合适（退出口）",
                                        may_redirect=True)
                if not isinstance(finished, Redirect):
                    return finished
                # ★★ **闸门把"结束"改道了** —— 和 `needsTool` 那条路**同一处置**：
                #   理由进帧（否则重挑动作是盲的），然后回到 ②′ **重新挑工具**。
                #   ⇒ 重进时帧里多了 `redirect_note`，所以"重问一次"问的**不是**
                #     同一个请求 —— 不违反那条"重发同 digest 是抽奖"的实测结论。
                ctx.redirect_note = (
                    f"A previous delivery was rejected ({finished.reason}): "
                    f"{finished.feedback}"
                )
                redirected = True
                self.trace.append({
                    "step": view.step, "node": "canDeliver",
                    "violation": "redirect_overrides_pickInput_escape",
                    "fatal": False,
                    "answer": f"revise/{finished.reason}", "remedy": "redirect",
                    "detail": ("pickInput 判了「没有合适的动作」而交付闸门判「没做完」"
                               f"⇒ 回到动作空间重挑（第 {self.redirects}/{MAX_REDIRECTS} "
                               f"次改道）；理由已进帧"),
                })
                continue
            if err is not None:
                return self._blocked(session, view, err)
            break

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
                                    batch=session.next_batch(),
                                    # ★ **这是"生成",不是"判定"** —— 自由文本
                                    #   不可枚举，只能写出来。把它算进判定准确率
                                    #   等于给一个猜出来的动作贴判定的标签（§8.2）。
                                    source="generate",
                                    note=f"{first} 不可枚举（provider=None）⇒ 只能生成，"
                                         f"不是从候选里挑的")
            return {first: self._generate_argument(session, view, tool, first)}, None

        options = [o for o in provider(ctx)]
        if not options:
            return {}, None
        if len(options) == 1:
            # ★ **只有一个候选就免问，而且这一档在退出口之前。**
            #
            #   ⚠️ 加退出口的时候这条捷径被**无意间关掉了**：当时写成
            #   `options += [PICK_INPUT_ESCAPE]` 再判 `len(options) == 1` ——
            #   而加完之后长度至少是 2，于是这个分支**永远走不到**，
            #   同时看起来还在那儿（"只有一个候选"那句注释就挂在死代码上）。
            #   实测（2026-10-03 的数）：`provider(ctx)` 返回单元素的情况真实存在，
            #   所以这不是理论问题 —— 每一次都白花一次判定，而账上只会看到
            #   `pickInput` 的判定次数偏高。
            #
            #   ★ 为什么捷径要**排在退出口之前**：`provider(ctx)` 只有一个候选时，
            #     "这些动作都不合适"和"做这个动作"之间没有可判的内容 ——
            #     退出口的全部意义是给**被迫在多个选项里挑**的判官一个出路
            #     （见 `PICK_INPUT_ESCAPE` 的说明）。只有一个候选时它没被强迫，
            #     而"要不要做这个动作"已经由**更前面**的 `needsTool` 判过了。
            #     §8.1：能由精确规则定的，不交给判定模型。
            return {first: options[0]}, None
        # ★★★ **问法跟候选的结构走。**优先级（见 `PICK_INPUT_SHAPE_AUTO`）:
        #
        #     ① 控制器**显式**指定的形状（对照臂）—— 压过一切
        #     ② 环境为**这一个工具**声明的形状（`Tool.candidate_shape`）
        #     ③ 全局默认（`PICK_INPUT_SHAPE` = 量出来的那个赢家）
        #
        #   ⚠️ ①②的顺序是这个函数里最容易搞反、而且**搞反了不报错**的一处:
        #     让①输给②,`react-typed-singlechoice` 就会静默地跑成
        #     `comparative`,量出来和 `react-typed` 一样 —— 臂名说谎。
        shape = (self.pick_input_shape if self.pick_input_shape != PICK_INPUT_SHAPE_AUTO
                 else (getattr(tool, "candidate_shape", None) or PICK_INPUT_SHAPE))
        shape = PICK_INPUT_SHAPE_ALIASES.get(shape, shape)
        if shape not in ("comparative", "admission"):
            # ★ 不静默降级 —— 见 `PICK_INPUT_SHAPE_ALIASES` 的说明。
            raise ValueError(
                f"pick_input_shape={self.pick_input_shape!r}（解析成 {shape!r}）不是已知题形；"
                f"只有 'comparative' / 'admission'（或 'auto'）"
            )
        if self.admission_question_form not in ("relational", "suffices"):
            raise ValueError(f"Unknown admission question form: {self.admission_question_form!r}")
        if shape == "admission" and not self.allow_choices_without_escape:
            # ★★★ **一候选一题**（2026-10-04）—— 见 `PICK_INPUT_CANDIDATE_ASK` 的说明。
            #
            #   ① **候选进状态（编号表）,题里只引用编号。**
            #      照 `jev-ultrafast::action_space`:"One index per observed element"。
            #      表只讲一次,而不是在 N 道题里各重写一遍说明。
            #   ② **N 道有界的小题,一次请求问完**（`μ` 的 `tool.admission` 一次问 16 个块）。
            #   ③ ★★★ **逃逸是推导出来的,不是选项。**
            #      旧形状里"以上都不合适"是候选表里的一个选项,判官得**记得去选它**;
            #      现在是 **"没有任何候选过线"** —— 从 N 个概率里直接得到。
            #      这也修掉了那件怪事:旧形状下 `top` 会**贴在门限上**,
            #      因为 N 选 1 的概率质量无处可去。
            ctx.action_table = "\n".join(
                f"[{i}] {o} — {_candidate_criterion(tool, o)}"
                for i, o in enumerate(options, 1)
            )
            ctx.action_rules = str(getattr(tool, "action_rules", "") or "")
            admission_ask = (PICK_INPUT_CANDIDATE_SUFFICES_ASK
                             if self.admission_question_form == "suffices"
                             else PICK_INPUT_CANDIDATE_ASK)
            questions = [
                _noul_question(f"pickInput::{i}",
                               admission_ask.format(ref=f"[{i}] {o}"),
                               criteria=PICK_INPUT_CANDIDATE_CRITERIA,
                               # ★ 门限 0:这是一次**打分**,不是一次"够不够果断"。
                               #   过不过线由**策略**判（下面那一个 `bar`）——
                               #   这样"没过线"是一个**分布的性质**,不是一个被丢掉的答案。
                               threshold=0.0, frame="pickInput")
                for i, o in enumerate(options, 1)
            ]
            if self.admission_answer_kind == "choice":
                # Keep the prompt and true/false descriptions identical to the
                # boolean control. Only the response vocabulary changes.
                criteria = dict(PICK_INPUT_CANDIDATE_CRITERIA,
                                unclear=PICK_INPUT_ADMISSION_UNCLEAR)
                questions = [
                    _choice_question(q.node, q.ask, list(criteria),
                                     criteria=criteria, threshold=0.0,
                                     frame="pickInput", escape="unclear")
                    for q in questions
                ]
            elif self.admission_answer_kind != "noul":
                raise ValueError(f"Unknown admission answer kind: {self.admission_answer_kind!r}")
            scored = self._ask(session, session.next_batch(), ctx, view.step, questions)
            ranked = [
                (i, o, (scored[f"pickInput::{i}"].probabilities.get("true", 0.0)
                        if self.admission_answer_kind == "choice"
                        else scored[f"pickInput::{i}"].prob_true()))
                for i, o in enumerate(options, 1)
                if f"pickInput::{i}" in scored
            ]
            if not ranked:
                self.trace.append({"step": view.step, "node": "pickInput",
                                   "violation": "answer_unusable",
                                   "fallback": "no_action_fits", "fatal": False,
                                   "detail": "候选题一道都没答出来 ⇒ 声明兜底=转去尝试收尾"})
                return {}, NO_ACTION_FITS
            ranked.sort(key=lambda t: -t[2])
            best_i, best_o, best_p = ranked[0]
            bar = NODE_THRESHOLDS["pickInput"]
            if self.admission_low_score_policy not in ("finish", "ranked_action"):
                raise ValueError(f"Unknown admission low-score policy: {self.admission_low_score_policy!r}")
            take_ranked = best_p < bar and self.admission_low_score_policy == "ranked_action"
            low_score_detail = (
                " ⇒ 按排序选择动作，风险与授权闸门照常运行"
                if take_ranked
                else " ⇒ 没有任何候选过线，转去尝试收尾（逃逸是推导出来的,不是选项）"
            )
            self.trace.append({
                "step": view.step, "node": "pickInput",
                "answer": f"[{best_i}] {best_o}" if (best_p >= bar or take_ranked) else "none_cleared_the_bar",
                "top": best_p,
                "detail": (f"一候选一题:{len(ranked)} 个候选各自打分,最高 [{best_i}] "
                           f"`{best_o}` = {best_p:.3f}（门限 {bar}）"
                           + ("" if best_p >= bar else low_score_detail)),
            })
            if best_p < bar:
                if self.admission_low_score_policy == "ranked_action":
                    return {first: best_o}, None
                if self.admission_low_score_policy != "finish":
                    raise ValueError(
                        f"Unknown admission low-score policy: {self.admission_low_score_policy!r}"
                    )
                return {}, NO_ACTION_FITS
            return {first: best_o}, None

        # ★★★ **退出口必须在候选里**（照 μ 的 `policy.ts`）。
        #   —— 放在捷径**之后**，理由见上。
        #
        # ★★ 对照组：`allow_choices_without_escape=True` 时**不加**退出口，
        #   并且显式声明 `closed=True` —— 那一档不是在"忘了加"，
        #   而是在**声明这个候选集真的封闭**。这正是要检验的那句假设。
        no_escape = self.allow_choices_without_escape
        if not no_escape:
            options = options + [PICK_INPUT_ESCAPE]

        asked = self._ask(session, session.next_batch(), ctx, view.step,
                          _choice_question("pickInput", PICK_INPUT_ASK, options,
                                           threshold=NODE_THRESHOLDS["pickInput"],
                                           # ★★ **候选必须带说明** —— 原来这里是空的，
                                           #   而 `_choice_question` 的文档写着空的代价
                                           #   （82/100 `wrong_tool`，置信度还经常 1.000）。
                                           criteria={o: (_PICK_INPUT_ESCAPE_CRITERION if o == PICK_INPUT_ESCAPE
                                                         else _candidate_criterion(tool, o))
                                                     for o in options},
                                           # ★ 对照组把候选集声明成**真的封闭** ——
                                           #   `escape=None, closed=True` 是唯一的合法形态
                                           #   （见 `_choice_question`：没有退出口又不说封闭
                                           #    就直接抛错，免得"忘了加"伪装成"封闭"）。
                                           escape=(None if no_escape else PICK_INPUT_ESCAPE),
                                           closed=no_escape))
        if "pickInput" not in asked:
            # ★★★ **弃答 ⇒ 走声明兜底,不重发这个请求。**
            #   `FALLBACK_POLICY["pickInput"] = "no_action_fits"`。
            #   重发一个逐字节相同的请求是抽奖（19/20 组置信度不同）,
            #   实测 13/20 题是这样死的（`BELOW_THRESHOLD_POLICY` 的说明）。
            #   ★ 而且这个兜底**不是"放行动作"** —— 它转去问 `canDeliver`,
            #     闸门拦得住（理由进帧,`MAX_REDIRECTS=1`）。
            #   ⚠️ `_ask_many` 已经为这次判定记过一行（`source="fallback"`）,
            #     所以这里**只路由,不再记一笔** —— 一条判定一行。
            self.trace.append({"step": view.step, "node": "pickInput",
                               "violation": "answer_unusable",
                               "fallback": "no_action_fits", "fatal": False,
                               "detail": "判定没答出来 ⇒ 声明兜底=转去尝试收尾"})
            return {}, NO_ACTION_FITS
        picked = asked["pickInput"]
        if picked.choice not in options:
            return {}, f"pickInput 选了候选外的 {picked.choice!r}"
        if picked.choice == PICK_INPUT_ESCAPE:
            # ★ 判官说「这些动作都不是下一步该做的」——**这不是出错**。
            #   它意味着要么任务已经做完，要么继续挑也没有意义。
            #   ⇒ 转去**尝试收尾**，让交付闸门去判「做完了没有 / 说得过不过头」。
            #     把这一步记成失败（`_blocked`）会让循环重试同一个请求，
            #     而那正是我们已经量过的抽奖。
            self.trace.append({"step": view.step, "node": "pickInput",
                               "answer": PICK_INPUT_ESCAPE,
                               "detail": f"判官说没有合适的动作（top={picked.top():.3f}）"
                                         f"⇒ 转去尝试收尾，由 canDeliver 判"})
            return {}, NO_ACTION_FITS
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
        if not self.gates_rules_first:
            # ── **判官产生档位**那一版（留作对照）────────────────────────
            # ★★★ 这一版就是实测那个 bug 的所在（`docs/ALFWORLD-ESCAPE.md` §4）：
            #   `score:risk` 由判官答，而 `_ask_many` 还会拿 `Question.threshold`
            #   再卡一道 —— `_score_question` 从不设门限，于是吃到 dataclass
            #   默认的 **0.5**。判官每次都正确答出 `risk=1`，置信度 0.39 ⇒
            #   被丢掉 ⇒ 授权闸门"不成立" ⇒ 20 题里 **4 题**这样死掉，
            #   一次工具都没调。**留它是为了让那件事可复现、可对照。**
            declared = getattr(tool, "base_risk", None)
            if declared is not None:
                risk_score = int(declared)
                asked = self._ask(session, batch, ctx, view.step, [
                    _noul_question("needs_auth", NEEDS_AUTH_ASK,
                                   criteria=NEEDS_AUTH_CRITERIA, threshold=0.5,
                                   frame="gradeRisk"),
                ])
                session.record_decision(
                    step=view.step, node="risk", answer=f"(declared:{risk_score})",
                    confidence=1.0, correct=True, latency_ms=0.0, batch=batch,
                    source="rule",
                    note=(f"{tool.name}.base_risk={risk_score}（工具声明，未问模型）；"
                          f"{RISK_LEGEND[risk_score] if 0 <= risk_score < len(RISK_LEGEND) else '未知档位'}"),
                )
                if "needs_auth" not in asked:
                    return "blocked"
                auth = asked["needs_auth"]
                risk_source = "declared"
            else:
                asked = self._ask(session, batch, ctx, view.step, [
                    _score_question("risk", GRADE_RISK_ASK, RISK_LEGEND,
                                    frame="gradeRisk"),
                    _noul_question("needs_auth", NEEDS_AUTH_ASK,
                                   criteria=NEEDS_AUTH_CRITERIA, threshold=0.5,
                                   frame="gradeRisk"),
                ])
                if not {"risk", "needs_auth"} <= set(asked):
                    # ★ 两问缺一**不作数**:拿 `risk=0` 或 `needs_auth=0` 顶上,等于
                    #   让一道授权闸门在「不知道」的时候**默认放行** —— 那是 fail open,
                    #   而 §8.5 的原话是「授权闸门不接受概率绕过」。
                    return "blocked"
                risk_score = asked["risk"].score
                auth = asked["needs_auth"]
                risk_source = "judged"
        else:
            # ── **规则定档、判官只确认**（默认，用户 2026-10-04 的决定）──────
            #
            #   判官只在一个方向上起作用：**说规则低估了**，抬 `RAISE_STEP` 档。
            #   "太高"不降、"说不好"不动 —— 单调性见 `docs/GATES-RULES-FIRST.md`。
            risk_score, risk_source = _risk_band(tool, arguments)
            session.record_decision(
                step=view.step, node="risk", answer=f"({risk_source}:{risk_score})",
                confidence=1.0, correct=True, latency_ms=0.0, batch=batch,
                source="rule",
                # ★ 查表来的那一格也要**留痕** —— 不然账上会以为这一趟只问了
                #   `needs_auth`，而"风险是谁定的"这个问题就答不上来。
                #   措辞照 `pickInput` 那条 `answer="(generated)"` 的先例：
                #   **用括号标出"这不是一次判定"**。
                note=(f"风险档位由**规则**给出：来源={risk_source}，档位={risk_score}"
                      f"（{RISK_LEGEND[risk_score] if 0 <= risk_score < len(RISK_LEGEND) else '未知档位'}）"
                      f"；工具声明 base_risk={getattr(tool, 'base_risk', None)}。"
                      f"**未问模型**：档位是查出来的，判官只准往上抬"),
            )
            asked = self._ask(session, batch, ctx, view.step, [
                _noul_question("needs_auth", NEEDS_AUTH_ASK,
                               criteria=NEEDS_AUTH_CRITERIA, threshold=0.5,
                               frame="gradeRisk"),
            ])
            if "needs_auth" not in asked:
                # ★★ **这一条是"判官缺席"里唯一仍然拒绝的一处**,而它是对的：
                #   `needs_auth` 是**收紧**方向的问题（它只能把 auto 变成 ask_human），
                #   而拒答在收紧方向上是安全的 —— 不放行不等于误杀。
                #   ⚠️ 它拦的是**不可逆动作**：`_risk_action` 里 `risk >= 2`
                #     本来就已经是 `ask_human` 了，这一档只在 `needs_auth` 上生效。
                return "blocked"
            auth = asked["needs_auth"]
            # ★★★ **档位来自工具声明 ⇒ 不问判官**（`docs/BATCH-1-PLAN.md` 的修法）。
            #
            #   实测（2026-10-04）:`risk_confirm` 在 ALFWorld 上 **287/291 答"说不好"**、
            #   在 TERNARY 上 **29/37 答"说不好"** —— 每步花一次调用、几乎不携带信息。
            #   而两个数据集的档位都是**工具自己声明的**（`act` 声明 1，`search`/`read_doc` 声明 0）。
            #
            #   ⇒ 这正是那条规矩的落点:**能由精确规则定的,不交给判定模型**（§8.1 第三行）。
            #     工具声明是**常量**;让判官去"确认"一个常量,它只能答"说不好"。
            #
            #   ★ **收紧通道没丢**:`needs_auth` 一直在问（上面那一段），
            #     它是独立的一道题,只往"问人"那个方向用力。
            #   ⚠️ 档位来自**模式表或"认不出来"**时仍然问 —— 那时规则是**猜的**,
            #     而 `UNKNOWN_TOOL_BAND = 2` 本身就是一个保守猜测,值得让判官插话。
            if not risk_source.startswith("declared"):
                risk_score, raised = self._confirm_risk(
                    session, view, ctx, batch, tool, arguments, risk_score)
                if raised:
                    risk_source = f"{risk_source}+judge_raised"
            else:
                self.trace.append({
                    "step": view.step, "node": "gradeRisk",
                    "answer": "(skipped)",
                    "detail": (f"档位来自工具声明（{risk_source}）⇒ **不问 `risk_confirm`**:"
                               f"让判官确认一个常量只会得到「说不好」"
                               f"（实测 287/291、29/37）。收紧仍由 `needs_auth` 承担"),
                })

        action = _risk_action(risk_score, auth.prob_true())
        detail = (f"risk={risk_score}（{RISK_LEGEND[risk_score] if 0 <= risk_score < len(RISK_LEGEND) else '未知档位'}，"
                  f"来源={risk_source}）"
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
                reason=(f"score:risk={risk_score} >= 1 → auto_audit;"
                        f" prob:needs_auth={auth.prob_true():.3f}"),
                risk=risk_score,
            )
        return action

    def _confirm_risk(self, session: Session, view: DecisionView, ctx: AgentCtx,
                      batch: int, tool, arguments: dict,
                      band: int) -> tuple[int, bool]:
        """**判官层**：确认规则的档位，**只准往上抬**。返回 `(档位, 是否抬过)`。

        ★★★ 单调性是全部内容：

            判官说"太高" ⇒ **不降**（规则的判断不被放松）
            判官说"说不好" ⇒ **不动**
            判官说"太低" ⇒ 抬 `RAISE_STEP` 档

        ★ 为什么"太高"不放行：放松方向一旦打开，判官就重新**产生**了裁决，
          而它最不擅长的就是这件事（没有状态、没有计划、没有记忆）。
          它说"太高"的价值在账上 —— 那是**规则可能过严**的证据，
          离线可以和"那些调用后来出没出事"对齐。要改的是规则，不是让判官放行。

        ★★ **档位是由规则给的，所以判官只需要回答"对不对"** ——
          这是一道**分类题**（三档立场 + 说不出），不是"这一调多危险"那道
          需要它建模后果的题。μ 的 `tool-admission` 是同一条道理。
        """
        asked = self._ask(session, batch, ctx, view.step, [
            _choice_question("risk_confirm", RISK_CONFIRM_ASK,
                             list(RISK_CONFIRM_CRITERIA), threshold=0.0,
                             criteria=dict(RISK_CONFIRM_CRITERIA),
                             frame="gradeRisk", closed=True),
        ], honor_shadow=False)
        stance = self._stance(asked.get("risk_confirm"))
        # ★ 判官的立场**不另记一行** —— 它就在 `risk_confirm` 那道题自己那一行里
        #   （`answer` = `too_low`/`too_high`/`correct`/`unsure`）。
        #   多记一份会让节点计数翻倍、把 `判定占比` 的分子分母一起灌水。
        #   理由和第一版犯的错写在 `_record_gate_stance` 的文档里。
        self.trace.append({
            "step": view.step, "node": "risk_confirm",
            "answer": f"stance:{stance or 'no_answer'}",
            "detail": (f"规则定档={band}"
                       f"（{RISK_LEGEND[band] if 0 <= band < len(RISK_LEGEND) else '?'}）；"
                       f"判官立场={stance or '(没答)'}"
                       + ("；**判官说规则低估了** ⇒ 抬 1 档（只抬不降）"
                          if stance == "too_low" else
                          "；判官说太高 ⇒ **不降**（单调性：判官只能收紧）"
                          if stance == "too_high" else "")),
        })
        if stance == "too_low":
            raised = min(len(RISK_LEGEND) - 1, band + RAISE_STEP)
            self.trace.append({"step": view.step, "node": "gradeRisk",
                               "answer": f"judge_raised {band}->{raised}",
                               "detail": ("判官说规则低估了这一调 ⇒ 抬 "
                                          f"{RAISE_STEP} 档（规则 {band} → {raised}）；"
                                          "判官只能收紧，不能放松")})
            return raised, raised != band
        return band, False

    @staticmethod
    def _signals(session: Session, tool_name: str) -> dict[str, tuple[str, ...]]:

        """那个工具声明的**环境成败信号**。没声明就空 —— 空 = 查不了，照旧问模型。"""
        out: dict[str, tuple[str, ...]] = {}
        for t in session.tools:
            if t.name != tool_name:
                continue
            for k, v in (t.observation_signals or {}).items():
                out[k] = tuple(out.get(k, ())) + tuple(v)
        return out

    @staticmethod
    def _hits(text: str, needles: tuple[str, ...]) -> list[str]:
        return [n for n in needles if n and n in (text or "")]

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

        # ★★★ **环境已经说过这一步没成 ⇒ 不必问模型。**
        #   `Nothing happens.` 是 TextWorld 的拒绝语：那一步**什么都没发生**，
        #   而"这一步成没成"正是可检索的（`str in observation`）。
        #   实测刚证明过：能查的东西让模型判，会误杀（`docs/GROUNDING-REAL-RUN.md`）。
        sig = self._signals(session, last.action.name)
        failed = self._hits(str(ctx.last_result), sig.get("failure", ()))
        if failed:
            session.record_decision(
                step=view.step, node="stepOk::environment", answer=f"(failed:{failed[0]})",
                confidence=1.0, correct=False, latency_ms=0.0,
                batch=session.next_batch(), source="rule",
                note=(f"上一步的观测里有环境自己给的失败信号 {failed} ⇒ "
                      f"`stepOk` 直接判 false（**确定性检查，未问模型**）"),
            )
            self.trace.append({"step": view.step, "node": "stepOk", "answer": "stop",
                               "detail": f"环境信号 {failed} —— 这一步没成"})
            return Decision(kind="unparsed", syntax="typed",
                            raw=(f"typed: 环境说这一步没成（{failed[0]}）:"
                                 f"{ctx.last_tool}({ctx.last_input}) -> "
                                 f"{ctx.last_result[:200]}"))

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
        # ★★★ **环境已经说过目标达成了 ⇒ 不必问模型。**
        #   `[task complete]` 是 loader 依据环境的 `won` 追加的 —— 也就是说
        #   **这一条就是判分器的真值**，只是提前出现在了观察里。
        #   拿它去问模型，等于让模型去猜一个**已经写在纸上的答案**。
        reached: list[str] = []
        for r in ctx.records():
            reached += self._hits(str(getattr(r, "result", "")), sig.get("goal_reached", ()))
        if reached:
            session.record_decision(
                step=view.step, node="isDone::environment",
                answer=f"(goal_reached:{reached[0]})", confidence=1.0,
                correct=True, latency_ms=0.0, batch=session.next_batch(),
                source="rule",
                note=(f"观测里有环境自己给的达成信号 {reached[0]} ⇒ `isDone` 直接判 true"
                      f"（**确定性检查，未问模型**）"),
            )
            return self._finish(session, view, ctx,
                                why=f"环境信号 {reached[0]}")

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
                *, why: str, batch: int = 0, deliver: bool = True,
                may_redirect: bool = False) -> Decision | Redirect:
        """生成答案,**并过交付闸门**（`canDeliver`）。

        ★★ 返回 `Redirect` = **闸门把"结束"改道了**（`_remedy` 判 `redirect`）：
        还有事没做，所以这一次不该收尾，请调用方**落到动作路径**去，
        并把它带的"为什么"放进 `ctx.redirect_note`（否则是盲改道）。

        ★ `may_redirect` **只有 `needsTool` 那一条调用点打开** —— 别的地方
          "回去做"没有落点，理由见 `_remedy`。其余调用点拿到的**一定是 `Decision`**。

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
        # ★ 留一份**改之前**的原文。`revise` 会覆盖 `ctx.draft`，而
        #   `gate_false_reject` 要判的正是"闸门打回的那一版本来对不对"——
        #   拿改完的那一版去判，等于用结果证明过程。
        original = draft

        if not deliver:
            # ★ 没有工具 → 闸门**没有可核对的材料**（见 `decide()` 里那条)。
            #   这里记一行,好让「为什么没跑 canDeliver」在轨迹里有答案 ——
            #   沉默地跳过会让它和「忘了接」长得一样。
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": "(skipped)", "detail": why})
            return Decision(kind="answer", answer=ctx.draft,
                            thought=f"生成答案（{why}）", syntax="generated")

        verdict, reason, feedback, applied = self.review_draft(session, view, ctx)
        if not applied:
            # ★★★ **shadow：闸门被问了、裁决记下了，但没有落地。**
            #   "没有判官时宿主的行为"就是**照交** —— 所以这里返回的是原文,
            #   不 revise、不 degrade、不改道、不拦。
            #   ★ `gate=""` 是对的:这一臂这一次**真的没有闸门在管**。
            #     裁决本身在 `canDeliver::shadow` 那一行里,离线可比对。
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": f"shadow/{verdict or 'unjudgeable'}",
                               "detail": f"shadow 模式：裁决={verdict or 'blocked'}，"
                                         f"未落地；按没有闸门的行为照交"})
            return Decision(kind="answer", answer=original,
                            thought=f"生成答案（{why}）", syntax="generated")
        # ★ 记下**第一次**裁决：修订之后再判的那个数已经被闸门影响过了，
        #   拿它算"闸门错没错"是循环论证（同 `core/agent.py::AgentOutcome.gate`）。
        first_gate = verdict
        if verdict == "revise":
            remedy = self._remedy(session, ctx, reason, may_redirect=may_redirect)
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": f"revise/{reason}", "remedy": remedy,
                               "detail": feedback})
            if remedy == "redirect":
                # ★★ **回去把没做的事做掉。** 见 `_can_deliver` 里那段：
                #   `incomplete` 的补救不是重写文本，而是回到动作空间。
                #   带上 `reason`/`feedback` —— 让动作路径**不是盲的**。
                self.redirects += 1
                return Redirect(reason=reason, feedback=feedback)
            # 补救＝**撤回**：把超出证据的部分撤掉，退回证据支持得了的范围。
            ctx.draft = self._degrade_text(session, view, reason=reason, feedback=feedback)
            verdict, reason, feedback = self._can_deliver(session, view, ctx)
            if verdict == "revise":
                # ★ 第二次仍然不合格 —— **如实交出去,并说明**（§8.10:不假装成功）。
                #   这里不再改第二遍:上限 1 次是刻意的（TS 侧同一条）。
                self.trace.append({"step": view.step, "node": "canDeliver",
                                   "answer": "degrade(again)",
                                   "detail": f"撤回一次后仍未过闸门:{feedback}"})
        if verdict == "blocked":
            # 闸门发不出去（帧缺判定依据 / 超预算）→ 这一步**不成立**,
            # 交给 `_blocked` 退回 `unparsed`,循环去看得见的地方弃答。
            # ★ 带上 `original`：判得出"闸门是保护还是误杀"全靠它（见 `_blocked`）。
            return self._blocked(session, view, "canDeliver", gate="blocked",
                                 draft=original)

        return Decision(kind="answer", answer=ctx.draft,
                        thought=f"生成答案（{why}）", syntax="generated",
                        gate=first_gate,
                        # ★ 只有真的 revise 过才有"改之前那一版"可谈。
                        draft=original if first_gate == "revise" else "")

    def review_draft(self, session: Session, view: DecisionView, ctx: AgentCtx
                     ) -> tuple[str, str, str, bool]:
        """跑交付闸门 `canDeliver`，**并遵守 shadow 模式**。

        返回 `(verdict, reason, feedback, applied)`：

          · `applied=True`  —— 裁决**生效**，调用方按 `verdict` 决定交付 / 修订 / 弃答。
          · `applied=False` —— **shadow**：裁决已记录，但**不生效**。
            调用方必须按"没有闸门"的行为走（照交原文）。
            裁决本身落在 `canDeliver::shadow` 那一行,离线用来算
            "闸门说 revise 的那些到底对不对"。

        ★★★ **为什么要把它抽成一个方法**:`_finish()` 和 `termination_only`
        都直接调 `_can_deliver` —— 两处各写一遍"跑闸门",于是**任何加在闸门上的
        档位都要改两处**,而漏掉一处不会报错,只会让那一臂静默地跑另一套语义
        （这正是 §8.15「要求写在一处、生效在另一处」的形状）。
        shadow 是第一个这样的档位,所以顺手把入口收成一个。

        ★ `verdict == "blocked"` 时 `reason` 是 `"unjudgeable"` —— 调用方要
          按 `_finish` 里那段处理（退回 `unparsed`，带 `original` 草稿）。
        """
        verdict, reason, feedback = self._can_deliver(session, view, ctx)
        if not self.gate_is_shadowed():
            return verdict, reason, feedback, True

        # ★ **记一行,说明"这次裁决存在、但没落地"。**
        #   为什么单开一行而不是塞进 `trace`:跑完之后还读得到的是 `trace.jsonl`,
        #   而"这一批是不是 shadow"正是**能不能进同一张表**的判据 ——
        #   它必须在盘上,不能在内存里。
        session.record_decision(
            step=view.step, node="canDeliver::shadow",
            answer=f"(shadow:{verdict or 'blocked'}/{reason or 'unjudgeable'})",
            # ★ 照 `(declared:N)` 的先例:括号 = "这一行不是一个判定"。
            #   `confidence=1.0 / correct=True` 是给校准类指标看的"别算我"，
            #   真实裁决在 `deliverable` / `unsupported` 那两行里，一行都没丢。
            confidence=1.0, correct=True, latency_ms=0.0,
            batch=session.next_batch(),
            source="fallback", fallback="shadow",
            note=(f"shadow 模式：闸门裁决={verdict or 'blocked'}"
                  f"{'/' + reason if reason else ''} —— **未落地**；"
                  f"按没有闸门的行为照交。本条供离线比对"
                  f"（{feedback[:200]}）"),
        )
        return verdict, reason, feedback, False

    def _remedy(self, session: Session, ctx: AgentCtx, reason: str,
                *, may_redirect: bool = False) -> str:
        """闸门拒绝交付之后，**该做什么补救**。

        ★★ 这一格是 2026-10-01 补上的，它修的是一个实测出来的因果链：

            闸门第一判 = `incomplete`（"没做完"）
            → 循环唯一的出路是**重写文本**（`_answer_text(revise=...)`）
            → 模型在那一刻**没法真的去做**，于是写了一个更像样的说法
            → 第二判 `unsupported` 冲到 0.86–0.99（"超出证据"）
            ⇒ 实测：补救改成**撤回**之后，假成功 26% → 5%，"改好了" 9 → 25

        补救按**病因**分：

            `overclaim`   → `degrade`：撤回证据支持不了的部分。说得太多，
                            正确的动作是**少说**，不是"换个说法再说一遍"。
            `incomplete`  → `redirect`：还有事没做 ⇒ **回去做**；
                            做不了（没有工具 / 改道次数用完 / 不在允许改道的那条路上）
                            ⇒ `degrade`，退回"如实报告拿不到什么"。

        ★ `may_redirect` **只由 `needsTool` 那条路打开**。别的地方说"回去做"
          没有落点：
            · 候选空了 ⇒ 本来就没得做；
            · 只剩 `DONE` ⇒ 是"想动但没得动"，不是"以为收尾了"；
            · 没有工具的任务 ⇒ 动作空间是空的（FTA 整份数据就是这个形状）。
          在这些地方强行走改道，只会白花一次判定然后撞上限。
        """
        if reason == "overclaim":
            return "degrade"
        if not may_redirect or self.redirects >= MAX_REDIRECTS:
            return "degrade"
        # ★ 用**改道的那套候选**判"有没有得做" —— 它不去重、不给出口。
        #   拿正向那套去判会把"只能换参数再做一次"误判成"没得做了"。
        return "redirect" if candidates(session, ctx, redirected=True) else "degrade"

    @staticmethod
    def _evidence_block(view: DecisionView) -> list[str]:
        """**给生成端看的工具输出** —— 两条生成路径共用这一份。

        ★★ 为什么必须共用:`_answer_text`（第一次生成）和 `_degrade_text`
          （闸门打回后的重写）都要它。第一版只给了前者,而后者**没有** ——
          更糟的是 `_degrade_text` 的指令是「**报告发生了什么**」:
          让它报告一件它看不见的事,它只能猜,而猜出来的就是那句
          "工具失败了、没有可用证据"。**一个盲眼的模型唯一能得出的结论。**
          ⇒ 一个投影器,两个调用点。

        ★ 它**跳过宿主伪步骤**（`__parse_error__`）—— 那是给我们自己看的纠正提示,
          不是环境观测（同一条理由见 `ctx_from_steps`）。
        """
        records = [StepRecord(step=s.index, tool=s.action.name or s.action.kind,
                              input=render_tool_input(s.action.arguments, s.action.content),
                              result=s.observation)
                   for s in view.history if not is_harness_pseudo_step(s)]
        evidence = render_evidence(records, last=ANSWER_EVIDENCE_STEPS,
                                   result_chars=ANSWER_EVIDENCE_RESULT_CHARS)
        return ["", "# Evidence collected so far", evidence] if evidence else []

    def _degrade_text(self, session: Session, view: DecisionView,
                      *, reason: str, feedback: str) -> str:
        """**撤回**：把回答退回证据支持得了的范围。

        ★★ 两件事必须在这里写清楚，都是实测逼出来的：

        **① 不能复用 `_answer_text(revise=...)` 的措辞。** 原来的反馈是
          "只写证据支持得了的话"，而实测它反而诱发编造 —— 因为那句话的框架
          仍然是**"给我一个答案"**。这里换掉的是**框架**，不是措辞：
          任务从"回答用户"改成"报告发生了什么"。

        **② 提示词必须是英文。** 第一版我写成中文，模型于是用中文回答 ——
          而 FTA 的词面判据（`benchmark/fta/detector.py`）的免责词表是**英文的**，
          它看不见"无法确认"，于是把「我无法确认 … 为 742 人」这句**明说不确认**
          的回答判成了"断言式编造"。实测后果：那 10 条"补救后变成编造"里
          大部分是这个假象。**换语言等于换模型行为，也等于让判据失明。**
        """
        from experiments.core.models import Message

        why = ("over-claiming (content beyond the evidence)" if reason == "overclaim"
               else "incomplete (the task's requirements were not met)")
        ask = (
            "# Delivery check failed\n"
            f"The previous draft was rejected. Reason: {why}.\n"
            f"Checker's note: {feedback}\n\n"
            "**Do not write another answer.** Do exactly one thing: report what happened.\n"
            "  - state plainly which part you could NOT obtain "
            "(did the tool fail / was the attachment missing / was access denied / was the data stale)\n"
            "  - state plainly what would be needed to obtain it\n"
            "  - keep only what the evidence supports; drop everything else\n"
            "  - do not guess a number, and do not give a best-guess answer\n"
            "Answer in English."
        )
        parts = [view.task_prompt, "", ask]
        # ★★★ **重写那一次也要看得见证据。** 这一条的指令是「报告发生了什么」——
        #   不给她证据,她就只能猜,而猜出来的是"工具失败了"。
        #   第一版这里没有证据块,而它正是那些"编造原因"的草稿的来源。
        parts += self._evidence_block(view)
        done = "; ".join(f"{s.action.name or s.action.kind}"
                         for s in view.history if not is_harness_pseudo_step(s))
        if done:
            parts += ["", "# What was done", done]
        return session.call_model([Message(role="user", content="\n".join(parts))]).text or ""

    def _evidence_pointer(self, ctx: AgentCtx, view: DecisionView) -> Pointer | None:
        """★★ **"这个答案指向哪一步的工具输出"** —— 交付闸门的举证题。

        ★ 选项是**可枚举、可检索的产物**（每一步的 `step_i`），不是一整段渲染过的
          文本 —— 判定的本性是穷尽枚举（`core/deciding.py` 模块头），
          而"指哪一步"正好是它能可靠回答的形状。

        ★ 校验器**闭包在构造时就把证据绑好**，所以 `_ask_many` 不需要知道证据
          长什么样 —— 它只负责"问、校验、降级"。

        ⚠️ 没有可指的东西（历史空、或答案里一个数字都没有）时**返回 `None`**，
          也就是**不要求举证**。这不是偷懒：要求一个指不出来的指认只会让
          闸门对每一条都报警，而"一条永远为真的告警等于没有告警"
          （`candidate_already_done` 就是这么死的）。
        """
        steps = [r for r in ctx.records() if getattr(r, "result", "")]
        # ★ `draft` 住在 `ctx` 上（`AgentCtx.draft`），**不在 `view` 上** ——
        #   闸门判的"要交出去的那一份"就是它（`_finish` 里刚填的）。
        draft = str(getattr(ctx, "draft", "") or "")
        if not steps or not draft:
            return None
        numbers = _numbers_in(draft)
        if not numbers:
            # 没有数字 ⇒ 词面校验无从下手。**不假装能验** —— 见 Pointer 的分档说明。
            return None
        ids = tuple(f"step_{r.step}" for r in steps)
        none = "none_of_the_recorded_steps"
        by_id = {f"step_{r.step}": str(r.result) for r in steps}

        def validate(cited: str) -> bool:
            """★ 草稿里的**每个数**都得在那一步的观测里出现。跑在模型之外。"""
            text = by_id.get(cited)
            if text is None:
                return False
            have = set(_numbers_in(text))
            return bool(numbers) and numbers <= have

        return Pointer(ask=("Which recorded step's tool output contains every number "
                            "stated in the answer?"),
                       options=ids + (none,), validate=validate, none_option=none)

    def _can_deliver(self, session: Session, view: DecisionView,
                     ctx: AgentCtx) -> tuple[str, str, str]:
        """`canDeliver` —— 交付闸门。返回 `(裁决, 理由, 说明)`。

        ★★ 策略**逐字**来自 `DECISION.md`,而且顺序是判据::

            prob:unsupported >= 0.5 → 超出证据
            prob:deliverable >= 0.6 → deliver
            else                    → 没做完

        `unsupported` 排在前面不是随手写的:「一个完整但凭空编了事实的回答,
        比一个不完整的回答更该被打回」。ALFWorld 那题编的完成报告正是这一类。

        ★ 两条合并成一次请求:都看**同一份 draft 和同一份证据**。

        ★★ **第三项 `理由` 是 2026-10-01 加的，因为它决定补救动作。**
        以前这里只回 `"revise"`，而 `revise` 把两种完全不同的病因说成同一句话：

            `"overclaim"`   说得太多（超出证据） → 补救是**撤回**到证据支持的范围
            `"incomplete"`  做得不够（没做完）   → 补救是**回去做**，不是重写

        实测（`fta × react-termination`，n=100）：那 8 条"草稿诚实、改完变成编造"
        的第一判**全部**是 `incomplete`（`deliverable` 0.12–0.31），而循环唯一的
        出路是重写文本 —— 于是改完之后 `unsupported` 从 0.07 冲到 0.86–0.99。

        **把"没做完"翻译成"重写"，等于让模型在没有新信息的情况下写得更像样。**
        """
        if self.gates_rules_first:
            return self._can_deliver_rules_first(session, view, ctx)

        # ── 以下是**判官产生裁决**那一版（`gates_rules_first=False`）────────
        # ★ 留着它是因为它**是这一批所有已测数字的那个方法**。
        #   规则优先那一版换了裁决的来源，两批**不能进同一张表**
        #   （`DECISION_SPEC_VERSION` 已随之 bump）。
        #
        #   ⚠️ 这一版里 `unjudgeable ⇒ blocked` 那条路是**故意留着**的：
        #     它是规则优先那一版要消灭的东西（`docs/ALFWORLD-ESCAPE.md` §4），
        #     而在它自己那一版里它是自洽的 —— 判官缺席 = 没有裁决 = 不放行。
        ungrounded = _ungrounded_numbers(ctx)
        if ungrounded:
            draft_text = str(getattr(ctx, "draft", "") or "")
            session.record_decision(
                step=view.step, node="deliverable::grounding",
                answer=f"(ungrounded:{','.join(ungrounded)})", confidence=1.0,
                correct=False, latency_ms=0.0, batch=session.next_batch(),
                source="rule",
                # ★★ **把被拦的草稿原文（节选）写进 `note`。**
                #   第一版只记了哪几个数没落地，于是事后**没法判断这次拦截对不对** ——
                #   实测（2026-10-08）就撞上了：4 条拦截，而我无法确认那些数是
                #   原始草稿自己的，还是被反馈文本带进去的。**判据必须可复核。**
                #
                #   ⚠️ 写 `note` 而**不是** `request_text`：后者只落到
                #     `--dump-requests` 那个 **opt-in 的转储文件**里，
                #     `DecisionRecord` 上根本没有这一栏 —— 不传开关就等于丢掉
                #     （又一个"配了没生效"）。
                note=(f"草稿里的数 {ungrounded} 在任何一步的工具输出里都找不到 ⇒ "
                      f"`deliverable` 直接判 false（**确定性检查，未问模型**）；"
                      f"草稿节选：{draft_text[:200]!r}"),
            )
            # ★★★ **反馈文本里不要再写那几个数。**
            #
            #   实测（2026-10-08，ALFWorld × react-typed）撞出的**反馈回路**：
            #   第一版反馈写的是「答案里出现了工具输出里没有的数 ['3','4','5']」，
            #   它进了 degrade 提示 ⇒ 模型把这三个数**抄进了下一版草稿** ⇒
            #   下一判又判它们未落地 —— **自己喂自己，反复触发**。
            #   证据就是那两条最终答案：「The tool failed to provide the specific
            #   numbers ['3', '4', '5'] required for the answer.」
            #
            #   ⇒ 反馈只说**性质**、不重复**内容**：回流的数字会被当成新的断言。
            return "revise", "overclaim", (
                "答案里出现了工具输出里没有的数字 —— "
                "退回证据支持得了的范围，**不要补新的数字，也不要重复那些数字本身**")

        batch = session.next_batch()
        # ★★★ **交付必须举证。** 这一版是**判官产生裁决**：两道 `noul` 直接决定
        #   `deliver` / `revise`，而 `docs/GROUNDING-STEP2-POINTER.md` 那条
        #   「一条裁决必须能指向什么」在这里只落在举证题上（`Pointer`）。
        #   ★ 规则优先那一版把这条要求推广到了闸门本身：规则给出的理由
        #     就是它要指的东西（`docs/GATES-RULES-FIRST.md`）。
        #
        # ★ `honor_shadow=False`：**闸门要看到自己的答案才算得出裁决。**
        #   shadow 的意思不是"别问",是"问了、记了，但**不照它做**" ——
        #   答案必须交到这一层来算出裁决,再由 `review_draft` 决定不落地。
        asked = self._ask(session, batch, ctx, view.step, [
            _noul_question("deliverable", DELIVERABLE_ASK,
                           criteria=DELIVERABLE_CRITERIA, threshold=0.6,
                           frame="canDeliver"),
            _noul_question("unsupported", UNSUPPORTED_ASK,
                           criteria=UNSUPPORTED_CRITERIA, threshold=0.5,
                           frame="canDeliver"),
        ], honor_shadow=False)
        if not {"unsupported", "deliverable"} <= set(asked):
            return "blocked", "unjudgeable", ""

        unsupported, deliverable = asked["unsupported"], asked["deliverable"]
        overclaim = unsupported.prob_true() >= 0.5
        incomplete = deliverable.prob_true() < 0.6
        if overclaim:
            note = (
                f"回答里有工具输出不支持的内容"
                f"（unsupported={unsupported.prob_true():.3f}，"
                f"deliverable={deliverable.prob_true():.3f}）"
            )
            return "revise", ("incomplete" if incomplete else "overclaim"), (
                note + ("；**而且事情本身也没做完** —— 先去把它做完"
                        if incomplete else "—— 退回证据支持得了的范围，不要补新说法")
            )
        if deliverable.prob_true() >= 0.6:
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": "deliver",
                               "top": deliverable.top(), "provider": "typed"})
            return "deliver", "", ""
        return "revise", "incomplete", (
            f"回答没有把任务要求的事做完"
            f"（deliverable={deliverable.prob_true():.3f}）"
        )

    # —— 闸门：规则先筛、判官只确认 ────────────────────────────

    def _delivery_certificate(self, session: Session, view: DecisionView,
                              ctx: AgentCtx) -> tuple[str, str, str, str] | None:
        """**规则层**：交付闸门的三条证书。返回 `(id, 裁决, 理由, 说明)`，`None` = 没有证书触发。

        ★★ 这一层**只认能在产物上跑一次就出结果的检查** —— 集合差、空串、全空。
          「能被否证的才配当规则。」凡是要先判断"这句话是什么意思"的，
          都进不了这里（见 `NOT_YET_CERTIFICATES`）。

        ★ 三条的顺序是判据：**先说得出话**（空草稿没得判），
          再说**话里有没有编的数**（最锐利的一条，也是实测抓假完成最有效的一条），
          最后才是**有没有材料**。
        """
        draft = str(getattr(ctx, "draft", "") or "")
        records = list(ctx.records())

        # ① 空草稿 —— 没有东西可交付
        if not draft.strip():
            session.record_decision(
                step=view.step, node="deliverable::empty", answer="(empty_draft)",
                confidence=1.0, correct=False, latency_ms=0.0,
                batch=session.next_batch(), source="rule",
                note="草稿去空白之后是空的 ⇒ 没有东西可交付（**确定性检查，未问模型**）",
            )
            return ("empty_draft", "revise", "incomplete",
                    "草稿是空的 —— 先写出一个答案")

        # ② 数字落地 —— **最锐利的一条**，也是唯一能抓"编一个数"的证书
        #
        #   实测（2026-10-07，ALFWorld × react-termination × 20 题）逼出来的结论：
        #   第一版做成一问一验（"哪一步包含这些数" + 校验被指的那一项），
        #   结果**误杀了两条 `won=True` 的题** —— 证据里明明写着
        #   `You move the watch 1 to safe 1. [task complete]`，而 Jev 答了"指不出来"。
        #   **指针本身也是模型判断，它有自己的错误率。**
        #   ⇒ 而"这个数在不在证据里"是**可检索的**。可检索的检查就不该问模型
        #     （§8.1：能由规则定的不交给判定模型）。
        ungrounded = _ungrounded_numbers(ctx)
        if ungrounded:
            session.record_decision(
                step=view.step, node="deliverable::grounding",
                answer=f"(ungrounded:{','.join(ungrounded)})", confidence=1.0,
                correct=False, latency_ms=0.0, batch=session.next_batch(),
                source="rule",
                # ★★ **把被拦的草稿原文（节选）写进 `note`。**
                #   第一版只记了哪几个数没落地，于是事后**没法判断这次拦截对不对** ——
                #   实测（2026-10-08）就撞上了：4 条拦截，而我无法确认那些数是
                #   原始草稿自己的，还是被反馈文本带进去的。**判据必须可复核。**
                #
                #   ⚠️ 写 `note` 而**不是** `request_text`：后者只落到
                #     `--dump-requests` 那个 **opt-in 的转储文件**里。
                note=(f"草稿里的数 {ungrounded} 在任何一步的工具输出里都找不到 ⇒ "
                      f"交付不成立（**确定性检查，未问模型**）；"
                      f"草稿节选：{draft[:200]!r}"),
            )
            # ★★★ **反馈文本里不要再写那几个数。**
            #
            #   实测（2026-10-08，ALFWorld × react-typed）撞出的**反馈回路**：
            #   第一版反馈写的是「答案里出现了工具输出里没有的数 ['3','4','5']」，
            #   它进了 degrade 提示 ⇒ 模型把这三个数**抄进了下一版草稿** ⇒
            #   下一判又判它们未落地 —— **自己喂自己，反复触发**。
            #   证据就是那两条最终答案：「The tool failed to provide the specific
            #   numbers ['3', '4', '5'] required for the answer.」
            #
            #   ⇒ 反馈只说**性质**、不重复**内容**：回流的数字会被当成新的断言。
            return ("ungrounded_number", "revise", "overclaim",
                    "答案里出现了工具输出里没有的数字 —— "
                    "退回证据支持得了的范围，**不要补新的数字，也不要重复那些数字本身**")

        # ③ 有没有可核对的材料 —— **每一次**工具调用都返回空
        observations = [str(getattr(r, "result", "") or "") for r in records]
        if records and all(not o.strip() for o in observations):
            session.record_decision(
                step=view.step, node="deliverable::no_evidence",
                answer="(no_evidence)", confidence=1.0, correct=False,
                latency_ms=0.0, batch=session.next_batch(), source="rule",
                note=(f"{len(records)} 次工具调用的输出全是空的 ⇒ 草稿没有可核对的材料"
                      f"（**确定性检查，未问模型**）"),
            )
            return ("no_evidence", "revise", "incomplete",
                    "每一次工具调用都返回了空输出 —— 草稿里的说法没有材料可核对")

        return None

    def _can_deliver_rules_first(self, session: Session, view: DecisionView,
                                 ctx: AgentCtx) -> tuple[str, str, str]:
        """**规则先筛、判官只确认**（用户 2026-10-04 的决定）。

        ★★★ 两条不变量，写在这里就是它们的规范：

        **① 单调性：判官只能把闸门收紧,永远不能放松。**

            final = 更严的那一个(规则的裁决, 判官的立场)

        **② 「不确定」永远不产生拒绝。**

          拒绝是规则的职权,而规则**只在有证书的时候**才拒绝。
          于是 "unjudgeable ⇒ blocked" 这条路**整条消失** ——
          而它正是实测那个 bug（`docs/ALFWORLD-ESCAPE.md` §4：
          判官答"风险 1，置信度 0.39"，0.5 的门限把这句话丢掉 ⇒ 授权闸门不成立
          ⇒ 20 题里 4 题 decline）。

        ★★ **为什么这样更对**：判官没有状态、没有计划、没有记忆，
          它最不擅长的就是产生一个跨整条轨迹的裁决；它擅长的是**对着一份具体材料
          回答一个具体问题**。"这条理由成立吗"正是后一种形状。
          顺带它把 `docs/GROUNDING-STEP2-POINTER.md` 那句要求
          （一条裁决必须能指向什么东西）从举证题推广到了闸门本身：
          **规则给出的理由就是它要指的东西。**

        ★★ **判官的分寸不进判据,只有内容进。** 两道确认题的门限都是 0 ——
          这两问不是决定,是报告;`top()` 照记,于是"犹豫的确认管不管用"
          是一个可以离线问的问题,而不是一个偷偷改变行为的门限。
        """
        cert = self._delivery_certificate(session, view, ctx)
        batch = session.next_batch()

        if cert is not None:
            cert_id, verdict, reason, feedback = cert
            options = list(CONFIRM_BLOCK_CRITERIA)
            asked = self._ask(session, batch, ctx, view.step, [
                _choice_question("deliverable::confirm", CONFIRM_BLOCK_ASK, options,
                                 threshold=0.0,
                                 criteria=dict(CONFIRM_BLOCK_CRITERIA),
                                 frame="canDeliver", closed=True),
            ], honor_shadow=False)
            stance = self._stance(asked.get("deliverable::confirm"))
            if stance == "does_not_hold":
                # ★★★ **判官说规则错了 —— 但闸门不放行。**
                #
                #   这是"规则是底线"最硬的一处：**否定一条规则不等于推翻它。**
                #   否定的价值在**账上** —— 它是"我们的规则可能错了"的证据,
                #   离线可以和 `won` 对齐算出**规则被否率**（这个数在设计里
                #   第一次存在）。放行则会让判官重新产生裁决,而那正是这次改掉的东西。
                #
                #   ⚠️ 所以这条路**必须有人看**:一条被反复否定却仍在拦的规则,
                #     说明规则错了,而那时该改的是规则,不是让判官放行。
                self.trace.append({"step": view.step, "node": "canDeliver",
                                   "violation": "judge_disagrees_with_rule",
                                   "fatal": False,
                                   "detail": (f"规则证书 {cert_id} 触发,而判官答"
                                              f"「这条理由不成立」⇒ **闸门仍不放行**"
                                              f"（规则是底线）;这条否定是规则质量的证据")})
            self._record_gate_stance(session, view, "deliverable::confirm",
                                     cert_id, stance, batch)
            return verdict, reason, feedback

        # 规则没有任何证书 ⇒ 规则判定为"可以交付"，但**判官可以提出反驳**。
        options = list(OBJECT_ALLOW_CRITERIA)
        asked = self._ask(session, batch, ctx, view.step, [
            _choice_question("deliverable::object", OBJECT_ALLOW_ASK, options,
                             threshold=0.0,
                             criteria=dict(OBJECT_ALLOW_CRITERIA),
                             frame="canDeliver", closed=True),
        ], honor_shadow=False)
        stance = self._stance(asked.get("deliverable::object"))
        self._record_gate_stance(session, view, "deliverable::object",
                                 "(no certificate)", stance, batch)
        if stance in ("overclaim", "incomplete"):
            # ★ **判官收紧** —— 这是它唯一能产生结果的权力。
            #   而且它只**命名**疾病（`_remedy` 靠病名决定补救），不产生裁决。
            self.trace.append({"step": view.step, "node": "canDeliver",
                               "answer": f"judge_objects/{stance}",
                               "detail": ("规则未触发任何证书，而判官指出了一个"
                                          f"证书查不出的问题（{stance}）⇒ 收紧为 revise")})
            return "revise", stance, (
                f"判官指出了一个确定性检查查不出的问题（{stance}）—— "
                f"确定性检查没有发现可证伪的问题，所以这一条来自判官"
            )
        self.trace.append({"step": view.step, "node": "canDeliver",
                           "answer": "deliver",
                           "detail": "规则无证书 = 可以交付；判官未提出反驳"})
        return "deliver", "", ""

    @staticmethod
    def _stance(answer: Answer | None) -> str:
        """判官在确认/反驳题上说了什么。**缺答 = 没有立场,不产生任何收紧或放松。**"""
        if answer is None:
            return ""
        return str(answer.choice or "")

    def _record_gate_stance(self, session: Session, view: DecisionView, node: str,
                            cert_id: str, stance: str, batch: int) -> None:
        """把判官的立场记进**轨迹**（不进判定账）。

        ★★★ **为什么不另记一行 —— 这是我自己写错又改回来的一处。**

          第一版给立场开了独立的一行（`answer="(stance:...)"`, `source="judge"`）。
          实测一跑就露了：15 次调用出了 **30 行 `risk_confirm`** ——
          判官的答案**本来就已经**在 `_ask_many` 为那道题记的那一行里
          （`answer` 就是 `too_low` / `correct` 那些值，连 `top` 都在）。
          多出来的那一行是**同一件事的第二个副本**，而后果是

            · 节点计数翻倍（`run_diagnostics` 直接可查）
            · **`判定占比` 的分子分母一起被灌水** —— 而那是头条指标

          `AGENTS.md` 那条"一条判定只记一行"说的就是这个：
          `record_decision` 的注释里写着第一版曾在"不果断"时又记一条，
          于是同一次判定在账上出现两遍。**我犯的是同一个错。**

        ★ 那"判官否定了规则"这件事还durable吗？**是** ——
          它在 `deliverable::confirm` 那一行的 `answer`（`does_not_hold`）里，
          和同一 (task, step) 的规则行**联起来**就是那条证据。
          离线联表是 `scripts/run_diagnostics.py` 的活，不是靠多记一行。
          ★ 这里只写 `trace`：它是给人读的，**不作为证据**（跑完就没了）。
        """
        self.trace.append({
            "step": view.step, "node": node, "answer": f"stance:{stance or 'no_answer'}",
            "detail": (f"规则证书={cert_id}；判官立场={stance or '(没答)'}"
                       + ("；**判官否定了规则**（闸门未放行，见 "
                          "`judge_disagrees_with_rule`）" if stance == "does_not_hold"
                          else "；**判官收紧了闸门**" if stance in ("overclaim", "incomplete")
                          else "")),
        })

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
        # ★★★ **把工具输出给生成端看** —— 这是 2026-10-04 补的,而且是必须的。
        #
        #   在那之前这里只有下面那行 `# What was done`（**工具名字**,没有输出）,
        #   而 `call_model` 是无状态的 ⇒ **写答案的模型看不见证据**。
        #   代价实测:9 道 `supported` 里 **8 道的答案就在工具输出里,0 道答出来**;
        #   而草稿里那句"工具失败、没有可用证据"**是一个盲眼的模型唯一能得出的结论**。
        #
        #   ★ 用同一套 `render_evidence`（和闸门同一个投影器）——
        #     两处各写一份"证据长什么样"必然分叉（§8.15 的形状）。
        #   ★ 它**跳过宿主伪步骤**（`__parse_error__`）—— 那是给我们自己看的纠正提示,
        #     不是环境观测（同一个理由见 `ctx_from_steps`）。
        parts += self._evidence_block(view)
        done = "; ".join(f"{s.action.name or s.action.kind}"
                         for s in view.history if not is_harness_pseudo_step(s))
        if done:
            parts += ["", "# What was done", done]
        return session.call_model([Message(role="user", content="\n".join(parts))]).text

    def _generate_argument(self, session: Session, view: DecisionView, tool, name: str) -> str:
        """**不可枚举的参数只能生成** —— 而生成要告诉它"这一栏要什么形状的值"。

        ★★★ 2026-10-04 实测:这一格原来只有一句「Give only the value for `query`」,
          于是模型把**自己的结论**当搜索词发了出去（`search('No value found. …')`）
          ⇒ 没有匹配 ⇒ 它如实报告"语料里没有" ⇒ 而语料里明明有两句互相冲突的数字。
          **`contradiction` 那 5 道全部死在这里:检索根本没发生。**

        ⇒ 用 `Tool.argument_hints`（**环境自己声明**这一栏要什么）。
          这和支持 `base_risk` / `observation_signals` / `describe_candidate`
          是同一条理由:**领域的事实由环境说,引擎猜不出来。**
        """
        lines = [f"Give only the value for `{name}` — nothing else, no quotes, no label."]
        rules = str(getattr(tool, "action_rules", "") or "").strip()
        if rules:
            # ★ 不可枚举的参数（`search[query]` 那种）也受益于"这个世界怎么运作":
            #   实测里它把**自己的结论**当搜索词发出去,就是因为没人告诉它
            #   这个工具要的是"语料里真的出现的短语"（见 `Tool.argument_hints`）。
            lines += ["", "# How this world works", rules]
        hint = str((getattr(tool, "argument_hints", None) or {}).get(name) or "").strip()
        if hint:
            lines += ["", f"# What `{name}` must be", hint]
        lines += ["", "# Task", view.task_prompt,
                  f"# Tool\n{tool.name}: {tool.description}"]
        return session.call_model([Message(role="user", content="\n".join(lines))]).text.strip()

    # —— 判定本身 ────────────────────────────────────────────

    def _ask_many(self, session: Session, batch: int, ctx: AgentCtx, step: int,
                  questions: list[Question], *, honor_shadow: bool = True
                  ) -> dict[str, Answer]:
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
        # ★★★ **有指针的题，把"指哪个"一起问出去。**
        #   判定的本性就是一次前向对所有问题并行打分（`core/deciding.py` 模块头），
        #   所以多问一道**不多一次往返** —— 这正是"举证"能便宜地加进来的原因。
        #   ★ 门限 0：引文是"挑一个"，不是"够不够果断"。挑得犹豫也要把它记下来，
        #     校验交给模型之外的代码（那才是这一整套的重点）。
        pointer_q = [
            Question(node=_POINTER_SUFFIX.join((q.node, "")), kind="choice",
                     ask=q.pointer.ask, options=q.pointer.options,
                     threshold=0.0, frame=q.frame)
            for q in questions if q.pointer is not None
        ]
        req = Request(frame=frame, questions=tuple(questions) + tuple(pointer_q))
        t0 = time.perf_counter()

        for v in req.check(ctx):
            self.trace.append({"step": step, "node": node, "violation": v.code,
                               "fatal": v.fatal, "detail": v.detail})
            # ★★ **违规必须落到事件流里,否则不算有人接收。**
            #
            #   第 10 轮那条失效链是「校验发现 → **无人接收** → 请求照发 → 静默掉点」。
            #   写进内存里一个 list 仍然不是接收 —— 跑完之后没人读得到它,
            #   于是下一个人重建现场时,看到的是「这里怎么少了一次判定」。
            #
            # ★★★ **但"落进事件流"不等于"记成一次判定" —— 这是我犯过三次的错。**
            #
            #   `fatal` 和**非** fatal 要分开记,因为它们是两件不同的事:
            #
            #     fatal     请求**不发**，这道题没有答案 ⇒ 这一行**就是**那次失败的判定
            #               （`(field_missing)` 之类），沿用问题的节点名是对的。
            #     非 fatal  请求照发、答案照收 ⇒ 这一行只是**我们自己的自查告警**
            #               （例:「候选里有做过的工具」）。它**不是**判定,
            #               而第一版把它记成了 `source="judge"` + `confidence=0.0`
            #               + `correct=False`,还**沿用了问题的节点名**。
            #
            #   ⚠️ 后果实测（2026-10-03，ALFWorld 20 题）：**413 行**自查告警
            #      （占全部 2107 行的 20%）被记成了判定,于是
            #
            #        · `pickTool` 的节点计数 240 → **436**（同一件事数了两遍）
            #        · 「判定占比」的**分子分母一起被灌水**:0.898 被读成 0.918
            #        · 校准分析里多出 413 个"置信度 0.0 且答错"的样本 ——
            #          而它们根本不是样本（`confidence` 那一列衡量的东西被稀释了）
            #
            #   ⇒ 自查告警记成**规则行**,节点名带 `::violation` 后缀,
            #     并按 `(declared:N)` 那条先例用括号标明"这一行不是一个判定"。
            #     **一个判定只记一行**（`record_decision` 的文档里记着同一个错的第一版）。
            #
            #   ★ 为什么不是"干脆不记":§8.4 那条不变量**要有人看见**。
            #     `candidate_already_done` 已经因为"每条都报警"死过一次
            #     （见 `_evidence_pointer` 的说明）,不能让它再因为"没人看得见"死第二次。
            fatal_row = bool(v.fatal)
            session.record_decision(
                step=step,
                # ★ 非 fatal 加后缀 —— 沿用问题名会让节点计数翻倍。
                node=(node if fatal_row else f"{node}::violation"),
                answer=f"({v.code})",
                # ★ fatal = 那次失败的判定（没有答案）；非 fatal = 自查记录。
                confidence=(0.0 if fatal_row else 1.0),
                correct=(not fatal_row),
                latency_ms=0.0, batch=batch,
                frame_digest=req.frame.digest(),
                request_digest=req.digest(), request_text=req.render(),
                # ★ 自查告警是**我们自己的规则**发现的，不是判官 —— 记 `rule`。
                source=("fallback" if fatal_row else "rule"),
                fallback=("validation_fatal" if fatal_row else ""),
                note=v.detail,
            )
            if not v.fatal:
                continue
            # ★ 不发。为什么发不出去已经记在账上了 —— 否则调用方只知道「没判定」。
            return {}

        t_req = time.perf_counter()
        resp = self.client.decide(DecideRequest(
            state={"frame": req.frame.render()},
            # ★★★ **用 `req.all_questions`，不是 `questions`。**
            #   指针题只加进了 `req`（帧/校验/渲染那一侧），而这里是**真正上线**
            #   的那一份。第一版写成 `for q in questions`，于是举证题**压根没发出去** ——
            #   而 `_ask_many` 里那段"读出 cited"拿到的是 None，降级路径永远走不到。
            #   ★ 这和 §8.15 那条是同一个形状：**要求写在了一处、生效在另一处。**
            questions={q.node: _wire(q) for q in req.all_questions},
        ))
        # ★ 把**这一次请求**的墙钟报给 session —— 批次耗时按请求累加。
        #   不报的话 `decision_ms` 会退化成「两次开批之间」,把那之间的
        #   生成调用和工具执行一起算进来（实测把框架时间减成了负数）。
        session.note_decision_request((time.perf_counter() - t_req) * 1000)
        # ★★ **这一批是谁答的，必须留痕。** 判定后端是降级链（先试托管 Jev，
        #   挂了退 Mock），而正常降级以前在日志上不留任何痕迹 —— 于是
        #   "这批是真 Jev 答的"变成一个**不可证伪**的说法。
        #   实测：跑完 152 批，`events.jsonl` 里搜「降级」零命中，
        #   而那不能证明没降级，只证明那个字符串当初没地方可写。
        session.note_batch(
            provider=resp.provider,
            actual_provider=resp.actual_provider or resp.provider,
            fallback_chain=resp.fallback_chain,
            degraded=resp.degraded,
            warnings=resp.warnings,
        )

        # ★★★ **先算「成立了没有」,再决定这一批里哪些答案算数。**
        #
        #   于是下面那段记账可以**一道题一行**,而不是一段代码重复三遍 ——
        #   一条判定只记一行,这一条在七个节点上同样成立。
        # ★ 指针题的 id 带后缀，免得和主问题撞名（`canDeliver` 那两道题共用一份帧）
        cited = {q.node: resp.answers.get(q.node + _POINTER_SUFFIX)
                 for q in questions if q.pointer is not None}
        asked = {q.node: resp.answers.get(q.node) for q in questions}
        # ★★★ **三件事要分开，以前只有一件。**
        #
        #   ① `met_bar`  —— 这次判定**够不够格**（`top >= threshold`）。
        #      记账里的 `correct` 记的是这个，语义没变。
        #   ② `usable`   —— 调用方**能不能拿到这个答案**。
        #      以前 ② == ①：不够格就丢掉。而对**动作类**节点，
        #      丢掉等于让循环去重发一个逐字节相同的请求 —— 那是抽奖，不是恢复
        #      （实测 20 组同 digest 请求里 19 组置信度不同；见 `BELOW_THRESHOLD_POLICY`）。
        #   ③ 未达门限却被采用 —— 只体现在 `note` 里，**不污染 `correct`**。
        #
        #   ★ 为什么要拆：`correct` 一旦被写成「我们用了它」，账上就再也分不出
        #     「果断地判对了」和「不果断但照走」—— 而那正是置信度这一栏要检验的事。
        below = {q.node: (asked[q.node] is not None and asked[q.node].top() < q.threshold)
                 for q in questions}
        met_bar = {q.node: (asked[q.node] is not None and not below[q.node])
                   for q in questions}
        # ★★★ **`shadow` 的题：答了、记了，但不许落地。**
        #   这是 μ 那一档的全部内容 —— 判定模型被问了,返回的却是
        #   "没有判官时宿主的那个答案"。**不这么做,"这条判定有没有用"
        #   永远只能靠换一个 agent 去比,而那不是同一回事。**
        # ★ 用**题族**匹配:一候选一题下题名是 `pickInput::3`,
        #   而 `shadow` / 兜底 / 门限都是按判定点登记的。
        shadowed = {q.node for q in questions
                    if question_family(q.node) in self._shadowed_questions}
        #   ★★ `honor_shadow=False` = **把答案交出去,只是不许它落地**。
        #     闸门需要它自己那两个答案**才能算出裁决** —— 不交出去的话
        #     `_can_deliver` 看到的是"没有答案",于是返回 `blocked/unjudgeable`,
        #     而记录下来的裁决会是 `(shadow:blocked/unjudgeable)`：
        #     **shadow 什么都没观察到,却看起来像观察过了。**
        #     （实测撞到:第一次实现就是这样,账上写着 blocked 而判官明明答了 0.1/0.1。）
        #   ⇒ 所以 shadow 分两件事:**记账**在 `_ask_many`（永远记）,
        #     **落不落地**由调用方声明的这一档定。
        usable = {
            q.node: (
                (q.node not in shadowed or not honor_shadow)
                and (
                    met_bar[q.node]
                    or (below[q.node]
                        and BELOW_THRESHOLD_POLICY.get(question_family(q.node)) == "accept")
                )
            )
            for q in questions
        }

        for q in questions:
            answer = asked[q.node]
            # ★★★ **举证校验：跑在判定模型之外。**
            #
            #   规则只说一件事：**一条肯定性裁决（`noul` 判 true）必须能指出依据。**
            #   指不出 ⇒ 该裁决**不成立**，按 false 处理，并写明是哪一项没通过。
            #
            #   ★ 为什么只约束"肯定"那一侧：`Acknowledge/deny` 不需要举证 ——
            #     否认一个说法不需要引文。而"我确认它成立"需要。
            #   ★ 为什么不是"重试"：指不出依据说明**证据里就没有**，
            #     再问一次同一个请求不会变出证据来（`docs/RETRY-DOES-NOT-HELP.md`）。
            pointer_note = ""
            if (q.pointer is not None and answer is not None
                    and answer.prob_true() >= q.threshold):
                got = cited.get(q.node)
                picked = got.choice if got is not None else ""
                ok = bool(picked) and q.pointer.validate(picked)
                if not ok:
                    pointer_note = (f"举证未通过：指到 {picked or '(没答)'}"
                                    f"{'（=指不出来）' if picked == q.pointer.none_option else ''}"
                                    f" ⇒ 该肯定性裁决不成立")
                    answer = replace(answer, noul=0.0)
                    asked[q.node] = answer
            if answer is None:
                # 后端没给 / 给了畸形的 —— §8.10:报出来,不假装
                detail = f"dropped={resp.dropped} missing={resp.missing} {resp.warnings}"
                # ★★ **兜底必须记名** —— 名字来自声明表,不是从代码里读出来的行为。
                #   没有这一栏,"这一步为什么没往下走"事后只能靠复现,
                #   而"重试"和"转去收尾"在日志上长得一模一样。
                fb = FALLBACK_POLICY.get(question_family(q.node), "retry")
                self.trace.append({"step": step, "node": q.node,
                                   "violation": "answer_unusable", "fallback": fb,
                                   "fatal": True, "detail": detail})
                session.record_decision(
                    step=step, node=q.node, answer="(answer_unusable)", confidence=0.0,
                    correct=False, latency_ms=(time.perf_counter() - t0) * 1000, batch=batch,
                    frame_digest=req.frame.digest(), request_digest=req.digest(),
                    request_text=req.render(),
                    note=f"{detail}；声明兜底={fb}（`FALLBACK_POLICY`）",
                    source="fallback", fallback=fb,
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
                correct=met_bar[q.node],
                # ★★ **一条判定只记一行。**
                #
                #   第一版这里在「不果断」时**又记了一条** —— 于是同一次判定在账上出现两遍,
                #   而**判定次数正是论文的头条指标之一**。这和 §8.10「按批计时、按记录求和
                #   会多算几倍」是同一类错:账目上的一个数被数了两遍,而账面上看不出来。
                #
                #   所以原因写在**同一行的 `note` 里**,不是另起一行。
                # ★★★ **这一列区分"判定模型判的"和"规则兜的底"。**
                #   过门限 ⇒ `judge`（它在管事）;没过门限 ⇒ `fallback`,
                #   名字写明是"低于门限仍采用"还是"低于门限就丢掉"。
                #   ⚠️ 指针校验把 `noul` 打成 0 的那条**仍算 `judge`** ——
                #      是模型答了、我们的规则否决了它,不是模型没答。
                # ★★★ **`shadow` 的答案进账，但 `source` 记成 `fallback`** ——
                #   因为**返回给循环的**确实是兜底。判定模型的答案就留在这一行的
                #   `answer`/`confidence` 里 ⇒ 离线能算「它的裁决对不对」,
                #   不需要把这一档接到行为上。
                #   ★ 名字 `"shadow"` 就是 μ 的 `judged=true ∧ source="fallback"`
                #     那一格 —— **它的 `judged` 在我们这里由兜底的名字承担**,
                #     不再单开一列:那一列会与 `source` 重复,而重复的列会各自漂移
                #     （`source="rule"`/`"generate"` 已经说明了"判官没被问"）。
                # ★ 规范状态键:让"同一状态重复问了几次、答的一样吗"以后**能从盘上重算**。
                #   `request_digest` 只是"发出去的那段字一样吗",不是"状态一样吗"。
                # ⚠️ 用 `q.frame or q.node`,**不是** `q.node` —— 题的名字和帧的名字
                #   不是一回事(`needs_auth` 那道题的帧叫 `gradeRisk`)。
                #   第一版写成 `q.node`,57 条测试当场红:`frame_for` 打错名字就炸。
                state_key=canonical_state(ctx, q),
                source=("fallback" if (below[q.node] or q.node in shadowed) else "judge"),
                fallback=("shadow" if q.node in shadowed else
                          (f"accept_below_bar"
                           if BELOW_THRESHOLD_POLICY.get(question_family(q.node)) == "accept"
                           else "drop_below_bar") if below[q.node] else ""),
                note=(pointer_note or (
                    # ★★ `shadow`：**这次判定没有落地**，理由要写在账上。
                    #   不写的话,它和一次"答案被采用了"在表里长得一样,
                    #   而两者的分数**不能进同一张表**。
                    "**shadow：判定已记录但未落地**（`SHADOW_DECISIONS`）—— "
                    "返回的是没有判官时的行为；本行的 `answer`/`confidence` "
                    "是该判定模型的真实裁决，供离线比对"
                    if q.node in shadowed else
                    ("" if not below[q.node] else (
                        f"top={answer.top():.3f} < {q.threshold}"
                        + ("，**低于门限仍采用**（该节点的失败可被循环观测并纠正；"
                           "重发相同请求是抽奖，见 `BELOW_THRESHOLD_POLICY`）"
                           if BELOW_THRESHOLD_POLICY.get(question_family(q.node)) == "accept"
                           else "，**弃答 ⇒ 按 `FALLBACK_POLICY` 走 "
                                f"{FALLBACK_POLICY.get(question_family(q.node), 'retry')}**"))))),
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
            if q.node in shadowed:
                # ★ 它不是违规,是**这一档设计如此** —— 所以 `fatal=False`,
                #   而且违规码和"答得不果断"分开,免得把 shadow 的批次读成坏批次。
                self.trace.append({
                    "step": step, "node": q.node, "violation": "shadow",
                    "fatal": False,
                    "detail": (f"{q.node}: 判定已记录（top={answer.top():.3f}）"
                               f"但**未落地**；返回的是没有判官时的行为"),
                })
            elif not usable[q.node]:
                self.trace.append({
                    "step": step, "node": q.node, "violation": "below_threshold",
                    "fatal": True,
                    "detail": (f"{q.node}: top={answer.top():.3f} < {q.threshold}"
                               f"（答得不果断,不许拿它往下走）"),
                })

        return {n: a for n, a in asked.items() if a is not None and usable[n]}

    def _ask(self, session: Session, batch: int, ctx: AgentCtx, step: int,
             question: Question | list[Question], *, honor_shadow: bool = True
             ) -> dict[str, Answer]:
        """一道题的形状（`_ask_many` 的薄壳）：`_ask(..., q)["节点"]`。

        ★ 留着它是因为大多数调用点只问一件事,而写成
          `_ask_many(..., [q])["节点"]` 会让「这一步要的是哪一个答案」
          淹没在样板里。**多题和单题走的是同一条路径** ——
          薄壳不许有自己的校验或记账,否则两条路会分叉。
        """
        return self._ask_many(session, batch, ctx, step,
                              [*question] if isinstance(question, list) else [question],
                              honor_shadow=honor_shadow)

    def _blocked(self, session: Session, view: DecisionView, why: str,
                 *, answer: Answer | None = None, gate: str = "",
                 draft: str = "") -> Decision:
        """这一步发不出去 / 判定不成立。

        ★ 返回 `unparsed` 而不是硬凑一个动作 —— `unparsed` 的措辞是
        **「没答出来」不是「答错了」**（`core/controller.py`）。循环会重试,
        重试用完就 `escalate`,而 `escalate` 是一种**能被看见**的结果。

        ⚠️ 弃答的**原因**放进 `raw`,而且开头就写明是 `typed:` ——
        不写的话,日志上它和「模型格式错了」长得一样,而那是完全不同的事。

        ★★ `draft` = **闸门拒绝交付时它打回的那一版**。必须带回去：
          闸门说 `blocked` 之后，我们既不知道那一版是编的还是诚实的，
          也就分不出闸门是**保护**了我们还是**误杀**了一个好答案 ——
          而这两件事一个说明闸门有用、一个说明闸门有害。
        """
        detail = ""
        if answer is None and self.trace:
            detail = self.trace[-1].get("detail", "")
        return Decision(kind="unparsed", syntax="typed", gate=gate, draft=draft,
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


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

#: ★ **列表序号** —— 行首的 `1.` / `2)` / `3、`，它们**不是关于世界的断言**。
#:
#: 实测（2026-10-08，ALFWorld × `react-typed`）：模型写了一份带编号的步骤清单
#:
#:     Here is a step-by-step breakdown of the actions …:
#:
#:     1.  **Pick up the mug**: Reach out and …
#:     2.  …
#:     3.  …
#:
#: 而观测里只出现过 1 和 2 ⇒ 那个 **`3` 被当成"证据里没有的数"**，
#: 整份草稿被判 `overclaim` 打回去重写。**那是序号，不是断言。**
#: （另一条更糟：草稿本身是"我做不到"的**诚实拒绝**，同样被拦去重写。）
#:
#: ⇒ 抽数字之前先把行首的列表序号剥掉。**序号是排版，值是内容** ——
#:   混在一起会让闸门对每一份带清单的回答都报警，而"一条永远为真的告警
#:   等于没有告警"（`candidate_already_done` 就是这么死的）。
_LIST_MARKER = re.compile(r"^\s*\d+[.)、](?!\d)\s*", re.M)


def _numbers_in(text: str) -> set[str]:
    """一段文本里**被断言**的数字（去掉千分位逗号；剥掉行首列表序号）。

    ★ 去逗号是踩过的:实测 `1,284` 被切成 `1` 和 `284`,于是同一条假声明
      有时判得中有时判不中（见 FTA 那一段 detector 的注释）。
    ★ 剥序号是实测逼出来的,见 `_LIST_MARKER`。
    """
    return {m.group(0).replace(",", "")
            for m in _NUMBER.finditer(_LIST_MARKER.sub("", text or ""))}


def _ungrounded_numbers(ctx: AgentCtx) -> list[str]:
    """草稿里的数，有没有在任何一步的工具输出里出现过。**纯检索，不问模型。**

    ★★ 两版闸门（判官产生裁决 / 规则先筛）**都走这一个函数**。
      第一版的规则优先实现把它抄了一份，于是同一件事有两处实现 ——
      而"数字落地"是这套闸门里最锐利的一条证书，两处实现分叉之后
      一批数字用哪个口径算就说不清了（§8.15 的形状）。

    ★ 为什么它可以当**证书**：这是集合差，不是意见。
      实测（2026-10-07，ALFWorld × react-termination × 20 题）：
      做成一问一验（"哪一步包含这些数" + 校验被指的那一项）时
      **误杀了两条 `won=True` 的题** —— 证据里明明写着
      `You move the watch 1 to safe 1. [task complete]`，而 Jev 答了"指不出来"。
      **指针本身也是模型判断，它有自己的错误率。**
      ⇒ 而"这个数在不在证据里"是**可检索的**，可检索的检查就不该问模型
        （§8.1：能由规则定的不交给判定模型）。

    ⚠️ **只管数字。** 纯散文的断言（"placed the apple in the fridge" 对着
      "the fridge is closed"）共享 token，检索抓不住 —— 那一档只有判官能抓，
      见 `NOT_YET_CERTIFICATES`。
    """
    evidence: set[str] = set()
    for r in ctx.records():
        evidence |= _numbers_in(str(getattr(r, "result", "")))
    return sorted(_numbers_in(str(getattr(ctx, "draft", "") or "")) - evidence)


def _risk_band(tool, arguments: dict) -> tuple[int, str]:
    """**规则层**：这一调的风险档位。返回 `(档位, 来源标签)`。**不问模型。**

    档位按这个顺序定：

      ① 工具声明了 `base_risk` ⇒ **它是这一调的地板**
      ② `RISK_PATTERNS` 跑在工具名 + 渲染后的参数上 ⇒ **只准往上抬,不准往下压**
      ③ 没声明、也没有模式命中 ⇒ `UNKNOWN_TOOL_BAND`（**2 = 不可逆 ⇒ 问人**）

    ★★★ **`base_risk` 从"覆盖"变成了"地板"，这是一处语义反转，要记下来。**
      `docs/GROUNDING-STEP1-DECLARED-RISK.md` 那一版是"查表就不问"——
      工具声明了就完全听它的。现在不是：**这一调的内容是更锐利的证据**，
      一个声明为只读的工具，参数里写着往 `/etc` 重定向，仍然要被抬上去。
      同一条理由也是判官只能抬不能降的那一条 —— 收紧方向永远开着。
      ⚠️ 代价如实说：模式跑在**文本**上，分不出"代码"和"数据"——
      一个只读工具的**参数值**里如果含有 `rm`，会被误抬（安全方向，但会多问人）。

    ★★ ③ 是这套设计里最需要盯着的一格：通用工具（`exec` / `act`）的危险
      取决于这一次的内容，而规则**认不出来不等于安全**。默认成 0
      就是把"不知道"静默读成"只读" —— 那正是这条设计要消灭的那类错。
      代价如实说：认不出来的调用会去问人。**"认不出来的比例"要作为
      一个数报出来**（账上 `risk` 那一行的 `source`，`unknown` 就是它）。

    ★ 顺序是判据：模式表第一条命中就返回，所以破坏性的模式必须排在前面
      （`rm` 既是"写"也是"毁"，表里 ③ 在 ① 之前）。
    """
    declared = getattr(tool, "base_risk", None)
    # 工具名和参数一起看 —— 「哪个工具」和「这一次的内容」都是风险的一部分。
    blob = f"{getattr(tool, 'name', '')} {render_tool_input(arguments, '')}".lower()
    hit = next(((band, pat) for pat, band in RISK_PATTERNS if re.search(pat, blob)), None)

    if declared is not None:
        floor = int(declared)
        if hit is not None and hit[0] > floor:
            # ★ 模式**抬**得动声明 —— 但绝不压得低。见上面那段语义反转。
            return hit[0], f"pattern>{floor}:{hit[1]}"
        return floor, "declared"
    if hit is not None:
        return hit[0], f"pattern:{hit[1]}"
    return UNKNOWN_TOOL_BAND, "unknown"


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
