"""跨模块共用的词汇。

**这里只有数据形状,没有行为。** 谁都可以 import 它,它不 import 任何人 ——
理由和 `src/vocab.ts` 一样:词汇互相指涉是天然的,但机制之间不该互相依赖。

一个刻意的取舍:**字段用 `tuple` 而不是 `list`**。轨迹是**已经发生的事**,
不该在评分阶段被人悄悄改一个元素 —— 那会让「这个分数是哪次跑出来的」失去意义。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, field
from typing import Any


@dataclass(frozen=True)
class Tool:
    """一个工具。**它属于 benchmark,不属于 baseline。**

    为什么强调这一点:`docs/PLAN-*.md` §2 要求所有 arm「同一批工具、同一份工具描述」。
    把工具的定义权放在 benchmark 一侧,这条要求就是**结构性**的,而不是靠自觉。
    """

    name: str
    description: str
    # JSON Schema 形状。判定模型的候选枚举要靠它，所以**必须是闭集**
    parameters: dict[str, Any]
    #: ★★★ **每步重建的候选** —— 环境自己给的那一份（`None` = 没有）。
    #:
    #: 为什么 `parameters` 里的静态 `enum` 不够:**上一步的动作改变了可选项。**
    #: 实测（2026-09-23,ALFWorld）:一开局 `admissible_commands` 有 **28 条**
    #: （`go to cabinet 1` …），**走到 cabinet 1 之后那 28 条全换了**。
    #: ALFWorld 的 loader 里早就登记过这件事（`alfworld.py::admissible`）:
    #:
    #:     「这是这个数据集上最值得单说的一处:候选每步重建（§8.4）
    #:       在这里**不是优化,是必需**」
    #:
    #: ★ 而在它接上之前,ALFWorld 上的 agent 是**自己编命令**的 ——
    #:   实测它发了 `examine counter` / `use apple` / `go north`,
    #:   这些**根本不是 ALFWorld 的动词**,环境一律回 `Nothing happens.`,
    #:   于是它卡在 `examine counter` 上连调 11 次。**28 条合法命令它一条都没看见。**
    live_candidates: Callable[[], Sequence[str]] | None = None
    #: ★★★ **这个工具自己声明的风险档位**（`None` = 它说不出）。
    #:
    #: 档位见 `jloop/typed.py::RISK_LEGEND`：
    #: `0` 只读 / `1` 可逆写 / `2` 不可逆 / `3` 破坏性。
    #:
    #: 为什么把它做成声明，而不是继续让判定模型猜：
    #:
    #:   `gradeRisk` 的第一条闸门是 `score:risk >= 2 → ask_human`，
    #:   而 `DECISION.md` 明写它是**硬规则、不接受概率绕过**。
    #:   可它的输入一直是一个**概率**（模型给的 `risk` 分）——
    #:   于是"硬"只是靠求值顺序撑着：只要模型把风险判低，那条规则就不会触发。
    #:   实测同一天的注释里就记着这件事：「把风险阈值从 2 提到 3 试图绕开第一条时，
    #:   第二条 `needs_auth=0.95` 兜住了」—— **兜住它的是另一道模型判断**。
    #:
    #:   而风险**本来就是工具的属性**：`delete_file` 是破坏性的，
    #:   这一点不随参数、不随上下文变。让模型去"猜"一个已知的常量，
    #:   就是 §8.2 那个形状——**能查表的东西不要问模型**。
    #:
    #: ★★ **为什么是 `None` 而不是 `0` 作默认**：两者意思完全不同。
    #:   `0` = 「我声明它只读」；`None` = 「**这个工具说不出**」。
    #:   通用工具就是后者：Terminal-Bench 的 `exec` 跑任意 shell、
    #:   ALFWorld 的 `act` 执行任意合法命令 —— 危险与否**取决于这一次的内容**，
    #:   工具本身没有可声明的常量。那种情况仍然要问模型，而且**必须问**。
    #:   把默认值写成 `0` 会让所有通用工具被静默地判成"只读"——
    #:   那正是这套东西最该防的失败。
    base_risk: int | None = None
    #: ★★★ **这个工具的输出里，哪些字符串是环境自己给的成败信号。**
    #:
    #: 两个键（都可以缺）：
    #:   `"failure"`      —— 出现即表示**这一步没成**（ALFWorld 的 `Nothing happens.`）
    #:   `"goal_reached"` —— 出现即表示**目标已经达成**（ALFWorld 的 `[task complete]`，
    #:                       由 loader 依据环境的 `won` 追加）
    #:
    #: ★ 为什么要声明而不是让判定模型去读：这两个信号**是可检索的**
    #:   （`str in observation`），而"这一步成没成""任务做完没有"是模型在猜。
    #:   实测（`docs/GROUNDING-REAL-RUN.md`）刚刚证明过：**能查的东西不要让模型判** ——
    #:   第一版把可检索的检查做成了"问模型 + 校验它指的那一项"，结果误杀了两条
    #:   已经赢了的题（证据里明明写着 `[task complete]`，而模型答"指不出来"）。
    #:
    #: ★ 由**持有环境的 benchmark** 声明，理由同 `base_risk`：这是环境的性质，
    #:   不是控制器的知识。控制器只负责"照着查"。
    observation_signals: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: ★★★ **领域给每一个候选一句"身份"** —— 判官靠它区分选项。
    #:
    #: 实测（2026-10-04，TERNARY）逼出来的:那个数据集的候选是 `d001…d040`,
    #: 而 `pickInput` 的判据来自一张**动词表**（ALFWorld 的领域知识）——
    #: 40 个候选**拿到同一句话**。判官答「一个都不合适」**21/21**(置信度 0.62)。
    #: **它是对的**:帧里、判据里,没有任何东西能区分那 40 个 id。
    #:
    #: ★ 而且这件事**不是帧预算能救的**:把整条请求从 4k 放宽到 32k、
    #:   还补上了 `last_result`,退出口**一次都没少**。**问题是选项本身没有信息。**
    #:
    #: ⇒ 所以每个数据集要**自己说出**它的候选是什么。这里是那个入口:
    #:   一个 `候选值 → 一句话` 的函数,由持有环境的 benchmark 提供
    #:   （和 `base_risk` / `observation_signals` 同一条理由:这是环境的性质,
    #:    不是引擎能猜的）。
    describe_candidate: Callable[[str], str] | None = None
    #: ★★★ **领域声明「这个参数要什么样的值」。**
    #:
    #: 实测（2026-10-04，TERNARY）逼出来的:`search.query` 是**生成**的
    #: （`provider=None` ⇒ `_generate_argument`），而给它的提示只有一句
    #: 「Give only the value for `query` — nothing else」——
    #: **一个字都没说它要的是「语料里字面出现的短语」**。
    #:
    #: 于是模型发出来的是**自己的结论**:
    #:
    #:     search('No value found. The provided corpus does not contain information
    #:             regarding the 2025 revenue of Caldera Metrics.')
    #:     → （没有匹配的行）
    #:
    #: 而语料里**明明有两句**（156 / 201，互相冲突）。
    #: ⇒ `contradiction` 那 5 道**全部**死在这里:**检索根本没发生**。
    #:
    #: ★ 为什么这一栏属于**环境**而不是引擎:它和 `base_risk` / `observation_signals` /
    #:   `describe_candidate` 是同一条理由 —— **领域的事实由环境说,引擎猜不出来**。
    #:   一个 `read_doc` 要 doc_id、一个 `search` 要关键词、一个文件工具要路径:
    #:   三者的形状只有各自的领域知道。
    argument_hints: dict[str, str] = field(default_factory=dict)
    #: ★★★ **这个世界的动作是怎么运作的** —— 环境语义,不是任务脚本。
    #:
    #: 照 `browser-use/jev-ultrafast`（⭐21,934）的 `NEXT_ACTION`：它把 12 条
    #: 浏览器语义写进题里（"不要切换一个已经勾上的开关""提交前先填好字段；
    #: 填好不等于提交了""`DONE` 需要可见证据说明所有要求都满足"）。
    #: μ 的 `browser-step` 照抄了这套。
    #:
    #: ★★ **那条界线必须守住**:`jev-ultrafast` 的 README 明写
    #:   *"There are **no site-specific action scripts or prepared field strings**"* ——
    #:   ⇒ 规则要写**「这个环境的语义」**,不能写**「这个任务的脚本」**:
    #:
    #:      ✅ 环境语义（凡是带容器的世界都这样）:先 open 才能 take;先 take 才能 put;
    #:         先 clean/heat/cool 才能 put
    #:      ❌ 任务脚本（在数据集上过拟合）:把 Vase 放进 Safe 219
    #:
    #:   这条界线是**"可泛化"和"过拟合数据集"的分界**,也决定它能不能进指纹。
    #:
    #: ★ 为什么属于环境而不是引擎:和 `base_risk` / `observation_signals` /
    #:   `describe_candidate` / `argument_hints` 同一条理由 —— **领域的事实由环境说**。
    action_rules: str = ""


@dataclass(frozen=True)
class Task:
    """一道题。`gold` 只给评分器看,不给 agent 看。"""

    task_id: str
    prompt: str
    gold: Any = None
    # 数据集自带的、可供裁判的证据（金标检索结果等）。`direct + 金标证据` 那一臂用它
    oracle_context: str | None = None
    # ★ **这一道题自己的工具集。**
    #   有些数据集每题给的函数不同（BFCL 就是:每条自带 `function`）,
    #   给一个全局 `tools()` 会让模型去调一个这道题根本没给它的函数。
    #   空元组 = 用 `Benchmark.tools()` 那个全局兜底。
    tools: tuple[Tool, ...] = ()
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Action:
    """agent 做的一件事。`kind` 只有三种,别加第四种。

    - `tool`  调一个工具。`name` + `arguments`
    - `answer` 交答案。`content`
    - `ask`    该问人 / 该弃答。**这是我们的设计独有的一种动作**,
              评测里必须能被看见,否则「拒答率」这个指标算不出来
    """

    kind: str
    name: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    content: str = ""


#: 伪工具的名字前缀。**它们不是函数调用,是循环控制。**
PSEUDO_TOOL_PREFIX = "__"


#: ★★★ **宿主自己的伪步骤,不是环境观测。** 现在是 `run_loop` 解析不出动作时
#: 塞进去的那一步,好让下一轮的 prompt 带上纠正提示。
#:
#: ★ 为什么它必须能被**点名**:实测（2026-10-04,Ternary）它泄漏进了 `evidence` ——
#:   判官的材料里出现 `__parse_error__() -> Could not parse an action.`,
#:   于是模型如实报告"文档读取过程中有解析错误",而**闸门判它 `overclaim`**:
#:   因为 `read_doc` 其实**读成功了**,那个解析错误是**我们自己的**。
#:   ⇒ 一条**我们工具链的失败**,经模型的嘴,变成了模型的一次编造,然后被我们的闸门罚。
#:   这是一条纯人工的因果链,而它只在把闸门的输入原文打出来时才看得见。
HARNESS_PSEUDO_TOOLS: tuple[str, ...] = ("__parse_error__",)


def is_harness_pseudo_step(step: "Step") -> bool:
    """这一步是**宿主自己**造出来的,不是环境里的一个动作。"""
    return (step.action.name or "") in HARNESS_PSEUDO_TOOLS


def is_tool_call(action: "Action") -> bool:
    """这一步**真的调了一个工具**吗?

    ★★ 为什么需要它,以及它是怎么被发现的（2026-09-22,`bfcl-v3-multiple`）:

    `run_loop` 在解析不出动作时会往轨迹里塞一步
    `action_tool("__parse_error__", {})` —— 好让**下一轮的 prompt 里带着纠正提示**。
    它的 `kind` 是 `"tool"`,因为 `Action.kind` **只有三种,不许加第四种**。

    于是**任何一个「数一下调了几次工具」的地方都会把它算进去**。BFCL 的判分器就是:

        called = [s.action.name for s in trajectory.steps if s.action.kind == "tool"]

    ⇒ 一步解析失败 + 一次正确调用 → `called = ['x', '__parse_error__']` ≠ 金标
      → **判成 `wrong_tool`,而那一步其实调对了。**

    ★ 而它**不产生 `ToolCallEvent`**（伪步骤不过 executor）——
      所以**工具事件里看不见它,只在 `steps` 里**。这就是为什么它藏了这么久。

    ★ 我当时在 `alfworld` 里手写了 `and not str(s.action.name).startswith("__")`,
      而 BFCL 里没写 —— **同一条规则在两处、只写了一处。** 所以它现在住在这里。
    """
    return action.kind == "tool" and not str(action.name).startswith(PSEUDO_TOOL_PREFIX)


@dataclass(frozen=True)
class Step:
    """一步 = 一个动作 + 它的观察。`decision_ms` / `model_ms` 逐层留,理由见 PROTOCOL §3.4。

    ★ `thought` 是 ReAct 的 `Thought:` 那一行。**它必须存在这个类型里**,
    否则 scratchpad 渲染不出来,而「ReAct 的 thought 到底有没有用」这个消融
    就无从做起 —— 我们现有的 `bench/react.ts` 正是漏了它,于是跑出来的是 act。
    """
    index: int
    action: Action
    observation: str = ""
    thought: str = ""
    # ★ 逐调用的时间**只在事件流里存一份**（`ModelCallEvent.timing` /
    #   `ToolCallEvent.working_time`）。这里再放一份 `model_ms` 就是
    #   「同一个量两处」—— 而且它是从控制器里取出来的,循环已经看不到那次调用了。
    #   `decision_ms` / `tool_ms` 同理,它们也各自有事件。



@dataclass(frozen=True)
class Trajectory:
    """一次运行的完整记录。**评分只看它** —— 所以它必须够全,足以重算任何指标。"""

    task_id: str
    arm: str
    steps: tuple[Step, ...] = ()
    final_answer: str | None = None
    # 逐判定一行：{node, answer, confidence, correct, batch, latency_ms}
    # ★ `confidence` 和 `correct` 必须在同一行 —— RQ2 全部指标从这一对算
    decisions: tuple[dict[str, Any], ...] = ()
    # 逐调用一行，见 PROTOCOL §3.4
    usage: tuple[dict[str, Any], ...] = ()
    escalated: bool = False
    error: str | None = None


@dataclass(frozen=True)
class Judgment:
    """评分结果。`correct` 是我们唯一需要的真假,其余是给人看的。"""

    correct: bool
    score: float = 0.0
    detail: str = ""
    # 失败分类（PLAN §3.8）。**逐条打标,不许只报总数**
    failure_class: str | None = None
