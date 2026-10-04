"""`react × typed` —— 论文 Table 2 的第一个格子。

这个文件测的不是「准确率」,是**两条臂只差一个控制器**这句话在代码里成不成立。

★ 最值钱的一条是 `test_the_typed_arm_does_not_reuse_the_react_prompt` ——
它钉住的是**加第二个控制器实现时撞出来的接口缺口**（`DecisionView` 只有
渲染好的 ReAct 提示词,没有任务原文）。那一条在只有一种实现时**永远看不到**。

跑法（在 `JevLoop/` 下）::

    python3 -m pytest experiments/tests -q
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.baseline.common import LoopConfig, run_loop  # noqa: E402
from experiments.baseline.react import ReAct  # noqa: E402
from experiments.benchmark.toy import CAPITALS, ToyCapitals  # noqa: E402
from experiments.core.agent import Session  # noqa: E402
from experiments.core.controller import DecisionView  # noqa: E402
from experiments.core.deciding import DecideResponse, parse_answers  # noqa: E402
from experiments.core.models import CallableModel, Message  # noqa: E402
from experiments.core.tools import ToolExecutor  # noqa: E402
from experiments.jloop.typed import TypedController, candidates  # noqa: E402


# ═══════════════════════════════════════════════════════════
# ★★★ 两版闸门，两组测试
#
# `gates_rules_first=False`（**判官产生裁决**）= 本文件里**历史那批测试**钉的方法，
# 也是 `docs/ALFWORLD-ESCAPE.md` 那批数字所属的方法。留着它是因为它是
# **已发表的对照**，而且规则优先那一版换的是裁决的来源，两者不能进同一张表
# （`DECISION_SPEC_VERSION` 已 bump）。
#
# 规则优先那一版（默认）的测试在 `test_gates_rules_first.py`。
# ★ 所以下面所有 `judge_gate(...)` 都是**显式**声明"我在测旧方法"，
#   而不是"忘了改" —— 名字本身就是这句话。
# ═══════════════════════════════════════════════════════════


def judge_gate(client, **kw):
    """旧方法（判官产生裁决）的控制器。**本文件历史测试都走它。**"""
    from experiments.jloop.typed import TypedController

    return TypedController(client, gates_rules_first=False, **kw)


def single_choice(client, **kw):
    """**旧题形**（`pickInput` 是一道 N 选 1）的控制器。

    ★ 一候选一题是 2026-10-04 起的新默认。而下面这几条测试钉的是**旧形状特有的行为**:
    退出口是候选表里的一个**选项**、`top()` 门限、`accept_below_bar` / `drop_below_bar`
    这两种兜底名字。**新形状下这些概念不存在**（逃逸变成"没有任何候选过线"），
    所以它们必须显式声明测的是旧形状 —— 而不是悄悄跟着默认值跑。
    """
    from experiments.jloop.typed import TypedController

    return TypedController(client, pick_input_shape="single_choice", **kw)




# ═══════════════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════════════


def _family(qid: str) -> str:
    """题的 id → 它属于哪个判定点（去掉逐候选那一层编号）。引擎里同一件事叫
    `typed.question_family`，这里保持同一个判据:只有 `::<数字>` 才是逐候选。"""
    head, sep, tail = qid.rpartition("::")
    return head if sep and tail.isdigit() else qid


def _candidate_ref(request, qid: str) -> str:
    """从**编号表**里读出这道题问的那个候选值。

    ★ 表在帧里（`actions_on_the_table`，形如 `[3] France — …`），
      而题里只有编号 —— 这正是 `jev-ultrafast` 的
      "dynamic, indexed action space"（状态里放表，题里只引用索引）。
      替身要读表，就像真判官要读表一样。
    """
    index = qid.rsplit("::", 1)[-1]
    frame = str((getattr(request, "state", None) or {}).get("frame") or "")
    for line in frame.splitlines():
        line = line.strip()
        if line.startswith(f"[{index}] "):
            rest = line[len(index) + 3:]
            return rest.split(" — ", 1)[0].strip()
    return ""


class ScriptedClient:
    """按脚本回答的判定后端。**它把每次请求都记下来** —— 「有没有发出去」要用。

    ★★ **它必须认三种问题形状,而且认出 `score`。**
    七个节点接齐之后多了一格 `score`（`gradeRisk` 的 `risk`,`vocab.ts` 里
    的 `{type:'score', criteria:[档位…]}`）。第一版这里只有 `choice` 和
    `noul` 两支,于是 `risk` 被当成 `noul` 答回去 —— 而 `parse_answers`
    **认值不认标签**,它会按 `noul` 收下,`Answer.score` 恒为 0。
    结果:每一调都被判成「只读」,`auto_audit` 和 `ask_human` 两条路
    **在测试里永远走不到** —— 而它们正是要测的东西。

    ★ `noul` 可以是:

    - 一个数 —— 所有 `noul` 题都答它;
    - 一个**列表** —— 按**调用顺序**依次取（越界后停在最后一个);
    - 一个 **dict** —— 按**问题 id** 取（`{"needsTool": 0.9}`）。

    接七个节点之前,顺序那套够用（一步只问两三次);现在一步最多四次请求、
    而且顺序取决于哪条分支先命中 —— **按位置写脚本会变成在测「调用顺序」,
    不是在测被测的东西**。所以需要精确控制时用 dict。
    """

    name = "scripted"

    def __init__(self, *, noul: float | list[float] | dict[str, float] = 0.9,
                 pick: dict[str, str] | None = None,
                 score: int = 0,
                 omit: tuple[str, ...] = (),
                 spread: float = 0.9) -> None:
        self.noul = noul
        self.pick = pick or {}
        #: `score` 题的档位。**默认 0 = 只读** —— 让绝大多数测试走过 `auto`,
        #: 要看闸门的那几条自己把它调到 1 / 2。
        self.score = score
        #: 选中项拿多少概率。**调低它就是「答得不果断」** ——
        #: §8.6 要 Mock 走到的那条路,这里可以精确地只让它发生在一道题上。
        self.spread = spread
        self.omit = set(omit)
        self.requests: list = []
        self._call = 0

    def _noul_for(self, qid: str) -> float:
        if isinstance(self.noul, dict):
            # ★ 逐候选的题（`pickInput::3`）用一个通配键 —— 否则给不出
            #   "needsTool 高、每个候选都低"这种组合，而那正是
            #   "没有任何候选过线"要测的东西。
            if qid.startswith("pickInput::") and "pickInput::*" in self.noul:
                return float(self.noul["pickInput::*"])
            return float(self.noul.get(qid, 0.9))
        if isinstance(self.noul, list):
            return float(self.noul[min(self._call, len(self.noul) - 1)])
        return float(self.noul)

    def decide(self, request):
        self.requests.append(request)
        self._call += 1

        raw: dict = {}
        for qid, q in request.questions.items():
            # ★★ **`omit` 按"判定点"理解,不是按"题"。**
            #   一候选一题之后题的 id 是 `pickInput::3`,而 `omit={"pickInput"}`
            #   的意思是"这一整个判定点都不答"。第一版按精确 id 比,
            #   于是它**什么都没省略** —— 而账上看起来一切正常
            #   （每道候选题都拿到了默认的 0.9）。
            if qid in self.omit or _family(qid) in self.omit:
                continue
            # ★ 读**线协议**的字段名（`type` / `criteria`）—— 这就是
            #   `vocab.ts` 里那个形状。读错了这套测试就白测。
            if q["type"] == "choice":
                opts = list(q["criteria"])
                chosen = self.pick.get(qid, opts[0])
                rest = max(1, len(opts) - 1)
                leftover = max(0.0, 1.0 - self.spread)
                raw[qid] = {"type": "choice", "choice": chosen,
                            "probabilities": {o: (self.spread if o == chosen
                                                  else leftover / rest)
                                              for o in opts}}
            elif q["type"] == "score":
                raw[qid] = {"type": "score", "score": self.score,
                            "confidence": self.spread}
            elif qid.startswith("pickInput::") and "pickInput" in self.pick:
                # ★★★ **一候选一题的新形状**（2026-10-04）。
                #
                #   旧形状是一道 N 选 1 的 `choice`，替身从 `criteria` 里挑一个
                #   就算"选中了"。新形状是 **N 道 `noul` 题**，每道问
                #   「`[i] <候选>` 是不是任务下一步要做的」，而候选表**在帧里**
                #   （`actions_on_the_table`，形如 `[3] France — …`）。
                #
                #   ⇒ 替身必须**像真判官那样读表**:认出第 `i` 行的候选值，
                #     是目标就答"是"，否则答"否"。
                #
                #   ⚠️ 第一版没做这件事，于是每道题都拿到默认的 `noul=0.9`
                #     ⇒ **全部平局** ⇒ 排序稳定 ⇒ **第一个候选胜出**（`Bhutan`）。
                #     而测试想要的是 `France`。**平局时按顺序取第一个，
                #     在真判官那里是"它没看出区别"，在替身这里是"脚本没写"。**
                want = str(self.pick["pickInput"])
                ref = _candidate_ref(request, qid)
                yes = bool(ref) and ref == want
                raw[qid] = {"noul": self.spread if yes else max(0.0, 1.0 - self.spread)}
            else:
                raw[qid] = {"noul": self._noul_for(qid)}

        # ★ 走真的归一化,不绕过它 —— 否则这些测试和 `parse_answers` 是两套口径
        answers, dropped, missing = parse_answers(raw, list(request.questions))
        return DecideResponse(answers=answers, provider=self.name,
                              dropped=dropped, missing=missing,
                              degraded=bool(dropped or missing))

    def asked(self, node: str) -> int:
        return sum(1 for r in self.requests if node in r.questions)

    def questions(self) -> list[str]:
        """按顺序摊平**问过的问题 id** —— 「哪几个节点被问到了、按什么顺序」
        用它,而不是去数请求数（一次请求可以带多道题）。"""
        return [qid for r in self.requests for qid in r.questions]


def capital_model(seen: list | None = None) -> CallableModel:
    """假模型:任务里问哪个国家就答哪个首都。**记下它看到的每条 prompt。**"""

    def responder(messages: list[Message]) -> str:
        if seen is not None:
            seen.append(messages[-1].content)
        text = messages[-1].content
        for country, capital in CAPITALS.items():
            if f"capital of {country}" in text:
                return capital
        return "I don't know."

    return CallableModel(responder, model_id="fake")


def pick_input_rows(session_or_rows) -> list:
    """`pickInput` 那一族的记账行 —— **两种题形都要认**。

    ★ 一候选一题（2026-10-04 起的新默认）下，`pickInput` 的记账行叫
      `pickInput::1` … `pickInput::N`（每道候选题一行）。
      旧的 N 选 1 形状下只有一行，就叫 `pickInput`。
      **按 `node == "pickInput"` 过滤会静默地一行都取不到** ——
      而"取不到"在断言里长得很像"这个行为没发生"。
    """
    rows = getattr(session_or_rows, "decision_records", None)
    rows = rows() if rows is not None else session_or_rows
    return [r for r in rows if r.node == "pickInput" or r.node.startswith("pickInput::")]


def asked_pick_input(client) -> bool:
    """这一轮问过 `pickInput` 吗（两种题形都算）。"""
    return any(n == "pickInput" or n.startswith("pickInput::") for n in client.questions())


def make_session(arm: str = "react", *, country: str = "France",
                 undeclared_risk: bool = False,
                 signals: dict | None = None) -> Session:
    bench = ToyCapitals()
    tools = list(bench.tools())
    if signals:
        # ★ 给工具装上**环境自己声明的成败信号**（ALFWorld 的 `act` 就是这样）
        tools = [replace(t, observation_signals=signals) for t in tools]
    if undeclared_risk:
        # ★★ **「工具说不出自己的风险」那一档。**
        #   `toy` 的 `lookup_capital` 是只读的，所以它声明 `base_risk=0` ——
        #   于是 `gradeRisk` 对它是**查表**，不问模型。
        #   而"让模型判风险"这条路**只在没有声明的工具上还存在**
        #   （Terminal-Bench 的 `exec`、ALFWorld 的 `act`：危险与否取决于这一调的内容）。
        #   所以要测那条路，就得用不声明的工具 —— 否则测的是一条已经不走的代码。
        tools = [replace(t, base_risk=None) for t in tools]
    task = next(t for t in bench.tasks(split="test", limit=None, seed=0)
                if t.task_id == f"toy/{country}")
    return Session(
        run_id=f"test/{arm}", task=task, arm=arm, tools=tools,
        executor=ToolExecutor(tools, bench.tool_impls()),
        model=capital_model(), max_steps=8, temperature=0.0, max_tokens=128,
    )


# ═══════════════════════════════════════════════════════════
# ★★ 两根轴是**组合**,不是两套代码
# ═══════════════════════════════════════════════════════════


def test_both_controllers_drive_the_very_same_loop() -> None:
    """★★ `react × llm` 和 `react × typed` 的差**只可能来自决策者**。

    这不是声明,是构造:两条臂共用同一个 `run_loop`、同一个 `build_prompt`、
    同一批工具、同一个 `max_steps`。**唯一不同的那个字段就是 `cfg.controller`。**
    """
    llm = ReAct()
    typed = ReAct(controller=judge_gate(ScriptedClient()))

    assert llm.config.controller is None, "llm 那格用默认控制器"
    assert isinstance(typed.config.controller, TypedController)

    differing = {f for f in LoopConfig.__dataclass_fields__
                 if getattr(llm.config, f) != getattr(typed.config, f)}
    assert differing == {"controller"}, f"两条臂还差了别的:{differing}"


def test_the_arm_name_stays_the_same_so_logs_do_not_get_two_spellings() -> None:
    """日志里 `arm` 决定 `log/<dataset>/<arm>/` 的路径。

    ★ 两条臂靠**目录名后缀**区分,不靠 `cfg.name` —— 否则同一个循环会有两个名字,
    而「我们跑的是哪一条臂」在日志里就说不准了（§3.4 那条计数检查防的是同一类事）。
    """
    assert ReAct().config.name == ReAct(controller=judge_gate(ScriptedClient())).config.name


def test_a_run_with_the_typed_controller_produces_a_correct_answer() -> None:
    """端到端:`react × typed` 在 toy 上真的走得通,并交出正确答案。

    ★ 脚本**按问题 id 写,不按调用顺序写** —— 七个节点接齐之后一步最多四次
    请求,而先命中哪条分支取决于判定答案。按位置写脚本会变成在测调用顺序。
    """
    session = make_session()
    outcome = ReAct(controller=judge_gate(ScriptedClient(
        noul={"needsTool": 0.9,               # 第一步:还要动手
              "isDone": 0.6,                  # 做完这一步,但任务没完
              "needs_auth": 0.1},             # 读写工作目录里的事,不用批
        pick={"pickInput": "France"},
    ))).solve(session)

    assert outcome.final_answer == "Paris"
    assert not outcome.escalated
    tool_steps = [s for s in outcome.steps if s.action.kind == "tool"]
    assert [s.action.name for s in tool_steps] == ["lookup_capital"]
    assert tool_steps[0].action.arguments == {"country": "France"}


# ═══════════════════════════════════════════════════════════
# ★★★ 加第二个实现才撞出来的接口缺口
# ═══════════════════════════════════════════════════════════


def test_the_typed_arm_does_not_reuse_the_react_prompt() -> None:
    """★★★ **`view.prompt` 是渲染产物,不是材料。**

    它是 `build_prompt` 拼好的 **ReAct 提示词** —— 里面写着
    `Action: <tool>[<argument>]`。拿它去让 LLM 生成最终答案,模型会照着格式
    吐一个动作行,而我们把那一行当答案收下。

    加 `TypedController` 时撞上的:想自己拼提示词,却发现**任务原文不在 view 里**,
    它只存在于 `prompt` 字符串的中间某处。于是第二个实现只有两条路:
    去 `prompt` 里做字符串手术,或者照抄 ReAct 的格式。**两条都是错的。**

    修法是把材料补进 view（`task_prompt`）。这条测试钉住的是:**生成答案用的
    提示词里不许出现 ReAct 的动作格式** —— 加了 `task_prompt` 之后仍然可能被改回去。
    """
    seen: list[str] = []
    session = make_session()
    session.model = capital_model(seen)

    ReAct(controller=judge_gate(ScriptedClient(
        noul={"needsTool": 0.9, "isDone": 0.6, "needs_auth": 0.1},
        pick={"pickInput": "France"},
    ))).solve(session)

    assert seen, "模型一次都没被调用?"

    # ★ 认「生成答案那一次」的判据:**它带着任务原文**（ReAct 的提示词也带着,
    #   但那条是 `build_prompt` 拼的,里面一定有 `Action:`）。
    #   ⚠️ 原来这里用「含 final answer」来认,而后来我们把那句多余的契约删了 ——
    #     **一条依赖措辞的测试,会因为我们改措辞而失效,而不是因为被测的东西坏了。**
    answer_prompts = [p for p in seen if "What is the capital of" in p]
    assert answer_prompts, "没找到生成答案的那次调用"
    for prompt in answer_prompts:
        assert "Action:" not in prompt, (
            "生成答案的提示词里带着 ReAct 的动作格式 —— "
            "模型会照着吐一个动作,而我们把它当答案收下"
        )


def test_the_typed_arm_does_not_add_a_second_output_contract() -> None:
    """★★★ **一条输出契约就够了** —— 而且它归 benchmark。

    `core/bench.py` 的分工表:「任务陈述 + **输出契约** → **benchmark**;
    交互协议 → baseline。**baseline 不许改任务陈述,只能加自己的协议块。**」

    实测代价(GSM8K × 100,单 commit):`react-typed` **63%**、9.8 个输出 token;
    而 `direct` **97%**、131.7 个 token —— **同一个模型**。
    我们那条 `ANSWER_FORMAT`(「只给最终答案」)**把推理一起禁掉了**。

    ★ 这正是已经记过的教训(两条契约并存时看不出模型听了哪条)——
      记过了还是又犯了一次,所以这条测试要**机械地**钉住。
    """
    session = make_session()
    seen: list[str] = []
    # ★ 生成端**不看参数**:这条测试要量的是「闸门打回之后有没有真的重写」,
    #   而不是「工具查的是哪个国家」。所以答案固定是那个首都 ——
    #   参数由闸门随便挑,证据里那一次调用返回的也正是这句话。
    session.model = CallableModel(
        lambda messages: (seen.append(messages[-1].content), "Paris")[1],
        model_id="fake")

    ReAct(controller=judge_gate(ScriptedClient(
        noul={"needsTool": 0.9, "isDone": 0.6, "needs_auth": 0.1},
        pick={"pickInput": "France"},
    ))).solve(session)

    answer_prompts = [p for p in seen if "What is the capital of" in p]
    assert answer_prompts
    for prompt in answer_prompts:
        # 契约只该出现一次,而且只该是 benchmark 写的那一条
        assert prompt.count("Answer with the city name only") == 1
        assert "final answer only" not in prompt.lower(), "我们又加了一条输出契约"
        assert "Do not emit an action" not in prompt, "同上"


def test_the_view_carries_the_task_text_not_only_a_rendered_prompt() -> None:
    """★ 上一条的根:view 里得有**任务原文**,不能只有渲染好的提示词。

    `task_prompt` 是后加的。它缺席时,任何不按 ReAct 格式生成的控制器
    都只能去 `prompt` 里做字符串手术 —— 而那是**靠字符串巧合**在工作。
    """
    import dataclasses

    assert "task_prompt" in {f.name for f in dataclasses.fields(DecisionView)}
    view = DecisionView(prompt="<渲染好的 ReAct 提示词>", tools=(), task_prompt="问题原文")
    assert view.task_prompt == "问题原文"


def test_run_loop_actually_fills_the_task_prompt() -> None:
    """★ 光有字段不算 —— `run_loop` 得真的把它填上,否则它是**永远为空的摆设**。"""
    captured: list[DecisionView] = []

    class Spy:
        name = "spy"

        def decide(self, session, view):
            captured.append(view)
            from experiments.core.controller import Decision
            return Decision(kind="answer", answer="Paris")

    session = make_session()
    session.model = capital_model()
    run_loop(session, LoopConfig(name="spy", instruction="x", controller=Spy()))

    assert captured and captured[0].task_prompt == session.task.prompt
    assert "capital of France" in captured[0].task_prompt


# ═══════════════════════════════════════════════════════════
# §8.4 候选每步重建 —— 在这里是**构造性的**,不是提示
# ═══════════════════════════════════════════════════════════


def test_the_same_frame_is_not_the_same_request() -> None:
    """★★★ **比「两次跑的是不是同一个判定」,要比请求的指纹,不是帧的。**

    实测踩过（2026-09-23）:我拿 `frame_digest` 相同当成了「请求相同」,
    于是把两批跑里同一次判定的差别读成了**判定后端随机**,还写进了文档。

    **后端是确定的**:同一个请求原样发 12 次,12 次都是 `top=1.0000`。

    真因是 `choice` 的**选项不在帧里** —— `pickTool` 的帧只有
    `task` + `last_result`（`excluded` 里明写着候选不占帧的字段,§8.4）。
    于是**换掉候选集而帧指纹一动不动**,实测同一个帧指纹 `bb30c546d43b63cd`:

        [war, leader]           -> war_details      top=1.00
        [war, leader, battle]   -> battle_details   top=0.99   ← 换了答案
        [war, leader, done]     -> war_details      top=0.71   ← 差 0.29

    ★ 而 `top=0.71` 离 `pickTool` 的 0.6 门限只有 0.11 ——
      这正是「判定贴在门限边上」的来源:**帧给的证据薄,不是后端乱。**
    """
    from experiments.core.frame import (AgentCtx, Question, Request,
                                        compile_frame, frame_for)

    ctx = AgentCtx(task="Who won the battle?")
    frame = compile_frame(frame_for("pickTool"), ctx)

    def request(options: list[str]) -> Request:
        return Request(frame=frame, question=Question(
            node="pickTool", kind="choice", ask="Which tool next?",
            options=tuple(options), threshold=0.6,
            criteria={o: "" for o in options}))

    two, three = request(["a", "b"]), request(["a", "b", "c"])

    # 前提:帧**一模一样** —— 这就是当初骗过我的那个同一性
    assert two.frame.digest() == three.frame.digest(), "前提不成立,这个测试就没意义了"
    # ★ 而请求**不一样**,指纹必须分得开
    assert two.digest() != three.digest(), (
        "换了候选集而请求指纹不变 —— 那么「指纹相同」又会骗下一个人一次")


def test_candidates_drop_what_was_already_done() -> None:
    """★★ §8.4:**固定的候选会让模型去选一个已经不适用的动作。**

    实测:写完文件后 `write_file` 还在候选里,模型**会再选它**。

    ★ 这里是**删掉**,不是在帧里提示一句 —— 提示可以被无视,而候选列表
    是模型唯一能选的东西。第 10 轮 R2 的病正是「候选由调用方给,没人检查删没删」。
    """
    session = make_session()
    seen: list[list[str]] = []

    class Spy:
        name = "spy"

        def decide(self, session_, view):
            from experiments.core.controller import Decision
            from experiments.core.frame import ctx_from_steps
            ctx = ctx_from_steps(view.task_prompt, list(view.history))
            seen.append(candidates(session_, ctx))
            if view.history:
                return Decision(kind="answer", answer="Paris")
            return Decision(kind="tool", tool="lookup_capital",
                            arguments={"country": "France"})

    run_loop(session, LoopConfig(name="spy", instruction="x", controller=Spy()))
    from experiments.jloop.typed import DONE

    assert seen[0] == ["lookup_capital"]
    assert "lookup_capital" not in seen[1], "做过的动作必须从候选里消失"
    # ★★★ **但候选不能变空 —— 必须留一个出口。**
    #
    #   实测（2026-09-22,`bfcl-v3-multiple × react-typed`）:把做过的删掉之后
    #   候选**只剩错的工具**,而模型没有「不做了」可挑 → 调了第二个工具 →
    #   `sorted(called) != sorted(gold)` → 判 `wrong_tool`。
    #
    #   `DECISION.md` 的 `pick_tool` 原文里就有 `done` 这一项 ——
    #   我实现 §8.4 时只做了「删」,漏了「删完要给出口」这另一半。
    assert seen[1] == [DONE], f"删完必须留出口,而不是留空:{seen[1]}"


def _field_line(frame: str, label: str) -> str:
    """从渲染好的帧里取一行。**按字段名取,不做子串匹配** ——
    工具名也会出现在 `already_done` 和 `task` 里,子串断言会假绿。"""
    for line in frame.splitlines():
        if line.startswith(f"{label}:"):
            return line
    raise AssertionError(f"帧里没有 {label!r} 这一行:\n{frame}")


def test_needs_tool_asks_about_the_task_not_about_the_tool_list() -> None:
    """★★★ **`needsTool` 问的是「任务还需要什么」,不是「还剩哪些工具」。**

    这条测试**替换掉了上一版**,而上一版断言的正好是反的 ——
    我当初以为「问『还有没有动作』的帧里必须装着动作」,于是给它加了
    `actions_left`（= `pickTool` 的候选列表）。**那是错的。**

    实测（2026-09-23,`multiple_68`）:这道题有三个**近义**的找书工具
    (`search_books` / `books_search` / `books_search`）。调掉第一个之后,
    `actions_left` 说「还剩 2 个」,于是::

        step1  needsTool = 0.74   <- 帧说「还剩 2 个」-> 要继续
        step1  pickTool  = __done__(0.46)  <- 看着同一个任务 -> 够了

    **两个节点给出相反答案,因为我把一个只属于 `pickTool` 的问题的答案
    塞进了 `needsTool` 的帧。** 工具存在 != 任务需要。

    ★ `actions_left` 在 `pickTool` 那边是**对的**（A/B 实测:贴门限 12% -> 2%）——
      它回答「下一个挑哪个」时,把选项列全就是全部的工作。
      同一个字段,两个节点,**方向相反**。
    """
    from experiments.core.frame import (AgentCtx, StepRecord, compile_frame,
                                        frame_for)

    ctx = AgentCtx(task="Find me a book.")
    ctx.history = (StepRecord(step=0, tool="library.search_books",
                              input="fiction",
                              result="(the call has been recorded)"),)
    ctx.last_result = "(the call has been recorded)"
    ctx.remaining = ("google.books_search", "openlibrary.books_search")

    needs = compile_frame(frame_for("needsTool"), ctx).render()
    assert "actions_left" not in needs, (
        "`needsTool` 的帧里不该有「还剩哪些工具」—— 它问的是任务,不是工具表:\n" + needs)
    assert "books_search" not in needs, "候选列表不许漏进这个帧"

    # ★ 而「做过什么」必须**是人话** —— 上一版渲染成了 dataclass 的 repr
    assert "StepRecord(" not in needs, (
        "`already_done` 渲染成了 Python 对象 dump:\n" + needs)
    assert "library.search_books(fiction) -> (the call has been recorded)" in needs

    # ★ 同一个字段在 `pickTool` 那边留着 —— 那里问的才是「挑哪个」
    pick = compile_frame(frame_for("pickTool"), ctx).render()
    assert "actions_left" in pick, "`pickTool` 需要候选表,那是它的问题的一部分"


def test_candidates_do_not_offer_the_exit_before_anything_is_done() -> None:
    """★ 反面:**一次都没做过时不给出口**。

    「不做了」应当是 `needsTool` 回答的问题,而它的帧正是为那个问题准备的。
    一上来就给 `done`,等于让判定模型有机会**跳过整个工具循环** ——
    而那正是 `needsTool` 存在的意义。
    """
    from experiments.core.frame import ctx_from_steps
    from experiments.jloop.typed import DONE

    session = make_session()
    ctx = ctx_from_steps("t", [])
    assert DONE not in candidates(session, ctx), "还没做过任何事,不该有出口"


def test_the_redo_violation_would_be_caught_if_a_caller_passed_a_stale_list() -> None:
    """★ 上一条是**构造上不可能**发生;这一条证明**万一发生会被抓住**。

    两道防线都要在:「构造上不会」防的是我们自己写错,
    「会被抓住」防的是以后有人从别的路径塞候选进来。
    """
    from experiments.core.frame import AgentCtx, Question, Request, compile_frame, frame_for
    from experiments.core.types import Action, Step

    steps = [Step(index=0, action=Action(kind="tool", name="lookup_capital",
                                         arguments={"country": "France"}),
                  observation="Paris")]
    ctx = AgentCtx(task="t", history=(), last_tool="", last_result="")
    from experiments.core.frame import ctx_from_steps
    stale = ctx_from_steps("t", steps)

    req = Request(
        frame=compile_frame(frame_for("pickTool"), ctx),
        question=Question(node="pickTool", kind="choice", ask="?",
                          options=("lookup_capital",)),
    )
    codes = {v.code for v in req.check(stale)}
    assert "candidate_already_done" in codes


# ═══════════════════════════════════════════════════════════
# ★★ 有人接收 —— 第 10 轮 R2/R5 那条失效链断在这里
# ═══════════════════════════════════════════════════════════


def test_a_fatal_violation_stops_the_request_from_being_sent() -> None:
    """★★★ **校验发现 → 无人接收 → 请求照发 → 判定静默掉点。**

    断在第三步和断在第四步的区别就是这里:帧缺了判定依据时
    `_ask()` 返回**空字典**,而 `client.requests` 里**一条都不会多**。

    发出去会怎样?判定模型答一个没有依据的答案,而日志上它和正常判定一样。
    """
    client = ScriptedClient()
    ctrl = judge_gate(client)

    session = make_session()
    # 构造一个「判定依据不在」的帧:空 ctx 让 needsTool 的 task 缺失
    from experiments.core.frame import AgentCtx

    from experiments.jloop.typed import NODE_THRESHOLDS, _noul_question

    blocked = ctrl._ask(session, 0, AgentCtx(), 0,
                        _noul_question("needsTool", "?",
                                       threshold=NODE_THRESHOLDS["needsTool"]))
    assert blocked == {}, "缺判定依据时必须返回空（= 发不出去）"
    assert client.requests == [], "★ 请求不许发出去"
    assert ctrl.trace[-1]["violation"] == "field_missing" and ctrl.trace[-1]["fatal"]


def test_a_blocked_step_becomes_unparsed_not_a_made_up_action() -> None:
    """★ 发不出去时返回 `unparsed`,**不硬凑一个动作**。

    `unparsed` 的措辞是「**没答出来**」不是「答错了」（`core/controller.py`）。
    循环会重试,重试用完就 `escalate` —— 而 `escalate` 是一种**能被看见**的结果。

    ⚠️ 而且原因必须写明是 `typed:` 开头 —— 不写的话,日志上它和
    「模型格式错了」长得一样,而那是完全不同的事。
    """
    ctrl = judge_gate(ScriptedClient(omit=("needsTool",)))
    session = make_session()
    outcome = ReAct(controller=ctrl).solve(session)

    assert outcome.final_answer is None and outcome.escalated
    assert "typed:" in (outcome.error or ""), f"弃答原因没说清是我们这一侧:{outcome.error!r}"


def test_an_unusable_answer_from_the_backend_is_reported_not_defaulted() -> None:
    """★★ §8.10:后端**少给**或给了**畸形**答案 → 报出来,**不许退回默认值**。

    返回 `0.5` 看着更「健壮」,但那会让「后端挂了」和「判定完成了」
    在调用方看来一样 —— 而这两件事要采取的行动完全不同。
    """
    client = ScriptedClient(omit=("needsTool",))
    ctrl = judge_gate(client)
    session = make_session()

    assert ctrl.decide(session, _view(session)) is not None  # 先跑一次,占位
    last = ctrl.trace[-1]
    assert last["violation"] == "answer_unusable" and last["fatal"]


def _view(session: Session, *, history: tuple = ()) -> DecisionView:
    return DecisionView(prompt="", tools=tuple(session.tools),
                        task_prompt=session.task.prompt, task_id=session.task.task_id,
                        step=len(history), history=history)


# ═══════════════════════════════════════════════════════════
# 判的 vs 生成的 —— 第一根轴要量的东西
# ═══════════════════════════════════════════════════════════


def test_a_free_text_argument_is_generated_and_marked_as_such() -> None:
    """★★ **哪一步是判的、哪一步是生成的,必须记清楚。**

    §8.2 那条硬约束:判定模型只能从枚举里挑（77 个候选时掉到 0.425）。
    所以一个参数**自由文本**的工具**不能被 `pickInput` 选中** ——
    把它做成 `choice` 是在骗自己,它只能靠猜。

    那种情况只能生成。★ 而含糊过去这个臂就没有意义了:
    论文第一根轴量的就是「多少决定真的被解耦了」。
    """
    from experiments.core.types import Tool
    from experiments.jloop.typed import _wire  # noqa: F401  (确认它在)

    session = make_session()
    # ★★★ **`base_risk=0` 现在必须显式声明。**
    #   闸门改成规则优先之后，档位不再由判官给：
    #   没声明 + 参数匹配不上任何模式 ⇒ `UNKNOWN_TOOL_BAND` = 2 = 不可逆
    #   ⇒ `ask_human`。以前不声明只是"让判官判"，现在不声明是"每一步问人"。
    #   ★ 这条测试要测的是**生成 vs 判定**，不是授权闸门 ——
    #     所以这个声明是**为了把它从授权闸门那里摘出来**，
    #     而它本身也是诚实的：`search(query)` 只读。
    session.tools = [Tool(name="search", description="自由文本", base_risk=0,
                          parameters={"type": "object",
                                      "properties": {"query": {"type": "string"}}})]
    session.executor = ToolExecutor(session.tools, {"search": lambda query: "ok"})

    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1})
    ctrl = judge_gate(client)
    decision = ctrl.decide(session, _view(session))
    session.finish_events()          # ★ 批次要封口才进事件流（见 runner 里那两行的顺序）

    assert decision.kind == "tool" and decision.tool == "search"
    assert decision.arguments.get("query"), "自由文本参数得生成出来"
    assert not asked_pick_input(client), "不可枚举的参数不该被拿去当 choice 判"
    # ★ 它记进账了,而且节点名说明了它不是判定
    nodes = [r.node for r in session.decision_records()]
    assert any(n.startswith("pickInput:") for n in nodes), nodes


def test_an_enumerable_argument_is_scored_not_generated() -> None:
    """反面:`country` 有 enum,所以它**应该**被判 —— 而且不该走生成。"""
    session = make_session()
    # ⚠️ `needs_auth` 必须显式给低 —— 这道**授权闸门**是七个节点接齐之后
    #    新出现的,而它的默认脚本值 0.9 会把这一调判成 `ask_human`
    #    （§8.5:授权闸门不接受概率绕过）。这条测试问的是参数怎么来的,
    #    不该被另一道闸门拦下 —— 那两条测试要分开,否则红的时候分不清是谁。
    client = ScriptedClient(noul={"needs_auth": 0.1}, pick={"pickInput": "Peru"})
    ctrl = judge_gate(client)
    decision = ctrl.decide(session, _view(session))

    session.finish_events()
    assert decision.arguments == {"country": "Peru"}
    assert asked_pick_input(client), "有候选来源就该判"
    assert not any("(generated)" in r.answer for r in session.decision_records())


def test_a_single_candidate_is_not_worth_a_decision_request() -> None:
    """★ 只有一个候选还去问「要哪一个」是白花一次判定。

    `needsTool` 刚判过「要不要用工具」,所以工具数=1 时这个问题**没有信息量**。
    §8.1 第三行:能由精确规则定的,不交给判定模型。
    """
    session = make_session()          # toy 只有一个工具
    client = ScriptedClient(noul={"needs_auth": 0.1})
    decision = judge_gate(client).decide(session, _view(session))

    assert decision.tool == "lookup_capital"
    assert client.asked("pickTool") == 0, "唯一候选不该发判定请求"


def test_a_task_with_no_tools_never_asks_whether_it_needs_one() -> None:
    """★ 没有工具的任务（GSM8K 那种）**一次判定都不该发**。

    两个理由,都是结构性的:

    ① 「要不要用工具」的答案恒为否,问它只是白花一次判定;
    ② `canDeliver` 判的是「回答有没有超出**工具输出**的支持」——
       没有工具就没有工具输出,那这道闸门**没有可核对的材料**,
       问它只会得到一个凭空的答案（§8.10 的形状)。

    ★ 这一条在接 `canDeliver` 之前是**绿的而理由是错的** ——
      那时它只覆盖了①,第 0 步问了一次 `deliverable`/`unsupported`
      这件事没有任何东西看得见。
    """
    session = make_session()
    session.tools = []
    session.executor = ToolExecutor([], {})
    client = ScriptedClient()
    decision = judge_gate(client).decide(session, _view(session))

    assert decision.kind == "answer"
    assert client.requests == [], "没有工具时一次判定都不该发"


# ═══════════════════════════════════════════════════════════
# 记账:按批,不按条
# ═══════════════════════════════════════════════════════════


def test_decisions_in_one_step_share_a_batch() -> None:
    """★★ **按批计时,不按记录。**

    一次请求判多路时,每一路都记同一份 latency 再求和会**多算几倍** ——
    实测 `decisionMs` 一度比整轮墙钟还大（3.31s vs 3.29s）。
    """
    session = make_session()
    # 两个工具 ⇒ pickTool 真的要判一次,加上 needsTool,共两次判定、同一批
    from experiments.core.types import Tool
    session.tools = list(session.tools) + [
        Tool(name="other", description="另一个", parameters={"type": "object", "properties": {}})]
    session.executor = ToolExecutor(session.tools, {"lookup_capital": lambda country: "Paris",
                                                    "other": lambda: "ok"})

    judge_gate(ScriptedClient(noul=0.9, pick={"pickTool": "lookup_capital"})).decide(
        session, _view(session))
    session.finish_events()

    records = session.decision_records()
    assert len(records) >= 2, f"这一步该有多次判定:{[r.node for r in records]}"
    # ★ 每一步的判定**分属不同的批**（批 = 一次请求）,而每一批都记着自己的题数与请求数
    for b in session.decision_batches():
        assert b.requests_in_batch == 1, (
            f"一个批只该对应一次请求,而它记了 {b.requests_in_batch} 次 —— "
            f"那么「合并省了几次往返」就再也量不出来")
        assert b.questions_in_batch == len(b.decisions)


def test_confidence_and_correctness_land_on_the_same_row() -> None:
    """★ RQ2 全靠这一对:**判定说它有多确定**,和**它到底对不对**,必须在同一行。

    分开记的话,「置信度 0.8 的那批判定对了多少」这个问题就没法回答 ——
    而它是「能不能拿置信度当门限」的唯一依据。
    """
    session = make_session()
    judge_gate(ScriptedClient(noul=0.9)).decide(session, _view(session))
    session.finish_events()

    records = session.decision_records()
    assert records
    for r in records:
        assert 0.0 <= r.confidence <= 1.0, f"{r.node} 的置信度不在 [0,1]:{r.confidence}"
        assert isinstance(r.correct, bool)


def test_a_confident_no_is_decisive_even_though_it_is_a_no() -> None:
    """★★★ **两个数是两件事,`top()` 和 `prob_true()` 不是同一个。**

    这是照 TS 的 `topGte` / `probGte` 逐字对齐时发现的 —— 我第一版写反了。

    | | 算什么 | TS |
    |---|---|---|
    | `top()` | **答得果不果断** —— `noul` 上是 `max(p, 1-p)` | `topGte` |
    | `prob_true()` | **「是」的概率** —— `noul` 上就是 `p` | `probGte` |

    所以 `noul=0.1` 是**一个果断的「否」**:`top()` 是 **0.9**,过得了果断度门限;
    而 `prob_true()` 是 **0.1**,过不了「是」的门限。
    同一个答案,两个门限,两个结论 —— 而它们**都对**。

    ⚠️ 第一版我把 `top()` 写成返回 `noul`,于是「果断的否」被读成「不确定」,
    而「要不要工具」那一支反而拿它当「很确定要工具」。**正好反了。**
    """
    from experiments.core.deciding import Answer

    no = Answer(kind="noul", noul=0.1, confidence=0.1)
    assert no.top() == pytest.approx(0.9), "果断的否也是果断"
    assert no.prob_true() == pytest.approx(0.1), "但它不是「是」"

    yes = Answer(kind="noul", noul=0.9, confidence=0.9)
    assert yes.top() == pytest.approx(0.9) and yes.prob_true() == pytest.approx(0.9)

    unsure = Answer(kind="noul", noul=0.5, confidence=0.5)
    assert unsure.top() == pytest.approx(0.5), "0.5 才是不果断"


def test_the_choice_top_is_the_selected_option_not_the_maximum() -> None:
    """★ TS 取的是**被选中的那一项**的概率,不是概率表的最大值。

    后端理论上可以给一个不是最大值的选项（概率表只是个分布,
    而 `choice` 是它自己声明的选中项）。两边取的不是同一个东西时,
    「同一个方法」这句话就有漏洞 —— 照抄 TS。"""
    from experiments.core.deciding import Answer

    a = Answer(kind="choice", choice="b",
               probabilities={"a": 0.9, "b": 0.4, "c": 0.1})
    assert a.top() == pytest.approx(0.4), "取选中项,不取最大值"


def test_pick_input_does_not_assume_files_and_gives_every_option_a_criterion() -> None:
    """★★★ 两个实测撞出来的错，各自钉一条。

    ① **问句不能预设动作的形状。** 原文是
       `"Which file should this tool call target?"` —— 而 ALFWorld 里
       **一个文件都没有**（工具是 `act`，候选是 `go to safe 1`）。
       Jev 于是去挑 `examine safe 1` / `look` / `inventory`，30 步全烧在只返回信息、
       不改变状态的动作上。措辞是从文件操作那套沿用来的，在这个域里说不通。

    ② **每个候选都要带说明。** 调用点原来没传 `criteria`，而
       `_choice_question` 的文档写着空的代价：候选只有名字 ⇒ 模型只能光看名字猜 ⇒
       实测 `bfcl-v3-multiple` 上 **82/100 `wrong_tool`，而置信度经常是 1.000**
       （判得很果断，只是错了）。**看起来像判定错，其实是喂少了。**
    """
    from experiments.jloop.typed import (
        PICK_INPUT_ASK,
        _PICK_INPUT_FALLBACK,
        _input_criterion,
    )

    assert "file" not in PICK_INPUT_ASK.lower(), (
        "pickInput 的问句又出现了「file」—— 那个域不是所有工具都在里面"
    )

    # 动词认得出 ⇒ 给该动词的语义
    assert "holding" in _input_criterion("take mug 1 from fridge 1")
    assert "report" in _input_criterion("examine safe 1").lower()
    assert "heat" in _input_criterion("heat apple 1 with microwave 1")
    # 认不出 ⇒ 给通用句，**不猜**
    assert _input_criterion("frobnicate the whatsit") == _PICK_INPUT_FALLBACK
    # 每个候选都有非空说明 —— 空说明正是 82/100 那次事故的形状
    for option in ("go to safe 1", "open safe 1", "inventory", "look"):
        assert _input_criterion(option).strip()


def test_below_threshold_pickInput_is_still_used_but_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    """★★★ **不果断的动作选择：照走，但账上记明。**

    ★ 实测（2026-10-02，ALFWorld）逼出来的。旧行为是**丢掉**这个答案 ⇒
      这一步不成立 ⇒ 循环**重发一个逐字节相同的请求**。
      而那个请求并不确定：同一 `request_digest` 出现多次的 20 组里，
      **19 组的置信度不同**（0.44 / 0.40 / 0.46）。
      ⇒ "重试"不是错误恢复，是**重新抽一次**；连撞 3 次就弃答，
      20 题里 13 题这样死掉。

    ★ 判据是**这个节点的失败能不能被循环观测到并纠正**：
      选**动作**的节点能（动作一执行就有新观测），
      而 `canDeliver`（产物是要交出去的答案）和 `gradeRisk`（不可逆动作）不能。
      所以这是一个**逐节点**的政策，不是一个全局开关。

    ★★ 而 `correct` **仍然是"够不够格"**，不是"我们用了它" ——
      否则账上再也分不出「果断地判对了」和「不果断但照走」，
      而置信度这一栏要检验的正是那件事。
    """
    from experiments.jloop.typed import BELOW_THRESHOLD_POLICY, NODE_THRESHOLDS

    assert BELOW_THRESHOLD_POLICY.get("pickInput") == "accept"
    assert "canDeliver" not in BELOW_THRESHOLD_POLICY, (
        "交付闸门**不能**放宽 —— 它的产物是要交出去的答案，"
        "放行一个不果断的答案就是放走一次可能错误的交付"
    )

    session = make_session()
    ctrl = single_choice(ScriptedClient(noul=0.9, pick={"pickInput": "France"},
                                          spread=0.2))
    ctrl.decide(session, _view(session))
    session.finish_events()

    rows = pick_input_rows(session)
    assert rows, [r.node for r in session.decision_records()]
    row = rows[-1]
    assert row.confidence < NODE_THRESHOLDS["pickInput"]
    # ① 照走：答案被采用了（否则这一步不成立，循环会重发同一个请求）
    assert row.answer == "France"
    # ② 但**不够格**这件事没有被抹掉
    assert row.correct is False, "没过门限就是没过门限 —— 不能因为我们用了它就记 True"
    # ③ 原因写在同一行的 note 里，而且要说清是"采用了"不是"丢掉了"
    assert "低于门限仍采用" in row.note, row.note


def test_a_choice_is_recorded_as_not_correct(monkeypatch: pytest.MonkeyPatch) -> None:
    """★★ **别拿 `correct=True` 当护身符。**

    全填 True 的话 `correct` 那一列恒为真,于是
    「置信度和正确性同现」这句话**在账面上永远成立** —— 而它本该被检验。
    """
    from experiments.jloop.typed import NODE_THRESHOLDS

    session = make_session()
    # ★ 只让 **pickInput** 不果断（选中项 0.2,其余 7 个分掉 0.8）——
    #   抬高全局门限会把前面的 needsTool 也一起拦掉,那是另一条测试的事。
    ctrl = single_choice(ScriptedClient(noul=0.9, pick={"pickInput": "France"},
                                          spread=0.2))
    ctrl.decide(session, _view(session))
    session.finish_events()

    rows = pick_input_rows(session)
    assert rows, [r.node for r in session.decision_records()]
    assert rows[-1].confidence == pytest.approx(0.2)
    assert rows[-1].confidence < NODE_THRESHOLDS["pickInput"]
    assert rows[-1].correct is False, "没过果断度门限就该记 False"


def test_an_undecided_choice_blocks_the_step_instead_of_guessing() -> None:
    """★★★ **被迫的选择 ≠ 挑得对。**

    选项是穷尽的,判定模型必须挑一个 —— 所以「挑了一个」本身不是证据。
    `top()` 判的正是这件事,不过门就**不许拿它往下走**。

    ★ 没有这道门的时候,`_arguments` 会照拿第一个候选,
    于是「不确定就别猜」在代码里**从来没有被走到过** —— 而 §8.6 要求
    Mock 必须让 policy 自己走到 `escalate`。
    """
    session = make_session(undeclared_risk=True)
    ctrl = judge_gate(ScriptedClient(noul=0.9, pick={"pickInput": "France"},
                                          spread=0.2))
    decision = ctrl.decide(session, _view(session))

    assert decision.kind == "unparsed", f"不该硬猜:{decision}"
    assert "below_threshold" in {t.get("violation") for t in ctrl.trace}
    assert "typed:" in decision.raw


def test_mock_actually_walks_to_escalate() -> None:
    """★★★ §8.6 的原话:**Mock 一律保守,让 policy 的置信度门限自己走到 `escalate`。**

    这条要求以前**没有被满足** —— Mock 把概率平均分给 8 个国家（每项 0.125）,
    而 `_arguments` 根本不看门限,照拿第一个。于是
    「不确定就别猜」这句话写在了文档里,在代码里走不到。

    现在它走到了:整条臂对着 Mock 跑完,必须**弃答**而不是猜一个。
    """
    from experiments.core.deciding import MockClient

    session = make_session()
    outcome = ReAct(controller=judge_gate(MockClient())).solve(session)

    assert outcome.final_answer is None
    assert outcome.escalated, "Mock 下必须弃答 —— 否则「不确定就别猜」没被走到"


def test_one_decision_is_recorded_exactly_once() -> None:
    """★★★ **一条判定只记一行 —— 而"一条判定"的单位变了。**

    ⚠️ 一候选一题（2026-10-04）之后，`pickInput` **合理地**产生 N 行:
    N 道候选题 = N 次判定 = N 行。旧断言写的是 `len(rows) == 1`，
    于是它把"新形状正常工作"读成了"记重了"。

    ★ 它要守的那条规矩没变:**同一道题不许出现两行**。
      第一次犯这个错是"不果断时又记一条"，第二次是自查告警沿用问题名，
      第三次是判官立场另开一行 —— 三次都是**同一件事记了两遍**。
    """
    session = make_session()
    ctrl = judge_gate(ScriptedClient(noul=0.9, pick={"pickInput": "France"}))
    ctrl.decide(session, _view(session))
    session.finish_events()

    rows = pick_input_rows(session)
    assert rows, [r.node for r in session.decision_records()]
    counted = [r.node for r in rows]
    assert len(counted) == len(set(counted)), (
        f"同一道题记了不止一行:{[n for n in counted if counted.count(n) > 1]}"
    )
    # 而"几行"应当等于"几道候选题" —— 也就是每个 node 恰好一行
    assert all(n.startswith("pickInput::") for n in counted) or counted == ["pickInput"], counted


def test_a_violation_reaches_the_event_stream_not_just_memory() -> None:
    """★★★ **写进内存里一个 list 不算「有人接收」。**

    第 10 轮那条失效链的中间三步是「校验发现 → **无人接收** → 请求照发」。
    把违规放进 controller 的一个属性上,跑完之后**没人读得到** ——
    下一个人重建现场时看到的只是「这里怎么少了一次判定」。

    所以违规要按「一次没成立的判定」记账,并落进事件流（§8.14 的帧指纹同理）。
    """
    from experiments.core.frame import AgentCtx
    from experiments.jloop.typed import NODE_THRESHOLDS, _noul_question

    session = make_session()
    ctrl = judge_gate(ScriptedClient())
    # 空 ctx ⇒ needsTool 缺「判定依据」⇒ fatal ⇒ 请求不发
    assert ctrl._ask(session, session.next_batch(), AgentCtx(), 0,
                     _noul_question("needsTool", "?",
                                    threshold=NODE_THRESHOLDS["needsTool"])) == {}
    session.finish_events()

    rows = session.decision_records()
    assert rows, "违规没进事件流 —— 那就还是「无人接收」"
    assert rows[0].node == "needsTool" and rows[0].correct is False
    assert "field_missing" in rows[0].answer
    assert "判定依据" in rows[0].note, f"原因要可读:{rows[0].note!r}"
    assert rows[0].frame_digest, "帧的指纹也要在（§8.14）"


def test_the_frame_digest_separates_nodes_that_see_different_frames() -> None:
    """★★ §8.14:`Frame.digest()` 每次都记。

    这条验证两件相反的事,少一件这个串就没有意义:

    ① 节点**读了**的字段变了,指纹必须变 —— 否则「两次运行帧不一样」
       永远发现不了,而「同一个方法」这句话就没有依据;
    ② 节点**没读**的字段变了,指纹**不该**变 —— 一个恒变的指纹
       （比如掺了时间戳）看起来也在「记录帧」,其实什么都说明不了。

    ★★ 2026-10-02 改过这一条：`pickInput` **原来不看 `history`**，
      而那次修改把 `history` 加进了它的帧（理由见 `NODE_FRAMES["pickInput"]`）——
      实测 ALFWorld 上它连续 5+ 次选同一个 `examine cabinet 1`，
      20 题里 13 题这样死掉。**一个不知道自己做过什么的判定，只能打转。**
      所以旧的「② pickInput 只看 task」不再成立，换成用 `stepOk` 表达同一个不变量
      （它读 `last_tool/last_input/last_result`，**不读** `task` / `draft`）。
    """
    from experiments.core.frame import AgentCtx, StepRecord, compile_frame, frame_for

    empty = AgentCtx(task="把 a 抄到 b")
    did = AgentCtx(task="把 a 抄到 b",
                   history=(StepRecord(step=0, tool="read_file", input="a", result="..."),),
                   last_tool="read_file", last_input="a", last_result="...")

    # ① 历史进了 `needsTool` 的帧 → 指纹必须变
    needs = frame_for("needsTool")
    assert compile_frame(needs, empty).digest() != compile_frame(needs, did).digest()

    # ①′ `pickInput` 现在**也**读历史（被 ALFWorld 的打转逼出来的）→ 指纹必须变
    pick = frame_for("pickInput")
    assert compile_frame(pick, empty).digest() != compile_frame(pick, did).digest()
    # 而 task 一变它也得变 —— 否则它连「看 task」这件事都没做到
    assert compile_frame(pick, empty).digest() != compile_frame(
        pick, AgentCtx(task="换个任务")).digest()

    # ② `stepOk` 不读 `task` / `draft` ⇒ 只改这两个字段，它的指纹**必须一动不动**
    step = frame_for("stepOk")
    base = AgentCtx(task="t", last_tool="read_file", last_input="a", last_result="ok")
    other = AgentCtx(task="完全不同的任务", last_tool="read_file", last_input="a",
                     last_result="ok", draft="一段草稿")
    assert compile_frame(step, base).digest() == compile_frame(step, other).digest()
    # 而它**读**的字段一变就得变 —— 否则 ② 会被一个常量指纹蒙混过去
    assert compile_frame(step, base).digest() != compile_frame(
        step, AgentCtx(task="t", last_tool="read_file", last_input="b", last_result="ok")).digest()


# ═══════════════════════════════════════════════════════════
# 注册 —— 「能跑」和「表里有数」之间差着这一步
# ═══════════════════════════════════════════════════════════


def test_the_typed_cells_are_reachable_by_name() -> None:
    """★ 一条臂写在文件里不等于**能被跑起来**。

    `scripts/run.py` 的名字解析是**显式**的（见 `core/registry.py` 的说明）——
    没登记的名字就是「没有这个 agent」,哪怕实现就在旁边。
    """
    from experiments.scripts.run import resolve_agent, typed_arms

    decider = ScriptedClient()
    # ★ `react-termination` 是 2026-09 加的**终点验证**那一臂（原计划 §3.3 的"关键比较"）：
    #   和 `react-typed` 共用同一个 `run_loop` / `build_prompt` / 同一批工具 /
    #   **同一个交付闸门**，只有"判定放几次"不同。它也要判定后端，所以一起登记。
    # ★ 目录里每加一格就要在这里加一行 —— 这条测试的作用就是**在有人加了臂却忘了
    #   登记时变红**（它已经拦下过一次）。各格的来历见 `jloop/` 各自的文件头。
    assert set(typed_arms(decider)) == {
        "react-typed",        # 全程七节点
        "act-typed",          # 同上，act 循环
        "react-termination",  # 只在终点判定（原计划的"关键比较")
        "react-selfcheck",    # 零资源自检（SelfCheckGPT 那个思路）
        # ★★ **退出口的单变量对照** —— 和 `react-typed` 只差
        #   `allow_choices_without_escape` 这一个开关。
        #   它存在的理由是一个实测教训:拿 2026-10-02T13-56-37Z 那批当基线，
        #   出口分布看起来大变（`declined` 13→4），**而那批早于
        #   `already_done` 进帧那次修复** —— 量到的是三件事的和，一件都归不到。
        #   单变量对照是唯一能把"退出口有没有用"问清楚的形式。
        "react-typed-noescape",
        # ★★ **题形的单变量对照** —— `pick_input_shape="single_choice"`
        #   （一道 N 选 1）对 `per_candidate`（N 道 yes/no）。
        #   它和 `react-typed-noescape` 不是同一个对照：那一格同时改了
        #   **题形和退出口**两件事，答不了"题形有没有用"。
        "react-typed-singlechoice",
        # ★★ **闸门的对照臂** —— `gates_rules_first=False`（判官产生裁决）。
        #   它换的是**裁决的来源**，和默认那一版的问法完全不同，
        #   所以两批数字不能进同一张表（`DECISION_SPEC_VERSION` 已到 typed-4）。
        "react-typed-judgegate",
    }
    for name in ("react-typed", "act-typed", "react-termination", "react-selfcheck",
                 "react-typed-noescape", "react-typed-singlechoice",
                 "react-typed-judgegate"):
        agent = resolve_agent(name, decider)()
        assert agent.config.controller is not None, f"{name} 没接上控制器"


def test_the_honest_gaps_are_gaps_not_silent_wrong_arms() -> None:
    """★★ **`plan-then-execute × typed` 故意不在表里。**

    它的计划藏在 `view.prompt` 的 preamble 里,而类型化那一路**不看 `prompt`**
    （它用 `task_prompt` 自己拼）—— 接上去的话计划会丢。

    列上去会跑出一个**看起来能跑、其实没在做同一件事**的臂 —— 那比缺一格糟得多:
    缺一格是空的,错的格子是**一个数**,而那个数会被当成「换了决策者」的对照。
    """
    from experiments.scripts.run import resolve_agent, typed_arms

    decider = ScriptedClient()
    assert "plan-then-execute-typed" not in typed_arms(decider)
    assert "rewoo-typed" not in typed_arms(decider), "ReWOO 的 Worker 没有决策可换"


def test_a_typed_arm_needs_a_decider_and_a_plain_arm_does_not() -> None:
    """★ 判定后端**只在真要用的时候才建** —— 一个跑 `direct` 的人
    不该被判定后端的配置拦住。两者问的是不同的问题（§8.9）。

    而且 `--decider http` 缺 key 时**要报错,不许静默退回 mock**:
    静默退回会让「判定后端是官方 Jev」和「判定后端是 mock」在日志上长得一样 ——
    而两者跑出来的数不能放在同一张表里。
    """
    import argparse

    from experiments.core.deciding import MockClient
    from experiments.scripts.run import build_decider

    def ns(**kw):
        return argparse.Namespace(**{"decider": "mock", "decider_url": "http://x/v1",
                                     "decider_key": None, "decider_model": "m", **kw})

    assert isinstance(build_decider(ns()), MockClient), "默认是 mock（离线可跑）"

    # 没有 key ⇒ 报错退出，不是静默降级
    # ★ 变量名和 TS 侧 `backends.ts` 一致 —— 两边读不同的名字就是一个坑
    old = os.environ.pop("TYPESAFE_API_KEY", None)
    try:
        with pytest.raises(SystemExit, match="TYPESAFE_API_KEY"):
            build_decider(ns(decider="http"))
    finally:
        if old is not None:
            os.environ["TYPESAFE_API_KEY"] = old

    # 有 key ⇒ 真的建出 HTTP 客户端，而且**挂着 mock 兜底**（§8.10 每级都报）
    decider = build_decider(ns(decider="http", decider_key="k"))
    assert decider.name == "http:m→mock", decider.name


# ═══════════════════════════════════════════════════════════
# ★★★ 线协议和措辞 —— 两处「照着隔壁抄」而不是「照着自己想」
# ═══════════════════════════════════════════════════════════


def test_the_wire_shape_matches_vocab_ts_exactly() -> None:
    """★★★ 第一版这三个字段名**全是我猜的**（`kind`/`ask`/`options`）,
    而正本是 `src/vocab.ts` 的 **`type`/`instructions`/`criteria`**。

    这和 `top()` 那次是同一个毛病:**猜一份已经写在隔壁的协议,而不去读它。**
    猜错的下场不是报错,是**打到一个真端点上才发现** —— 而那时已经跑了一批。

    ★ 而且 `choice` 的 `criteria` **键就是选项本身**
    （会原样回到 `answers[id].choice`）,不是另开一个 `options` 列表。
    """
    from experiments.core.frame import Question
    from experiments.jloop.typed import _wire

    n = _wire(Question(node="q", kind="noul", ask="A?", criteria={"true": "t", "false": "f"}))
    assert set(n) == {"type", "instructions", "criteria"}
    assert n == {"type": "noul", "instructions": "A?", "criteria": {"true": "t", "false": "f"}}

    c = _wire(Question(node="q", kind="choice", ask="B?", options=("x", "y")))
    assert c["type"] == "choice" and c["instructions"] == "B?"
    assert list(c["criteria"]) == ["x", "y"], "选项就是 criteria 的键"

    s = _wire(Question(node="q", kind="score", ask="C?"))
    assert s["type"] == "score" and "criteria" in s


def test_an_absent_noul_criteria_is_omitted_not_sent_empty() -> None:
    """★ `vocab.ts` 里 `criteria` 对 `noul` 是**可选**的:
    `criteria ? {type,instructions,criteria} : {type,instructions}`。

    送一个空 `{}` 和「不送」不是一回事 —— 后者才是那个类型声明说的形状。"""
    from experiments.core.frame import Question
    from experiments.jloop.typed import _wire

    assert "criteria" not in _wire(Question(node="q", kind="noul", ask="A?"))


def test_needs_tool_asks_about_actions_not_about_tool_calls() -> None:
    """★★★ **这一条钉的是三次事故里的那一次。**

    `DECISION.md` 的 `## needs_tool` 原文:

    > ★ 判据是「任务还有没有没做的动作」,不是「还有没有没拿到的信息」。
    > 实测:任务「把 alpha.ts 里的 totalOf 抄到新文件 summary.ts 里」,
    > 读完 alpha.ts 之后这个节点判了 `answer`(0.36) → loop 直接去生成回答,
    > **文件从没被写出来**。

    我第一版写的措辞是
    `"Does this task still require a tool call before it can be answered?"`
    —— 问的是**工具调用**,而事故的教训正是「要问**任务要求的动作**」。
    「写一个文件」在这个问法下又一次落在问题之外。

    ★ 而且 `vocab.ts` 说「**问题 ID 不会到达模型**」—— 措辞是模型能看到的全部。
    """
    from experiments.jloop.typed import NEEDS_TOOL_ASK, NEEDS_TOOL_CRITERIA

    assert "action" in NEEDS_TOOL_ASK.lower(), "问的是动作,不是工具调用"
    # ★ 判据必须把「写」明说 —— 那正是事故的修法
    assert "writing" in NEEDS_TOOL_CRITERIA["true"]
    assert set(NEEDS_TOOL_CRITERIA) == {"true", "false"}


def test_the_two_choice_nodes_do_not_share_a_threshold() -> None:
    """★★ `DECISION.md` 里 `pick_tool` 是 **0.6**、`pick_input` 是 **0.5**。

    我第一版只有一个全局 `top`。用一个常量卡两个节点,
    **必然改错其中一个,而两边都还是「看起来在卡门限」** ——
    和那个「死配置」的 bug 是同一个形状。

    ★ 顺带钉住:`needsTool` 的 0.5 是 **`probGte`** 语义（P(true)）,
    两个 `choice` 是 **`topGte`** 语义（果断程度）。同一批数字,两种含义。
    """
    from experiments.jloop.typed import NODE_THRESHOLDS

    # ★ 七个节点接齐之后,表里多了 `stepOk` / `isDone` 两条
    assert NODE_THRESHOLDS == {"needsTool": 0.5, "pickTool": 0.6, "pickInput": 0.5,
                              "stepOk": 0.6, "isDone": 0.6}
    assert NODE_THRESHOLDS["pickTool"] != NODE_THRESHOLDS["pickInput"]
    # ★★★ **`stepOk` 是 0.6 不是 0.5,这条有讲究**（`DECISION.md` 的 `step_ok`）:
    #   它是七个判定点里唯一一个「放行 = 当没事发生」的门 —— 放行的意思是
    #   「这一步成功了」,于是**失败被吞掉**。`noul` 的 0.5 是最不确定的取值,
    #   而门限是闭区间 `>=` —— 一个等于「毫无信息」的值不该能放行任何事。
    assert NODE_THRESHOLDS["stepOk"] == 0.6
    # ⚠️ `gradeRisk` / `canDeliver` **故意不在表里** —— 它们的策略是
    #   `DECISION.md` 里那几条顺序求值的规则 (`score:risk >= 2` 先于
    #   `prob:needs_auth`),不是一道题一个果断度门限。塞一个 0.5 进来
    #   会让「硬规则不接受概率绕过」（§8.5）看起来也能被绕过。
    assert "gradeRisk" not in NODE_THRESHOLDS and "canDeliver" not in NODE_THRESHOLDS


# ═══════════════════════════════════════════════════════════
# ★★★ 批次耗时量的必须是「判定请求」,不是「两次开批之间」
# ═══════════════════════════════════════════════════════════


def test_a_batch_times_its_own_requests_not_the_gap_between_batches() -> None:
    """★★★ 实测（`bfcl-v3-simple × react-typed`,2026-09-22）:`decision_ms` 记成了**整个任务时长**。

    因为 `next_batch()` 在 `decide()` 开头关上一批,而那一批的开批时间是
    **上一步 decide 开始时** —— 于是中间的**生成调用**和**工具执行**全落在区间里。
    后果:`decison_ms ≈ wall`,和 `tool_ms` **双重计算**,
    `framework_ms = wall − model − decision − tool` 被减成 **−1670ms / −11335ms**。

    ★ **负的框架时间是症状,不是病。** 病是那个数**量的不是它名字说的东西** ——
    和今天修的其他几个是同一个形状。

    所以批次耗时改成**该批内判定请求自己的墙钟之和**。
    """
    session = make_session()
    ctrl = judge_gate(ScriptedClient(noul=0.9, pick={"pickInput": "France"}))

    # 开批 → 判一次 → 中间**假装去生成/调工具**(纯 sleep,不属于判定)
    batch = session.next_batch()
    ctrl.decide(session, _view(session))
    time.sleep(0.05)                     # ← 这 50ms 绝不该进 decision
    session.finish_events()

    batches = session.decision_batches()
    assert batches, "一批都没有"
    for b in batches:
        if b.requests_in_batch:
            assert b.latency_ms < 50.0, (
                f"批次耗时 {b.latency_ms:.1f}ms 把开批之后那 50ms 也算进去了 —— "
                f"它量的应该是判定请求自己"
            )


def test_requests_and_questions_are_counted_separately() -> None:
    """★★ **两个数分开记,而它们的比值就是论文要量的东西。**

    - **请求数** = HTTP 往返次数。PLAN 表 2:「一步 4–6 次请求,
      这是全项目最大的已知浪费」—— 那个「4–6」就是这个计数器。
    - **题数** = 几道判定题。一次请求可以判多路（Jev 一次前向并行打分）。

    相等 = 一步一请求;请求数远小于题数 = 合并得对。
    **合成一个数就永远分不出这两种情况** —— 而这两种情况的成本差着几倍。
    """
    session = make_session()
    # 两个工具 ⇒ pickTool 真要判一次;加上 needsTool、pickInput,一步三次请求
    from experiments.core.types import Tool
    session.tools = list(session.tools) + [
        Tool(name="other", description="另一个", parameters={"type": "object", "properties": {}})]
    session.executor = ToolExecutor(session.tools, {"lookup_capital": lambda country: "Paris",
                                                    "other": lambda: "ok"})

    judge_gate(ScriptedClient(noul={"needs_auth": 0.1},
                                   pick={"pickTool": "lookup_capital"})).decide(
        session, _view(session))
    session.finish_events()

    batches = session.decision_batches()
    assert batches
    # ★★★ **两个节点确实合并进了一次请求**:`gradeRisk` 问两件事
    #   （`risk` + `needs_auth`,`DECISION.md` 里 kind 是 `mixed`）——
    #   它们共享同一份帧,所以一次往返就能都答了。
    #   而「彼此独立 + 证据形状相同」正是合并的判据,不是「能塞多少塞多少」。
    merged = [b for b in batches if b.questions_in_batch > b.requests_in_batch]
    assert merged, (
        "没有任何一批是合并过的 —— 那么「判定有没有被合并」这件事"
        f"在账上就看不出来了:{[(b.questions_in_batch, b.requests_in_batch) for b in batches]}"
    )
    # ★ 而两个数**必须分开记**:相等 = 一步一请求（PLAN 说那是全项目最大的浪费）,
    #   题数远大于请求数 = 合并得对。合成一个就永远分不出这两种情况。
    assert all(b.requests_in_batch >= 1 for b in batches)


def test_a_single_tool_dataset_still_terminates_after_doing_it() -> None:
    """★★★ 回归测试:`bfcl-v3-simple × react-typed` 曾经**从 97/100 掉到 0/100**。

    那个子集只有 **1 个工具**。加 `DONE` 出口之后,工具做完时
    `candidates()` 返回 `[DONE]` —— 而「唯一候选」那条捷径把它**当成工具名**
    去 `view.tools` 里找,`next(...)` 直接 `StopIteration` → 整题 `agent_error`。

    ★ **加出口时引入的回归,而它只打在「工具数 = 1」的子集上** ——
      另一个子集（2–4 个工具）走 `else` 分支,完全没受影响。
      所以「只在有工具的数据集上测」这条纪律要再加一条:
      **同一处改动的两个子集都要测。**

    这条测试用一个只有 1 个工具、且 `needsTool` 一直说「还要」的环境,
    确认它**不会炸**,而是走到生成。

    ★ 七个节点接齐之后,这条路上多了两个**事后**判定（`stepOk` / `isDone`）——
    而它们和 `DONE` 出口是可以互相遮挡的:如果 `isDone` 说「完了」,
    循环就从**另一条**出口收尾了,`options == [DONE]` 那一段根本走不到。
    所以脚本里 `isDone` 特意判「还没完」:这条测试要打的是 `DONE` 那条路,
    不是 `isDone` 那条。**两个出口都要各自被测到** —— 否则一条遮住另一条,
    而有东西坏掉时看起来像「被遮住的那条没事」。
    """
    from experiments.core.controller import Decision
    from experiments.core.frame import ctx_from_steps
    from experiments.jloop.typed import DONE, TypedController

    session = make_session()          # toy 只有一个工具
    # `needsTool` 恒为「还要」;`isDone` 判「还没完」—— 这样第二步才会走到
    # 「候选只剩 `DONE`」那条路（`isDone` 说完了就会直接去生成,那条路
    # 是**另一条**出口,它有自己的测试）。授权闸门放行。
    client = ScriptedClient(noul={"needsTool": 0.9, "isDone": 0.1,
                                  "needs_auth": 0.1})

    class Spy(TypedController):
        def _finish(self, session, view, ctx, *, why, batch=0):
            return Decision(kind="answer", answer="PARIS", syntax="generated")

    ctrl = Spy(client)
    # 第一步:调用唯一的工具
    d1 = ctrl.decide(session, _view(session))
    assert d1.kind == "tool" and d1.tool == "lookup_capital"

    # 第二步:工具已做过 → 候选只剩 DONE → **必须走到生成,不许炸**
    session.next_batch()
    from experiments.core.types import Action, Step

    step = Step(index=0, action=Action(kind="tool", name="lookup_capital",
                                       arguments={"country": "France"}),
                observation="Paris")
    d2 = ctrl.decide(session, _view(session, history=(step,)))
    assert d2.kind == "answer", f"做完之后必须能收尾,而不是炸:{d2}"
    assert {t.get("answer") for t in ctrl.trace} >= {DONE}


# ═══════════════════════════════════════════════════════════
# ★★★ 七个节点一起接（2026-09-23）—— 四个新节点各自的回归
#
# 前面那些测试钉的是「两条臂只差一个控制器」和「判的 vs 生成的」。
# 这一节钉的是**新接上的四个节点里,每一个都真的在链路上工作** ——
# 接上一个节点却没有任何东西看得见它,和没接是一样的（§8.16）。
# ═══════════════════════════════════════════════════════════


def _tool_step(tool: str = "lookup_capital", *, country: str = "France",
               observation: str = "Paris"):
    """造一个「刚刚调过工具」的历史 —— 事后判定的输入就是它。"""
    from experiments.core.types import Action, Step

    return Step(index=0, action=Action(kind="tool", name=tool,
                                       arguments={"country": country}),
                observation=observation)


def test_step_ok_and_is_done_run_at_the_start_of_the_next_decide() -> None:
    """★★★ **两个事后判定在下一次 `decide()` 的开头补跑。**

    `stepOk` / `isDone` 判的都是「**刚刚**那一步」,而 `decide()` 只在**事前**
    被调用 —— 工具还没跑,没有东西可判。所以它们只能在**下一次进来**时补跑,
    而 `view.history` 的最后一步就是那次调用。

    ★ 这一条测试的判据是**顺序**,不是「问过没有」:`stepOk` 必须排在
    `needsTool` **之前**。放后面的话,`needsTool` 会在一个**塌了的历史**上判
    「还要不要动作」—— 它判得"没错"（历史里确实有那些动作),
    错的是我们没告诉它上一步没成。
    """
    session = make_session()
    # `isDone` 必须判「还没完」—— 说完了整步就在 isDone 那一格收尾了,
    # 而这条测试要的是**顺序**,不是 `isDone` 的出口（那条另有测试）。
    client = ScriptedClient(noul={"needsTool": 0.9, "isDone": 0.1,
                                  "needs_auth": 0.1})
    ctrl = judge_gate(client)

    ctrl.decide(session, _view(session, history=(_tool_step(),)))

    asked = client.questions()
    assert "stepOk" in asked and "isDone" in asked, (
        f"事后判定没有补跑 —— 那么工具失败和任务完成这两件事都没人看:{asked}")
    assert asked.index("stepOk") < asked.index("needsTool"), (
        f"事后判定必须排在事前判定之前:{asked}")


def test_a_failed_step_stops_instead_of_being_treated_as_success() -> None:
    """★★★ **`stepOk` 是七个判定点里唯一一个「放行 = 当没事发生」的门。**

    它放行的意思是「这一步成功了,继续」—— 于是**失败被吞掉**。
    所以这条测试判两件事:动作是 `stop`（不是继续),**而且理由是 `stepOk`**。

    ⚠️ 只断言「返回了 `unparsed`」是不够的:`isDone` 或别的节点出问题
    也会走到 `unparsed`。**两种完全不同的原因在结果上长得一样** ——
    这正是 §8.10 那个形状,所以这里的断言按**原因**分开写。
    """
    session = make_session()
    # 第一步成功、第二步失败:脚本只让第二个 `stepOk` 判否 ——
    # ★ 按**问题 id** 写脚本,不是按调用位置。
    client = ScriptedClient(noul={"stepOk": 0.1})
    ctrl = judge_gate(client)

    decision = ctrl.decide(session, _view(session, history=(_tool_step(),)))

    assert decision.kind == "unparsed", f"这一步没成,不该继续:{decision}"
    assert "stepOk" in decision.raw and "stop" in decision.raw, decision.raw
    # ★ 而且它**不是**被 `needsTool` 那一侧拦下的（那种失败看起来一样）
    assert "needsTool" not in decision.raw, "原因是别的节点,不许记成 stepOk"


def test_is_done_finishes_the_loop_after_a_successful_step() -> None:
    """★★ `isDone` 判「完了」→ **收尾去生成**,不再调第二个工具。

    这是**语义早停**:简单任务在第一步之后就结束,而不是傻等到 `max_iter`。
    实测的反面（`DECISION.md` 的 `is_done` 一节):旧措辞里有半句
    「any further tool call would not add information」,于是两个文件都读完了
    它还不肯停 —— 因为「读任何一个还没读过的文件都会增加信息」。
    """
    session = make_session()
    client = ScriptedClient(noul={"stepOk": 0.9, "isDone": 0.9})
    ctrl = judge_gate(client)

    decision = ctrl.decide(session, _view(session, history=(_tool_step(),)))

    assert decision.kind == "answer", f"判了做完就该去生成:{decision}"
    assert decision.answer == "Paris"
    # ★ 收尾之后就**不该再问「还要不要动作」** —— 顺序反了的话会多花一次判定
    assert "needsTool" not in client.questions(), client.questions()


def test_can_deliver_carries_the_tool_evidence_not_just_the_draft() -> None:
    """★★★ **交付闸门必须看得到工具输出。**

    这是接节点时查出来的「静默缺席」:`canDeliver` 判的是「回答有没有超出
    **工具输出**的支持」,而它的帧里原来只有 `task` + `draft` ——
    **既没看 `last_result`、也没声明不看**。

    实测（ALFWorld `pick_heat_then_place_in_recep-Apple-None-Fridge-10`）:
    任务要「把**加热过的**苹果放进冰箱」,agent 只走了一步（冰箱还关着),
    就交了「I placed the microwaved apple in the fridge.」—— **编的**,
    而 `escalated=False`,没有任何东西拦它。原因就是这个:那句话在帧里
    **没有任何反证**。

    ★ 所以这条测试判的是**帧的正文**:证据要在里面,而且要在里面**看得见**
    那次调用返回了什么（不是只有工具名）。
    """
    from experiments.core.frame import AgentCtx, compile_frame, ctx_from_steps, frame_for

    steps = [_tool_step(observation="You arrive at fridge 1. The fridge 1 is closed.")]
    ctx = ctx_from_steps("把加热过的苹果放进冰箱", steps)
    frame = compile_frame(frame_for("canDeliver"), ctx)

    assert "evidence" in {f.name for f in frame_for("canDeliver").fields}, (
        "帧声明里没有证据这一栏 —— 那闸门就还是瞎的")
    rendered = frame.render()
    assert "The fridge 1 is closed." in rendered, (
        "工具返回的内容没进交付闸门的帧 —— 编的完成报告在帧里就没有反证:\n" + rendered)
    # ★ 而且它**不是**整段 history 塞进来:过的是证据,不是历史
    assert "history" in dict(frame_for("canDeliver").excluded), (
        "要有声明说明为什么给的是证据而不是整段历史")
    # 空 ctx 时它是「缺上下文」而不是「缺判定依据」—— 第 0 步没有证据是正常状态
    assert "evidence" in compile_frame(frame_for("canDeliver"),
                                       AgentCtx(task="t", draft="d")).missing


def test_an_unsupported_answer_is_sent_back_once_and_then_delivered() -> None:
    """★★★ **闸门打回之后，补救必须真的发生**（而且只一次）。

    `DECISION.md` 的 `can_deliver` 一节 + TS 侧的原话:「以前它只是被拼进
    `halt` 字符串,草稿原样返回。」

    ★ 上限 1 次也是判据:第二次还不合格就**如实交出去**并说明 ——
    不无限重试,那会变成一个收费循环。

    ★★ **2026-10-01：补救从 `revise`（重写）改成 `degrade`（撤回）。**
      这一格给的是 `unsupported=0.9`（"超出证据"），病因是 `overclaim`，
      所以正确动作是**少说**、退回证据支持得了的范围 ——
      不是"换个说法再说一遍"。实测后者会诱发编造：`fta × react-termination`
      那 8 条"草稿诚实、改完变成编造"，改完 `unsupported` 从 0.07 冲到 0.99。
    """
    session = make_session()
    seen: list[str] = []
    # ★ 生成端**不看参数**:这条测试要量的是「闸门打回之后有没有真的重写」,
    #   而不是「工具查的是哪个国家」。所以答案固定是那个首都 ——
    #   参数由闸门随便挑,证据里那一次调用返回的也正是这句话。
    session.model = CallableModel(
        lambda messages: (seen.append(messages[-1].content), "Paris")[1],
        model_id="fake")

    class Gate:
        """一个**什么都答「是」**的后端,只有 `unsupported` 第一次判 true。

        ★ 计数器只在 **`canDeliver` 那两次请求**上走（按问题内容认,
        不按第几次调用认)—— 把别的节点也算进去的话,
        「第几次修订」就取决于前面问过几次,而不是闸门说了什么。

        ★ 别的题一律给「是」:这条测试只让**一条**判据拦人。
        `choice`（`pickInput`)必须真的给出选项 ——
        给一个 `noul` 回去,`parse_answers` 会按「空选项」丢掉它,
        于是整条路死在参数那一步,**而原因看起来像「闸门」**。
        """

        def __init__(self) -> None:
            self.gates = 0

        def decide(self, request):
            qs = list(request.questions)
            is_gate = "unsupported" in qs or "deliverable" in qs
            if is_gate:
                self.gates += 1
            reject = is_gate and self.gates == 1
            raw = {}
            for qid, q in request.questions.items():
                if q["type"] == "choice":
                    opts = list(q["criteria"])
                    # 挑哪个国家**无所谓** —— 上面那个生成端不看参数,
                    # 工具也只是回一句「Paris」。这里只要诚实给出一个选项。
                    want = opts[0]
                    raw[qid] = {"type": "choice", "choice": want,
                                "probabilities": {o: (0.9 if o == want
                                                      else 0.1 / max(1, len(opts) - 1))
                                                  for o in opts}}
                    continue
                if q["type"] == "score":
                    # `gradeRisk` 的 `risk` —— **0 = 只读**(最低档),
                    # 于是授权闸门放行。给 `noul` 回去的话它会按
                    # `Answer(kind="score")` 收下、分数恒为 0 —— 那也能过,
                    # 但那是**碰巧**,不是这条测试要说的事。
                    raw[qid] = {"type": "score", "score": 0, "confidence": 0.9}
                    continue
                if qid == "needs_auth":
                    # ★ 授权闸门（§8.5）**不接受概率绕过** —— 这一格给 0.9 就会
                    # 判 `ask_human` 并把整步停下,而这条测试要说的是交付闸门
                    # 打回之后有没有**真的重写**。两条闸门要分开测。
                    raw[qid] = {"noul": 0.1}
                    continue
                raw[qid] = {"noul": 0.9 if (qid != "unsupported" or reject) else 0.1}
            answers, dropped, missing = parse_answers(raw, qs)
            return DecideResponse(answers=answers, provider="gate",
                                  dropped=dropped, missing=missing)

    ctrl = judge_gate(Gate())

    # ① 第一步:真的调一次工具（`canDeliver` 要拿它的返回逐句核对回答,
    #    所以这一步不能跳 —— 跳了的话证据是空的,而空证据下闸门判什么都"对"）
    first = ctrl.decide(session, _view(session))
    assert first.kind == "tool", f"第一步该调工具:{first}"

    # ② 第二步:带上前一步的历史 → `stepOk`/`isDone` 补跑 → 生成 → 过闸门
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    decision = ctrl.decide(session, _view(session, history=(step,)))

    assert decision.kind == "answer", f"闸门最终要放行:{decision}"
    assert len(seen) == 2, (
        f"打回之后必须**真的再来一次生成** —— 生成被调用了 {len(seen)} 次")
    assert any("Delivery check failed" in p for p in seen), (
        "第二次生成必须带着闸门给的理由 —— 否则是在同一个盲区里再写一遍")
    assert any("unsupported=" in p for p in seen if "Delivery check failed" in p), (
        "★ 而且要带上**具体意见**（哪个问题、概率多少），不只是换一个框架")
    assert any("Answer in English" in p for p in seen if "Delivery check failed" in p), (
        "★★ 提示词必须是英文 —— 判据的免责词表是英文的，"
        "把模型带到中文会让「无法确认」变成「断言式编造」（实测踩过）")
    assert ("canDeliver", "revise/overclaim") in {
        (t.get("node"), t.get("answer")) for t in ctrl.trace
    }, "★ 轨迹里要留下**病因**：它决定补救是撤回还是回去做"


def test_a_step_that_never_ran_has_no_step_ok() -> None:
    """★ 上一步不是工具调用时,`stepOk` **没有对象可判**,不许问。

    两种情况都要挡住:

    - 第 0 步（还没有历史）;
    - `__parse_error__` —— 那是 `run_loop` 为了让下一轮 prompt 带上纠正提示
      塞进轨迹的**伪步骤**,它**不产生 `ToolCallEvent`**（`core/types.py`
      的 `is_tool_call` 就是为这件事存在的）。拿它去问「这一步成没成」,
      是在对一个**从未发生的调用**判成败。
    """
    session = make_session()
    client = ScriptedClient(noul={"needsTool": 0.1})
    ctrl = judge_gate(client)

    # 第 0 步:没有历史
    ctrl.decide(session, _view(session))
    assert "stepOk" not in client.questions(), "第 0 步没有东西可判,不该发 stepOk"

    # 伪步骤:解析失败那一步
    from experiments.core.types import Action, Step

    err = Step(index=0, action=Action(kind="tool", name="__parse_error__", arguments={}),
               observation="could not parse")
    client.requests.clear()
    ctrl.decide(session, _view(session, history=(err,)))
    assert "stepOk" not in client.questions(), (
        "伪步骤不产生工具事件,拿它判成败是在判一个从未发生的调用")


def test_grade_risk_applies_the_hard_rule_before_the_probability_one() -> None:
    """★★★ **两条闸门独立,而顺序就是那条硬规则**（§8.5）。

    `DECISION.md` 的 `grade_risk` policy::

        score:risk >= 2      → ask_human     ← 硬规则,**不接受概率绕过**
        prob:needs_auth>=0.5 → ask_human
        score:risk >= 1      → auto_audit
        else                 → auto

    `resolvePolicy` 是**顺序求值、第一条命中就返回**。所以把 `score:risk` 提到
    `needs_auth` 前面不是风格问题 —— 反过来的话,一个「风险 3 但模型说不用授权」
    的调用会被放过去。这条测试打的就是那一格:**风险够高 + 概率说不用批**。
    """
    from experiments.jloop.typed import _risk_action

    # ★ 纯函数先钉一遍 —— 策略本身在这里,不在 `decide()` 的 if 里
    assert _risk_action(3, 0.0) == "ask_human", "硬规则不许被概率绕过"
    assert _risk_action(2, 0.0) == "ask_human"
    assert _risk_action(0, 0.95) == "ask_human", "第二条是模型判断"
    assert _risk_action(1, 0.0) == "auto_audit"
    assert _risk_action(0, 0.0) == "auto"

    # ★ 再走一次链路:`risk=3` 说不用批 → 仍然是 `ask`（授权闸门拦下）
    session = make_session(undeclared_risk=True)
    ctrl = judge_gate(ScriptedClient(noul={"needs_auth": 0.0}, score=3))
    decision = ctrl.decide(session, _view(session))

    assert decision.kind == "ask", f"风险 3 必须问人,不许放过去:{decision}"
    assert decision.raw.startswith("typed:"), (
        "弃答/问人的原因要写明是我们这一侧 —— 否则日志上和「模型格式错了」一样")


def test_auto_audit_leaves_a_trail_in_the_event_stream_not_just_in_memory() -> None:
    """★★★ **`auto_audit` 承诺了留痕,那留痕就必须真的发生。**

    `DECISION.md` 的原话:「以前这条分支和 `auto` 完全一样,只多打一行 trace。」
    ★ 而「只多打一行 trace」在证据上等于没留 —— `trace` 是**内存里的调试列表**,
    跑完就没了。这条痕必须进**事件流**（`events.jsonl`),那里是跑完之后
    还读得到的唯一地方。

    ★ 它**不进 `DecisionRecord`** 也是判据:留痕不是一次判定,记进去会污染
    `correct` 那一列 —— 而那一列正是 RQ2 要量的东西（§8.1:代码按精确规则
    写下来的一条记录,不是判定）。
    """
    session = make_session(undeclared_risk=True)
    ctrl = judge_gate(ScriptedClient(noul={"needs_auth": 0.0}, score=1))

    decision = ctrl.decide(session, _view(session))
    session.finish_events()

    assert decision.kind == "tool", "risk=1 是中等风险:**放行,但留痕**"
    audits = session.audit_records()
    assert len(audits) == 1, f"auto_audit 没有留下痕:{audits}"
    rec = audits[0]
    assert rec.tool == "lookup_capital"
    assert rec.risk == 1 and "risk" in rec.reason
    # ★ 而它不是判定 —— 别把留痕算进判定次数
    assert all(r.node != "audit" for r in session.decision_records())


def test_the_risk_frame_describes_this_call_not_the_previous_one() -> None:
    """★★ `gradeRisk` 的帧里 `target` 必须是**这一调**的参数。

    `NODE_FRAMES["gradeRisk"]` 写的是 `FrameField("last_input", 200, "target")`
    —— 也就是「`AgentCtx.last_input` 就是这一调的目标」。而 `ctx` 是从
    **已完成的历史**拼出来的:第 0 步时它是空的,第 N 步时它是**上一步**的输入。

    ⇒ 不显式填的话,闸门会对着一片空白（第 0 步,请求被 `field_missing` 拦下)
    或者**上一步的输入**判这一调的风险 —— 而它会照答,答案是凭空生成的（§8.10）。
    """
    session = make_session(undeclared_risk=True)
    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1})
    ctrl = judge_gate(client)

    # ★ 从**第 0 步**走（没有历史）—— 那一格才是「`ctx.last_input` 是空的」
    #   那个 bug 的形状。从第 1 步走的话,`target` 会拿到**上一步**的输入:
    #   帧里有东西,判定照答,而答案是凭空生成的（§8.10)—— 静默的那种错。
    decision = ctrl.decide(session, _view(session))
    assert decision.kind == "tool"

    risk_reqs = [r for r in client.requests if "risk" in r.questions]
    assert risk_reqs, "没有发出 gradeRisk 的请求"
    frame = risk_reqs[-1].state["frame"]
    # ★ 这一调要调 `lookup_capital`（唯一候选）,所以 target 就是它的参数名
    assert "target:" in frame, f"帧里没有 target 这一行:\n{frame}"
    assert "last_input" not in frame, "帧里漏了内部字段名 —— 那是给模型看的正文"


def test_a_declared_tool_risk_is_looked_up_not_judged() -> None:
    """★★★ **能查表的东西不要问模型。**

    `gradeRisk` 的第一条闸门是 `score:risk >= 2 → ask_human`，而 `DECISION.md`
    明写它是**硬规则、不接受概率绕过**。可它的输入一直是一个**概率**（模型给的
    `risk` 分）—— 于是"硬"只靠求值顺序撑着：模型把风险判低，那条规则就不触发。
    实测那条注释自己就承认过：「把风险阈值从 2 提到 3 试图绕开第一条时，
    第二条 `needs_auth=0.95` 兜住了」——**兜住它的还是模型**。

    而风险**本来就是工具的属性**。工具声明了 `base_risk` ⇒ 查表，不问。
    这同时把"风险 3 但模型说不用授权"这个洞**结构性**堵死：
    高风险的 `risk` 不再是一个可以被概率拉低的东西。

    ★ 另一半同样重要：**没声明就必须问**（`exec` / `act` 那种，
      危险与否取决于这一调的内容）。把默认值当 0 会让所有通用工具被静默判成"只读"。
    """
    from experiments.core.types import Tool

    # ① 裸 Tool 默认**没有**声明 —— `None` 不是 0
    assert Tool(name="x", description="d", parameters={}).base_risk is None

    # ② 声明了 ⇒ 不问 risk，而且账上留一行 "(declared:N)"
    session = make_session()                       # toy 的 lookup_capital 声明了 0
    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1})
    judge_gate(client).decide(session, _view(session))
    session.finish_events()
    assert not [r for r in client.requests if "risk" in r.questions], \
        "工具声明了 base_risk，却还是拿它去问了模型"
    rows = [r for r in session.decision_records() if r.node == "risk"]
    assert rows, "查表来的那一格也要留痕 —— 否则『风险是谁定的』答不上来"
    assert rows[-1].answer == "(declared:0)", rows[-1].answer
    assert "base_risk" in rows[-1].note

    # ③ 没声明 ⇒ 必须问模型
    session = make_session(undeclared_risk=True)
    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1}, spread=0.1)
    judge_gate(client).decide(session, _view(session))
    assert [r for r in client.requests if "risk" in r.questions], \
        "工具说不出自己的风险时，必须问模型 —— 默认成 0 等于静默判「只读」"


def test_an_affirmative_verdict_without_a_valid_pointer_is_downgraded() -> None:
    """★★★ **判了"是"，却指不出依据 ⇒ 那条肯定性裁决不成立。**

    这是 `docs/UNDECIDED-DIAGNOSIS.md` 那条原理的通用化：一个概率**没法被证明
    是错的**，而一个**指认**可以。所以要求不是"判得更谨慎"，是**换一种输出** ——
    裁决要带一个指向某份产物的指针，校验跑在**模型之外**。

    ★ 只约束**肯定**那一侧：否认一个说法不需要引文，"我确认它成立"才需要。

    ★ 不是"重试"：指不出依据说明**证据里就没有**，再问一次同一个请求不会
      变出证据来（`docs/RETRY-DOES-NOT-HELP.md`）。
    """
    from experiments.core.frame import AgentCtx, Pointer, Question

    def run(cited: str):
        session = make_session()
        client = ScriptedClient(noul=0.9, pick={"isDone::pointer": cited})
        ctrl = judge_gate(client)
        q = Question(node="isDone", kind="noul", ask="这一步成了吗？", threshold=0.5,
                     criteria={"true": "成了", "false": "没成"},
                     pointer=Pointer(ask="哪一步证明了它？", options=("step_0", "step_1", "none"),
                                     validate=lambda c: c == "step_0", none_option="none"))
        got = ctrl._ask(session, session.next_batch(), AgentCtx(task="t"), 0, q)
        session.finish_events()
        rows = [r for r in session.decision_records() if r.node == "isDone"]
        # 指针题也要问出去 —— 它和主问题在**同一次请求**里（判定的本性）
        asked_ids = set(client.requests[0].questions)
        assert any("::pointer" in n for n in asked_ids), asked_ids
        return got["isDone"].prob_true(), rows[-1]

    # ① 指到了、而且校验通过 ⇒ 肯定性裁决保留
    p, row = run("step_0")
    assert p == pytest.approx(0.9)
    assert not row.note, row.note

    # ② 指到"指不出来" ⇒ 降级成 false，并在账上写明
    p, row = run("none")
    assert p == 0.0, "指不出依据却仍然按 true 走 —— 那这条要求等于没有"
    assert "举证未通过" in row.note and "指不出来" in row.note, row.note

    # ③ 指到了、但校验不过（模型之外的代码说它不成立）⇒ 同样降级
    p, row = run("step_1")
    assert p == 0.0
    assert "举证未通过" in row.note


def test_no_pointer_means_no_extra_question() -> None:
    """★ 没有指针的题**一步都不多走** —— 否则新旧两批不可比。

    `gradeRisk` 那类（工具说不出风险）和没有可指产物的场合都不该被强加举证：
    **要求一个指不出来的指认，只会让闸门对每一条都报警**，而"一条永远为真的
    告警等于没有告警"（`candidate_already_done` 就是这么死的）。
    """
    session = make_session(undeclared_risk=True)
    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1}, spread=0.1)
    judge_gate(client).decide(session, _view(session))
    assert not [n for r in client.requests for n in r.questions if "::pointer" in n], \
        "没有指针的题不该多问"


def test_the_evidence_pointer_requires_the_drafts_numbers_to_be_grounded() -> None:
    """★ 交付闸门的举证：**草稿里的每个数都得在某一步的观测里出现**。

    ★ 为什么只做数字：数字是最锐利的可证伪内容（实测里"编一个数"是最常见的
      一类假声明），而且去千分位逗号这件事是踩过的坑（`1,284` 被切成 `1` 和 `284`）。

    ⚠️ **纯散文的断言管不了** —— "placed the apple in the fridge" 对着观测
      "the fridge is closed" 共享 token，词面检查抓不住。强度分档写进 `Pointer`。
    """
    from experiments.core.frame import AgentCtx, StepRecord

    ctrl = judge_gate(ScriptedClient())
    view = _view(make_session())

    # ① 草稿里没数字 ⇒ **不要求举证**（不假装能验）
    ctx = AgentCtx(task="t", history=(StepRecord(step=0, tool="act", input="x", result="ok"),),
                   draft="placed the apple in the fridge")
    assert ctrl._evidence_pointer(ctx, view) is None

    # ② 草稿里有数字、观测里也有 ⇒ 校验通过
    ctx = AgentCtx(task="t", history=(StepRecord(step=0, tool="act", input="x",
                                                 result="You pick up apple 3"),),
                   draft="apple 3 is in the fridge")
    ptr = ctrl._evidence_pointer(ctx, view)
    assert ptr is not None and ptr.validate("step_0") is True
    assert ptr.none_option in ptr.options

    # ③ 数字是编的 ⇒ 校验不过（**这就是它要抓的那一类**）
    ctx = AgentCtx(task="t", history=(StepRecord(step=0, tool="act", input="x",
                                                 result="You pick up apple 3"),),
                   draft="apple 7 is in the fridge")
    assert ctrl._evidence_pointer(ctx, view).validate("step_0") is False

    # ④ 一个不存在的步骤 ⇒ 不过
    ctx = AgentCtx(task="t", history=(StepRecord(step=0, tool="act", input="x", result="7"),),
                   draft="7 apples")
    assert ctrl._evidence_pointer(ctx, view).validate("step_99") is False


def test_can_deliver_grounds_the_drafts_numbers_deterministically() -> None:
    """★★★ **数字落地是确定性检查，不问模型。**

    ★ 这条的形状是实测改出来的（2026-10-07，ALFWorld × react-termination × 20 题）：

      第一版做成一问一验（"哪一步包含这些数" + 校验被指的那一项），
      结果**误杀了两条 `won=True` 的题** —— 证据里明明写着
      `You move the watch 1 to safe 1. [task complete]`，而 Jev 答了"指不出来"。
      **指针本身也是模型判断，它有自己的错误率**；校验器只查"被指的那项对不对",
      **发现不了模型漏指了一个存在的项**。

    ⇒ 而"这个数在不在证据里"是**可检索的**。可检索的检查就不该问模型 ——
      问了只是把一个确定的东西换成一个会错的意见。这和 `base_risk` 那条同一条道理：
      **能查的不要问。**

    ⇒ 判据：草稿里的每个数都要在**全部已记录证据**里找得到；找不到 ⇒ `deliverable` 不成立。
    """
    from experiments.core.frame import AgentCtx, StepRecord

    def run(draft: str, result: str):
        session = make_session()
        client = ScriptedClient(noul={"deliverable": 0.95, "unsupported": 0.05})
        ctrl = judge_gate(client)
        ctx = AgentCtx(task="t",
                       history=(StepRecord(step=0, tool="act", input="x", result=result),),
                       draft=draft)
        ctrl._can_deliver(session, _view(session), ctx)
        session.finish_events()
        rows = [r for r in session.decision_records() if r.node == "deliverable"]
        ground = [r for r in session.decision_records() if r.node == "deliverable::grounding"]
        # ★ 未落地时**直接返回、根本不问模型** ⇒ 没有请求、也没有 `deliverable` 那一行。
        #   `None` 就是"没问"，和"问了答 0"是两件事。
        return (rows[-1] if rows else None), ground, (
            set(client.requests[0].questions) if client.requests else set())

    # ① 数字在证据里 ⇒ 照常判，没有落地记录，也**不问指针**
    row, ground, asked = run("apple 3 is on the countertop", "You see apple 3 there")
    assert row.confidence == pytest.approx(0.95), row
    assert not ground, "数字落地查得到，不该留下未落地记录"
    assert not [n for n in asked if "::pointer" in n], asked

    # ② 数字是编的 ⇒ **确定性**判 false，并记下是哪几个数
    row, ground, asked = run("apple 7 is on the countertop", "You see apple 3 there")
    assert row is None, "数没落地就不该去问模型 —— 能查的不要问"
    assert not asked, asked
    assert ground and "7" in ground[-1].answer, [r.answer for r in ground]
    # ★★ 被拦的草稿原文也要落盘 —— 否则事后**没法判断这次拦截对不对**。
    #   实测（2026-10-08）就撞上了：4 条拦截，而我无法确认那些数是原始草稿的，
    #   还是被反馈文本带进去的（见下一条测试）。
    assert "apple 7" in ground[-1].note, ground[-1].note

    # ③ 没有数字 ⇒ 这一档不管（只管数字）
    row, ground, _ = run("I looked around and found nothing", "nothing")
    assert row.confidence == pytest.approx(0.95)
    assert not ground



def test_environment_signals_settle_step_ok_and_is_done_without_asking_the_model() -> None:
    """★★★ **环境已经写在纸上的答案，不要再去问模型。**

    `AlfWorld` 的 `act` 声明了两个信号（`Tool.observation_signals`）：

        failure      —— `Nothing happens.`（TextWorld 的拒绝语：这一步什么都没发生）
        goal_reached —— `[task complete]`（**loader 依据 `infos["won"]` 追加的**）

    后者尤其值得单说：**它就是判分器的真值**，只是提前出现在了观察里。
    拿它去问模型，等于让模型猜一个已经写在纸上的答案。

    ★ 这是在实测的教训上做的（`docs/GROUNDING-REAL-RUN.md`）：第一版把可检索的检查
      做成"问模型 + 校验它指的那一项"，**误杀了两条已经赢了的题** ——
      证据里明明写着 `[task complete]`，而模型答"指不出来"。
      ⇒ **能查的不要问。**
    """
    from experiments.core.types import Action, Step

    sig = {"failure": ("Nothing happens.",), "goal_reached": ("[task complete]",)}

    # ① 环境说这一步没成 ⇒ `stepOk` 直接 false，**不问模型**
    session = make_session(signals=sig)
    client = ScriptedClient(noul=0.99)          # 模型本来会说"成了"
    ctrl = judge_gate(client)
    steps = (Step(index=0, action=Action(kind="tool", name="lookup_capital",
                                         arguments={"country": "France"}),
                  observation="Nothing happens."),)
    out = ctrl.decide(session, _view(session, history=steps))
    session.finish_events()
    assert out.kind == "unparsed", out
    assert not client.requests, "环境已经说了没成，不该再去问模型"
    rows = [r for r in session.decision_records() if r.node == "stepOk::environment"]
    assert rows and "Nothing happens." in rows[-1].answer, [r.answer for r in rows]

    # ② 环境说目标达成 ⇒ `isDone` 直接 true，**不问模型**
    session = make_session(signals=sig)
    client = ScriptedClient(noul=0.99)
    ctrl = judge_gate(client)
    steps = (Step(index=0, action=Action(kind="tool", name="lookup_capital",
                                         arguments={"country": "France"}),
                  observation="You arrive.  [task complete]"),)
    ctrl.decide(session, _view(session, history=steps))
    session.finish_events()
    assert not [r for r in client.requests if "isDone" in r.questions], \
        "环境已经说了达成，不该再去问模型"
    rows = [r for r in session.decision_records() if r.node == "isDone::environment"]
    assert rows and "[task complete]" in rows[-1].answer, [r.answer for r in rows]

    # ③ 工具**没声明**信号 ⇒ 照旧问模型（默认空 dict = 查不了）
    session = make_session()
    client = ScriptedClient(noul={"needsTool": 0.9, "stepOk": 0.9, "isDone": 0.1})
    ctrl = judge_gate(client)
    steps = (Step(index=0, action=Action(kind="tool", name="lookup_capital",
                                         arguments={"country": "France"}),
                  observation="Nothing happens."),)
    ctrl.decide(session, _view(session, history=steps))
    assert [r for r in client.requests if "stepOk" in r.questions], \
        "没声明的工具查不到信号，必须问模型 —— 默认当成「没成」是凭空捏造"


def test_the_ungrounded_feedback_does_not_echo_the_numbers_back() -> None:
    """★★★ **反馈里重复那几个数，会把自己喂回草稿。**

    实测（2026-10-08，ALFWorld × `react-typed`）撞出来的**反馈回路**：

      第一版反馈写的是「答案里出现了工具输出里没有的数 ['3','4','5']」，
      它进了 degrade 提示 ⇒ 模型把这三个数**抄进了下一版草稿** ⇒
      下一判又判它们未落地 —— **自己喂自己，反复触发**。

    证据就是那两条最终答案：

        "The tool failed to provide the specific numbers ['3', '4', '5'] required
         for the answer. To obtain them, the tool would need to …"

    ⇒ 反馈只说**性质**、不重复**内容**：回流的数字会被当成新的断言。
    """
    from experiments.core.frame import AgentCtx, StepRecord

    session = make_session()
    ctrl = judge_gate(ScriptedClient(noul={"deliverable": 0.95, "unsupported": 0.05}))
    ctx = AgentCtx(task="t",
                   history=(StepRecord(step=0, tool="lookup_capital", input="x",
                                       result="You see apple 3"),),
                   draft="apple 7 and apple 9 are there")
    verdict, reason, feedback = ctrl._can_deliver(session, _view(session), ctx)
    assert (verdict, reason) == ("revise", "overclaim"), (verdict, reason)
    assert "7" not in feedback and "9" not in feedback, (
        f"反馈里把数字写回去了 —— 下一版草稿会抄它，然后被反复拦：{feedback!r}"
    )
    assert "数字" in feedback


def test_list_markers_are_not_asserted_numbers() -> None:
    """★★★ **序号是排版，值是内容。**

    实测（2026-10-08，ALFWorld × `react-typed`）：模型写了一份带编号的步骤清单 ——

        Here is a step-by-step breakdown of the actions …:
        1.  **Pick up the mug**: Reach out and …
        2.  …
        3.  …

    观测里只出现过 1 和 2 ⇒ 那个 **`3` 被当成"证据里没有的数"**，
    整份草稿被判 `overclaim` 打回去重写。**那是序号，不是关于世界的断言。**
    另一条更糟：草稿本身是"我做不到"的**诚实拒绝**，同样被拦去重写。

    ⇒ 抽数字之前先剥掉行首的列表序号。**混在一起会让闸门对每一份带清单的回答
      都报警**，而"一条永远为真的告警等于没有告警"
      （`candidate_already_done` 就是这么死的）。
    """
    from experiments.jloop.typed import _numbers_in

    # 行首序号：`1.` / `2)` / `3、` —— 剥掉
    assert _numbers_in("1. pick up\n2) move\n3、done") == set()
    # 但**断言的值**要留下
    assert _numbers_in("it weighs 3 kg") == {"3"}
    assert _numbers_in("1,284 units") == {"1284"}       # 千分位照旧
    assert _numbers_in("3.5 million") == {"3.5"}        # 小数点不是序号
    # 序号和值混在一行：只剥序号
    assert _numbers_in("1. put apple 7 in the fridge") == {"7"}


def test_a_choice_question_must_offer_an_escape() -> None:
    """★★★ **没有退出口的 choice 问题，判官被迫挑一个真选项，而且挑得很果断。**

    这条是抄 μ 的（`packages/kyrn-judge/src/policy.ts`）：

      > Option names that mean "nothing fits". A choice question without one is
      > **forced to pick a real option even for off-topic input, and does so at full
      > confidence**, so specs must include one unless the option set is truly closed.

    而它的 `defineDecision` **没有退出口就直接抛错**，注册不上。

    ★★ 我们违反这条的代价已经量到了 —— `pickInput` 是 **28 选 1 的强制选择**：

        · `top` 常年 0.44–0.55（概率质量摊在 28 个都合理的选项上）
        · 0.5 那道门限**恰好落在众数上** —— 那个门限是畸形问题的变通办法
        · 一轮里 `examine cabinet 1` 被挑了 56 次 —— 它没有"这不是进展"可答

    ⇒ 所以这条在**构造处**强制，而不是靠自觉。豁免要显式写 `closed=True` 并给理由。
    """
    from experiments.jloop.typed import DONE, _choice_question

    # ① 没有退出口 ⇒ 当场抛错
    with pytest.raises(ValueError, match="没有退出口"):
        _choice_question("pickTool", "?", ["a", "b"], threshold=0.6)

    # ② 退出口不在选项里 ⇒ 也抛错（说了有、实际没有，比不说更坏）
    with pytest.raises(ValueError, match="不在选项里"):
        _choice_question("pickTool", "?", ["a", "b"], threshold=0.6, escape="none")

    # ③ 给了就过
    q = _choice_question("pickTool", "?", ["a", DONE], threshold=0.6, escape=DONE)
    assert q.escape == DONE

    # ④ 真的封闭 ⇒ 显式豁免
    q = _choice_question("pickTool", "?", ["a"], threshold=0.6, closed=True)
    assert q.closed_choices and not q.escape


def test_no_candidate_clearing_the_bar_means_stop_not_failure() -> None:
    """★★★ **没有任何候选过线 ⇒ 转去尝试收尾,不是把这一步判成失败。**

    ★ 这是旧测试 `test_the_pick_input_escape_means_stop_not_failure` 在新题形下的等价命题。
      旧形状里"这些动作都不合适"是候选表里的**一个选项**，判官得**记得去选它**；
      新形状（一候选一题）把它变成 **"N 个概率没有一个过线"** ——
      从分布直接得到，判官不需要"记得"任何事。

    ★ 处置没变，而且理由没变:判成失败会让循环**重发同一个请求**,
      而那正是我们已经量过的抽奖（同 digest 19/20 组置信度不同）。
      正确的处置是**转去问闸门** —— 它拦得住,而且理由会进帧。
    """
    from experiments.jloop.typed import NODE_THRESHOLDS, NO_ACTION_FITS  # noqa: F401

    session = make_session()
    # 每个候选都答"不是"（远低于门限）⇒ 没有任何候选过线
    # `needsTool` 要高（否则直接收尾、压根走不到参数那一步），
    # 而**每一个候选都要低** —— 用通配键表达"没有任何候选过线"。
    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1,
                                  "pickInput::*": 0.05})
    ctrl = TypedController(client, gates_rules_first=True)
    out = ctrl.decide(session, _view(session))
    session.finish_events()

    assert asked_pick_input(client), "候选题得真的问出去过"
    # 它没被当成失败 —— 走的是收尾那条路（闸门会被问到），不是 `_blocked`
    asked = {n for r in client.requests for n in r.questions}
    assert "deliverable::object" in asked or "deliverable::confirm" in asked, (
        f"没有候选过线 ⇒ 应当转去问闸门:{asked}"
    )
    assert out.kind in ("answer", "ask"), out
    # 而这件事在轨迹里看得见
    trace = [t for t in ctrl.trace if t.get("node") == "pickInput"]
    assert any("没有" in str(t.get("detail", "")) for t in trace), trace


def test_every_decision_row_says_who_decided_it() -> None:
    """★★★ **「判定模型做了这个决定」这句话必须可核对。**

    加 `source` 这一列之前，下面四件事在 `trace.jsonl` 里**长得一模一样**：

        · 工具自己声明了风险 ⇒ 查表，模型压根没被问
        · 只有一个候选 ⇒ 不问（§8.1「能由规则定的不交给模型」）
        · 参数不可枚举 ⇒ **只能生成**，不是从候选里挑的
        · 模型答了但没过门限 ⇒ **兜底**在往下走

    ★ 于是「多少控制是被判出来的」只能靠读代码数 —— 而那正是论文第一根轴。
      **量不出来的东西不算量过。**

    ★★ 默认值是 `"judge"`，故意的：忘了写的地方会错成"判定做的"（占比虚高），
      看得见；错成"规则做的"会把功劳记给规则，而那是看不见的。
    """
    from experiments.core.spec import DECISION_SOURCES

    session = make_session()
    ctrl = judge_gate(ScriptedClient(noul=0.9, pick={"pickInput": "France"}))
    ctrl.decide(session, _view(session))
    session.finish_events()

    rows = session.decision_records()
    assert rows, "一行判定都没有"
    assert all(r.source in DECISION_SOURCES for r in rows), [r.source for r in rows]
    # ★ 一次真判定（模型从枚举里挑了 France 并且够果断）⇒ judge
    judge = pick_input_rows(rows)
    assert judge and judge[-1].source == "judge", judge[-1]
    assert judge[-1].fallback == "", "判出来了就不该有兜底的名字"


def test_a_lookup_is_recorded_as_a_rule_not_as_a_judgment() -> None:
    """★★ **查表 ≠ 判定。** 工具声明了 `base_risk` 的时候，`risk` 那一格的
    答案是代码从表里读的 —— 把它记成一次判定，判定次数就虚高了，
    而「判定次数」正是头条指标之一。

    ★ `toy` 的 `lookup_capital` 声明了 `base_risk=0`，所以它走的就是这条路；
      `undeclared_risk=True` 才让风险回到模型手上（那是另一条测试）。
    """
    session = make_session()
    ctrl = judge_gate(ScriptedClient(noul=0.9, pick={"pickInput": "France"}))
    ctrl.decide(session, _view(session))
    session.finish_events()

    rows = [r for r in session.decision_records() if r.node == "risk"]
    assert rows, [r.node for r in session.decision_records()]
    assert rows[-1].source == "rule", rows[-1]
    assert rows[-1].answer.startswith("(declared:"), rows[-1].answer
    assert "未问模型" in rows[-1].note, rows[-1].note


def test_free_text_arguments_are_recorded_as_generated() -> None:
    """★★ **不可枚举的参数只能生成 —— 记账上要写"生成"，不是"判定"。**

    §8.2：判定模型只能从枚举里挑。所以 `search[query]` 那种自由文本
    是**写出来**的。把它记成判定，论文第一根轴就自己在骗自己。
    """
    from experiments.core.types import Tool
    from experiments.benchmark.toy import ToyCapitals

    bench = ToyCapitals()
    # 造一个**参数不可枚举**的工具（`candidate_provider` 认不出它的参数名）
    tools = [replace(t, name="freeform_search", parameters={
        "type": "object", "properties": {"query": {"type": "string"}}})
        for t in bench.tools()]
    session = make_session()
    session.tools = tools
    ctrl = judge_gate(ScriptedClient(noul=0.9))
    ctrl.decide(session, _view(session))
    session.finish_events()

    rows = [r for r in session.decision_records() if r.node.startswith("pickInput:")]
    assert rows, [r.node for r in session.decision_records()]
    assert rows[-1].source == "generate", rows[-1]
    assert rows[-1].answer == "(generated)"


def test_below_the_bar_the_row_names_the_fallback_that_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    """★★★ **兜底可以发生，但必须留下名字**（抄 μ 的 `Decision.fallback`）。

    μ 的 `DecisionSpec` **必须**写一个 `fallback`，判定不出来就照它执行、
    并把 `source` 记成 `"fallback"`。它的理由不是优雅，是**不许静默**。

    ★ 我们这边同一件事分成两种，所以名字也必须分得开：

        · 答了但 `top` 没过门限 ⇒ `accept_below_bar` / `drop_below_bar`
        · 压根没答（后端丢了）   ⇒ `FALLBACK_POLICY` 里那一档
    """
    from experiments.jloop.typed import FALLBACK_POLICY, NODE_THRESHOLDS

    # ① 答了但不够果断，而且那个节点声明的是 accept ⇒ 名字要写"低于门限仍采用"
    session = make_session()
    ctrl = single_choice(ScriptedClient(noul=0.9, pick={"pickInput": "France"},
                                          spread=0.2))
    ctrl.decide(session, _view(session))
    session.finish_events()
    row = pick_input_rows(session)[-1]
    assert row.confidence < NODE_THRESHOLDS["pickInput"]
    assert row.source == "fallback" and row.fallback == "accept_below_bar", row

    # ② 压根没答（后端返回了、但这一题缺席）⇒ 名字来自声明表
    session = make_session()
    ctrl = single_choice(ScriptedClient(noul=0.9, omit=("needsTool",)))
    ctrl.decide(session, _view(session))
    session.finish_events()
    rows = [r for r in session.decision_records() if r.node == "needsTool"]
    assert rows, [r.node for r in session.decision_records()]
    assert rows[-1].source == "fallback", rows[-1]
    assert rows[-1].fallback == FALLBACK_POLICY["needsTool"] == "retry", rows[-1]
    assert rows[-1].fallback in rows[-1].note, (
        f"名字要能读出来:{rows[-1].note!r}"
    )


def test_the_gate_still_fails_closed_but_says_so() -> None:
    """★★★ **我们和 μ 唯一的真冲突：闸门弃答时 fail-open 还是 fail-closed。**

    μ 是**生产判官库**：兜底的第一目标是"别卡住用户的请求"，所以默认 fail-open。
    我们是**评测**控制正确性：闸门 fail-open 的意思是
    **放走一次没有任何东西为它背书的交付**，而"放走了多少次"从结果里看不出来
    —— 那会把评测变成不可证伪。

    ⇒ 决议：**闸门保留 fail-closed**，但**必须记名** ——
      于是「拦截里有多少次其实是兜底而不是判断」是一个可查的数，
      不需要把闸门改成 fail-open。表在 `FALLBACK_POLICY`，理由在 `docs/MU-CONFLICT.md`。
    """
    from experiments.jloop.typed import FALLBACK_POLICY

    for gate in ("canDeliver", "gradeRisk", "needs_auth"):
        assert FALLBACK_POLICY[gate] == "reject", (
            f"{gate} 不许 fail-open —— 见 docs/MU-CONFLICT.md"
        )
    # ★ 动作类不是"更宽松"，是**弃答之后重发同一个请求会抽奖**（19/20 组置信度不同）
    assert FALLBACK_POLICY["pickInput"] == "no_action_fits"
    assert FALLBACK_POLICY["needsTool"] == FALLBACK_POLICY["pickTool"] == "retry"
    # ★ 交付闸门**不许**有"低于门限仍采用"这一档
    from experiments.jloop.typed import BELOW_THRESHOLD_POLICY
    assert "canDeliver" not in BELOW_THRESHOLD_POLICY
    assert "gradeRisk" not in BELOW_THRESHOLD_POLICY


def test_pick_input_keeps_the_retry_lottery_out_of_the_account() -> None:
    """★★ **`pickInput` 弃答 ⇒ 转去问闸门，不重发那个请求。**

    重发一个**逐字节相同**的请求不是错误恢复，是重新抽一次
    （实测 20 组同 digest 里 19 组置信度不同），**13/20 题**是这样死的。

    ★ 而这个兜底**不是放行动作** —— 它转去问 `canDeliver`，闸门拦得住
      （把话说回来，理由进帧，`MAX_REDIRECTS=1`）。
    """
    from experiments.jloop.typed import FALLBACK_POLICY

    session = make_session()
    # 后端整批丢掉 pickInput 这一题
    client = ScriptedClient(noul=0.9, omit=("pickInput",))
    ctrl = judge_gate(client)
    out = ctrl.decide(session, _view(session))

    assert asked_pick_input(client), "这一题得真的问出去过"
    # 兜底是"转去收尾"⇒ 走 canDeliver，而不是 unparsed/blocked
    assert out.kind in ("answer", "ask"), out
    asked = {n for r in client.requests for n in r.questions}
    # ★ typed-4 起交付闸门问的是 `deliverable::confirm`（规则拒绝时确认）
    #   或 `deliverable::object`（规则放行时反驳）—— 旧名字 `deliverable` 不存在了。
    assert any(n.startswith("deliverable") for n in asked), asked
    assert FALLBACK_POLICY["pickInput"] == "no_action_fits"


# ═══════════════════════════════════════════════════════════
# ★★★ `shadow` 模式 —— 把"这条判定有没有用"变成可从日志回答的问题
# ═══════════════════════════════════════════════════════════


def _shadow_gate_reached(*, shadow: frozenset[str]):
    """跑到**交付闸门**那一步（生成答案 → `canDeliver`），并返回那次 `decide`。

    ★ 为什么要绕一步：`canDeliver` 判的是**刚生成的那份草稿**，而草稿只在
      "不用再动作了"的时候才生成。所以必须先真的调一次工具，再让
      `needsTool` 说"不用动作了"。**第 0 步直接跑是到不了闸门的** ——
      第一版就是这么写的，拿到的是 `kind="tool"`，测的根本不是闸门。
    """
    session = make_session()
    client = ScriptedClient(noul={"needsTool": 0.9, "unsupported": 0.1,
                                  "deliverable": 0.1, "needs_auth": 0.1},
                            pick={"pickInput": "France"})
    ctrl = judge_gate(client, shadow=shadow)
    first = ctrl.decide(session, _view(session))
    assert first.kind == "tool", f"第一步该真的调工具:{first}"
    client.noul["needsTool"] = 0.1          # 第二步：它说"不用动作了" ⇒ 去生成答案
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    return ctrl, session, client, ctrl.decide(session, _view(session, history=(step,)))


def test_shadow_records_the_verdict_but_does_not_let_it_steer() -> None:
    """★★★ **问了、记了，但返回的是"没有判官"的行为**（抄 μ 的 `shadow`）。

    μ 的三种模式（`decision.ts`）：

        `off`    不问，直接返回 `fallback`
        `shadow` **问了、也记了，但返回的仍然是 `fallback`**
        `active` 返回判定结果

    ★ 我们以前没有这一档：一个节点要么接着、要么没接。于是
      **「这条判定要是有用吗」从日志里答不出来** —— 每一次对比都是
      **两个不同的 agent 在比**，而不是同一条轨迹上的两种裁决。

    ★★ 判据是**两件事同时成立**：
      ① 闸门真的被问了（`deliverable`/`unsupported` 有判定行 + 置信度）；
      ② 交付路径**没有**被它改动（`gate=""`，草稿是原文，没有 degrade）。
      少了 ① 就退化成 `off`，少了 ② 就成了 `active`。
    """
    ctrl, session, client, out = _shadow_gate_reached(shadow=frozenset({"canDeliver"}))
    session.finish_events()

    # ① 闸门被问了 —— 而且裁决是"没做完"（deliverable 0.1）
    asked = {n for r in client.requests for n in r.questions}
    assert {"deliverable", "unsupported"} <= asked, asked
    rows = [r for r in session.decision_records() if r.node == "deliverable"]
    assert rows, "闸门的问题必须真的问出去过，否则测的是 off 不是 shadow"
    assert rows[-1].answer not in ("(answer_unusable)", "")

    # ② 但它没有改动交付 —— 草稿照交，原文，`gate` 是空
    assert out.kind == "answer", out
    assert out.answer == "Paris", f"shadow 不许改草稿:{out.answer!r}"
    assert out.gate == "", "shadow 的那一次**真的没有闸门在管** —— gate 必须是空"

    # ③ 裁决本身留在盘上，供离线比对
    shadow_rows = [r for r in session.decision_records() if r.node == "canDeliver::shadow"]
    assert shadow_rows, "裁决必须落到 trace.jsonl，不能只在内存里"
    row = shadow_rows[-1]
    assert row.answer.startswith("(shadow:revise/incomplete)"), row.answer
    assert row.source == "fallback" and row.fallback == "shadow", row
    assert "未落地" in row.note, row.note


def test_shadow_rows_cannot_be_mistaken_for_a_judgment() -> None:
    """★ **shadow 的行不许被读成一次生效的判定。**

    如果它记成 `source="judge"`，那么「判定占比」和"判准率"都会把它算进去 ——
    而它的行为根本不是它决定的。**账目上必须能把它挑出来**，
    否则 shadow 的批次会污染 active 的批次，而那正是它要防止的事。
    """
    _ctrl, session, _client, _out = _shadow_gate_reached(
        shadow=frozenset({"canDeliver"}))
    session.finish_events()

    shadowed = [r for r in session.decision_records() if r.fallback == "shadow"]
    assert shadowed, [r.node for r in session.decision_records()]
    assert all(r.source == "fallback" for r in shadowed), shadowed
    # ★ `deliverable`/`unsupported` 那两行也必须是 fallback —— 否则
    #   "判定占比"会把一次**没有落地**的判定算成有效的。
    nodes = {r.node for r in shadowed}
    assert {"deliverable", "unsupported", "canDeliver::shadow"} <= nodes, nodes


def test_shadow_is_off_unless_asked_for() -> None:
    """★★ **不许默认 shadow。**

    默认 shadow 的话,跑出来的分数是"没有判官"的分数,而报告上
    它和"接了判官"一模一样 —— 这正是这批代码一直在防的那类错:
    **一个数被换掉了,而账面上看不出来。**
    """
    from experiments.jloop.typed import SHADOW_DECISIONS

    assert SHADOW_DECISIONS == frozenset(), "默认必须是空的"
    assert judge_gate(ScriptedClient()).shadow == frozenset()
    assert not judge_gate(ScriptedClient()).gate_is_shadowed()


def test_shadowing_an_action_node_falls_back_instead() -> None:
    """★ 动作类判定点 shadow ⇒ **走 `FALLBACK_POLICY` 那一档**（"判官没答"的行为）。

    `canDeliver` 是特例（"没有闸门"= 照交）；动作类的没有判官行为就是它声明的那一档。
    ★ 这一档必然让任务更容易失败 —— 而那正是它的用途：**它给出的是反事实基线**，
      不是要拿来出分的。
    """
    from experiments.jloop.typed import PICK_INPUT_ESCAPE

    session = make_session()
    client = ScriptedClient(noul={"needsTool": 0.9}, pick={"pickInput": "France"})
    ctrl = judge_gate(client, shadow=frozenset({"pickInput"}))
    out = ctrl.decide(session, _view(session))
    session.finish_events()

    picks = pick_input_rows(session)
    assert picks, [r.node for r in session.decision_records()]
    # ★ 一候选一题下记账的 `answer` 是**答案的取值**（`noul` 是个概率），不是选项名。
    #   "判定模型确实答了"这件事由"这一行不是 `(answer_unusable)`"来说。
    assert all(not str(p.answer).startswith("(") for p in picks), picks
    assert all(p.fallback == "shadow" for p in picks), picks
    # 但它没落地：走的是 `no_action_fits` ⇒ 转去收尾，而不是真的调那个动作
    assert out.kind in ("answer", "ask"), out
    assert not (out.kind == "tool" and out.arguments.get("country") == "France")
    assert PICK_INPUT_ESCAPE  # 引一下，说明走的是那条路


# ═══════════════════════════════════════════════════════════
# ★★★ "同一个方法"这句话必须可核对
# ═══════════════════════════════════════════════════════════


def test_the_decision_spec_fingerprint_is_pinned() -> None:
    """★★★ **改了问法/门限/兜底而没 bump 版本 ⇒ 这条测试红。**

    抄 μ 的 `DecisionSpec.version`：它的原话是
    *"Bump whenever question wording or policy changes, so ledger records stay comparable."*

    ★★ 我们的缺口比它小、但更难看：`meta` 里有 `commit` + `dirty` + `prompt_hash`，
      而 **`prompt_hash` 只覆盖 `benchmark:dataset_version:arm`** ——
      问法的字改了、门限挪了、兜底换了，这三样**一个都不动**。
      于是"那两批是同一个方法吗"在盘上答不出来（`docs/MU-CONFLICT.md` 第 6 行）。

    ★ μ 靠纪律（记得 bump）。我们把它做成机械的：**字面量改了而版本没改，
      指纹就对不上**；下一个人在 diff 里能看到这一行红，而不是半年后
      在两批数之间发现问法不一样。

    ★★ 修法：改 `DECISION_SPEC_VERSION`，并把下面这个值更新成新的。
      **两个都要动** —— 只改指纹不 bump 版本，版本号就失去意义了。
    """
    from experiments.jloop.typed import DECISION_SPEC_VERSION, decision_spec_digest

    assert DECISION_SPEC_VERSION == "typed-9", (
        "bump 版本时把这一行也改掉，并把下面的指纹更新成新的"
    )
    assert decision_spec_digest() == "039e0a4fc27b0ed0", (
        "判定规格的指纹变了 —— 问法 / 门限 / 兜底 / 帧预算里有东西被改动。\n"
        "  · 如果是**有意的**改动：bump `DECISION_SPEC_VERSION`，"
        "并把这条断言里的值换成新指纹。\n"
        "  · 否则：把它改回去。\n"
        "  ⚠️ 这不是形式主义 —— 指纹变了而版本没变，"
        "两批数就会被当成同一个方法放在同一张表里。"
    )


def test_no_question_constant_escapes_the_fingerprint() -> None:
    """★★★ **新增一个问法而忘了登记 ⇒ 这条测试红。**

    指纹表是**手写的**（`DECISION_SPEC_PARTS`），所以它有"漏了一个"的风险 ——
    而漏掉的那一个恰好是改动、指纹却不动，正是上面那条测试要防的事。

    ⇒ 所以这条测试反过来查：模块里**任何一个大写常量**（含 `_` 开头的）
      要么在指纹表里，要么在**显式忽略表**里并写明理由。
      没有第三条路 —— §8.15「要求写在一处、生效在另一处」就是从这个洞爬进来的。
    """
    from experiments.jloop import typed as m

    def is_constant(name: str, value: object) -> bool:
        bare = name.lstrip("_")
        if not bare or not bare.replace("_", "").isupper():
            return False
        if name.startswith("__"):
            return False
        # 类型 / 函数 / 模块不是"一个问法或一条策略"
        return not (isinstance(value, type) or callable(value)
                    or type(value).__name__ == "module")

    unregistered = sorted(
        n for n, v in vars(m).items()
        if is_constant(n, v)
        and n not in m.DECISION_SPEC_PARTS
        and n not in m.DECISION_SPEC_IGNORED
    )
    assert not unregistered, (
        f"这些常量既不在 `DECISION_SPEC_PARTS` 里也不在 `DECISION_SPEC_IGNORED` 里："
        f"{unregistered}\n"
        f"  改动问法/门限/兜底 ⇒ 加进 `DECISION_SPEC_PARTS`（指纹就会变）；\n"
        f"  与问法无关（跑法、正则、题 id）⇒ 加进 `DECISION_SPEC_IGNORED` 并写明理由。"
    )
    # 反方向也要查：登记了却已不存在的名字会让"我登记过"变成一句空话
    from experiments.core import frame as fm

    dangling = [n for n in m.DECISION_SPEC_PARTS
                if not hasattr(m, n) and not hasattr(fm, n)]
    assert not dangling, f"`DECISION_SPEC_PARTS` 里这些名字已经不存在了：{dangling}"


def test_a_single_pick_input_candidate_is_not_asked() -> None:
    """★★★ **只有一个候选就免问 —— 这条捷径差点被退出口悄悄关掉。**

    加退出口时写成 `options += [PICK_INPUT_ESCAPE]` 再判 `len(options) == 1`：
    长度至少是 2，于是那个分支**永远走不到**，而注释还挂在那儿，看起来那条
    捷径在用。账上只会表现为 `pickInput` 的判定次数偏高 —— 而"判定次数"
    是头条指标之一，所以这个错**会被记成正面的东西**。

    ★ 捷径必须排在退出口**之前**：只有一个候选时判官没有被强迫挑，
      而"要不要做这个动作"刚由 `needsTool` 判过（§8.1：能由精确规则定的
      不交给判定模型）。退出口的意义是给**被迫在多个选项里挑**的判官一条出路。
    """
    from experiments.core.types import Tool
    from experiments.jloop.typed import PICK_INPUT_ESCAPE

    session = make_session()
    # ★ `needs_auth` 要给低：授权闸门（§8.5）不接受概率绕过，默认 0.9
    #   会判 `ask_human` 并把整步停下 —— 那测的就成了授权闸门。
    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1})
    ctrl = judge_gate(client)
    # 把候选压到**恰好一个** —— provider 只会给出 `France`
    import experiments.jloop.typed as m
    real = m.candidate_provider

    def one(_tool):
        def provider(_ctx):
            return (c for c in ("France",) if True)
        return provider

    m.candidate_provider = one
    try:
        out = ctrl.decide(session, _view(session))
    finally:
        m.candidate_provider = real

    assert out.kind == "tool", out
    assert out.arguments.get("country") == "France", out.arguments
    asked = {n for r in client.requests for n in r.questions}
    assert "pickInput" not in asked, (
        f"只有一个候选却问了 pickInput —— 白花一次判定:{asked}"
    )
    assert PICK_INPUT_ESCAPE  # 退出口仍然存在，只是这条路上用不上


def test_the_escape_can_be_switched_off_for_a_single_variable_ab(monkeypatch: pytest.MonkeyPatch) -> None:
    """★★★ **退出口要能单独关掉，否则"它有没有用"永远答不了。**

    实测撞到的（2026-10-03）：拿 `2026-10-02T13-56-37Z` 那批 20 题当基线，
    出口分布从 `declined 13 / delivered 2` 变成 `declined 4 / delivered 12` ——
    看起来像退出口的功劳。**但那批早于 `already_done` 进帧那一次修复**
    （`docs/ALFWORLD-TYPED-ROUND2.md`），所以量到的是
    「帧 + 每候选判据 + 退出口」三件事的**和**，一件都归不到头上。

    ★ 开关的名字照抄 μ 的 `DecisionSpec.allowChoicesWithoutEscape` ——
      他们的默认是"必须有"，豁免要**显式写出来**，这正是我们要的那件事。
    ★ 关掉时**必须声明 `closed=True`**，不是默默不加：
      "这个候选集真的封闭"和"忘了加退出口"是**两个不同的假设**，
      而 `_choice_question` 的抛错就是为了不让人把它们混起来。
    """
    from experiments.jloop.typed import PICK_INPUT_ESCAPE

    # 默认：退出口在线协议里
    on = make_session()
    c_on = single_choice(ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1}))
    c_on.decide(on, _view(on))
    on_opts = [x for r in c_on.client.requests for qid, q in r.questions.items()
               if qid == "pickInput" for x in q["criteria"]]
    assert PICK_INPUT_ESCAPE in on_opts, on_opts

    # 关掉：退出口不在，而且候选集是**声明的封闭集**
    off = make_session()
    c_off = single_choice(ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1}),
                          allow_choices_without_escape=True)
    c_off.decide(off, _view(off))
    off_opts = [x for r in c_off.client.requests for qid, q in r.questions.items()
                if qid == "pickInput" for x in q["criteria"]]
    assert off_opts, "对照组也得问 pickInput —— 否则它测的不是同一件事"
    assert PICK_INPUT_ESCAPE not in off_opts, off_opts
    # ★ 其余候选**完全一样** —— 单变量说的是这个
    assert set(off_opts) <= set(on_opts), "对照组多出了默认组没有的候选"
    assert set(on_opts) - set(off_opts) == {PICK_INPUT_ESCAPE}


def test_every_registered_spec_part_is_actually_found() -> None:
    """★★★ **指纹取不到的东西,等于没有指纹 —— 而这一条正是漏了很久的那个 bug。**

    旧的 `decision_spec_digest()` 写的是::

        holder = frame_mod if hasattr(frame_mod, name) else globals()
        getattr(holder, name, "<missing>")

    而 **`globals()` 是 dict** —— `getattr` 在 dict 上取不到任何名字。
    于是 `typed.py` 那 27 个常量**全部被记成 `'<missing>'`**,
    指纹实际上只覆盖了 `frame.py` 那 7 个。

    ⇒ 那条"改了问法而没 bump 版本就红"的保证,**一直是空头支票**:
      问法、判据、门限、兜底表**一个都没进指纹**。

    ★ 发现它的路径本身是论据:给 `OBJECT_ALLOW_CRITERIA` 加了一个真的语义改动
      （`honest_refusal`），而**指纹一点没动**。如果那次改动被别的东西挡住了,
      这个 bug 会继续藏着 —— 所以必须有一条**专门查"取不到"**的守卫。
    """
    from experiments.core import frame as fm
    from experiments.jloop import typed as m

    missing = [n for n in m.DECISION_SPEC_PARTS
               if not hasattr(m, n) and not hasattr(fm, n)]
    assert not missing, f"这些 part 两边都取不到,指纹里会被记成 <missing>:{missing}"

    # 而且**至少有一个 typed.py 的常量**必须真的进得去 —— 否则等于只盖了帧
    from_typed = [n for n in m.DECISION_SPEC_PARTS if hasattr(m, n)]
    assert len(from_typed) >= 20, (
        f"指纹只覆盖到 {len(from_typed)} 个 typed.py 的常量 —— 太少了,"
        f"问法/判据/门限很可能没进去"
    )


def test_the_answer_generator_can_see_the_evidence() -> None:
    """★★★ **写答案的那一次调用必须看得见工具输出 —— 这一条曾是整条臂最大的洞。**

    实测（2026-10-04，TERNARY）:`_answer_text` 的提示词里只有

        # Task             <题目>
        # What was done    search; read_doc          ← **只有工具名字**

    而 `call_model` 是**无状态**的（每次单条消息的全新补全）⇒
    **写答案的模型看不见自己搜集到的证据。**

    代价,按 `supported` 那 9 题量:**8 道的答案就在工具输出里,而 0 道答出来了。**
    草稿里那句"工具失败、没有可用证据"**不是一个编造,是一个盲眼的模型唯一能得出的结论**。
    而 `react-termination` 的内层是 `LLMController`（ReAct 的提示词带完整 scratchpad）
    ⇒ **它的生成端看得见证据** —— 那就是 8/20 与 14/20 之间的差距。

    ★ 判据是**看真的发出去的那条消息**,不是看这段代码想干什么。
    """
    seen: list[str] = []
    session = make_session()
    session.model = capital_model(seen)
    ctrl = judge_gate(ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1}))
    first = ctrl.decide(session, _view(session))
    step = _tool_step(first.tool, country="France", observation="Paris")
    seen.clear()
    ctrl.decide(session, _view(session, history=(step,)))
    assert seen, "一次模型调用都没发生"
    prompt = seen[-1]
    assert "Paris" in prompt, (
        f"生成端的提示词里没有工具输出 —— 那它答不出任何需要证据的问题。拿到的是:\n{prompt[:400]}"
    )
    assert "# Evidence" in prompt, prompt[:300]


def test_a_generated_argument_is_told_what_shape_the_value_has() -> None:
    """★★★ **不可枚举的参数是"生成"的 —— 而生成必须知道这一栏要什么形状。**

    实测（2026-10-04，TERNARY）:这一格原来只有一句
    「Give only the value for `query` — nothing else」，于是模型把**自己的结论**
    当搜索词发了出去:

        search('No value found. The provided corpus does not contain information
                regarding the 2025 revenue of Caldera Metrics.')
        → （没有匹配的行）

    而语料里**明明有两句互相冲突的**（156 / 201）。
    ⇒ `contradiction` 那 5 道**全部**死在这里:**检索根本没发生。**

    ★ 修法是 `Tool.argument_hints` —— **环境自己声明这一栏要什么**。
      和 `base_risk` / `observation_signals` / `describe_candidate` 同一条理由:
      **领域的事实由环境说,引擎猜不出来。**

    ★ 判据是**看真的发出去的那条消息**。默认 `toy` 的工具**没有**声明 hints,
      所以这一条测试要**造一个有的** —— 否则它测的是"没声明时也还好",
      而那正是原来那个洞。
    """
    from experiments.core.types import Tool

    seen: list[str] = []
    session = make_session()
    session.model = capital_model(seen)
    hint = "1–3 words that appear LITERALLY in the corpus; not a sentence"
    session.tools = [Tool(name="search", description="d", base_risk=0,
                          parameters={"type": "object",
                                      "properties": {"query": {"type": "string"}}},
                          argument_hints={"query": hint})]
    ctrl = judge_gate(ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1}))
    ctrl.decide(session, _view(session))
    assert seen, "参数生成没有发生"
    prompt = seen[-1]
    assert hint in prompt, (
        f"`argument_hints` 没有进生成提示词 —— 那模型只能猜这一栏要什么。拿到的是:\n{prompt[:400]}"
    )
    assert "# What `query` must be" in prompt, prompt[:300]
