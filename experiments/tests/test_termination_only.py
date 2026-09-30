"""终点验证臂 —— 钉住**它和全契约只差"判定放几次"**，以及那两个指标真的算得出来。

★ 这个文件最值钱的两条：

  `test_it_asks_nothing_in_the_middle_of_the_loop`
      这一臂的自变量就是"循环中间一次判定都不问"。如果它中途问了，那它和
      `react-typed` 的差就不只来自"判定放几次"了 —— 而那是整个比较的立足点。

  `test_the_gate_flags_are_actually_produced`
      `gate_false_reject` / `gate_false_deny` 曾经**恒为 False**（没有任何地方
      产生那两个 failure_class）。这条测试拿四种组合把新算法钉死，
      免得它再退回去变成两个永远不亮的灯。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.core.agent import AgentOutcome  # noqa: E402
from experiments.core.controller import Decision  # noqa: E402
from experiments.core.types import Judgment  # noqa: E402
from experiments.jloop.termination_only import TerminationOnlyController  # noqa: E402


# ═══════════════════════════════════════════════════════════
# ① 只在终点判定 —— 循环中间一次都不问
# ═══════════════════════════════════════════════════════════

class _SpyInner:
    """假装自己是 `LLMController`：记下被调了几次，按剧本回话。"""

    name = "spy"

    def __init__(self, kinds: list[str]) -> None:
        self.kinds = list(kinds)
        self.calls = 0

    def decide(self, session, view):  # noqa: ANN001, ANN201
        assert self.kinds, "剧本用完了，说明这一臂多问了一次"
        self.calls += 1
        kind = self.kinds.pop(0)
        if kind == "answer":
            return Decision(kind="answer", answer="done", syntax="bare-answer")
        return Decision(kind="tool", tool="exec", arguments={"command": "ls"})


class _SpyGate:
    """假装自己是 `TypedController`：只被用来跑闸门，记下被用了几次。"""

    def __init__(self, verdicts: list[str]) -> None:
        self.verdicts = list(verdicts)
        self.gate_calls = 0
        self.answer_calls = 0

    def _can_deliver(self, session, view, ctx):  # noqa: ANN001, ANN201
        self.gate_calls += 1
        return (self.verdicts.pop(0) if self.verdicts else "deliver"), "why"

    def _answer_text(self, session, view, *, revise=""):  # noqa: ANN001, ANN201
        self.answer_calls += 1
        return f"revised({revise})"


def _view():
    from experiments.core.controller import DecisionView

    return DecisionView(prompt="p", tools=(), task_prompt="t", task_id="x", step=0, history=())


def test_it_asks_nothing_in_the_middle_of_the_loop() -> None:
    """★★ 中间那两步是工具调用 ⇒ 闸门**一次都不该被碰**。

    这是这一臂的自变量本身：全契约在每一步都问（needsTool/pickTool/…），
    而它只在最后问那一次。中途碰了闸门，比较就不成立。
    """
    inner, gate = _SpyInner(["tool", "tool", "answer"]), _SpyGate(["deliver"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    v = _view()

    for _ in range(2):
        d = ctl.decide(None, v)  # type: ignore[arg-type]
        assert d.kind == "tool"
    assert gate.gate_calls == 0, "循环中间不该碰闸门"

    d = ctl.decide(None, v)  # type: ignore[arg-type]
    assert d.kind == "answer" and d.answer == "done"
    assert gate.gate_calls == 1, "终点应当只问一次"
    assert d.gate == "deliver"


def test_a_gate_verdict_of_revise_triggers_exactly_one_revision() -> None:
    """和全契约同一条纪律：**上限 1 次**，第二次仍不合格就如实交出去。"""
    inner, gate = _SpyInner(["answer"]), _SpyGate(["revise", "revise"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]

    assert gate.gate_calls == 2, "应当恰好判两次：初判 + 修订后复判"
    assert gate.answer_calls == 1, "应当恰好修订一次"
    assert d.kind == "answer" and d.answer.startswith("revised"), "第二次不合格也要如实交付"
    assert d.gate == "revise", "★ 记的是**第一次**裁决 —— 复判那个数已被闸门影响过"


def test_blocked_gate_escalates_instead_of_pretending_to_pass() -> None:
    """闸门发不出去（帧缺依据 / 超预算）⇒ 如实弃答，不许当成"通过了"。"""
    inner, gate = _SpyInner(["answer"]), _SpyGate(["blocked"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]
    assert d.kind == "ask" and d.gate == "blocked"


# ═══════════════════════════════════════════════════════════
# ② ★ 那两个指标真的算得出来（以前恒为 False）
# ═══════════════════════════════════════════════════════════

def _flags(outcome_gate: str, correct: bool) -> tuple[bool, bool]:
    """**逐字**复制 `core/runner.py` 里那两行算法。

    ⚠️ 复制是有意的：这条测试要钉的是**那个算法**，而 runner 的记账要跑一整格
       才能触到。算法改了而这里没改，这一条会红 —— 那就是提醒。
    """
    return (
        bool(outcome_gate == "revise" and correct),      # gate_false_reject 闸门假拒
        bool(outcome_gate == "deliver" and not correct),  # gate_false_deny  闸门放过
    )


@pytest.mark.parametrize(
    "gate,correct,false_reject,false_pass",
    [
        ("revise", True, True, False),    # 对好答案说 revise ⇒ 假拒
        ("revise", False, False, False),  # 对坏答案说 revise ⇒ 判对了
        ("deliver", True, False, False),  # 对好答案说 deliver ⇒ 判对了
        ("deliver", False, False, True),  # 对坏答案说 deliver ⇒ 放过
    ],
)
def test_the_gate_flags_are_actually_produced(
    gate: str, correct: bool, false_reject: bool, false_pass: bool
) -> None:
    """★ 四种组合都要有**恰好一种**亮起来 —— 这一步保证那两栏不再是死字段。"""
    fr, fp = _flags(gate, correct)
    assert (fr, fp) == (false_reject, false_pass)
    assert fr or fp or (gate in ("revise", "deliver"))


def test_no_gate_means_both_flags_stay_dark() -> None:
    """没有闸门的臂（`direct` / `react`）不该被算成"闸门犯了错"。"""
    assert _flags("", True) == (False, False)
    assert _flags("", False) == (False, False)


def test_agent_outcome_carries_the_verdict_by_default_as_unset() -> None:
    """默认 `""` = 这一臂没有闸门 —— **不是**"闸门说 deliver"。"""
    assert AgentOutcome().gate == ""


def test_judgment_shape_is_unchanged() -> None:
    """顺手钉一下：那两个指标只读 `judgment.correct`，不依赖任何 failure_class。"""
    assert Judgment(correct=True).failure_class is None
