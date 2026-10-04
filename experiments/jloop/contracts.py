"""**我们这一侧的具体契约** —— 一个数据集一份,手写。

## 范围（用户 2026-10-04 的决定）

> 「提取这件事我们可以假设先不用管,因为我们这里是在不同的数据集上面测效果来展示的,
>  我们可以对于这些数据集自己先写一个规范的决策契约。我们先完成后半部分的事情。」

所以:**从文本抽契约不做。** 每个数据集手写一份规范契约,引擎执行它,判定账溯源它。
论文要主张的是**后半部分**,不是提取。

★★ **代价必须写下来:手写契约本身就是一个调参面。** 同一个数据集,契约可以写松也可以写紧,
而我们看得到分数。缓解办法三条,缺一条这个数就不可信:

  1. **带版本**（`version`）—— 改了问法或策略就 bump；
  2. **带指纹**（`typed.py::decision_spec_digest`）—— 改了而没 bump,测试红；
  3. **写它的时间点要能交代** —— 最好在看到结果之前写。报告里要说明
     "为了这个数据集调过几次契约",而不是装作一次写对。

## 这个文件里有什么

  `QUESTIONS`  所有题（问法、判据、门限、退出口）—— **从 `typed.py` 的常量构造,不重写一遍**
  `CONTRACTS`  按方法版本分的判定点表（`typed-3` = 判官产生裁决；`typed-4` = 规则先筛）
  `HOSTS`      宿主声明它发得出哪些事件,以及哪些**发晚了**
  `problems()` 三样一起校验（这是我们的 SHACL，见 `core/contract.py` 的说明）
"""

from __future__ import annotations

from experiments.core.contract import (
    DecisionSpec,
    Host,
    QuestionSpec,
    validate_all,
)
from experiments.jloop import typed as t

# ═══════════════════════════════════════════════════════════
# 题表 —— 每道题只在这里写一次
# ═══════════════════════════════════════════════════════════
#
# ★★★ **问法不在这里重写一遍,而是从 `typed.py` 的常量取。**
#   两处各写一份问法,改了其中一处就是"配了没生效"那个坑,
#   而且它**看起来还在生效**（`docs/MU-CONFLICT.md` 第 6 行那个洞）。

