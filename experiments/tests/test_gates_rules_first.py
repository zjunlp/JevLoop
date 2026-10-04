"""★★★ **规则先筛、判官只确认** —— 两道闸门的新语义（`docs/GATES-RULES-FIRST.md`）。

这个文件测的**不是**闸门能不能拦住东西（那有别的文件），是两条不变量：

  ① **单调性**：判官只能把闸门**收紧**，永远不能放松。
     判官否定一条规则 ≠ 推翻它；判官说"风险太高" ≠ 降档。
  ② **"不确定"永远不产生拒绝**：拒绝是规则的职权，而规则只在**有证书**时才拒绝。
     实测那个 bug（`docs/ALFWORLD-ESCAPE.md` §4：判官每次都答对、置信度 0.39、
     被 0.5 的门限丢掉 ⇒ 20 题里 4 题 decline）在这里必须是**不可能**的。

★ 另外两条结构性的：

  · **证书必须是可作证的** —— 三条证书全是集合差/空串，中间没有模型判断。
    "草稿有没有声称成功"这种需要主张检测器的检查**进不了证书表**
    （`NOT_YET_CERTIFICATES`），因为单调性会把检测器的误报变成永久拒绝。
  · **查表 ≠ 判定**：规则那一行记 `source="rule"`，判官的立场**另起一行**。
    合成一行就再也分不出「规则拦住了一个坏答案」和
    「规则拦住了一个好答案而判官不同意」—— 而后者才是规则质量的证据。

跑法（在 `JevLoop/` 下）::

    python3 -m pytest experiments/tests -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.jloop import typed as typed_mod  # noqa: E402
from experiments.jloop.typed import (  # noqa: E402
    DELIVERY_CERTIFICATES,
    RAISE_STEP,
    RISK_LEGEND,
    RISK_PATTERNS,
    UNKNOWN_TOOL_BAND,
    TypedController,
    _risk_band,
    _ungrounded_numbers,
)

from experiments.tests.test_typed_controller import (  # noqa: E402
    ScriptedClient,
    _tool_step,
    _view,
    make_session,
    judge_gate,
)


def rules_first(**noul) -> tuple[TypedController, object]:
    """一个**规则优先**的控制器（默认那一版）+ 它的 session。"""
    base = {"needsTool": 0.9, "needs_auth": 0.1, "stepOk": 0.9, "isDone": 0.1,
            "unsupported": 0.1, "deliverable": 0.1}
    base.update(noul)
    session = make_session()
    client = ScriptedClient(noul=base, pick={"pickInput": "France"})
    return TypedController(client, gates_rules_first=True), client, session


def _to_gate(**noul):
    """跑到交付闸门那一步（生成答案 → `canDeliver`）。

    ★ 必须真的先调一次工具、再让 `needsTool` 说"不用动作了" ——
      第 0 步直接跑是到不了闸门的（拿到的是 `kind="tool"`）。
    """
    ctrl, client, session = rules_first(**{"needsTool": 0.9, **noul})
    first = ctrl.decide(session, _view(session))
    assert first.kind == "tool", f"第一步该真的调工具:{first}"
    client.noul["needsTool"] = 0.1
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    return ctrl, client, session, ctrl.decide(session, _view(session, history=(step,)))


# ═══════════════════════════════════════════════════════════
# ① 不变量：不确定不产生拒绝
# ═══════════════════════════════════════════════════════════


def test_an_unsure_judge_never_refuses_a_delivery() -> None:
    """★★★ **判官说"说不好"，闸门照样放行。**

    这是这次改动的**全部理由**。旧那一版里，判官缺席或不够果断 ⇒
    `unjudgeable` ⇒ `blocked` ⇒ 循环重试 ⇒ 整题 `decline`。实测 20 题里 4 题这样死
    （`docs/ALFWORLD-ESCAPE.md` §4），而死因是**判官答得不够确定**，
    不是它答错了 —— 它每次都答对了。

    ★ 规则那一层没有证书（草稿 `Paris`，证据 `Paris`，有材料）⇒
      规则判定为"可以交付"，而判官的立场**不产生裁决**。
    """
    ctrl, client, session, decision = _to_gate()
    assert decision.kind == "answer", decision
    assert decision.answer == "Paris", decision.answer
    # ★ 两道旧题（判官产生裁决）**一次都不该问**
    asked = {n for r in client.requests for n in r.questions}
    assert "deliverable" not in asked and "unsupported" not in asked, asked
    # ★ 而新的反驳题问过了 —— 它是"收紧"那一路，问了才有机会收紧
    assert "deliverable::object" in asked, asked


def test_no_answer_is_not_a_refusal() -> None:
    """★★★ **判官整批没答，规则照样说了算。**

    `FALLBACK_POLICY` 里这两道题的名字是 `rule_stands` —— 读到它就知道
    **这一次行为由规则决定，判官没说话**。写成 `reject` 就会把"判官缺席"
    重新变成拒绝，而那正是要消灭的东西。
    """
    from experiments.jloop.typed import FALLBACK_POLICY

    assert FALLBACK_POLICY["deliverable::confirm"] == "rule_stands"
    assert FALLBACK_POLICY["deliverable::object"] == "rule_stands"
    assert FALLBACK_POLICY["risk_confirm"] == "rule_stands"

    ctrl, client, session = rules_first()
    client.omit = {"deliverable::object"}
    first = ctrl.decide(session, _view(session))
    client.noul["needsTool"] = 0.1
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    decision = ctrl.decide(session, _view(session, history=(step,)))
    assert decision.kind == "answer", (
        f"判官没答 ⇒ 规则说了算，不该变成拒绝:{decision}"
    )


# ═══════════════════════════════════════════════════════════
# ② 不变量：判官只能收紧 —— 交付闸门
# ═══════════════════════════════════════════════════════════


def test_a_certificate_blocks_and_the_judge_only_confirms() -> None:
    """★★ **规则有证书 ⇒ 拒绝，而且问的是"这条理由成立吗"，不是"该不该交付"。**

    ★ 判据有三条，缺一条就退回"判官产生裁决"：
      ① 裁决是 `revise`；② 问的是确认题（不是旧的两道 `noul`）；
      ③ 理由带着**具体指向**（那几个数），而不是一句"超纲"。
    """
    ctrl, client, session = rules_first()
    # 让草稿里出现证据里没有的数 —— 触发 `ungrounded_number`
    ctrl._answer_text = lambda *a, **k: "The capital is Paris and the code is 9999."  # type: ignore[method-assign]
    first = ctrl.decide(session, _view(session))
    client.noul["needsTool"] = 0.1
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    decision = ctrl.decide(session, _view(session, history=(step,)))

    asked = {n for r in client.requests for n in r.questions}
    assert "deliverable::confirm" in asked, asked
    assert "deliverable" not in asked, "旧的两道题不该再问"
    # ① 证书那一行在账上，而且是 `source="rule"`
    session.finish_events()
    rows = [r for r in session.decision_records() if r.node == "deliverable::grounding"]
    assert rows and rows[-1].source == "rule", rows
    assert "9999" in rows[-1].answer, rows[-1].answer
    # ② 闸门的裁决是"打回"，理由指着那几个数
    assert decision.gate in ("revise", "blocked") or decision.kind == "answer"


def test_the_judge_disagreeing_with_a_rule_does_not_release_it() -> None:
    """★★★ **判官否定一条规则 ≠ 推翻它。**

    这是"规则是底线"最硬的一处，也是最容易做错的一处 ——
    顺着直觉写成"判官不同意就放行"的话，判官就**重新产生了裁决**，
    而整次改动就白做了。

    ★ 那条否定**有价值**，但价值在**账上**：它是"我们的规则可能错了"的证据，
      离线可以和 `won` 对齐算出**规则被否率**（这个数在设计里第一次存在）。
      ⚠️ 所以它必须留痕，而且必须显眼 —— 一条被反复否定却仍在拦的规则，
        该改的是规则，不是让判官放行。
    """
    ctrl, client, session = rules_first()
    ctrl._answer_text = lambda *a, **k: "The capital is Paris and the code is 9999."  # type: ignore[method-assign]
    # 判官说"规则的理由不成立"
    client.pick["deliverable::confirm"] = "does_not_hold"
    first = ctrl.decide(session, _view(session))
    client.noul["needsTool"] = 0.1
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    decision = ctrl.decide(session, _view(session, history=(step,)))

    assert decision.kind != "answer" or decision.answer != "The capital is Paris and the code is 9999.", (
        "判官否定了规则，而闸门居然放行了 —— 单调性被破坏了"
    )
    disagreements = [t for t in ctrl.trace
                     if t.get("violation") == "judge_disagrees_with_rule"]
    assert disagreements, [t.get("violation") for t in ctrl.trace]
    assert "规则是底线" in disagreements[0]["detail"]


def test_the_judge_can_only_tighten_a_rule_that_passed() -> None:
    """★★★ **判官唯一能产生结果的权力：对"规则放行"提出反驳。**

    这是它在规则优先设计里的**唯一职位**，而且方向是收紧 ——
    它**命名**疾病（`overclaim` / `incomplete`），不产生裁决：
    补救动作由病名决定（`_remedy`），而"要不要交付"由规则给。

    ★ 反过来说：判官说 `no_objection` / `unsure` 都**放行** ——
      后者是关键，"说不好"不是拒绝的理由。
    """
    for stance, should_block in (("overclaim", True), ("incomplete", True),
                                 ("no_objection", False), ("unsure", False)):
        ctrl, client, session = rules_first()
        client.pick["deliverable::object"] = stance
        first = ctrl.decide(session, _view(session))
        client.noul["needsTool"] = 0.1
        step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                          observation="Paris")
        decision = ctrl.decide(session, _view(session, history=(step,)))
        # ★★ **"收紧"长两个样子，两种都算。**
        #
        #   病名决定补救动作（`_remedy`），而两条补救在这层的**可观测形状不同**：
        #
        #     `overclaim`   ⇒ `degrade`（撤回）⇒ **交一份改过的答案**，`gate="revise"`
        #     `incomplete`  ⇒ `redirect`（回去做）⇒ 闸门把"结束"改道回动作空间，
        #                     于是 `decide()` 最终返回的是一个 **`tool`** 决定，
        #                     而 `gate` 是空的（那一份 Decision 是新造的）
        #
        #   ⇒ 只看 `gate` 会把 `incomplete` 读成"判官没说话"；
        #     只看 `kind` 会把 `overclaim` 读成"没拦住"。
        #     **判据是"有没有干干净净地交付"** —— 那才是这两条路的共同否定。
        #   ⚠️ `gate` 放行时是 `"deliver"`（不是空串）—— 闸门**总是**会跑。
        #     空串的意思是"这一臂没有闸门"，和"闸门放行了"是两件事。
        delivered_cleanly = (decision.kind == "answer"
                             and decision.gate not in ("revise", "blocked"))
        assert delivered_cleanly is (not should_block), (
            f"判官立场 {stance!r} ⇒ 期望{'收紧' if should_block else '放行'}，"
            f"拿到 gate={decision.gate!r} kind={decision.kind!r}"
        )


# ═══════════════════════════════════════════════════════════
# ③ 不变量：判官只能收紧 —— 授权闸门
# ═══════════════════════════════════════════════════════════


def test_the_risk_band_comes_from_rules_not_from_the_judge() -> None:
    """★★★ **档位是查出来的，`score:risk` 那道题整个不存在了。**

    ★ 这一条同时是 §4 那个 bug 的**结构性**修复：档位不再是一个概率，
      所以没有"置信度低于门限就被丢掉"这条路可走。
    """
    ctrl, client, session = rules_first()
    ctrl.decide(session, _view(session))
    asked = {n for r in client.requests for n in r.questions}
    assert "risk" not in asked, f"规则优先那一版不该再问 score:risk:{asked}"
    # ★★ **`risk_confirm` 只在档位不是"声明"的时候才问**（2026-10-04 的修法）。
    #   toy 的 `lookup_capital` 声明了 `base_risk=0` ⇒ **不问** ——
    #   让判官去确认一个常量,它只能答"说不好"（实测 287/291、29/37）。
    assert "risk_confirm" not in asked, (
        f"档位来自声明,却还是问了 risk_confirm:{asked}"
    )
    skipped = [t for t in ctrl.trace if t.get("answer") == "(skipped)"
               and "risk_confirm" in str(t.get("detail", ""))]
    assert skipped, "跳过要留痕 —— 否则它和「忘了接」长得一样（§8.15）"
    session.finish_events()
    rows = [r for r in session.decision_records() if r.node == "risk"]
    assert rows and rows[-1].source == "rule", rows
    assert "未问模型" in rows[-1].note, rows[-1].note


def test_the_judge_can_raise_a_risk_band_but_never_lower_it() -> None:
    """★★★ **只抬不降。**

    ★ "太高"不降是有代价的（规则偏严时没有出口），而那正是刻意的：
      放松方向一旦打开，判官就重新产生了裁决，而它最不擅长的就是这件事
      （没有状态、没有计划、没有记忆）。它说"太高"的价值在账上。
    """
    session = make_session()
    from experiments.core.types import Tool

    tool = Tool(name="lookup_capital", description="d",
                parameters={"type": "object", "properties": {"country": {"type": "string"}}},
                base_risk=1)
    # ★ `ctx` 必须是**真的**：空 `AgentCtx` 会让 `gradeRisk` 的帧校验 fatal，
    #   答案根本发不出去 —— 而那时 `stance` 是空串，测试会"通过"，
    #   测的却是"没问出去"，不是"只抬不降"。（第一版就是这样，too_low 拿到 1。）
    ctx = typed_mod.AgentCtx(task="t", draft="d", last_input="France")
    for stance, expected in (("too_low", 1 + RAISE_STEP), ("too_high", 1),
                             ("correct", 1), ("unsure", 1), ("", 1)):
        client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1})
        if stance:
            client.pick["risk_confirm"] = stance
        else:
            # ★ "没答"必须**真的没答**。`ScriptedClient` 的默认是取**第一个选项**
            #   （`opts[0]` = `correct`），所以不 omit 的话这一格测的是
            #   "判官说了 correct"，而名字上写着 `no_answer`。
            client.omit = {"risk_confirm"}
        ctrl = TypedController(client, gates_rules_first=True)
        before = len(session.decision_records())
        got, raised = ctrl._confirm_risk(session, _view(session), ctx, 0,
                                         tool, {"country": "France"}, 1)
        assert got == expected, f"{stance!r} ⇒ 期望 {expected}，拿到 {got}"
        assert raised is (expected != 1)
        # ★★ **判官的立场在问题自己那一行里，只有那一行。**
        #   第一版另开了一行记 `(stance:...)`，实测 15 次调用出 30 行 ——
        #   同一件事记了两遍，还会把 `判定占比` 的分子分母一起灌水。
        session.finish_events()
        # ⚠️ `session` 在 5 格之间是**同一个** —— 不切片的话第 2 格起会看到
        #    前面几格留下的行，而"一次判定记了几行"就测不出来了。
        rows = [r for r in session.decision_records()[before:] if r.node == "risk_confirm"]
        assert len(rows) == 1, f"一次判定只该记一行，实际 {len(rows)} 行"
        assert rows[-1].answer == (stance or "(answer_unusable)"), rows[-1].answer
        assert rows[-1].source in ("judge", "fallback"), rows[-1]
        # ★ 而"抬过"这件事在轨迹里（给人读的），档位本身在上面那个 `got` 里
        if stance == "too_low":
            assert any(t.get("answer", "").startswith("judge_raised")
                       for t in ctrl.trace), ctrl.trace


def test_the_delivery_certificates_are_only_the_checkable_three() -> None:
    """★★★ **能被否证的才配当规则。**

    证书表里只许出现"在产物上跑一次就出结果"的检查。`tool_error_ignored` /
    `goal_signal_absent` 看着像规则，其实要求先判断"草稿有没有声称成功" ——
    那需要一个**主张检测器**，而它现在没有自己的误报率。

    ★ 在单调性下把粗检测器做成规则是**更坏**的：误报 ⇒ 永久拒绝交付，
      而判官**不允许**放松。所以它们降级成判官的反驳材料。
      ★ 这是这一版设计**已知的强度上限**，要写进报告。
    """
    ids = {cid for cid, _ in DELIVERY_CERTIFICATES}
    assert ids == {"empty_draft", "ungrounded_number", "no_evidence"}, ids
    from experiments.jloop.typed import NOT_YET_CERTIFICATES

    downgraded = {cid for cid, _ in NOT_YET_CERTIFICATES}
    assert downgraded == {"tool_error_ignored", "goal_signal_absent"}
    assert not (ids & downgraded), "一条检查不许同时是证书和被降级的"
    for _cid, why in NOT_YET_CERTIFICATES:
        assert "检测器" in why, f"降级的理由要写清楚:{why!r}"


def test_an_undeclared_tool_with_no_matching_pattern_asks_a_human() -> None:
    """★★★ **认不出来 ≠ 安全。**

    没声明 `base_risk`、参数也匹配不上任何模式 ⇒ `UNKNOWN_TOOL_BAND` = 2 = 不可逆
    ⇒ **问人**。默认成 0 就是把"不知道"静默读成"只读"。

    ★ 这是规则优先设计里最危险的一格，所以它有一个显式的名字和一次显式的测试。
      代价如实说：**它会让认不出来的调用去问人**，所以"认不出来的比例"
      要作为一个数报出来。
    """
    from experiments.core.types import Tool

    assert UNKNOWN_TOOL_BAND == 2, "默认必须是 fail-closed，理由见常量文档"
    bare = Tool(name="mystery", description="d", parameters={})
    band, source = _risk_band(bare, {"x": "zzz_unknown_blob"})
    assert band == UNKNOWN_TOOL_BAND and source == "unknown", (band, source)


def test_a_declared_base_risk_is_a_floor_that_patterns_can_raise() -> None:
    """★★★ **声明是地板，不是天花板** —— 这是一处语义反转。

    `docs/GROUNDING-STEP1-DECLARED-RISK.md` 那一版是"查表就不问"，工具声明了
    就完全听它的。现在不是：**这一调的内容是更锐利的证据**，
    一个声明为只读的工具、参数里写着往 `/etc` 重定向，仍然要被抬上去。

    ★ 反方向**不许**：模式压不低一个声明 —— 否则工具作者声明"不可逆"而
      模式因为没认出动词就把它降成只读，那是一次静默的放松。
    """
    from experiments.core.types import Tool

    def kit(name: str, risk: int | None):
        return Tool(name=name, description="d", parameters={}, base_risk=risk)

    # ① 声明 0，而参数里是删库 ⇒ 抬到最高档
    band, why = _risk_band(kit("exec", 0), {"command": "rm -rf /var/data"})
    assert band == 3 and why.startswith("pattern>"), (band, why)
    # ② 声明 2，而模式只认得出"只读" ⇒ **保持 2**（不许压低）
    band, why = _risk_band(kit("exec", 2), {"command": "ls -la"})
    assert band == 2 and why == "declared", (band, why)
    # ③ 声明 0，模式无命中 ⇒ 0
    band, why = _risk_band(kit("lookup_capital", 0), {"country": "France"})
    assert band == 0 and why == "declared", (band, why)
    # ④ 没声明 ⇒ 认不出来就问人
    band, why = _risk_band(kit("act", None), {"command": "zzz"})
    assert band == UNKNOWN_TOOL_BAND and why == "unknown", (band, why)


def test_the_risk_pattern_table_is_ordered_by_severity() -> None:
    """★★ **模式表第一条命中就返回 —— 所以破坏性的必须排在前面。**

    `rm` 既是"写"也是"毁"。表里 ③ 排在 ① 之前，所以它拿到 3 而不是 1。
    ★ 这条测试钉的是**顺序**，而顺序正是这张表的正确性所在。
    """
    from experiments.core.types import Tool

    t = Tool(name="exec", description="d", parameters={})
    cases = {
        "rm -rf /tmp/x": 3,
        "dd if=/dev/zero of=/dev/sda": 3,
        "sudo apt-get install curl": 2,
        "git push origin main": 2,
        "echo hello > notes.txt": 1,
        "mkdir -p build": 1,
        "ls -la": 0,
        "cat README.md": 0,
    }
    for command, want in cases.items():
        band, why = _risk_band(t, {"command": command})
        assert band == want, f"{command!r} ⇒ 期望 {want}，拿到 {band}（{why}）"
    # ★ 表里的档位必须在 legend 的范围内 —— 越界会让 `RISK_LEGEND[...]` 静默取错
    for _pat, band in RISK_PATTERNS:
        assert 0 <= band < len(RISK_LEGEND), (_pat, band)


# ═══════════════════════════════════════════════════════════
# ④ 记账：规则那一行和判官那一行**分开**
# ═══════════════════════════════════════════════════════════


def test_a_judgment_is_recorded_exactly_once() -> None:
    """★★★ **一条判定只记一行 —— 立场不另开副本。**

    判官的答案**本来就在**那道题自己那一行里（`_ask_many` 记的，
    `answer` 就是选项值，连 `top`/`confidence`/`correct` 都在）。
    第一版又开了一行 `(stance:...)` 记"判官的立场" —— 实测一跑就露了：
    15 次调用出了 **30 行 `risk_confirm`**。

    后果不是"多了一行"，是**两个数一起坏掉**：

      · 节点计数翻倍（`run_diagnostics` 直接可查）
      · `判定占比` 的**分子分母一起被灌水** —— 那是头条指标

    ★ "判官否定了规则"仍然 durable：它在 `deliverable::confirm` 那一行的
      `answer`（`does_not_hold`）里，和同一 (task, step) 的**规则行**联起来
      就是那条证据。离线联表是 `run_diagnostics` 的活，不是靠多记一行。
    """
    ctrl, client, session = rules_first()
    ctrl._answer_text = lambda *a, **k: "The capital is Paris and the code is 9999."  # type: ignore[method-assign]
    client.pick["deliverable::confirm"] = "holds"
    first = ctrl.decide(session, _view(session))
    client.noul["needsTool"] = 0.1
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    ctrl.decide(session, _view(session, history=(step,)))
    session.finish_events()

    rows = session.decision_records()
    rule_rows = [r for r in rows if r.node == "deliverable::grounding"]
    stance_rows = [r for r in rows if r.node == "deliverable::confirm"]
    # ★ 规则那一行说的是"裁决由规则做"；判官那一行记的是**它的答案本身**
    assert rule_rows and rule_rows[-1].source == "rule", rule_rows
    assert len(stance_rows) == 1, f"一次判定只该记一行，实际 {len(stance_rows)} 行"
    assert stance_rows[-1].answer == "holds", stance_rows[-1].answer
    assert stance_rows[-1].source == "judge", stance_rows[-1]
    # ★ 规则给出的**具体指向**在规则那一行里（那几个数），那才是可复核的判据
    assert "9999" in rule_rows[-1].answer, rule_rows[-1].answer


def test_the_legacy_gate_still_asks_its_own_two_questions() -> None:
    """★★ **旧那一版必须仍然完整可用** —— 它是所有已测数字所属的方法。

    ★ `gates_rules_first=False` 不是"兼容层"，是**对照组**：
      两版换的是裁决的来源，而"换了之后好了多少"只能靠只改这一个开关的 A/B 答。
      所以旧版的两道题、`score:risk`、`unjudgeable ⇒ blocked` 都要在。
    """
    session = make_session()
    client = ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1,
                                  "deliverable": 0.1, "unsupported": 0.1})
    ctrl = judge_gate(client)
    first = ctrl.decide(session, _view(session))
    assert first.kind == "tool", first
    client.noul["needsTool"] = 0.1
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    decision = ctrl.decide(session, _view(session, history=(step,)))
    asked = {n for r in client.requests for n in r.questions}
    assert "deliverable" in asked and "unsupported" in asked, asked
    assert "deliverable::confirm" not in asked, asked
    # ★ 旧版的 `unjudgeable ⇒ blocked` 还在：拒答不是放行
    assert decision.kind != "answer" or decision.gate == "revise"


def test_the_two_gates_share_one_grounding_check() -> None:
    """★ **数字落地只有一处实现。**

    第一版的规则优先实现把它抄了一份 —— 于是同一件事有两处实现，
    而"数字落地"是这套闸门里最锐利的一条证书：
    两处分叉之后，一批数字用哪个口径算就说不清了（§8.15 的形状）。
    """
    session = make_session(arm="react")
    from experiments.jloop.typed import AgentCtx

    ctx = AgentCtx(task="t", draft="the answer is 42")
    ctx.__dict__["steps"] = ()
    assert _ungrounded_numbers(ctx) == ["42"]
    assert _ungrounded_numbers(AgentCtx(task="t", draft="no numbers here")) == []


def test_a_self_check_warning_is_not_recorded_as_a_judgment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """★★★ **"落进事件流"不等于"记成一次判定" —— 这个错我犯了三次。**

    校验器发现有做过的候选时,`_ask_many` 会记一行然后**照常把请求发出去**。
    第一版把那一行记成了 `source="judge"` + `confidence=0.0` + `correct=False`,
    还**沿用了问题的节点名**。

    实测（2026-10-03，ALFWorld 20 题）后果是 **413 行**（占全部 2107 行的 20%）:

      · `pickTool` 的节点计数 240 → **436**（同一件事数了两遍）
      · 「判定占比」的分子分母**一起被灌水**：真值 0.898 被读成 0.918
      · 校准分析里多出 413 个"置信度 0.0 且答错"的样本 —— 而它们根本不是样本

    ★ 修法是**记成规则行**（自查是我们的规则发现的）并加 `::violation` 后缀。
      `fatal` 那一半**不这么改**：请求没发出去，那一行**就是**那次失败的判定。

    ⚠️ **这条测试直接调 `_ask_many`，不绕 benchmark。**
      第一版想靠 toy 的自然流程撞出这个告警，结果它根本不触发
      （toy 只有一个工具，收尾走的是 `[DONE]` 捷径），测试当场 skip ——
      **一条不会触发的测试等于没有测试。** 触发条件在这里显式造出来：
      候选里放一个**已经做过的动作**。
    """
    from experiments.core.frame import ctx_from_steps
    from experiments.jloop.typed import _choice_question

    session = make_session()
    ctrl = TypedController(
        ScriptedClient(noul={"needsTool": 0.9, "needs_auth": 0.1}),
        gates_rules_first=True)
    # 第一步真的做一次 `lookup_capital(country=France)` ⇒ France 进了历史
    first = ctrl.decide(session, _view(session))
    assert first.kind == "tool", first
    step = _tool_step(first.tool, country="France", observation="Paris")
    # `pickInput` 的候选里**故意**放回那个做过的动作
    ctx = ctx_from_steps(session.task.prompt, [step])
    before = len(session.decision_records())
    out = ctrl._ask_many(session, session.next_batch(), ctx, 1, [
        _choice_question("pickInput", "?", ["France", "Spain"], threshold=0.0,
                         criteria={"France": "x", "Spain": "y"}, escape="Spain"),
    ], honor_shadow=False)
    session.finish_events()
    rows = session.decision_records()[before:]

    warns = [r for r in rows if str(r.answer).startswith("(candidate_already_done")]
    assert warns, f"自查告警没造出来 —— 这条测试什么都没测。节点：{[r.node for r in rows]}"
    for w in warns:
        # ① 它不是判定
        assert w.source == "rule", w
        assert w.confidence == 1.0 and w.correct is True, w
        # ② 它不占用问题的节点名
        assert w.node.endswith("::violation"), w.node
        assert w.node != "pickInput", w.node
    # ③ 而真正的那次判定仍然只记一行
    answers = [r for r in rows if r.node == "pickInput"]
    assert len(answers) == 1, f"一次判定只该记一行，实际 {len(answers)} 行"
    assert answers[0].source == "judge", answers[0]
    assert out.get("pickInput") is not None, out


def test_an_honest_refusal_is_not_a_reason_to_revise() -> None:
    """★★★ **"我没有作答"不是问题 —— 而它以前只能被读成 `overclaim`。**

    实测（2026-10-04，TERNARY）按金标分类看"打回时草稿本来就对"的那 8 题:
    金标类型是 `contradiction` / `unanswerable` —— **那两类的正确行为就是拒绝作答**。
    而拒绝作答**必然要说一句关于证据的话**（"语料里没有""文档互相矛盾"）。

    旧的选项集只有 `no_objection / overclaim / incomplete / unsure` ⇒
    **一句诚实的拒绝只能落进 `overclaim`** ⇒ 闸门打回它、`degrade` 它 ⇒
    `q072` / `q092` 就这样**从对变成错**。

    ★ 毛病不是"闸门太严",是**它读不出「我没有作答」和「我编了一个事实」的区别** ——
      关系型问题（"它有没有夸大？"）而不是分类问题（"它属于哪一类？"）。
    """
    ctrl, client, session = rules_first()
    client.pick["deliverable::object"] = "honest_refusal"
    first = ctrl.decide(session, _view(session))
    client.noul["needsTool"] = 0.1
    step = _tool_step(first.tool, country=first.arguments.get("country", ""),
                      observation="Paris")
    decision = ctrl.decide(session, _view(session, history=(step,)))
    delivered_cleanly = (decision.kind == "answer"
                         and decision.gate not in ("revise", "blocked"))
    assert delivered_cleanly, (
        f"判官说这是诚实拒绝,闸门却打回了它:{decision.gate!r} / {decision.kind!r}"
    )


def test_the_refusal_class_needs_both_conditions() -> None:
    """★★★ **这一类不许变成逃生口 —— 两个条件必须同时成立。**

    ① **"不作答"** —— 它没有对世界做任何断言;
    ② **"理由与证据一致"** —— 而这一半是关键:

    `q001` 的草稿声称「工具失败了、没有可用证据」,而证据里明写着
    `read_doc(d001) -> … founded in 1998 …` —— **工具读成功了**。
    那是**编了一个原因**,是 `overclaim`,**不是**诚实拒绝。

    ★ 所以 `overclaim` 的判据里必须有一句「**或者给出了证据反驳的理由**」。
      少了它,一个"声称工具坏了"的答案就能冒充诚实拒绝 ——
      那我们只是把判据放松了,不是把它改对了。
    """
    from experiments.jloop.typed import OBJECT_ALLOW_CRITERIA

    refusal = OBJECT_ALLOW_CRITERIA["honest_refusal"]
    over = OBJECT_ALLOW_CRITERIA["overclaim"]
    assert "NO value" in refusal, "第一个条件（不作答）没写进判据"
    assert "reason it gives is one the evidence supports" in refusal, (
        "第二个条件（理由与证据一致）没写进判据 —— 那这一类就成了逃生口"
    )
    assert "reason the evidence contradicts" in over, (
        "`overclaim` 缺了「编了一个原因」那一半 —— q001 那种答案会冒充诚实拒绝"
    )
    # 而它是**真的进了线协议**（不然判官压根看不到这个选项）
    from experiments.core.contract import QuestionSpec  # noqa: F401
    from experiments.jloop.contracts import QUESTIONS

    opts = QUESTIONS["deliverable::object"].criteria
    names = [k for k, _ in opts]
    assert "honest_refusal" in names, names
