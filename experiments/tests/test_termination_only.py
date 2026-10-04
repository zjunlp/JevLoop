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

    def __init__(self, verdicts: list[str], *, reason: str = "overclaim") -> None:
        self.verdicts = list(verdicts)
        self.reason = reason
        self.gate_calls = 0
        self.degrade_calls = 0
        self.trace: list[dict] = []

    def _can_deliver(self, session, view, ctx):  # noqa: ANN001, ANN201
        self.gate_calls += 1
        return (self.verdicts.pop(0) if self.verdicts else "deliver"), self.reason, "why"

    def review_draft(self, session, view, ctx):  # noqa: ANN001, ANN201
        """★ 闸门的**唯一入口** —— `termination_only` 现在只走这一个。

        替身必须实现它替的那个接口。以前这一臂直接调 `_can_deliver`,于是
        "加在闸门上的档位"会有两个调用点 —— `shadow` 就是这么撞出来的:
        直接调 `_can_deliver` 的话,`shadow` 在这一臂**静默失效**,
        而它会照样跑出一份看起来正常的分数。
        """
        return (*self._can_deliver(session, view, ctx), True)

    def _remedy(self, session, ctx, reason):  # noqa: ANN001, ANN201
        """★ 默认 `degrade`：`redirect` 在 `termination_only` 里**没有落点**
        （这一臂没有先验路径），所以那条路单独测 —— 见
        `test_a_redirect_without_an_apriori_path_falls_back_to_degrade`。"""
        self.last_reason = reason
        return "degrade"

    def _degrade_text(self, session, view, *, reason, feedback):  # noqa: ANN001, ANN201
        self.degrade_calls += 1
        return f"degraded({reason}:{feedback})"


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


def test_a_gate_verdict_of_revise_triggers_exactly_one_remedy() -> None:
    """和全契约同一条纪律：**上限 1 次**，第二次仍不合格就如实交出去。

    ★ 补救是 `degrade`（撤回证据支持不了的部分），**不再是 `revise`（重写）**——
      见 `_can_deliver` 里那段实测因果链：把"没做完"翻译成"重写"会诱发编造。
    """
    inner, gate = _SpyInner(["answer"]), _SpyGate(["revise", "revise"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]

    assert gate.gate_calls == 2, "应当恰好判两次：初判 + 撤回后复判"
    assert gate.degrade_calls == 1, "★ 应当恰好撤回一次 —— 而且走的是 degrade 不是重写"
    assert d.kind == "answer" and d.answer.startswith("degraded"), "第二次不合格也要如实交付"
    assert d.gate == "revise", "★ 记的是**第一次**裁决 —— 复判那个数已被闸门影响过"


def test_a_redirect_without_an_apriori_path_falls_back_to_degrade() -> None:
    """★★ **改道需要先验那一段存在。**

    `termination_only` 这一臂没有动作选择路径（`pickTool` / `pickInput` 都由
    生成模型自己决定），所以闸门说"没做完、回去做"在这里**没有落点**。
    它必须**明着退化**并留下痕迹，而不是静默地重写一遍 ——
    静默退化正是当初那 27 条被读成误伤的那类问题。
    """
    inner, gate = _SpyInner(["answer"]), _SpyGate(["revise"], reason="incomplete")
    gate._remedy = lambda session, ctx, reason: "redirect"  # type: ignore[method-assign]
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]

    assert d.answer.startswith("degraded"), "没有先验路径 ⇒ 只能撤回"
    notes = [t for t in gate.trace if t.get("remedy") == "redirect→degrade"]
    assert notes, "退化必须留痕，否则它和「设计成重写」长得一样"
    assert "没有先验路径" in notes[0]["detail"]