QUESTIONS: dict[str, QuestionSpec] = {
    # ── 动作空间 ────────────────────────────────────────────
    "needsTool": QuestionSpec(
        node="needsTool", kind="noul", ask=t.NEEDS_TOOL_ASK,
        criteria=tuple(t.NEEDS_TOOL_CRITERIA.items()),
        threshold=t.NODE_THRESHOLDS["needsTool"],
    ),
    "pickTool": QuestionSpec(
        node="pickTool", kind="choice", ask=t.PICK_TOOL_ASK,
        criteria_from="tool_descriptions",
        threshold=t.NODE_THRESHOLDS["pickTool"],
        # ★ 退出口是 `DONE`（"够了,别再调工具了"）—— 见 `decide()` 里那段说明。
        escape=t.DONE,
    ),
    "pickInput": QuestionSpec(
        node="pickInput", kind="choice", ask=t.PICK_INPUT_ASK,
        criteria_from="action_verbs",
        threshold=t.NODE_THRESHOLDS["pickInput"],
        escape=t.PICK_INPUT_ESCAPE,
    ),
    # ── 事后判定 ────────────────────────────────────────────
    "stepOk": QuestionSpec(
        node="stepOk", kind="noul", ask=t.STEP_OK_ASK,
        criteria=tuple(t.STEP_OK_CRITERIA.items()),
        threshold=t.NODE_THRESHOLDS["stepOk"],
    ),
    "isDone": QuestionSpec(
        node="isDone", kind="noul", ask=t.IS_DONE_ASK,
        criteria=tuple(t.IS_DONE_CRITERIA.items()),
        threshold=t.NODE_THRESHOLDS["isDone"],
    ),
    # ── 授权闸门 ────────────────────────────────────────────
    "risk": QuestionSpec(
        # ⚠️ **这一道只在 `typed-3` 里有。** 它的门限是 `Question.threshold` 的
        #   dataclass 默认值 **0.5**，而 `_score_question` 从不显式设它 ——
        #   于是"判官答了 risk=1、置信度 0.39"被丢掉 ⇒ 授权闸门不成立 ⇒
        #   整题 decline。实测 20 题里 4 题这样死（`docs/ALFWORLD-ESCAPE.md` §4）。
        #   **契约里写着这个 0.5,所以那个病在这里是看得见的。**
        node="risk", kind="score", ask=t.GRADE_RISK_ASK,
        criteria=tuple((label, label) for label in t.RISK_LEGEND),
        threshold=0.5, frame="gradeRisk",
    ),
    "needs_auth": QuestionSpec(
        node="needs_auth", kind="noul", ask=t.NEEDS_AUTH_ASK,
        criteria=tuple(t.NEEDS_AUTH_CRITERIA.items()),
        threshold=0.5, frame="gradeRisk",
    ),
    "risk_confirm": QuestionSpec(
        node="risk_confirm", kind="choice", ask=t.RISK_CONFIRM_ASK,
        criteria=tuple(t.RISK_CONFIRM_CRITERIA.items()),
        # ★ 门限 0：这不是决定,是报告 —— 只有内容进判据,分寸不进。
        threshold=0.0, frame="gradeRisk",
        # ★ 三个立场（对 / 太低 / 太高 / 说不好）对一条命题是**穷尽**的,
        #   所以这个候选集是真的封闭,豁免退出口；豁免要**写出来**。
        closed_choices=True,
    ),
    # ── 交付闸门 ────────────────────────────────────────────
    "deliverable": QuestionSpec(
        node="deliverable", kind="noul", ask=t.DELIVERABLE_ASK,
        criteria=tuple(t.DELIVERABLE_CRITERIA.items()),
        threshold=0.6, frame="canDeliver",
    ),
    "unsupported": QuestionSpec(
        node="unsupported", kind="noul", ask=t.UNSUPPORTED_ASK,
        criteria=tuple(t.UNSUPPORTED_CRITERIA.items()),
        threshold=0.5, frame="canDeliver",
    ),
    "deliverable::confirm": QuestionSpec(
        node="deliverable::confirm", kind="choice", ask=t.CONFIRM_BLOCK_ASK,
        criteria=tuple(t.CONFIRM_BLOCK_CRITERIA.items()),
        threshold=0.0, frame="canDeliver", closed_choices=True,
    ),
    "deliverable::object": QuestionSpec(
        node="deliverable::object", kind="choice", ask=t.OBJECT_ALLOW_ASK,
        criteria=tuple(t.OBJECT_ALLOW_CRITERIA.items()),
        threshold=0.0, frame="canDeliver", closed_choices=True,
    ),
}


# ═══════════════════════════════════════════════════════════
# 宿主 —— 循环宿主声明它发得出什么
# ═══════════════════════════════════════════════════════════

#: `react` 那个循环宿主（`baseline/common.py::run_loop`）。
#:
#: ★★★ **它有一条债,而这条债在这里是数据。**
#:   `action.returned`（"上一步的观测拿到了"）它**发晚了** —— 迟到一个
#:   `step.began`。因为循环在**下一步之前**才调 `decide()`，所以
#:   `stepOk` / `isDone` 只能在下次进来时补跑（`_review_last_step`）。
#:   `docs/ENGINE-VS-HOST.md` §2 把这条列为"循环步这个代理已经错了"的第一处证据。
REACT_LOOP = Host(
    name="react-loop",
    # ★ 六个可移植位置**它都服务** —— 但 `after-tool` 是晚的,见下。
    serves=frozenset({
        "step-start", "tool-choice", "input-choice",
        "before-call", "after-tool", "after-generate",
    }),
    served_late={
        "after-tool": (
            "晚一个 step-start：循环在下一步之前才调 decide()，"
            "所以 stepOk/isDone 要 `_review_last_step` 补跑"
            "（docs/ENGINE-VS-HOST.md §2 的第一条证据）"
        ),
    },
)

HOSTS: dict[str, Host] = {REACT_LOOP.name: REACT_LOOP}


# ═══════════════════════════════════════════════════════════
# 判定点表 —— **按方法版本分**
# ═══════════════════════════════════════════════════════════
#
# 为什么按版本分而不是只有一份:两版的**裁决来源不同**（`decided_by`），
# 而那是这次改动本身。两批数字不能进同一张表,契约也不该合成一份。

