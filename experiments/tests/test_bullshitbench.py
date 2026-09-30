"""BullshitBench + DRACO —— 钉住**成对**这件事，以及那条重复实现的对应关系。

★ 这个文件最值钱的两条：

  `test_the_pair_defeats_the_degenerate_solvers`
      一个「一律质疑」或「一律照答」的 agent，在**单独一个**数据集上都能拿满分。
      只有**成对**跑，它们才会同时在一个上满分、在另一个上零分。
      这条测试就是"为什么不能只接一个"的可执行版本。

  `test_python_detector_matches_the_frozen_probes`
      Python 侧判据是 TS 侧 `PREMISE_PATTERNS` 的镜子（语言边界造成的重复）。
      两边各有一条测试读**同一份** `probe_samples.json` —— 任何一边漂了就变红。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.benchmark.bullshitbench import (  # noqa: E402
    PAIR,
    BullshitBench,
    Draco,
    load_probe_samples,
)
from experiments.benchmark.bullshitbench.premise import (  # noqa: E402
    admits_own_limit,
    challenges_premise,
)
from experiments.core.types import Trajectory  # noqa: E402

_HAS_DATA = (BullshitBench().dataset_dir / "bullshitbench" / "bullshitbench_tasks.csv").is_file()
needs_data = pytest.mark.skipif(
    not _HAS_DATA, reason="数据没下载（跑 datasets.py --fetch bullshitbench / draco）"
)


def _tasks(b):
    return list(b.tasks(split="all", limit=None, seed=0))


def _ans(b, t, answer: str):
    return b.score(t, Trajectory(task_id=t.task_id, arm="test", final_answer=answer))


# ═══════════════════════════════════════════════════════════
# ① 形状
# ═══════════════════════════════════════════════════════════

@needs_data
def test_both_sides_have_a_hundred_tasks_and_no_tools():
    """★ 无工具是**设计**，不是省事：它把判定从工具循环里彻底剥离。"""
    for B, n in ((BullshitBench, 100), (Draco, 100)):
        b = B()
        assert len(_tasks(b)) == n, b.name
        assert list(b.tools()) == [], f"{b.name} 不该有工具"
        assert b.tool_impls() == {}


@needs_data
def test_bullshitbench_premises_are_all_fake():
    """实测 `is_control` 100/100 = FALSE —— 所以这里**出不了误伤率**，必须写清楚。"""
    b = BullshitBench()
    assert all(t.gold["wants_challenge"] is True for t in _tasks(b))
    assert len({t.gold["technique"] for t in _tasks(b)}) >= 5, "手法太单一就只测了一种伪造"


@needs_data
def test_draco_premises_are_all_valid():
    """★ 另一半：全是合法前提，所以这里**出不了假确认率**。"""
    b = Draco()
    assert all(t.gold["wants_challenge"] is False for t in _tasks(b))


@needs_data
def test_the_pair_is_the_pair():
    assert PAIR == ("bullshitbench", "draco")


# ═══════════════════════════════════════════════════════════
# ② ★ 成对才挡得住退化解 —— 这就是不能只接一个的理由
# ═══════════════════════════════════════════════════════════

_CHALLENGE = "This question contains a false premise and fabricated terminology."
_ANSWER = "本文档支持这个结论：该指标为 412。"


@needs_data
def test_each_degenerate_solver_sweeps_one_side_only():
    """★★ 一律质疑 / 一律照答 —— 各自在一个数据集上满分，在另一个上零分。

        只报 bullshitbench ⇒ 「一律质疑」100%
        只报 draco         ⇒ 「一律照答」100%
    这条测试就是"必须成对"的可执行版本。
    """
    bb, dr = BullshitBench(), Draco()
    bt, dt = _tasks(bb), _tasks(dr)
    for label, answer, sweep_bb in (("一律质疑", _CHALLENGE, True), ("一律照答", _ANSWER, False)):
        bb_ok = sum(_ans(bb, t, answer).correct for t in bt)
        dr_ok = sum(_ans(dr, t, answer).correct for t in dt)
        assert (bb_ok == 100) is sweep_bb, f"{label} 在 bullshitbench 上是 {bb_ok}/100"
        assert (dr_ok == 100) is (not sweep_bb), f"{label} 在 draco 上是 {dr_ok}/100"
        assert not (bb_ok == 100 and dr_ok == 100), f"{label} 同时刷满了两个数据集"


@needs_data
def test_failure_classes_name_the_two_error_kinds():
    """假确认与误伤各有自己的名字 —— 报告里要能分开数。"""
    b, d = BullshitBench(), Draco()
    j = _ans(b, _tasks(b)[0], "The answer is 42.")
    assert j.failure_class == "unsupported_completion", j
    jd = _ans(d, _tasks(d)[0], "The premise here is fabricated, so I will not answer.")
    assert jd.failure_class == "over_abstention", jd


@needs_data
def test_empty_answer_is_no_answer_not_a_verdict():
    b = BullshitBench()
    j = _ans(b, _tasks(b)[0], "   ")
    assert j.failure_class == "no_answer" and not j.correct


# ═══════════════════════════════════════════════════════════
# ③ ★ 镜子不许漂：Python 与 TS 各读同一份探针
# ═══════════════════════════════════════════════════════════

def test_python_detector_matches_the_frozen_probes():
    """★ 探针里的每一条，Python 侧判据都要给出标注的答案。

    TS 侧有一条对称的测试读**同一个文件**（`tests/premise-probe.test.ts`）——
    两份重复实现靠它对齐。任何一边改了模式，对应语言的测试就红。
    """
    for s in load_probe_samples():
        got = challenges_premise(str(s["text"]))
        assert got is s["challenges_premise"], (
            f"探针不符：{s['text'][:60]!r}\n  期望 {s['challenges_premise']}，实得 {got}\n  理由：{s['why']}"
        )


def test_the_two_speech_acts_stay_separate():
    """★「我做不到」不许被当成「你的前提是假的」—— 这条边界是外部数据照出来的。"""
    assert challenges_premise("I cannot determine this from the corpus.") is False
    assert admits_own_limit("I cannot determine this from the corpus.") is True
    assert challenges_premise("This contains a false premise.") is True
    assert admits_own_limit("This contains a false premise.") is False


# ═══════════════════════════════════════════════════════════
# ④ 缺数据要说清怎么拿
# ═══════════════════════════════════════════════════════════

def test_missing_data_points_at_the_fetch_command():
    for B in (BullshitBench, Draco):
        b = B(dataset_dir=Path("/definitely/not/here"))
        with pytest.raises(FileNotFoundError) as e:
            b._rows()
        assert "--fetch" in str(e.value)
        assert b.name in str(e.value)
