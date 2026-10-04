"""**"回去接着做"** —— 闸门把"结束"改道回动作空间。

★ 这个文件最值钱的四条：

  `test_the_gate_says_which_disease_it_found`
      两种病因说成同一句话，补救就没法分 —— 这正是那 8 条编造的根。
      `unsupported` 高 ⇒ `overclaim`（说得太多）；`deliverable` 低 ⇒ `incomplete`（做得不够）。

  `test_overclaim_degrades_instead_of_rewriting`
      实测（2026-10-01，`fta × react-termination`）：那 8 条"草稿诚实、改完变成编造"
      的第一判全是 `incomplete`，而循环只会**重写** —— 于是 `unsupported` 从 0.07
      冲到 0.99。**把"没做完"翻译成"重写"，等于让模型在没有新信息时写得更像样。**

  `test_incomplete_redirects_when_there_is_still_something_to_do`
      `incomplete` 且有候选动作 ⇒ **回去做**。这是本次新增的那一格裁决。

  `test_decide_falls_through_to_the_action_path_on_redirect`
      ★★★ 改道不能只是返回一个字符串 —— `decide()` 必须真的**落到 pick 那一段**，
      而不是把 `None` 当答案、也不是重新问一遍 `needsTool`（那会死循环）。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.core.deciding import DecideResponse  # noqa: E402
from experiments.jloop import typed as typed_mod  # noqa: E402
from experiments.jloop.typed import MAX_REDIRECTS, TypedController  # noqa: E402

from experiments.tests.test_typed_controller import (  # noqa: E402
    ScriptedClient,
    pick_input_rows,
    _tool_step,
    _view,
    make_session,
)

#: 让"还能不能动作"变确定的一把脚本 —— 默认**不需要动作**（走收尾），
#: 且**做得不够**（`deliverable` 低）。要看别的分支的测试自己覆盖。
def _scripted(**noul) -> ScriptedClient:
    base = {"needsTool": 0.1, "stepOk": 0.9, "isDone": 0.1,
            "unsupported": 0.1, "deliverable": 0.1,
            # ★ `needs_auth` 必须显式给低：授权闸门（§8.5）**不接受概率绕过**，
            #   漏掉它就会默认 0.9 ⇒ 判 `ask_human` 并把整步停下，
            #   于是这条测试测的变成了授权闸门，不是交付闸门。
            "needs_auth": 0.1}
    base.update(noul)
    return ScriptedClient(noul=base, pick={"pickTool": "lookup_capital"})


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




def _ctx():
    from experiments.jloop.typed import AgentCtx

    return AgentCtx(task="t", draft="d")


# ═══════════════════════════════════════════════════════════
# ① 闸门把**病因**说清楚（以前只说 "revise"）
# ═══════════════════════════════════════════════════════════


def test_the_gate_says_which_disease_it_found() -> None:
    s = make_session()

    over = judge_gate(_scripted(unsupported=0.9, deliverable=0.9))
    assert over._can_deliver(s, _view(s), _ctx())[:2] == ("revise", "overclaim"), \
        "超出证据 ⇒ overclaim（补救是撤回）"

    under = judge_gate(_scripted(unsupported=0.1, deliverable=0.1))
    assert under._can_deliver(s, _view(s), _ctx())[:2] == ("revise", "incomplete"), \
        "做得不够 ⇒ incomplete（补救是回去做）"

    ok = judge_gate(_scripted(unsupported=0.1, deliverable=0.9))
    assert ok._can_deliver(s, _view(s), _ctx())[:2] == ("deliver", ""), "证据支持得住 ⇒ 直接放行"


def test_the_feedback_carries_the_probability() -> None:
    """说明里要带概率 —— 否则日志上分不出这条是闸门的新判还是旧账。"""
    s = make_session()
    ctl = judge_gate(_scripted(unsupported=0.9, deliverable=0.9))
    verdict, reason, feedback = ctl._can_deliver(s, _view(s), _ctx())
    assert verdict == "revise" and "unsupported=" in feedback


def test_unjudgeable_is_its_own_reason() -> None:
    """闸门答不出来（缺答案）⇒ `blocked` + `unjudgeable`，不混进那两种病因。"""
    s = make_session()
    ctl = judge_gate(_scripted())
    ctl.client.omit = {"unsupported", "deliverable"}
    assert ctl._can_deliver(s, _view(s), _ctx())[:2] == ("blocked", "unjudgeable")


# ═══════════════════════════════════════════════════════════
# ② 病因 → 补救 的映射
# ═══════════════════════════════════════════════════════════


def test_overclaim_degrades_instead_of_rewriting() -> None:
    """★★ "说得太多"的补救是**少说**（撤回），不是"换个说法再说一遍"。"""
    assert judge_gate(_scripted())._remedy(None, _ctx(), "overclaim") == "degrade"


def test_incomplete_redirects_when_there_is_still_something_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★ **本次新增的那一格**：做得不够 ⇒ 回去做。"""
    monkeypatch.setattr(typed_mod, "candidates", lambda session, ctx, **kw: ["lookup_capital"])
    assert judge_gate(_scripted())._remedy(None, _ctx(), "incomplete", may_redirect=True) == "redirect"


