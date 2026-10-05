"""Two truncation units stay separately observable, and the default is no cap.

2026-10-05：全局逐字段上限和 20 条候选上限都删掉了（实测窗口 131,072 字符，
我们最大请求只有 5,153，用掉 4%）。**机制不删** —— 显式给了预算的地方
照样要同时报出「数量」和「字符」两种损失，不许互相覆盖。
"""
from experiments.core.frame import (
    MAX_LISTED_CANDIDATES,
    AgentCtx,
    FrameField,
    FrameSpec,
    NODE_FRAMES,
    compile_frame,
)


def test_count_and_character_truncation_do_not_overwrite_each_other(monkeypatch):
    # 显式给 20 条 / 40 字符：两种截断同时发生，两种信息都要留住。
    import experiments.core.frame as F

    monkeypatch.setattr(F, "MAX_LISTED_CANDIDATES", 20)
    spec = FrameSpec("t", (FrameField("history", 40, "history", clip="head"),))
    values = ["candidate-" + str(i) + ("x" * 30) for i in range(25)]
    frame = compile_frame(spec, AgentCtx(history=values))
    assert frame.count_truncations["history"] == (25, 20)
    assert frame.truncations["history"][0] > frame.truncations["history"][1]
    rendered = frame.render()
    assert "items 25→20" in rendered
    assert "chars" in rendered


def test_no_limits_by_default_means_no_truncation_notice():
    """全局上限删掉之后，一个正常大小的帧**不该**再冒出截断提示。"""
    assert MAX_LISTED_CANDIDATES is None
    spec = NODE_FRAMES["needsTool"]
    assert all(f.budget is None for f in spec.fields), "逐字段预算应当全部删掉"
    ctx = AgentCtx(task="t", last_result="y" * 20000)
    ctx.history = tuple("h" * 3000 for _ in range(40))
    frame = compile_frame(spec, ctx)
    assert frame.truncations == {}
    assert frame.count_truncations == {}
    assert "truncated" not in frame.render()
    assert "y" * 20000 in frame.render(), "20000 字的观察应当整条进帧"
    assert "h" * 3000 in frame.render(), "每条历史也应当完整"
