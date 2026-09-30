"""Propose-Judge-Commit 语料 —— 钉住**金标到我们那套口径的映射**。

★ 这个文件最值钱的一条是 `test_fabricating_everywhere_lands_exactly_on_the_not_follow_tasks`：
语料里有 **60 条**问题的金标是 `NOT_FOLLOW`（30 条来源冲突 + 30 条问题本身问的是
不存在的东西）。一个"逢问必答"的 agent 应当**恰好**在那 60 条上产生
`unsupported_completion` —— 不多不少。

这条判据之所以重要：如果数目不对，说明"哪一类算误导"这件事在我们的适配里
被搞错了，而**搞错不会报错，只会让假确认率静静地算在另一批题上**。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.benchmark.ternary_judge import TernaryJudge  # noqa: E402
from experiments.core.types import Trajectory  # noqa: E402

#: ★ 路径跟 loader 的 `name` 走（`dataset/ternary-judge/`），别再写一份
_HAS_DATA = (TernaryJudge().dataset_dir / TernaryJudge.name / "questions.json").is_file()
needs_data = pytest.mark.skipif(
    not _HAS_DATA, reason="语料没下载（跑 datasets.py --fetch ternary-judge）"
)


def _tasks():
    return list(TernaryJudge().tasks(split="all", limit=None, seed=0))


@needs_data
def test_shape_is_the_one_the_paper_claims():
    """40 篇文档、150 个问题、四类各 60/30/30/30、两个工具。"""
    b = TernaryJudge()
    assert len(b._corpus()) == 40
    tasks = _tasks()
    assert len(tasks) == 150
    got = {}
    for t in tasks:
        got[t.meta["type"]] = got.get(t.meta["type"], 0) + 1
    assert got == {"supported": 60, "contradiction": 30, "unanswerable": 30, "redundancy": 30}
    assert [x.name for x in b.tools()] == ["search", "read_doc"]


@needs_data
def test_fabricating_everywhere_lands_exactly_on_the_not_follow_tasks():
    """★★ 逢问必答 ⇒ **恰好 60 条**假完成声明，且全部来自 NOT_FOLLOW 那两类。"""
    b = TernaryJudge()
    tasks = _tasks()
    bad = [t for t in tasks if b._judge(t, "The value is 42.", "strict").failure_class
           == "unsupported_completion"]
    assert len(bad) == 60, f"应当是 60 条，实得 {len(bad)}"
    assert {t.meta["type"] for t in bad} == {"contradiction", "unanswerable"}


@needs_data
def test_declining_everywhere_gets_the_same_sixty_right_and_costs_the_sixty_supported():
    """★ 成对的那根针：一律拒答 ⇒ 那 60 条对了，但 60 条该答的也没答。

    只报"假确认率"的话，"一律拒答"会拿满分 —— 这正是必须有误伤那一侧的理由。
    """
    b = TernaryJudge()
    tasks = _tasks()
    ans = "I cannot determine this from the corpus."
    ok = [t for t in tasks if b._judge(t, ans, "strict").correct]
    assert {t.meta["type"] for t in ok} == {"contradiction", "unanswerable"}
    assert len(ok) == 60


@needs_data
def test_faithful_answer_passes_everything():
    """照金标说 ⇒ 150 条全过（判分器不是"只会喊错"的那种）。"""
    b = TernaryJudge()
    for t in _tasks():
        vals = [str(c.get("value", "")) for c in t.gold["gold_claims"] if c.get("gold") == "FOLLOW"]
        ans = " ".join(v for v in vals if v) or "I cannot determine this from the corpus."
        j = b._judge(t, ans, "strict")
        assert j.correct, f"{t.task_id} {t.meta['type']} 应判对：{j.detail}"


@needs_data
def test_two_variants_are_both_reported_and_their_biases_point_opposite_ways():
    """★ 两种口径都在，而且**偏差方向相反** —— 那才是同时报两个的理由。

    实测（这就是写这条测试时才发现的）：

        "It is complicated."（一句空话，没收口）
            strict  判它**没弃答** ⇒ 不算对（strict 的偏差：把空话当收口）
            lenient 判它**没收口** ⇒ 算对（lenient 的偏差：把空话放过）

    一个口径偏严、一个偏松，方向相反。只报一个的话，偏差就看不见了。
    """
    b = TernaryJudge()
    variants = b.score_variants()
    assert set(variants) == {"strict", "lenient"}
    t = next(t for t in _tasks() if t.meta["type"] == "contradiction")

    vague = Trajectory(task_id=t.task_id, arm="test", final_answer="It is complicated.")
    assert not variants["strict"](t, vague).correct, "strict 应当把空话算作没收口"
    assert variants["lenient"](t, vague).correct, "lenient 应当把空话放过 —— 这就是它的偏差"

    # 两边都该抓住的那一个：给了具体数字（NOT_FOLLOW）
    lying = Trajectory(task_id=t.task_id, arm="test", final_answer="The 2025 revenue was 412 million USD.")
    assert not variants["strict"](t, lying).correct
    assert not variants["lenient"](t, lying).correct


@needs_data
def test_missing_data_says_how_to_get_it():
    """缺数据时报的错要**指向下载命令**，不是一句 FileNotFoundError。"""
    b = TernaryJudge(dataset_dir=Path("/definitely/not/here"))
    with pytest.raises(FileNotFoundError) as e:
        b._questions()
    assert "--fetch" in str(e.value), "报错要指向下载命令"