TYPED_4: dict[str, DecisionSpec] = {
    "stepOk": DecisionSpec(
        id="stepOk", version=1, position="after-tool",
        questions=("stepOk",), policy="step_ok", fallback="retry",
        effects=("proceed", "abstain"), decided_by="judge",
    ),
    "isDone": DecisionSpec(
        id="isDone", version=1, position="after-tool",
        questions=("isDone",), policy="is_done", fallback="retry",
        effects=("finish", "proceed"), decided_by="judge",
    ),
    "needsTool": DecisionSpec(
        id="needsTool", version=1, position="step-start",
        questions=("needsTool",), policy="needs_tool", fallback="retry",
        effects=("proceed", "finish"), decided_by="judge",
    ),
    "pickTool": DecisionSpec(
        id="pickTool", version=1, position="tool-choice",
        questions=("pickTool",), policy="pick_tool", fallback="retry",
        effects=("proceed", "abstain"), decided_by="judge",
    ),
    "pickInput": DecisionSpec(
        id="pickInput", version=1, position="input-choice",
        questions=("pickInput",), policy="pick_input", fallback="no_action_fits",
        effects=("proceed", "finish"), decided_by="judge",
    ),
    "gradeRisk": DecisionSpec(
        id="gradeRisk", version=2, position="before-call",
        # ★ 档位**不在这两道题里** —— 它由规则给（工具声明 → 模式表 →
        #   认不出来就是 2）。这两道题只是"要不要人批"和"规则的低估对吗"。
        questions=("needs_auth", "risk_confirm"), policy="risk_rules_first",
        fallback="reject", effects=("proceed", "audit", "ask_human", "refuse"),
        decided_by="both",
        note=("档位由 RISK_PATTERNS / base_risk 定；判官只准往上抬（不降）。"
              "★ **档位来自工具声明时 `risk_confirm` 不问** —— 让判官去确认一个常量,"
              "它只能答「说不好」(实测 287/291、29/37)。收紧仍由 `needs_auth` 承担"),
    ),
    "canDeliver": DecisionSpec(
        id="canDeliver", version=2, position="after-generate",
        # ★ 三条**证书**在问任何题之前先跑；这两道题是"确认"和"反驳"。
        questions=("deliverable::confirm", "deliverable::object"),
        policy="delivery_rules_first", fallback="reject",
        effects=("deliver", "revise", "abstain", "redirect"),
        decided_by="both",
        note=("证书：空草稿 / 编了数 / 没有材料；判官只能收紧，否定不放行。"
              "★ `deliverable::object` 有一类 **`honest_refusal`**（诚实拒绝）——"
              "在 `contradiction`/`unanswerable` 那两类金标下**拒绝作答才是正确行为**,"
              "而旧的选项集只能把它读成 `overclaim`（2026-10-04）"),
    ),
}

TYPED_3: dict[str, DecisionSpec] = {
    # 前五个和 typed-4 只有版本不同 —— 它们没变。
    **{k: v for k, v in TYPED_4.items()
       if k in ("stepOk", "isDone", "needsTool", "pickTool", "pickInput")},
    "gradeRisk": DecisionSpec(
        id="gradeRisk", version=1, position="before-call",
        # ★ **档位是判官答的**（`score:risk`），而门限那个 0.5 就在题表里。
        questions=("risk", "needs_auth"), policy="risk_judge_first",
        fallback="reject", effects=("proceed", "audit", "ask_human", "refuse"),
        decided_by="judge",
        note="★ 已知缺陷：score:risk 的 0.5 门限会丢掉答对但不够果断的档位（4/20 题）",
    ),
    "canDeliver": DecisionSpec(
        id="canDeliver", version=1, position="after-generate",
        questions=("deliverable", "unsupported"), policy="delivery_judge_first",
        fallback="reject", effects=("deliver", "revise", "abstain", "redirect"),
        decided_by="judge",
        note="unjudgeable ⇒ blocked（判官弃答等于不放行）",
    ),
}

CONTRACTS: dict[str, dict[str, DecisionSpec]] = {
    "typed-4": TYPED_4,   # 规则先筛、判官只确认（默认）
    "typed-3": TYPED_3,   # 判官产生裁决（对照臂 `react-typed-judgegate`）
}


def problems(host: str = "react-loop") -> list[str]:
    """**全部契约** + 题表 + 宿主,一次校验。空 = 通过。

    ★ 跨契约查,不逐份查 —— 理由见 `core/contract.py::validate_all`。
    """
    return validate_all(CONTRACTS, QUESTIONS, HOSTS[host])
