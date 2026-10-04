"""决策契约 —— **领域无关的 schema**,以及宿主的事件契约。

## 这是什么

一个 agent 的"控制"部分,可以写成若干个**判定点**。每个判定点是:

    什么时候问（触发器）· 它能看什么（证据）· 问什么（问题）
    · 答案怎么变成结果（策略）· 判不出来怎么办（兜底）· 现在生效吗（模式）

这个文件只定义**那张表**,不定义任何一个具体的判定点。
具体的契约写在数据集那一侧（`jloop/contracts.py`），因为**契约是按数据集写的**。

## 为什么触发器和宿主分开声明

★★★ 一个判定点该在什么时候跑,**不是偏好,是它的证据什么时候出现**
（`docs/ENGINE-VS-HOST.md` §1）。所以触发器是契约的一部分。

但"宿主在什么时候发得出这个事件"是**宿主的属性**。两件事分开声明,才谈得上:

  · 换一个宿主(循环宿主 / 流程宿主)不用改契约;
  · 一个触发器这个宿主发不出来 ⇒ **报"放不进去"**,而不是静默不跑。

⚠️ 我们现在的宿主有一个**已知的债**,而且它在这里是**可见的**:
`action.returned`（"上一步的观测拿到了"）它**发晚了** —— 迟到一个 `step.began`
（因为循环在下一步之前才调 `decide()`，见 `_review_last_step`）。
`Host.served_late` 把这件事写下来。**这条债写在数据里,不写在注释里。**
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ═══════════════════════════════════════════════════════════
# 事件词汇表 —— **领域无关**
# ═══════════════════════════════════════════════════════════

#: ★★★ **位置（position）** —— `DECISION.md` 里 `when:` 那一栏的第一个 token。
#:
#: ⚠️ **名字不是我起的,是 `DECISION-CONTRACT.md` §2 已经定下的六个。**
#:   我第一版自己造了一套 `input.received` / `action.returned` 这种"事件名",
#:   理由是"position 是宿主相对的时刻,会把契约绑死在循环上"。
#:   那个理由**不成立**:§4.1 已经写明"节点声明"和"宿主控制流图"分开,
#:   而 position 是**可移植的名字**,由宿主适配器映射到它自己的时刻
#:   （`docs/DECISION-CONTRACT.md` §2「Portable core versus host adapter」）。
#:   ⇒ 两套词汇描述同一个东西,而**同一个东西有两个名字是这个项目最大的阅读成本**。
#:     按用户 2026-10-04 的规范:一个概念只留一个名字。留文档里的那个。
PORTABLE_POSITIONS: tuple[str, ...] = (
    "step-start",       # 一个 step 的开头（可以选下一步做什么了）
    "tool-choice",      # 决定需要动手之后（挑哪个工具）
    "input-choice",     # 选定的工具需要参数时
    "before-call",      # 每次真正调用工具之前
    "after-tool",       # 每次工具执行之后（成没成 / 做完了吗）
    "after-generate",   # 生成之后、答案发出去之前
)

#: 一个位置合法 = 它是那六个之一,**或者**是一个带命名空间的宿主阶段。
#:
#: ★ 命名空间这一档是 §7 给的出口:"A host may add ... a namespaced host phase"。
#:   没有它,非循环宿主（企业流程那种）就没有地方放自己的判定点,
#:   而契约会变成只有循环能用的东西 —— 那正是 §4.1 明说不该发生的。
def is_position(name: str) -> bool:
    return name in PORTABLE_POSITIONS or ("." in name and not name.startswith("."))


#: 结果词表 —— 一个判定点的结果对宿主意味着什么。**也领域无关。**
#:
#: ★ 这一栏是"契约"和"文档"的分界:没有它,一个判定点只说"我问了什么"，
#:   不说"所以呢"。有了它,宿主才知道怎么执行。
EFFECTS: tuple[str, ...] = (
    # 继续（不改变宿主的下一步）
    "proceed",
    # 停下，不再做动作，去收尾
    "finish",
    # 交出去
    "deliver",
    # 打回去重来一次
    "revise",
    # 回去接着做（改道回动作空间）
    "redirect",
    # 这一步不成立，按"没答出来"处理
    "abstain",
    # 停下来问人
    "ask_human",
    # 拒绝执行
    "refuse",
    # 只留痕，不改行为
    "audit",
)

#: 模式 —— 照 μ 的三种。
MODES: tuple[str, ...] = ("off", "shadow", "active")


# ═══════════════════════════════════════════════════════════
# 契约的 schema
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class QuestionSpec:
    """一道题。**题是契约的原子单位** —— 一次请求可以带多道。"""

    #: 题的 id。判定账里 `DecisionRecord.node` 用它的**前缀**
    #: （派生行会加 `::violation` / `::grounding` 这类后缀）。
    node: str
    #: `noul`（是/否，给"答案是的概率"）· `choice`（从枚举里挑）· `score`（打分档）
    kind: str
    #: 问的原话。**逐字,不许两处各写一份。**
    ask: str
    #: `noul` / `score` 的判据。`choice` 的判据按选项算（见 `criteria_from`）。
    criteria: tuple[tuple[str, str], ...] = ()
    #: `choice` 的判据从哪来:一个**注册过的构造器名字**（运行时才知道选项）。
    criteria_from: str = ""
    #: 果断程度门限。`top() >= threshold` 才算数。
    #:
    #: ⚠️ **0 是有意义的值**,不是"没设"。报类型的题（确认 / 反驳）用 0:
    #:   它们不是决定,是报告 —— 只有内容进判据,分寸不进。
    threshold: float = 0.0
    #: 证据长什么样（帧节点名）。空 = 用 `node`。
    frame: str = ""
    #: `choice` 的退出口:一句"以上都不合适"的选项名。**照 μ 的 `policy.ts`。**
    escape: str = ""
    #: `closed_choices=True` = **声明这个候选集真的封闭**（三个立场这种穷尽的选项集）。
    #: 没有退出口又不说封闭 ⇒ `_choice_question` 抛错。
    #:
    #: ⚠️ 名字和 `frame.Question.closed_choices` **对齐**（2026-10-04）。
    #:   契约层原来叫 `closed`,帧层叫 `closed_choices` —— **一个概念两个名字**,
    #:   而用户 2026-10-04 的规范里那条说得最清楚:永远不换同义词。
    closed_choices: bool = False

    def __post_init__(self) -> None:
        if self.kind not in ("noul", "choice", "score"):
            raise ValueError(f"{self.node}: 没有这种题 {self.kind!r}")
        if self.kind == "choice" and not self.escape and not self.closed_choices:
            # ★ 构造处就炸:没有退出口的 choice 会让判官**被迫挑一个真选项,
            #   而且挑得很果断**（μ 的 `policy.ts` 原话）。实测下游是
            #   28 选 1、`top` 贴在门限上、一个命令一轮挑 56 次。
            raise ValueError(
                f"{self.node}: choice 必须有退出口,或者显式声明 closed_choices=True"
                "（见 docs/MU-CONFLICT.md 第 1 行）"
            )
        if self.kind == "score" and self.criteria and self.criteria_from:
            raise ValueError(f"{self.node}: criteria 和 criteria_from 只能有一个")


@dataclass(frozen=True)
class DecisionSpec:
    """一个判定点。**契约的最小可执行单位。**"""

    #: 判定点名。账上、轨迹上、报告里都用这个名字 —— **只用一个名字**。
    id: str
    #: ★ 改了问法或策略就 bump。它进 `decision_spec_digest()`，
    #:   所以"两批是不是同一个方法"这句话是可核对的（`docs/MU-CONFLICT.md` 第 6 行）。
    version: int
    #: **问在哪个位置** —— `PORTABLE_POSITIONS` 之一,或一个命名空间宿主阶段。
    #: 宿主必须声明它服务这个位置（`Host.serves`）。
    position: str
    #: **问哪几道题**（`QuestionSpec.node`）。一次判定点可以问多道。
    questions: tuple[str, ...]
    #: **答案怎么变成结果** —— 注册在宿主策略表里的名字。
    #:
    #: ⚠️ 策略是**代码**（一个纯函数），不是数据。这一点照 μ:
    #:   它的 `policy(answers, input)` 也是一个函数。能把策略写成表的
    #:   我们已经写成表了（`RISK_PATTERNS` / `DELIVERY_CERTIFICATES`），
    #:   写不成的就留成有名字的函数 —— **有名有姓就够,不必假装是数据。**
    policy: str
    #: **判不出来怎么办** —— 兜底表里的名字。照 μ 的 `DecisionSpec.fallback`。
    fallback: str
    #: 这个判定点能产生哪些结果（`EFFECTS` 的子集）。**写在契约里,不写在代码里。**
    effects: tuple[str, ...]
    #: ★★★ **这个判定点的裁决是谁做的。** 照 μ 的 `Decision.source` 那一对，
    #: 但把它提到**契约**这一层 —— 因为"规则先筛、判官只确认"这件事
    #: 就是这一个字段从 `"judge"` 变成 `"both"`（`docs/GATES-RULES-FIRST.md`）。
    #:
    #:   `"rule"`  只有规则,一道题都不问（问了也是白问）
    #:   `"judge"` 裁决由判官产生（`typed-3` 及以前）
    #:   `"both"`  **规则先筛、判官只确认,而且只准收紧**（`typed-4` 默认）
    #:
    #: ★ 有它才能查"这个判定点声明自己是规则、却还问了三道题"这种自相矛盾。
    decided_by: str = "judge"
    #: 现在的模式（`off` = 不问,直接兜底；`shadow` = 问了但不算数）。
    mode: str = "active"
    #: 帧的节点名（证据长什么样）。空 = 用 `id`。
    frame: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if not is_position(self.position):
            raise ValueError(
                f"{self.id}: 位置 {self.position!r} 不合法。"
                f"要么是六个可移植位置之一 {PORTABLE_POSITIONS},"
                f"要么是带命名空间的宿主阶段（`acme.review` 这种,见 §7）"
            )
        if self.mode not in MODES:
            raise ValueError(f"{self.id}: 没有这种模式 {self.mode!r}")
        if self.decided_by not in ("rule", "judge", "both"):
            raise ValueError(f"{self.id}: 没有这种裁决来源 {self.decided_by!r}")
        bad = [e for e in self.effects if e not in EFFECTS]
        if bad:
            raise ValueError(f"{self.id}: 这些结果不在结果词表里 {bad}")


@dataclass(frozen=True)
class Host:
    """一个宿主**声明它服务哪些位置**,以及**服务得准不准**。

    ★ 这一份就是 `docs/DECISION-CONTRACT.md` §4.2 第 9 条要的
      **adapter capability report** —— 那句话的原文是
      "record the node in the adapter capability report",而在这之前
      它只是一句要求,没有东西产出它。
    """

    name: str
    #: 它服务得了的位置（六个可移植位置 + 它自己命名空间的阶段的子集）。
    serves: frozenset[str]
    #: 它自己定义、不在六个可移植位置里的阶段（§7 的出口）。
    phases: frozenset[str] = frozenset()
    #: ★★ **服务得了、但服务晚了的位置** —— 位置名 → 为什么晚。
    #:
    #: 这一栏是**债的账本**。第一版想把它省掉（"反正发得出来"），
    #: 而 `action.returned` 正好是那个反例:循环宿主在**下一步的开头**才发它,
    #: 于是我们写了 `_review_last_step` 去补跑 `stepOk`/`isDone`。
    #: 那条补跑不是设计,是**这个晚发造成的**（`docs/ENGINE-VS-HOST.md` §2）。
    #: 写在数据里,下一个人就不用从代码里把它考古出来。
    served_late: dict[str, str] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# 校验 —— **这是我们的 SHACL**
# ═══════════════════════════════════════════════════════════
#
# semantica 用 SHACL 在**使用之前**拒掉一个不合规的图（`docs/TEXT-TO-CONTROL.md`）。
# 我们需要等价的东西,而且**比它更需要**:它的产物是陈述（错了顶多查错）,
# 我们的产物是**会执行的控制**（错了会改变 agent 的行为）。
#
# ★ 所以校验不是加分项,是必须项。这里返回**问题清单**而不是抛错 ——
#   理由和 `Request.check()` 一样:一条违规要能被**报出来、被人接住**,
#   而不是让调用方在栈里发现它。


def validate(specs: dict[str, DecisionSpec], questions: dict[str, QuestionSpec],
             host: Host) -> list[str]:
    """契约 + 问题表 + 宿主,三样一起查。返回问题清单（空 = 通过）。"""
    problems: list[str] = []

    for sid, spec in sorted(specs.items()):
        if spec.id != sid:
            problems.append(f"{sid}: 契约的 id 是 {spec.id!r} —— 键和字段必须一致")
        # ① 这个位置宿主服务得了吗（服务不了就说出来,不许静默不跑 —— §1 原话:
        #    "A host must not silently ignore an unknown declaration."）
        if spec.position not in host.serves:
            problems.append(
                f"{sid}: 位置 {spec.position!r} 宿主 {host.name!r} 服务不了 ⇒ **放不进去**"
            )
        # ② 题必须都在问题表里
        for q in spec.questions:
            if q not in questions:
                problems.append(f"{sid}: 引用了不存在的问题 {q!r}")
        # ★ 自相矛盾的两条:声明纯规则却问了题 / 声明要问却没题
        if not spec.questions and spec.decided_by != "rule":
            problems.append(
                f"{sid}: decided_by={spec.decided_by!r} 却一道题都没有"
                f"（纯规则的判定点要写 decided_by='rule'）"
            )
        if spec.questions and spec.decided_by == "rule":
            problems.append(
                f"{sid}: 声明 decided_by='rule' 却问了 {len(spec.questions)} 道题 —— 那些题不会有人用"
            )
        # ③ 结果词表非空
        if not spec.effects:
            problems.append(f"{sid}: 没写结果 —— 宿主不知道拿它怎么办")

    # ⑤ 晚服务的位置必须真的在 serves 里（不许把"服务不了"写成"服务晚了"）
    for pos in sorted(host.served_late):
        if pos not in host.serves:
            problems.append(
                f"宿主 {host.name!r}: {pos!r} 写成「服务晚了」但它根本不在 serves 里"
            )

    return problems


def validate_all(contracts: dict[str, dict[str, DecisionSpec]],
                 questions: dict[str, QuestionSpec], host: Host) -> list[str]:
    """**全部契约 + 题表 + 宿主**,一次查完。

    ★ 为什么要跨契约查"题有没有人用":`risk` / `deliverable` / `unsupported`
      只属于 `typed-3`,`risk_confirm` / `deliverable::confirm` / `deliverable::object`
      只属于 `typed-4`。**在一个契约里查,正常的东西会被报成"写了没接"。**
      （第一版就是这么写的,而它一次报了六条假问题 —— 校验器的假阳性
      正是"没人看这个告警"的成因,见 `candidate_already_done` 那次。）
    """
    problems: list[str] = []
    for name, specs in sorted(contracts.items()):
        problems += [f"[{name}] {p}" for p in validate(specs, questions, host)]
    used = {q for specs in contracts.values() for spec in specs.values()
            for q in spec.questions}
    for qid in sorted(questions):
        if qid not in used:
            problems.append(f"问题 {qid!r} 没有任何契约用它 —— 写了没接（§8.15）")
    return problems


def capability_report(specs: dict[str, DecisionSpec], host: Host) -> dict:
    """这份契约在这台宿主上**每一个位置放得下什么** —— 适配器能力报告。

    ★ `docs/DECISION-CONTRACT.md` §4.2 第 9 条要的就是它
      （"record the node in the adapter capability report"）。
      在它存在之前那条只是一句要求,**没有东西产出它** ——
      而"要求写在一处、没有东西产出它"正是 §8.15 那个形状。

    ★ 晚服务的位置**单独列出来**,不并进"服务得了"里。
      理由是实测的:`after-tool` 在这台宿主上晚一个 `step-start`,
      而那就是 `stepOk`/`isDone` 需要 `_review_last_step` 补跑的全部原因
      （`docs/ENGINE-VS-HOST.md` §2）。并进去的话,这笔债就看不见了。
    """
    out: dict[str, dict] = {}
    for sid, spec in sorted(specs.items()):
        entry = out.setdefault(spec.position, {"nodes": [], "served": spec.position in host.serves,
                                               "late": host.served_late.get(spec.position, "")})
        entry["nodes"].append(sid)
    for pos in sorted(host.serves - set(out)):
        out[pos] = {"nodes": [], "served": True, "late": host.served_late.get(pos, "")}
    return out


def dispatch(specs: dict[str, DecisionSpec], position: str) -> tuple[str, ...]:
    """**一个位置上有哪些判定点,以及覆盖顺序。**

    ★★ 顺序不再由代码里的书写顺序决定,而是**查出来的**。
      这是"事件排法"和"步序排法"的实质区别:步序的顺序是免费的,
      但它是**隐含的**;事件的顺序要声明,而声明出来的东西**能被人看、能被改**。
    """
    return tuple(sorted(sid for sid, s in specs.items() if s.position == position))