def test_blocked_gate_escalates_instead_of_pretending_to_pass() -> None:
    """闸门发不出去（帧缺依据 / 超预算）⇒ 如实弃答，不许当成"通过了"。"""
    inner, gate = _SpyInner(["answer"]), _SpyGate(["blocked"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]
    assert d.kind == "ask" and d.gate == "blocked"


# ═══════════════════════════════════════════════════════════
# ② ★ 那两个指标真的算得出来（以前恒为 False）
# ═══════════════════════════════════════════════════════════

def _flags(outcome_gate: str, draft_correct: bool, correct: bool) -> tuple[bool, bool, bool]:
    """**逐字**复制 `core/runner.py` 里那三行算法。

    ⚠️ 复制是有意的：这条测试要钉的是**那个算法**，而 runner 的记账要跑一整格
       才能触到。算法改了而这里没改，这一条会红 —— 那就是提醒。

    ★★ 2026-10-01 修正：`gate_false_reject` 现在判的是**闸门打回的那一版草稿**，
       不是改完之后那一版。旧算法（`revise ∧ 最终 correct`）把"修订救回来了"
       也算成误伤 —— 实测 `fta × react-termination` 报了 27 条，全部 `none`。
    """
    return (
        bool(outcome_gate == "revise" and draft_correct),                  # 闸门假拒
        bool(outcome_gate == "deliver" and not correct),                   # 闸门放过
        bool(outcome_gate == "revise" and not draft_correct and correct),  # 闸门改好了
    )


@pytest.mark.parametrize(
    "gate,draft_ok,final_ok,false_reject,false_pass,corrected",
    [
        # 草稿**本来是对的**、被打回 ⇒ 这才是误伤
        ("revise", True, True, True, False, False),
        # 草稿对、改完反而错了 ⇒ 也是误伤（而且更糟）
        ("revise", True, False, True, False, False),
        # ★★ 草稿坏、改好了 ⇒ **闸门立功**，旧判据把它记成误伤
        ("revise", False, True, False, False, True),
        # 草稿坏、改完还是坏 ⇒ 闸门白忙，但两个错都不算它头上
        ("revise", False, False, False, False, False),
        ("deliver", False, True, False, False, False),   # 对好答案说 deliver ⇒ 判对了
        ("deliver", False, False, False, True, False),   # 对坏答案说 deliver ⇒ 放过
    ],
)
def test_the_gate_flags_are_actually_produced(
    gate: str, draft_ok: bool, final_ok: bool,
    false_reject: bool, false_pass: bool, corrected: bool,
) -> None:
    """★ 六种组合都要有**恰好一种**亮起来 —— 这一步保证那几栏不再是死字段。"""
    fr, fp, gc = _flags(gate, draft_ok, final_ok)
    assert (fr, fp, gc) == (false_reject, false_pass, corrected)


def test_a_successful_correction_is_not_reported_as_a_false_reject() -> None:
    """★★ **回归钉。** 旧判据下这一格是 `False, True`（误伤）—— 它是反的。

    "闸门要求修订、修订之后对了"意思是**闸门把一个坏答案救回来了**。
    把它记账成误伤，读表的人会得出"闸门只会帮倒忙"的相反结论。
    """
    fr, _fp, gc = _flags("revise", draft_correct=False, correct=True)
    assert fr is False, "改好了不该算误伤"
    assert gc is True, "改好了必须被记下来，否则这一类就从账上消失了"


def test_a_false_reject_and_a_correction_are_mutually_exclusive() -> None:
    """★ 一次 revise 不可能既误伤又立功 —— 两条判据的 `draft_correct` 相反。"""
    for draft_ok in (True, False):
        for final_ok in (True, False):
            fr, _fp, gc = _flags("revise", draft_ok, final_ok)
            assert not (fr and gc)


def test_no_gate_means_all_flags_stay_dark() -> None:
    """没有闸门的臂（`direct` / `react`）不该被算成"闸门犯了错"。"""
    assert _flags("", True, True) == (False, False, False)
    assert _flags("", False, False) == (False, False, False)


def test_the_revised_decision_carries_the_pre_revision_draft() -> None:
    """★★ 草稿必须**回传**，否则"闸门打回的那一版本来对不对"根本无从判起。

    实测：`gate_false_reject` 旧判据在 `fta × react-termination` 上报了 27 条"误伤"，
    而它们**全部**是改好之后的答案 —— 分不出立功还是误伤，就是因为原文丢了。
    """
    inner, gate = _SpyInner(["answer"]), _SpyGate(["revise", "deliver"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]

    assert d.gate == "revise"            # 第一次裁决
    assert d.draft == "done"             # ★ 打回之前那一版
    assert d.answer == "degraded(overclaim:why)"  # 交出去的是撤回后的
    assert d.draft != d.answer


def test_a_clean_delivery_carries_no_draft() -> None:
    """闸门没 revise 过 ⇒ 没有"改之前那一版"可谈，`draft` 必须是空。

    空和"草稿为空字符串"要分得开：前者是"不该有"，后者是"真有一个空草稿"。
    """
    inner, gate = _SpyInner(["answer"]), _SpyGate(["deliver"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]
    assert d.gate == "deliver"
    assert d.draft == ""


def test_a_blocked_gate_also_carries_the_draft() -> None:
    """★★ 闸门说 `blocked` 时**同样**要把打回的那一版带回来。

    没有它，那 27 次弃权在账上只有"闸门拒绝了"，读不出是**保护**（草稿在编）
    还是**误杀**（草稿本来就诚实）—— 一个说明闸门有用，一个说明闸门有害。
    """
    inner, gate = _SpyInner(["answer"]), _SpyGate(["blocked"])
    ctl = TerminationOnlyController(inner=inner, gate=gate)  # type: ignore[arg-type]
    d = ctl.decide(None, _view())  # type: ignore[arg-type]
    assert d.kind == "ask"
    assert d.gate == "blocked"
    assert d.draft == "done", "被拒绝的那一版要留下"


def test_the_draft_is_measured_for_both_verdicts_that_push_back() -> None:
    """`_draft_was_correct` 只在 `revise` / `blocked` 上有意义 —— 别的状态是**没测**。"""
    import inspect

    from experiments.core.runner import _draft_was_correct

    src = inspect.getsource(_draft_was_correct)
    assert '"revise"' in src and '"blocked"' in src
    assert 'outcome.gate != "revise"' not in src, "旧判据只认 revise，blocked 那批读不出来"


def test_agent_outcome_carries_the_verdict_by_default_as_unset() -> None:
    """默认 `""` = 这一臂没有闸门 —— **不是**"闸门说 deliver"。"""
    assert AgentOutcome().gate == ""
    assert AgentOutcome().draft == ""


# ═══════════════════════════════════════════════════════════
# ③ 弃权 ≠ 崩溃 —— 三种"没交出答案"必须分得开
# ═══════════════════════════════════════════════════════════

def test_abstention_is_not_a_harness_crash() -> None:
    """★★ 实测（`fta × react-termination`，n=100）：30 条非正确答案里 28 条是
    **闸门弃权**、2 条是真 `TimeoutError`，而它们原来同属 `agent_error`。

    ⇒ 看表的人会把 28 次"闸门拒绝交付"读成 28 次崩溃。本项目的规矩是弃权要单独计。
    """
    from experiments.core.runner import _no_answer_class

    # 闸门说 blocked → 退回弃答：这是**闸门**在弃权
    assert _no_answer_class(AgentOutcome(escalated=True, gate="blocked",
                                         error="该问人：")) == "gate_blocked"
    # 模型自己要求问人 / 步数用完：这是 **agent** 在弃权
    assert _no_answer_class(AgentOutcome(escalated=True, error="该问人：")) == "no_answer"
    # 真异常：没有 escalated
    assert _no_answer_class(AgentOutcome(error="TimeoutError: timed out")) == "agent_error"


def test_judgment_shape_is_unchanged() -> None:
    """顺手钉一下：那两个指标只读 `judgment.correct`，不依赖任何 failure_class。"""
    assert Judgment(correct=True).failure_class is None
