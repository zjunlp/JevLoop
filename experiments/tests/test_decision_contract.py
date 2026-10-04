"""**决策契约** —— 领域无关的 schema、每个数据集一份的契约、宿主的能力声明。

这个文件测的是契约这件东西**成不成立**,不是某个判定点判得对不对。
四条最有价值:

  `test_the_contract_is_the_one_the_program_actually_asks`
      ★★★ **扫描 `typed.py` 的源码**,把每一条真正问出去的问题抓出来,断言它
      在契约里登记过。**"加了一道题而忘了写进契约"就是这条测试变红的原因。**
      没有它,契约会慢慢变成一份"当年写过、后来越来越不像"的文档。

  `test_the_position_vocabulary_is_the_one_in_decision_md`
      ★★★ 契约里的位置名**从 `DECISION.md` 的 `when:` 行里解析出来比**。
      两份东西描述同一个概念,而"一个概念两个名字"是这个项目最大的阅读成本
      （用户 2026-10-04 的规范）。漂了要红。

  `test_a_position_the_host_cannot_serve_is_an_error_not_a_silence`
      放不进去的判定点要**报出来**。`DECISION-CONTRACT.md` §1 的原话:
      "A host must not silently ignore an unknown declaration."

  `test_decided_by_is_where_the_gate_change_lives`
      闸门那次改动,在契约里就是**一个字段**从 `"judge"` 变成 `"both"`。

跑法（在 `JevLoop/` 下）::

    python3 -m pytest experiments/tests -q
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.core.contract import (  # noqa: E402
    EFFECTS,
    MODES,
    PORTABLE_POSITIONS,
    DecisionSpec,
    Host,
    QuestionSpec,
    capability_report,
    dispatch,
    is_position,
    validate,
    validate_all,
)
from experiments.jloop.contracts import (  # noqa: E402
    CONTRACTS,
    HOSTS,
    QUESTIONS,
    REACT_LOOP,
    problems,
)

TYPED_SRC = REPO / "experiments" / "jloop" / "typed.py"
DECISION_MD = REPO / "DECISION.md"


# ═══════════════════════════════════════════════════════════
# ① 契约和程序不许漂
# ═══════════════════════════════════════════════════════════


def test_the_contract_validates_against_the_host() -> None:
    """契约 + 题表 + 宿主,一次查完必须是空的。"""
    found = problems()
    assert found == [], "契约没通过自校验:\n" + "\n".join(found)


def test_the_contract_is_the_one_the_program_actually_asks() -> None:
    """★★★ **程序真正问出去的题,契约里必须都登记过。**

    ★ 判据是**扫源码**,不是扫一份手写的名单 —— 手写名单会跟着代码一起过时,
      而那正是这条测试要防的事。构造器只有三个,所以正则够稳:
      `_noul_question("x"` / `_choice_question("x"` / `_score_question("x"`。

    ⚠️ 一个反例说明为什么必须扫源码:`risk` 这道题只在 `typed-3` 那条分支上问,
      而它在 AST 上和在运行时的形状完全不同 —— 只有源码文本能一次都抓到。
    """
    src = TYPED_SRC.read_text(encoding="utf-8")
    asked = set()
    for ctor in ("_noul_question", "_choice_question", "_score_question"):
        asked |= set(re.findall(rf'{ctor}\(\s*"([^"]+)"', src))
    # `risk_confirm` 走的是同一条构造器，但它由 `_confirm_risk` 传名字
    assert asked, "一道题都没扫到 —— 正则坏了,这条测试就成了摆设"
    missing = sorted(q for q in asked if q not in QUESTIONS)
    assert not missing, (
        f"这些题程序会问,但契约里没有登记:{missing}\n"
        f"  ⇒ 把它们写进 `jloop/contracts.py::QUESTIONS`,"
        f"并挂到某个判定点上（否则 `validate_all` 会报「写了没接」）"
    )


def test_a_question_nobody_uses_is_reported() -> None:
    """反方向:题表里多出来的东西也要报 —— **写了没接**（§8.15）。"""
    questions = dict(QUESTIONS, orphan=QuestionSpec(node="orphan", kind="noul", ask="?"))
    # ★ 这条必须走 `validate_all` —— "题有没有人用"要**跨契约**查:
    #   `risk` / `deliverable` / `unsupported` 只属于 typed-3,
    #   逐份查会把正常的东西报成"写了没接"（第一版就这么报了六条假问题）。
    found = validate_all(CONTRACTS, questions, REACT_LOOP)
    assert any("orphan" in p for p in found), found
    # 而单契约的 validate 不管这件事 —— 这是刻意的分工
    assert not any("orphan" in p
                   for p in validate(CONTRACTS["typed-4"], questions, REACT_LOOP))


def test_the_position_vocabulary_is_the_one_in_decision_md() -> None:
    """★★★ **位置名从 `DECISION.md` 的 `when:` 行里解析出来比。**

    `DECISION.md` 是那份**原始规约**,而契约是它的机器可读形状。两份东西
    描述同一个概念 —— 用户 2026-10-04 的规范说得很清楚:**一个概念只留一个名字,
    永远不换同义词**,因为换名字是这类项目最大的阅读成本。

    ⇒ 所以漂了要红。改了 `DECISION.md` 的 `when:` 就该改 `PORTABLE_POSITIONS`。
    """
    used = set()
    for line in DECISION_MD.read_text(encoding="utf-8").splitlines():
        m = re.match(r"\s*when:\s*([^\s—]+)", line)
        if m:
            used.add(m.group(1))
    assert used, "没从 DECISION.md 里解析出 when: —— 正则或文件结构变了"
    assert used == set(PORTABLE_POSITIONS), (
        f"DECISION.md 里的位置和代码里的对不上。\n"
        f"  只有文档有:{sorted(used - set(PORTABLE_POSITIONS))}\n"
        f"  只有代码有:{sorted(set(PORTABLE_POSITIONS) - used)}"
    )


def test_every_declared_position_is_actually_used() -> None:
    """六个位置里,`tool-choice`/`input-choice` 这些**不能只是摆设**。

    ★ 这条查的是"契约声明了六个位置,而实际只用了四个"这类**空声明**。
      它允许某个位置暂时没人用,但**不许有位置是造出来凑数的** ——
      现在六个都有节点,所以这里断言全满。
    """
    used = {s.position for specs in CONTRACTS.values() for s in specs.values()}
    assert used == set(PORTABLE_POSITIONS), sorted(set(PORTABLE_POSITIONS) - used)


# ═══════════════════════════════════════════════════════════
# ② 宿主的能力声明
# ═══════════════════════════════════════════════════════════


def test_a_position_the_host_cannot_serve_is_an_error_not_a_silence() -> None:
    """★★★ **放不进去的判定点要报出来。**

    `DECISION-CONTRACT.md` §1 的原话:*"A host must not silently ignore an unknown
    declaration."* 静默不跑是最坏的一种:它在日志上看起来像"这一步不需要判定"。

    ★ `acme.review` 是 §7 给的出口（命名空间宿主阶段）。**它合法,但循环宿主
      服务不了** —— 所以两件事分开:位置本身合法,这台宿主放不下。
    """
    spec = DecisionSpec(id="review", version=1, position="acme.review",
                        questions=(), policy="p", fallback="f",
                        effects=("proceed",), decided_by="rule")
    assert is_position("acme.review"), "命名空间阶段本身应当合法（§7）"
    found = validate({"review": spec}, {}, REACT_LOOP)
    assert any("放不进去" in p for p in found), found

    # 而一个真定义了这个阶段的宿主,就放得下
    host = Host(name="acme", serves=frozenset({"acme.review"}),
                phases=frozenset({"acme.review"}))
    assert validate({"review": spec}, {}, host) == []


def test_the_late_served_position_is_declared_as_a_debt() -> None:
    """★★★ **这台宿主有一条债,而它在数据里,不在注释里。**

    `after-tool`（"工具执行之后"）这个位置循环宿主**服务晚了** ——
    迟一个 `step-start`。因为循环在下一步之前才调 `decide()`,所以
    `stepOk` / `isDone` 只能在下次进来时补跑（`_review_last_step`）。

    ★ 那条补跑**不是设计,是这笔债**（`docs/ENGINE-VS-HOST.md` §2 的第一条证据）。
      第一版想把 `served_late` 省掉（"反正服务得了"）—— 省掉之后这笔债
      就只能靠人从代码里考古出来。
    """
    assert "after-tool" in REACT_LOOP.served_late, (
        "循环宿主服务 `after-tool` 是晚的,这件事必须写在数据里"
    )
    # 而那两个判定点正好在它上面 —— 债和受影响的东西要对得上
    late_nodes = dispatch(CONTRACTS["typed-4"], "after-tool")
    assert set(late_nodes) == {"stepOk", "isDone"}, late_nodes
    # 报告里要能看出来
    rep = capability_report(CONTRACTS["typed-4"], REACT_LOOP)
    assert rep["after-tool"]["late"], rep["after-tool"]


def test_a_host_cannot_claim_a_debt_it_does_not_serve() -> None:
    """不许把"服务不了"写成"服务晚了" —— 那是同一件事的两种推脱。"""
    bad = Host(name="liar", serves=frozenset({"step-start"}),
               served_late={"after-tool": "假装只是晚"})
    found = validate({}, {}, bad)
    assert any("服务晚了" in p for p in found), found


# ═══════════════════════════════════════════════════════════
# ③ 构造处的硬规则（这是我们的 SHACL）
# ═══════════════════════════════════════════════════════════


def test_a_choice_question_without_an_escape_cannot_even_be_declared() -> None:
    """★★ **没有退出口的 choice 问题,在**声明的时候**就炸。**

    照 μ 的 `policy.ts`:那种问题会让判官**被迫挑一个真选项,而且挑得很果断**。
    实测下游是 28 选 1、`top` 贴在门限上、一个命令一轮挑 56 次。

    ★ 两条合法出路:**给退出口**,或者**显式声明 `closed=True`** 并说明为什么
      那个候选集真的封闭（三个立场对一条命题就是穷尽的）。
      没有第三条 —— 沉默地不加,和"声明封闭"必须能分开。
    """
    with pytest.raises(ValueError, match="必须有退出口"):
        QuestionSpec(node="c", kind="choice", ask="?")
    # 给了就过
    assert QuestionSpec(node="c", kind="choice", ask="?",
                        escape="none_of_these").escape == "none_of_these"
    # 声明封闭也过 —— 而这是个**声明**,不是遗漏
    assert QuestionSpec(node="c", kind="choice", ask="?", closed_choices=True).closed_choices


def test_a_rule_only_decision_point_needs_no_questions() -> None:
    """★★ `decided_by="rule"` 的判定点**一道题都不问**,而它必须能声明自己如此。

    ★ 反过来也要查:声明纯规则却挂着三道题,那三道题**不会有人用** ——
      而"配了没生效"正是这个仓库反复栽的形状。
    """
    rule = DecisionSpec(id="r", version=1, position="step-start", questions=(),
                        policy="p", fallback="f", effects=("proceed",),
                        decided_by="rule")
    assert validate({"r": rule}, {}, REACT_LOOP) == []

    # 声明纯规则却挂了题 ⇒ 报
    both = DecisionSpec(id="r", version=1, position="step-start",
                        questions=("needsTool",), policy="p", fallback="f",
                        effects=("proceed",), decided_by="rule")
    assert any("不会有人用" in p for p in validate({"r": both}, QUESTIONS, REACT_LOOP))
    # 声明要问却一道题都没有 ⇒ 报
    empty = DecisionSpec(id="r", version=1, position="step-start", questions=(),
                         policy="p", fallback="f", effects=("proceed",),
                         decided_by="judge")
    assert any("一道题都没有" in p for p in validate({"r": empty}, {}, REACT_LOOP))


def test_the_result_vocabulary_is_closed() -> None:
    """结果词表是封闭的 —— 写一个表外的词要炸,不许静默当成"继续"。"""
    with pytest.raises(ValueError, match="不在结果词表"):
        DecisionSpec(id="x", version=1, position="step-start", questions=(),
                     policy="p", fallback="f", effects=("make_coffee",),
                     decided_by="rule")
    assert "deliver" in EFFECTS and "ask_human" in EFFECTS and "revise" in EFFECTS
    assert MODES == ("off", "shadow", "active")


# ═══════════════════════════════════════════════════════════
# ④ 闸门那次改动,在契约里就是一个字段
# ═══════════════════════════════════════════════════════════


def test_decided_by_is_where_the_gate_change_lives() -> None:
    """★★★ **"规则先筛、判官只确认"在契约里就是 `decided_by` 从 `judge` 变成 `both`。**

    这条是这次改动**在数据上的形状**。我们量的所有东西（退出口、判定占比、
    规则被否率）都挂在这个字段上,所以它必须能被断言,而不只是写在散文里。

    ★ 两版的问法也必须跟着换:`typed-3` 问 `deliverable`/`unsupported`/`risk`,
      `typed-4` 问 `deliverable::confirm`/`deliverable::object`/`risk_confirm`。
      换了一个不改另一个 = 契约在描述一个不存在的程序。
    """
    t3, t4 = CONTRACTS["typed-3"], CONTRACTS["typed-4"]
    # 闸门
    assert t3["canDeliver"].decided_by == "judge"
    assert t4["canDeliver"].decided_by == "both"
    assert t3["canDeliver"].questions == ("deliverable", "unsupported")
    assert t4["canDeliver"].questions == ("deliverable::confirm", "deliverable::object")
    # 授权闸门同理
    assert t3["gradeRisk"].decided_by == "judge"
    assert t4["gradeRisk"].decided_by == "both"
    assert "risk" in t3["gradeRisk"].questions
    assert "risk" not in t4["gradeRisk"].questions, (
        "typed-4 里风险档位由规则给 —— `score:risk` 那道题不该再问"
    )
    # ★ 动作类那五个**没变** —— 它们不是这次改动的对象
    for sid in ("needsTool", "pickTool", "pickInput", "stepOk", "isDone"):
        assert t3[sid].decided_by == t4[sid].decided_by == "judge", sid
        assert t3[sid].questions == t4[sid].questions, sid


def test_the_known_defect_is_written_in_the_contract() -> None:
    """★ **那个 0.5 门限要写在契约里,因为它就是那个 bug。**

    `typed-3` 的 `score:risk` 门限是 `Question.threshold` 的 dataclass 默认值
    **0.5**,而 `_score_question` 从不显式设它。判官每次都答对（`risk=1`）,
    置信度 0.39 ⇒ 被丢掉 ⇒ 授权闸门"不成立" ⇒ 20 题里 **4 题**这样死,
    一次工具都没调（`docs/ALFWORLD-ESCAPE.md` §4）。

    ★ 契约里看得见这个 0.5,所以那个病不需要读代码才知道。
    """
    assert QUESTIONS["risk"].threshold == 0.5
    assert QUESTIONS["risk"].kind == "score"
    assert "0.5" in CONTRACTS["typed-3"]["gradeRisk"].note, (
        "已知缺陷要写在判定点的 note 里 —— 不写的话下一个人得重新发现它一次"
    )
    # 而 typed-4 里那道确认题的门限是 0:不是决定,是报告
    assert QUESTIONS["risk_confirm"].threshold == 0.0
    assert QUESTIONS["risk_confirm"].closed_choices, "三个立场对一条命题是穷尽的 ⇒ 声明封闭"


# ═══════════════════════════════════════════════════════════
# ⑤ 规范状态键 —— "同一个状态"到底指什么
# ═══════════════════════════════════════════════════════════


def test_the_state_key_covers_evidence_question_and_options() -> None:
    """★★★ **三样缺一不可:证据、题的身份、候选集。**

    ★★★ 第三条是实测逼出来的(2026-10-04)。第一版只用了证据 —— 也就是帧声明那几个
      字段 —— 于是 `pickInput` 在规范键下算出 **57.3% 的决定翻转率**。
      而它的题就是"从这些候选里挑一个",**候选集却没进键**:
      两个不同候选集下给出不同的答案(**都对**)被算成了翻转。

      ⇒ 那是**键的缺陷,不是判官的不稳定。** 差一点就被写进论文当成"判官不稳定"的证据。

    ★ 而 `request_digest()` 是覆盖选项的(它当初就是为这件事建的)。
      所以键必须也覆盖,否则同一件事有两个口径。
    """
    from experiments.core.frame import AgentCtx, Question, canonical_state

    ctx = AgentCtx(task="t", last_result="You arrive at safe 1.")
    def q(opts, esc):
        return Question(node="pickInput", kind="choice", ask="?",
                        threshold=0.0, options=opts, escape=esc)

    a = q(["go to safe 1", "look"], "look")
    # ① 候选集不同 ⇒ 状态不同
    b = q(["go to safe 1", "look", "examine"], "examine")
    assert canonical_state(ctx, a) != canonical_state(ctx, b), "候选集没进键"
    # ② 证据不同 ⇒ 状态不同。★ 用**帧里真的声明了的**那一段证据来测 ——
    #    `stepOk` 的帧含 `last_result`,而 `pickInput` 的帧**故意没有它**
    #    (它的排除理由:「判的是**这一调**的目标,不是上一步返回了什么」)。
    ok = Question(node="stepOk", kind="noul", ask="?", threshold=0.6)
    other = AgentCtx(task="t", last_result="You arrive at fridge 1.")
    assert canonical_state(ctx, ok) != canonical_state(other, ok), "证据没进键"
    # ③ 完全一样 ⇒ 状态相同(**这就是重复检测成立的前提**)
    assert canonical_state(ctx, a) == canonical_state(ctx, q(["go to safe 1", "look"], "look"))


def test_every_node_that_needs_the_last_observation_declares_it() -> None:
    """★★★ **缺了 `last_result` 的节点,状态键会粗到把不同情况算成同一个 —— 这个洞已经补上。**

    ★ 这条测试的前身是 2026-10-04 的一个发现:`pickInput` 的帧声明里**没有**
      `last_result`,而它的排除理由写的是「判的是**这一调**的目标,不是上一步返回了什么」。
      **那句话反了** —— 不知道刚刚发生了什么,就选不出下一步该做什么。
      `needsTool` / `isDone` 一直都有它,只有这个节点漏了。

    ★ 代价是实测的(TERNARY,2026-10-04):`pickInput` 的 41 个候选里 40 个是
      `d001…d040`,判官答"一个都不合适" **20/20**(置信度 0.62)。
      **它是对的** —— 帧里没有任何东西能区分那 40 个 id。

    ⇒ 所以这条测试现在钉的是**反方向**:需要看"上一步返回了什么"的节点,
      必须声明 `last_result`。漏一个就红。
    """
    from experiments.core.frame import frame_for

    # 判的是**上一步**（成没成 / 下一步做什么）⇒ 必须看上一步的返回
    for node in ("stepOk", "needsTool", "pickInput", "pickTool"):
        fields = {f.name for f in frame_for(node).fields}
        assert "last_result" in fields, (
            f"{node} 的帧没有 `last_result` —— 它判不出下一步该做什么"
        )
    # ★ `isDone` **故意没有它**,而且写了理由:「判的是『任务做完没有』,
    #   不是『上一步返回了什么』」。那是**另一个方向**的教训 ——
    #   `stepOk` 反过来是因为**带了** `task` 才被拉到任务级(实测)。
    #   ⚠️ 但 `isDone` 这条排除**没有量过**:一个"任务做完了吗"的判断,
    #     在看不到最后一次观测时是否够用,我们不知道。**这是待测项,不是 bug。**
    assert "last_result" not in {f.name for f in frame_for("isDone").fields}, (
        "isDone 的帧现在含 last_result 了 —— 那是方法改动,要 bump 规格版本并重测"
    )


def test_a_declared_field_is_not_also_declared_as_excluded() -> None:
    """★★ **既声明又排除 = 自相矛盾**,而且它会让状态键说不清。

    ★ 这条也是实测抓的:把 `last_result` 加进 `pickInput` 的 `fields` 之后
      **没有**同时从 `excluded` 里删掉,`test_frame.py` 当场红:
      `pickInput: last_result 既声明又不声明`。
      ⇒ 两栏之间的一致性必须有东西守,否则"这个字段到底进不进帧"会**两处都答**,
        而帧预算、状态键、审计三件事都建立在这个答案上。
    """
    from experiments.core.frame import NODE_FRAMES

    for node, spec in NODE_FRAMES.items():
        declared = {f.name for f in spec.fields}
        excluded = {name for name, _ in spec.excluded}
        assert not (declared & excluded), (
            f"{node}: {sorted(declared & excluded)} 既声明又不声明"
        )


def test_a_new_run_can_be_re_analysed_from_disk() -> None:
    """★★★ **状态键必须进账,否则那个数没法复核。**

    2026-10-04 第一次算"有效控制熵"时,判定行里**只有指纹、没有字段值** ——
    于是那个数**没法从盘上重算一遍**。一个不能复核的数不能进论文。

    ★ 而且还有个后果:`pickInput` 的翻转率到底是多少,**旧日志永远算不准**
      (候选集不在日志里)。所以这一栏不是锦上添花,是**唯一**能让以后的 run
      被精确分析的东西。
    """
    from experiments.core.spec import DecisionRecord

    assert "state_key" in DecisionRecord.__dataclass_fields__, (
        "`DecisionRecord` 上没有 `state_key` —— 那么新 run 一样没法复核"
    )
    # 记录行的默认值是空串(不是假的键):没算过就留空,不许编一个
    assert DecisionRecord.__dataclass_fields__["state_key"].default == ""


def test_no_script_shadows_an_installed_package() -> None:
    """★★★ **`experiments/scripts/` 里不许有名字和已安装的顶层包撞的文件。**

    实测（2026-10-04）：`experiments/scripts/datasets.py` 把 HuggingFace 的
    `datasets` 包**遮住了** —— 按文件跑时 `sys.path[0]` 就是 `experiments/scripts`,
    于是 `from datasets import load_dataset` 找到的是**我们自己的那个文件**:

        ImportError: cannot import name 'load_dataset' from 'datasets'
                     (/…/experiments/scripts/datasets.py)

    ★ 后果的形状值得记下来:**它只打在 import 了那个包的数据集上。**
      ALFWorld / ternary-judge / FTA 都不 import HF `datasets`,所以那一批
      **四个 run 全跑通、只有 GSM8K 炸**。一个只打在一条分支上的错,
      最容易被读成"这条分支本身有问题"。

    ⇒ 判据用 `find_spec`,不 `import` —— 这样这个包装没装都能查。
    """
    import importlib.util

    scripts = REPO / "experiments" / "scripts"
    shadowed = []
    for f in sorted(scripts.glob("*.py")):
        if f.stem.startswith("_"):
            continue
        # 把 `experiments/scripts` 放到最前面,模拟"按文件跑"的那个 sys.path
        saved = list(sys.path)
        try:
            sys.path.insert(0, str(scripts))
            spec = importlib.util.find_spec(f.stem)
        except (ImportError, ValueError):
            spec = None
        finally:
            sys.path[:] = saved
        if spec is not None and spec.origin and str(scripts) in str(spec.origin):
            # 它自己是"解析到自己"—— 只有当外面也存在同名包时才算遮住
            pass
        if spec is not None and spec.origin and str(REPO) not in str(spec.origin):
            shadowed.append((f.name, spec.origin))
    assert not shadowed, (
        f"这些脚本的名字和外面已安装的包撞了,会把它们遮住:{shadowed}\n"
        f"  ⇒ 改个名字（`datasets.py` → `dataset_catalog.py` 那次的修法）"
    )
