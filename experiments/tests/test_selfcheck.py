"""零资源自检臂 —— 钉住**它的定义性质**：不碰判定后端、不碰金标、要花生成。

★ 这个文件最值钱的一条是 `test_it_never_touches_the_decision_backend`：

    这一格的**全部意义**就是"不靠判定模型、不靠金标，只看它自己前后一致不一致"。
    如果它偷偷调了判定后端，"零资源自检"这个标签就是假的 ——
    而它跑出来的数字会和 `react-termination` 混成一谈。

  第二条是 `test_inconsistent_samples_are_flagged`：一个"稳定犯错"的模型会拿高分
  （方法公开的已知弱点），所以这里也要钉住**发散会被抓到**，
  否则这一格退化成"永远 deliver"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.core.controller import Decision, DecisionView  # noqa: E402
from experiments.core.models import Message  # noqa: E402
from experiments.jloop.selfcheck import SelfCheckController  # noqa: E402


class _Inner:
    """内层控制器：第一次给答案，之后不该再被问到（采样走的是 session）。"""

    name = "inner"

    def __init__(self, answer: str = "the answer is 42") -> None:
        self.answer = answer
        self.calls = 0

    def decide(self, session, view):  # noqa: ANN001, ANN201
        self.calls += 1
        return Decision(kind="answer", answer=self.answer, syntax="bare-answer")


class _Session:
    """最小 session：给 `call_model` 记账，并**证明没有判定后端被碰过**。"""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.model_calls = 0
        self.decider_touched = False

    def call_model(self, messages: list[Message]):  # noqa: ANN201
        self.model_calls += 1
        text = self.replies.pop(0) if self.replies else ""
        return type("R", (), {"text": text})()

    # 判定后端那一路（MockClient 会调它）—— 被调到就说明这一臂不"零资源"了
    def record_decision(self, *_a, **_k):  # noqa: ANN002, ANN003
        self.decider_touched = True

    def next_batch(self):  # noqa: ANN201
        self.decider_touched = True
        return 0


def _view():
    return DecisionView(prompt="TASK?", tools=(), task_prompt="TASK?", task_id="x", step=0, history=())


# ═══════════════════════════════════════════════════════════
# ① ★ 定义性质：不碰判定后端
# ═══════════════════════════════════════════════════════════

def test_it_never_touches_the_decision_backend() -> None:
    """★★ 这一格之所以叫"零资源"，就是因为它不问判定模型、不看金标。"""
    s, inner = _Session(["42", "42", "42"]), _Inner("42")
    ctl = SelfCheckController(inner=inner, k=3)
    d = ctl.decide(s, _view())  # type: ignore[arg-type]
    assert d.gate == "deliver"
    assert s.decider_touched is False, "★ 它不该碰判定后端 —— 碰了就不是零资源自检了"
    assert s.model_calls == 3, "应当恰好采 k 次"


def test_the_samples_are_sessions_business_so_they_get_billed() -> None:
    """★ 采样必须走 `session.call_model` —— 绕过去的话"它更便宜"会是假的。"""
    # 自洽 ⇒ deliver：恰好 k 次
    ok = _Session(["same answer"] * 3)
    SelfCheckController(inner=_Inner("same answer"), k=3).decide(ok, _view())  # type: ignore[arg-type]
    assert ok.model_calls == 3, "三次额外生成必须进账本"

    # 不自洽 ⇒ revise：**k 次采样 + 1 次修订**。★ 这是这个方法的成本形状，
    #   报告里要一起报（它省掉的是判定后端的钱，不是模型的钱）。
    bad = _Session(["a", "b", "c", "d"])
    SelfCheckController(inner=_Inner("totally different"), k=3).decide(bad, _view())  # type: ignore[arg-type]
    assert bad.model_calls == 4, "走 revise 时是 k + 1 次生成"


# ═══════════════════════════════════════════════════════════
# ② 判据：自洽就放行，发散就判不合格
# ═══════════════════════════════════════════════════════════

def test_consistent_samples_are_delivered() -> None:
    s = _Session(["the answer is 42"] * 3)
    d = SelfCheckController(inner=_Inner("the answer is 42"), k=3).decide(s, _view())  # type: ignore[arg-type]
    assert d.gate == "deliver" and d.answer == "the answer is 42"


def test_inconsistent_samples_are_flagged() -> None:
    """★ 发散要被抓到 —— 否则这一格退化成"永远 deliver"。"""
    s = _Session(["completely different", "another thing entirely", "something else"])
    ctl = SelfCheckController(inner=_Inner("the answer is 42"), k=3)
    d = ctl.decide(s, _view())  # type: ignore[arg-type]
    assert d.gate == "revise", "三次采样都不像原答案 ⇒ 应当判不合格"
    assert ctl.consistency < ctl.threshold


def test_it_cannot_catch_a_consistently_wrong_model() -> None:
    """⚠️ **把方法的已知弱点钉成预期行为**：稳定地犯同一个错 ⇒ 它给高分。

    这不是 bug，是 SelfCheckGPT 公开的弱点（判据是"自洽"不是"正确"）。
    钉住它是为了两件事：① 报告里必须这么写；② 将来有人想"修"它之前先看到这条。
    """
    s = _Session(["wrong but stable"] * 3)
    d = SelfCheckController(inner=_Inner("wrong but stable"), k=3).decide(s, _view())  # type: ignore[arg-type]
    assert d.gate == "deliver", "★ 一致地错 ⇒ 这一格会放行（已知弱点，不是回归）"


def test_low_threshold_note_is_documented() -> None:
    """阈值是拍的 —— 至少要保证它是个显式参数，不是散在代码里的魔数。"""
    assert SelfCheckController().threshold == 0.5
    assert SelfCheckController(threshold=0.9).threshold == 0.9


# ═══════════════════════════════════════════════════════════
# ③ 采不出答案 ≠ 通过
# ═══════════════════════════════════════════════════════════

def test_no_samples_at_all_escalates_instead_of_passing() -> None:
    """★ 一次都没采出来 ⇒ 不许当成"通过了"（那会把"没做成"读成"没事"）。"""
    s = _Session(["", "", ""])
    d = SelfCheckController(inner=_Inner("x"), k=3).decide(s, _view())  # type: ignore[arg-type]
    assert d.kind == "ask" and d.gate == "blocked"


def test_non_answer_steps_pass_through_untouched() -> None:
    """工具调用那一步**不该被这一臂碰** —— 它只在终点做判定。"""

    class _ToolInner:
        name = "t"

        def decide(self, session, view):  # noqa: ANN001, ANN201
            return Decision(kind="tool", tool="exec", arguments={"command": "ls"})

    s = _Session([])
    d = SelfCheckController(inner=_ToolInner(), k=3).decide(s, _view())  # type: ignore[arg-type]
    assert d.kind == "tool" and s.model_calls == 0