def test_incomplete_degrades_when_there_is_nothing_left_to_do(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ 没得做的时候改道没有落点 —— 必须退化，不能空转。

    FTA 整份数据就是这个形状：工具**按构造坏掉了**，动作空间是空的。
    所以它上面降低编造率靠的是 `degrade`，不是 `redirect`。
    """
    monkeypatch.setattr(typed_mod, "candidates", lambda session, ctx, **kw: [])
    assert judge_gate(_scripted())._remedy(None, _ctx(), "incomplete", may_redirect=True) == "degrade"


def test_the_redirect_cap_is_what_stops_a_fee_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★ 用满改道次数之后必须退化 —— 否则就是收费循环（和 `revise` 上限 1 次同理）。"""
    monkeypatch.setattr(typed_mod, "candidates", lambda session, ctx, **kw: ["lookup_capital"])
    ctl = judge_gate(_scripted())
    assert ctl.redirects == 0
    assert ctl._remedy(None, _ctx(), "incomplete", may_redirect=True) == "redirect"

    ctl.redirects = MAX_REDIRECTS
    assert ctl._remedy(None, _ctx(), "incomplete", may_redirect=True) == "degrade", \
        "用满上限之后还在改道 ⇒ 那个循环没有出口"


# ═══════════════════════════════════════════════════════════
# ③ 改道真的落到动作路径上（不是只返回一个字符串）
# ═══════════════════════════════════════════════════════════


def _after_one_real_step():
    """跑到**第二次 `decide()`**，而且此时 `needsTool` 说"不用动作了"。

    ★ 为什么要这么绕：toy 在第 0 步就有候选动作，如果一上来 `needsTool` 就是低，
      第一次 `decide()` 就会直接收尾并被改道 —— 那测的是"第一次就改道"，
      不是"做了一步之后才发现没做完"。**改道的意义在后者。**
    """
    session = make_session()
    client = _scripted(needsTool=0.9)          # 第一步：还要动作
    ctl = judge_gate(client)
    first = ctl.decide(session, _view(session))
    assert first.kind == "tool", f"第一步该真的调工具:{first}"
    client.noul["needsTool"] = 0.1             # 第二步：它说"不用动作了"
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    return ctl, session, step


def test_decide_falls_through_to_the_action_path_on_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★★ 整件事的关键：`_finish` 返回 `None` 之后，`decide()` 必须**落到 pick
    那一段** —— 不是把 `None` 当答案返回，也不是重新问一遍 `needsTool`
    （那会"改道 → 又问 → 又说不用 → 死循环"）。

    判据：拿到的是 `tool`，`redirects` 记了一次，而且轨迹里留下
    **`needsTool` 与闸门矛盾**的那一笔 —— 矛盾必须可见，否则它看起来像顺利收尾。
    """
    monkeypatch.setattr(typed_mod, "candidates", lambda s, c, **kw: ["lookup_capital"])
    ctl, session, step = _after_one_real_step()

    d = ctl.decide(session, _view(session, history=(step,)))

    assert ctl.redirects == 1, "闸门判「没做完」⇒ 应当改道一次"
    assert d is not None and d.kind == "tool", (
        f"改道之后必须回到动作路径，而不是交一份答案（拿到的是 {d}）"
    )
    contradictions = [t for t in ctl.trace
                      if t.get("violation") == "redirect_overrides_needsTool"]
    assert contradictions, "矛盾必须留痕 —— 否则它看起来像一次顺利的收尾"
    assert "回到动作空间" in contradictions[0]["detail"]


def test_redirect_does_not_re_ask_needs_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """★★ 改道之后**不许重新问 `needsTool`** —— 它刚说"不用动作了"，
    再问一遍就是"改道 → 又问 → 又说不用 → 死循环"。"""
    monkeypatch.setattr(typed_mod, "candidates", lambda s, c, **kw: ["lookup_capital"])
    ctl, session, step = _after_one_real_step()
    before = ctl.client.asked("needsTool")

    ctl.decide(session, _view(session, history=(step,)))
    assert ctl.client.asked("needsTool") == before + 1, (
        "这一轮只该问一次 needsTool（在闸门之前）—— 改道之后不能再问"
    )


def test_a_redirect_is_visible_as_a_decision_not_only_in_the_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★ 改道也要在**判定轨迹**里看得见 —— 它是一次判定驱动的控制流改道，
    不是实现细节。看不见的话，"闸门有没有影响过路径"在日志上答不出来。"""
    monkeypatch.setattr(typed_mod, "candidates", lambda s, c, **kw: ["lookup_capital"])
    ctl, session, step = _after_one_real_step()
    ctl.decide(session, _view(session, history=(step,)))

    rows = [(t.get("node"), t.get("answer"), t.get("remedy")) for t in ctl.trace]
    assert ("canDeliver", "revise/incomplete", "redirect") in rows, rows


def test_only_the_two_escape_points_may_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★ **`may_redirect` 只由两个"提前收尾"的出口打开。**

    ① `needsTool` 说"不用动作了"；② `pickInput` 选了退出口（"这些动作都不合适"）。
    两者形状相同：**都是主动想收尾，而闸门说没做完** ⇒ 回去做。

    ★ 别的地方说"回去做"没有落点：候选空了是本来就没得做；只剩 `DONE` 是
    "想动但没得动"，不是"以为收尾了"。在那些地方强行走改道，只会白花一次判定
    然后撞上限 —— 所以**默认不许**，而不是"忘了传"。
    """
    monkeypatch.setattr(typed_mod, "candidates",
                        lambda session, ctx, **kw: ["lookup_capital"])
    ctl = judge_gate(_scripted())
    assert ctl._remedy(None, _ctx(), "incomplete", may_redirect=True) == "redirect"
    assert ctl._remedy(None, _ctx(), "incomplete") == "degrade", (
        "没开这一路的调用点一律退化 —— 别让「回去做」漏到没有落点的地方"
    )


# ═══════════════════════════════════════════════════════════
# ④ 改道的候选集和正向**不是同一个问题**
# ═══════════════════════════════════════════════════════════


def test_redirect_candidates_do_not_dedup_and_do_not_offer_the_exit() -> None:
    """★★★ 正向问"还有什么事没做过"，改道问"缺的是哪一块" —— 所以不是同一套：

      · **不去重**：`go to X` → `go to Y` 是同一个动词，按名字去重会把唯一能
        补上缺口的那一步删掉（ALFWorld 那一类就是这个形状）
      · **不给 `DONE`**：它是刚刚被驳回的那个动作，再端上来是自相矛盾，
        模型顺手挑一次就白跑一轮判定
    """
    from experiments.core.frame import StepRecord
    from experiments.jloop.typed import DONE, candidates

    s = make_session()
    first = s.tools[0].name
    ctx = _ctx()
    ctx.history = (StepRecord(step=0, tool=first, input="", result="ok"),)

    forward = candidates(s, ctx)
    assert first not in forward, "正向要按工具名去重"
    assert DONE in forward, "正向要给出口"

    redirect = candidates(s, ctx, redirected=True)
    assert first in redirect, "★ 改道要把做过的工具放回来（换个参数再做一次）"
    assert DONE not in redirect, "★ 改道不许把刚被驳回的出口再端上来"


def test_the_rejection_reason_reaches_the_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★★ **改道不许是盲的。** 闸门算出了"缺什么"，那条信息必须进帧 ——
    否则 `pickTool` 看到的是和之前一模一样的帧：它会去调工具，
    但没有任何依据挑对那一个。
    """
    monkeypatch.setattr(typed_mod, "candidates",
                        lambda session, ctx, **kw: ["lookup_capital"])
    ctl, session, step = _after_one_real_step()
    ctl.decide(session, _view(session, history=(step,)))

    assert ctl.redirects == 1
    # ★ 光在轨迹里写一句"理由已进帧"**不算证据** —— 那是自己说自己。
    #   真证据是：**发出去的帧正文里**要能看到那条驳回理由。
    #   判定请求的 `state["frame"]` 就是帧全文（`Request.render()` 的产物）。
    frames = [r.state.get("frame", "") for r in ctl.client.requests]
    assert any("rejected" in f for f in frames), (
        "被驳回的理由必须真的出现在发出去的帧里 —— 否则改道还是盲的"
    )
    assert any("not met" in f or "incomplete" in f for f in frames), (
        "而且要带着**病因**，不能只说「有一份被打回了」"
    )


def test_a_single_parameterized_tool_is_never_deduped_away() -> None:
    """★★★ **单工具 + 参数化**的环境里调一次工具不等于"做完了"。

    ALFWorld 只有**一个**工具 `act`，参数是命令原文，合法命令由环境每步重建
    （实测开局 28 条，走到 cabinet 1 之后全换）。按工具名去重的话，调一次之后
    候选只剩 `[DONE]`，**循环会在第一步就收尾** —— 那不是"做完了"，是"没得选了"。

    ★ 这和 `candidates` 自己的注释是矛盾的（注释说删的是"已经做过的那一次动作"，
      代码删的是**工具名**）。两个在多工具数据集上重合，在单工具上差得离谱。
    """
    from experiments.core.frame import StepRecord
    from experiments.core.types import Tool
    from experiments.jloop.typed import DONE, candidates

    live = Tool(
        name="act",
        description="Execute one command in the environment.",
        parameters={"type": "object", "properties": {"command": {"type": "string"}}},
        live_candidates=lambda: ["go to cabinet 1", "look at desk"],
    )

    class _S:
        tools = (live,)

    ctx = _ctx()
    ctx.history = (StepRecord(step=0, tool="act", input="look", result="a desk"),)

    left = candidates(_S(), ctx)
    assert "act" in left, "★ 带 live_candidates 的工具做完一次**还要留在候选里**"
    assert left != [DONE], "单工具环境不该在第一步就只剩出口"


def test_a_plain_tool_is_still_deduped() -> None:
    """反面：**没有** `live_candidates` 的工具照旧按名字去重（BFCL 那一类）。"""
    from experiments.core.frame import StepRecord
    from experiments.core.types import Tool
    from experiments.jloop.typed import DONE, candidates

    plain = Tool(name="search", description="d", parameters={})

    class _S:
        tools = (plain,)

    ctx = _ctx()
    ctx.history = (StepRecord(step=0, tool="search", input="x", result="ok"),)
    assert candidates(_S(), ctx) == [DONE], (
        "普通工具做过就该从候选里消失 —— 否则同一个动作会被反复挑"
    )


def test_the_redirect_note_is_actually_a_frame_field() -> None:
    """★ 光设 `ctx.redirect_note` 没用 —— 帧只渲染**声明过**的字段。
    没在 `FrameSpec` 里声明，它就是个死字段（本项目的老账）。"""
    from experiments.core.frame import NODE_FRAMES

    for node in ("needsTool", "pickTool", "pickInput"):
        names = [f.name for f in NODE_FRAMES[node].fields]
        assert "redirect_note" in names, f"{node} 的帧里没有 redirect_note ⇒ 死字段"


def test_a_missing_deliverable_answer_does_not_produce_a_redirect() -> None:
    """闸门答不出来时是 `blocked`（弃权），**不是改道** —— 两件事要分得开。

    改道的前提是"闸门判出任务没做完"；判不出来的时候它没有任何依据说
    "还有事没做"，那就不该动控制流。

    ★ 两臂对 `blocked` 的出口**不一样，而且是有意的**：

        `react-typed`（全契约）  退回 `unparsed`，交给循环去看得见的地方重试/弃答
                                 —— 因为它循环里本来就有重试这条路
        `react-termination`      直接 `ask` —— 那一臂只在终点判一次，
                                 没有"下一步"可以退回去

      这条测试钉的是**全契约那一侧**；`termination_only` 那一侧见
      `test_blocked_gate_escalates_instead_of_pretending_to_pass`。
    """
    ctl, session, step = _after_one_real_step()
    ctl.client.omit = {"unsupported", "deliverable"}
    d = ctl.decide(session, _view(session, history=(step,)))

    assert ctl.redirects == 0, "判不出来 ⇒ 不许动控制流"
    assert d is not None and d.kind == "unparsed", f"缺依据 ⇒ 退回 unparsed:{d}"
    assert d.gate == "blocked", "而且要把 blocked 这个裁决带回去（它是弃权的证据）"


# ═══════════════════════════════════════════════════════════
# ⑤ ★★★ 第二条改道入口：`pickInput` 的退出口
#
#   实测撞出来的（2026-10-03，ALFWorld seed20261020）：退出口被选中、
#   闸门又把收尾改道 ⇒ `_finish` 返回 `Redirect` ⇒ 没人检查 ⇒
#   `AttributeError: 'Redirect' object has no attribute 'kind'`，
#   整道题 0 步、`stop_reason="error"`。
#
#   **`_finish` 的返回类型是 `Decision | Redirect`，而只有一条调用点检查过它。**
#   加第二条调用点时没人检查 —— 这类错不会在类型检查里现形，因为
#   `decide()` 的返回标注也是联合类型。
# ═══════════════════════════════════════════════════════════


def _escape_chosen(monkeypatch: pytest.MonkeyPatch):
    """跑到 `pickInput`，并让判官挑**退出口**。"""
    from experiments.jloop.typed import PICK_INPUT_ESCAPE

    monkeypatch.setattr(typed_mod, "candidates",
                        lambda s, c, **kw: ["lookup_capital"])
    session = make_session()
    client = _scripted(needsTool=0.9)
    client.pick["pickInput"] = PICK_INPUT_ESCAPE
    return judge_gate(client), session, client


def test_the_pick_input_escape_does_not_leak_a_redirect_object(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★★ **退出口 → 闸门改道，返回的必须还是一个 `Decision`。**

    `run_loop` 只认 `Decision`。把 `Redirect` 漏出去不是"行为略有不同"，
    是当场崩掉整道题（0 步、`stop_reason="error"`）。
    """
    from experiments.jloop.typed import Redirect

    ctl, session, client = _escape_chosen(monkeypatch)
    out = ctl.decide(session, _view(session))

    assert not isinstance(out, Redirect), (
        "`Redirect` 漏给了 `run_loop` —— 这就是那个 AttributeError"
    )
    assert out.kind in ("answer", "tool", "ask", "unparsed"), out
    # 闸门判"没做完" ⇒ 应当改道一次，而且只有一次（上限）
    assert ctl.redirects == 1, ctl.redirects
    trace = [t for t in ctl.trace
             if t.get("violation") == "redirect_overrides_pickInput_escape"]
    assert trace, [t.get("violation") for t in ctl.trace]
    assert "理由已进帧" in trace[0]["detail"]


def test_the_re_ask_after_a_redirect_is_not_the_same_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★★ **改道之后重问的那一次，不是同一个请求。**

    这条是那个改道**合不合法**的全部依据。我们量过：重发一个逐字节相同的请求
    不是错误恢复，是重新抽一次（20 组同 digest 里 19 组置信度不同）。
    所以"退出口被选中之后回去重挑"只有在**帧真的变了**的时候才成立 ——
    变的那一项就是 `redirect_note`（闸门给的理由）。

    ★ 判据用 `request_digest`，**不是** `frame_digest`：后者只覆盖帧，
      而 `choice` 的选项不在帧里。这里恰好两者都会变，但用对的那个。
    """
    ctl, session, client = _escape_chosen(monkeypatch)
    ctl.decide(session, _view(session))
    session.finish_events()

    rows = pick_input_rows(session)
    # ★ 一候选一题（新默认）之后，**一次**问动作空间就是 N 行，不是一行
    #   （`pickInput::1` … `pickInput::N`）。所以「两次问」在账上是**两段**
    #   同 digest 的行，而不是相邻两行。按相邻行断言会把「同一次问的第 2 个
    #   候选」当成「第二次问」—— 于是这条判据恒真，等于没测。
    #   ⇒ 先把连续的相同请求压成一个请求，再比第 1 个和第 2 个请求。
    asks: list[str] = []
    for r in rows:
        if not asks or asks[-1] != r.request_digest:
            asks.append(r.request_digest)
    assert len(asks) >= 2, (
        f"应当重问过一次（两个不同的请求），实际只看到 {len(asks)} 个：{asks}"
    )
    assert asks[0] != asks[1], (
        "重问的请求和第一次逐字节相同 ⇒ 那不是恢复，是抽奖"
    )
    assert ctl.redirects == 1
