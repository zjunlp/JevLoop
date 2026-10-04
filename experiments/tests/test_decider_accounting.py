"""判定后端的账 —— **「这批到底是谁答的」必须可证，不能靠"没看见降级"**。

★ 这个文件最值钱的两条：

  `test_a_batch_event_records_who_answered`
      判定后端是一条**降级链**（先试托管 Jev，挂了退 Mock）。而"降级"以前只在
      内存里报一次：只有"答案不可用"那条路会把 `warnings` 塞进 `note`，
      **正常降级时响应看起来完全正常，日志上不留任何痕迹**。

      实测（2026-10-01）：`fta × react-termination` 跑完 152 批判定，
      `events.jsonl` 里搜「降级」**零命中** —— 而这**不能证明没降级**，
      只证明那个字符串当初没地方可写。**不可证伪的"没发生"**比报了降级还危险：
      它让"我们跑的是真 Jev"变成一个没有证据的说法。

  `test_the_planned_backend_is_recorded_even_if_it_never_answered`
      `meta.json` 的 `decider` 以前**写死成 `id="none"`** —— 带了 Jev 的格子和
      `direct` 在 meta 里长得一模一样。又是一个"信息在手里、没往回传"。
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.benchmark.toy import ToyCapitals  # noqa: E402
from experiments.core.agent import Session  # noqa: E402
from experiments.core.deciding import (  # noqa: E402
    PINNED_JEV_MODEL,
    FallbackClient,
    HttpJevClient,
    MockClient,
)
from experiments.core.models import CallableModel  # noqa: E402
from experiments.core.tools import ToolExecutor  # noqa: E402


def _session() -> Session:
    bench = ToyCapitals()
    tools = list(bench.tools())
    task = next(iter(bench.tasks(split="test", limit=1, seed=0)))
    return Session(
        run_id="t", task=task, arm="x", tools=tools,
        executor=ToolExecutor(tools, bench.tool_impls()),
        model=CallableModel(lambda m: "Lima", model_id="stub"),
        max_steps=2, temperature=0.0, max_tokens=64,
    )


def _one_batch(s: Session, *, provider: str, degraded: bool, warnings: list[str]):
    s.note_batch(provider=provider, degraded=degraded, warnings=warnings)
    s.record_decision(step=0, node="canDeliver", answer="deliver",
                      confidence=0.9, correct=True, latency_ms=1.0, batch=0)
    s.finish_events()
    return [e for e in s.events if e.type == "decision_batch"][-1]


# ═══════════════════════════════════════════════════════════
# ① 谁答的，进事件流
# ═══════════════════════════════════════════════════════════


def test_a_batch_event_records_who_answered() -> None:
    """★ 一批判定必须带着"谁答的"落盘 —— 否则事后查不出这批是不是 Mock 答的。"""
    s = _session()
    ev = _one_batch(s, provider="http:" + PINNED_JEV_MODEL, degraded=False, warnings=[])
    assert ev.provider == "http:" + PINNED_JEV_MODEL
    assert ev.degraded is False
    assert ev.warnings == []


def test_a_degradation_is_recorded_and_counted() -> None:
    """★★ 降级了就必须看得出来 —— `provider` 保留**原计划**那个，
    所以只有 `degraded` 这个布尔认得出降级发生过（照 TS 侧 `provider-fallback.ts`）。"""
    s = _session()
    ev = _one_batch(
        s, provider="http:" + PINNED_JEV_MODEL, degraded=True,
        warnings=["降级：原计划用 http:jev-1.13.0，实际用 mock"],
    )
    assert ev.provider == "http:" + PINNED_JEV_MODEL, "provider 记的是**原计划**那个"
    assert ev.degraded is True
    assert "降级" in ev.warnings[0]
    # ★ 而且要累计得出来 —— 跑完要大声报，不能只在 event 里躺着
    assert s.decider_degradations == 1
    assert s.decider_providers == ["http:" + PINNED_JEV_MODEL]


def test_batch_state_does_not_leak_into_the_next_batch() -> None:
    """一批降过级，不代表下一批也降过 —— 状态必须逐批清零。"""
    s = _session()
    _one_batch(s, provider="mock", degraded=True, warnings=["降级"])
    s.note_batch(provider="mock", degraded=False, warnings=[])
    s.record_decision(step=1, node="canDeliver", answer="deliver",
                      confidence=0.9, correct=True, latency_ms=1.0, batch=1)
    s.finish_events()  # 第二批也要封口，否则它还没进事件流
    evs = [e for e in s.events if e.type == "decision_batch"]
    assert evs[-2].degraded is True
    assert evs[-1].degraded is False, "上一批的降级不该跟过来"
    assert evs[-1].warnings == []


# ═══════════════════════════════════════════════════════════
# ② meta 里的 decider 记的是**计划**那个
# ═══════════════════════════════════════════════════════════


def test_the_planned_backend_is_recorded_even_if_it_never_answered() -> None:
    """★ `meta.json` 的 `decider` 必须是真的那个 —— 以前写死成 `id="none"`，
    于是带 Jev 的格子和 `direct` 在 meta 里长得一模一样。"""
    from experiments.scripts.run import decider_ref

    ref = decider_ref(FallbackClient([
        HttpJevClient("https://api.typesafe.ai", "k"),
        MockClient(),
    ]))
    assert ref is not None
    assert ref.id == f"http:{PINNED_JEV_MODEL}"   # ★ 降级链的**第一个**
    assert ref.version == PINNED_JEV_MODEL        # ★ 版本要钉住
    assert "mock" not in ref.id, "不该记实际答话的那个（那会让降级在 meta 里隐形）"


def test_no_decider_means_none_not_a_guess() -> None:
    """没有判定后端的臂（`direct` / `react`）—— 记 `None`，不猜。"""
    from experiments.scripts.run import decider_ref

    assert decider_ref(None) is None


def test_a_single_client_still_reports_its_own_identity() -> None:
    """不套降级链时也要认得出自己。"""
    from experiments.scripts.run import decider_ref

    ref = decider_ref(HttpJevClient("https://api.typesafe.ai/", "k"))
    assert ref is not None and ref.version == PINNED_JEV_MODEL
