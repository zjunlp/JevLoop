"""★★★ **`read_doc` 的候选集是「检索报出来的那几篇」，不是整个语料。**

为什么单独一个文件钉住它：这条曾经错得很安静，而且**错的方向看起来更好**。

原来 `read_doc` 的候选是整个语料 40 篇，于是控制器每步问判官
「这 40 篇里该读哪一篇」。实测（2026-10-04，20 题）：

    react-typed（一候选一题）        8/20
    react-typed-singlechoice（N 选 1） 15/20、12/20   ← **看起来更好**

而那个"更好"是假象：17/20 题的候选数超过 `MAX_OPTIONS`，走了
`accept_below_bar` 兜底 —— 也就是**明知不够果断，还是拿分布的第一个**。
它赢在一张 40 选 1 的彩票上。同一批账里，40 个候选题**没有一个过 0.5 的线**
（最高 0.26），说明判官并没有在挑，它是在猜。

按实体名检索**只命中 1~3 篇**（150 题里 1 篇 18、2 篇 18、3 篇 114），
所以那道题里 37~39 个候选是**已知不相关的**。修法是环境把候选源声明清楚
（`Tool.live_candidates`，和 ALFWorld 同一个机制）—— 不动 benchmark 的判分。
"""
from __future__ import annotations

import pytest

from experiments.benchmark.ternary_judge.ternary_judge import TernaryJudge


def _bench() -> TernaryJudge:
    return TernaryJudge()


def _tools(b: TernaryJudge) -> dict:
    return {t.name: t for t in b.tools()}


def test_read_doc_offers_only_the_documents_the_search_reported() -> None:
    """★★★ 检索之后，候选集就是检索结果里出现的那些 `[dNNN]`。"""
    b = _bench()
    tasks = list(b.tasks(split="test", limit=1, seed=20261003))
    b.on_task(tasks[0])
    tools = _tools(b)
    impls = b.tool_impls()

    before = list(tools["read_doc"].live_candidates())
    assert len(before) == 40, (
        f"还没检索时应当回退到整个语料（40 篇），实际 {len(before)} 篇 —— "
        "这条回退是**故意的**：那时判官确实没有别的信息，"
        "而 40 这个数本身就是「这是一次回退」的信号"
    )

    out = impls["search"](query="Aldermont Systems")
    assert out.strip(), "检索没报出任何东西，这条测试就没在测候选源"
    reported = {line.split("]")[0].lstrip("[") for line in out.splitlines()}
    after = list(tools["read_doc"].live_candidates())

    assert set(after) == reported, (
        "候选集不是检索报出来的那几篇 —— 而「该读哪一篇」这个问题的"
        f"可答性全靠它。检索报了 {sorted(reported)}，候选给了 {sorted(after)}"
    )
    assert len(after) < len(before), "候选集没有收窄，等于没生效"
    assert set(after) < set(before), "候选集里出现了检索没报过的文档"


def test_the_candidate_set_does_not_leak_across_tasks() -> None:
    """★★ 实例状态跨题复用，所以 `on_task` 必须把它清掉。

    不清的话第 2 题的候选集里带着第 1 题检索到的 doc_id。串味**不会报错**,
    只会让候选集看起来"更宽" —— 而更宽正是这条测试要防的那个病。
    """
    b = _bench()
    tasks = list(b.tasks(split="test", limit=2, seed=20261003))
    tools = _tools(b)

    b.on_task(tasks[0])
    b.tool_impls()["search"](query="Aldermont Systems")
    assert b._seen_docs, "第一题没检索到东西，这条测试就没在测串味"

    b.on_task(tasks[1])
    assert not b._seen_docs, "换题之后还留着上一题的检索结果"
    assert len(tools["read_doc"].live_candidates()) == 40, (
        "换题之后候选集应当回到「还没检索」那一档"
    )


def test_the_benchmark_scoring_is_untouched_by_the_candidate_source() -> None:
    """★ 候选源是**动作空间**的声明，不是判分的改动。

    这条是那个硬约束的守门人：「评估一定要严格按 benchmark 自己的评估逻辑来」。
    声明的候选集不该让任何一道题的判分变样。
    """
    b = _bench()
    tasks = list(b.tasks(split="test", limit=3, seed=20261003))
    answer = "Aldermont Systems was founded in 1998."
    b.on_task(tasks[0])
    b.tool_impls()["search"](query="Aldermont Systems")
    assert b.check(tasks[0], answer) == b._judge(tasks[0], answer, b.headline).correct
