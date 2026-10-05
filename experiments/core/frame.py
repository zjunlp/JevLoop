"""★ **决策帧 —— 判定模型看得见的那一份有界状态。**

## 为什么这个文件值得单独存在

`AGENTS.md` §8.2:**帧里没有的,它判不出来** —— 不是判错,是压根看不见。
而我们的三次事故**全部出在帧上**,没有一次是判定模型的问题:

| 事故 | 帧错在哪 | 症状 |
|---|---|---|
| `canDeliver` 把工具结果 clip 到 **100** 字符 | 帧喂少了 | 判定**正确地**判出 `unsupported=0.67`;改成 600 立刻通过 |
| `stepOk` 的帧里**带着 `task`** | 帧喂多了 | 被判到任务级,`ok=0.470` 判否 → `stop` → **任何多步任务都跑不完** |
| `needsTool` 给的是 `steps_done: 2`（**计数**）| 形状不对 | 分不出「读过了」和「写过了」→ 写任务里文件从没被写出来 |

**三次都改对了判定,但看起来像判定错了。** 所以帧不能是「各调用点手拼的一个 dict」——
那样上面三处**没有任何办法被复查**。

## 所以:帧是**声明**出来的,不是拼出来的

```python
FrameSpec(
    node="step_ok",
    fields=(FrameField("last_tool", label="tool"),
            FrameField("last_input", label="input"),
            FrameField("last_result", label="output")),
    # ★ 显式声明「本节点故意不看什么」,以及为什么
    excluded=(("task", "判的是这一步,不是这个任务 —— 带上它会被拉到任务级（实测）"),),
)
```

**`excluded` 是这份设计里最值钱的一栏。** 三次事故里有两次是「不该看的看了」,
而删掉一个字段之后**没有任何东西记得它曾经在过** —— 声明出来,下一个人才知道为什么不能加回去。

## 和 TS 那份的关系（★ 必须对齐,`AGENTS.md` §8.7.2）

`JevLoop/src/frame.ts` 是**权威**。Python 这份是它的**推广**,差别只有一处:

| TS 的 `AgentCtx` | 为什么它不通用 | 这里 |
|---|---|---|
| `files` / `readFiles` | 那是**文件工具**特有的 | 改成「候选由每个工具的 `candidates(ctx)` 算」—— 换成检索 / API / 环境动作都成立 |
| `canWrite` | 同上（`write_file` 有没有内容来源）| 同上,归候选提供方 |

其余字段（`task` / `history` / `earlier` / `lastTool` / `lastResult` / `draft`）**逐字保留**。

★ `AGENTS.md` §8.7.2 重写 `verify:port` 时,**这里就是行为对照的主要对象**:
桩掉判定模型,两份实现跑同一批输入,**每一步的帧必须逐字相同**。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from experiments.core.types import Step, Tool, is_harness_pseudo_step

# ═══════════════════════════════════════════════════════════
# 词汇
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StepRecord:
    """历史里的一步。**和 TS 的 `StepRecord` 逐字对齐**（`step` / `tool` / `input` / `result`）。"""

    step: int
    tool: str
    input: str
    result: str

    def __str__(self) -> str:
        """★★★ **帧里的人话版** —— 不这样,模型看到的是 dataclass 的 repr。

        实测（2026-09-23,`multiple_68`）:`clip="list"` 走
        `", ".join(str(x) for x in items)`,于是 `already_done` 那一行是::

            already_done: StepRecord(step=0, tool='library.search_books', input='',
                          result='(BFCL scores the call itself rather than...')

        **204 个字符,主体是 Python 语法,而且把 `last_result` 逐字重复了一遍。**
        可帧要回答的是「**任务要求的事做完没有**」—— 交给模型的却是对象 dump。

        ★ 分工:**这里给形状**(调过什么、按什么顺序),**`last_result` 给细节**
          (最近一次到底返回了什么)。

        ★★★ **2026-10-05：每条的 60 字符截断删掉了。** 它原本的理由是
          「两份都全给等于同一段话出现两遍，白占预算」。实测那个理由不成立：
          窗口 131,072 字符，我们最大的一条请求 5,153（4%）；
          而 60 字截断把 `You open the safe 1. … In it, you see a...`
          **切在物品清单上** —— 一格有 1 件东西记得住、有 2 件以上一件都看不见。
          「找花瓶」正是要翻多物品的容器。**省下 9% 换掉最要紧的信息，不划算。**
        """
        arg = f"({self.input})" if self.input else "()"
        res = " ".join(self.result.split())
        return f"{self.tool}{arg} -> {res}" if res else f"{self.tool}{arg}"


@dataclass
class AgentCtx:
    """agent 的**可观测状态** —— 帧的原料池。

    ★ 这里**没有 `gold`**、没有 reward、没有数据集内部字段。
    和 `DecisionView` 只带 `task_id` 是同一条理由:**接口上拿不到,比约定不许强**。
    """

    task: str = ""
    history: tuple[StepRecord, ...] = ()
    # 之前几轮**问过什么**,压成一句话。判定要的是**指代关系**
    # （「再读一遍那个文件」里的「那个」）,不是上一轮的完整经过。
    earlier: str = ""
    last_tool: str = ""
    last_input: str = ""
    last_result: str = ""
    # 生成出来的回答 —— `canDeliver` 用它
    draft: str = ""
    # 每个工具的候选参数（`None` = 这个工具不用挑参数）。
    # ★ **每步重建** —— 固定的候选会让模型去选一个已经不适用的动作（§8.4）。
    candidates: dict[str, list[str]] = field(default_factory=dict)
    # 候选被窗口截断时**必须明说**（TS 的 `MAX_FILE_OPTIONS = 20` 那条）
    #: ★★★ **还剩哪些动作没做** —— 工具名的列表，由调用方每步重算。
    #:
    #: `needsTool` 问的是「这个任务还有没有没做的动作?」，
    #: 而它的帧原来只有 `already_done`（**做过什么**）——
    #: **问「还有没有」却不给「有哪些」**，模型只能从「做过的」反推，那是猜。
    #:
    #: 实测（2026-09-22,`bfcl-v3-multiple × react-typed`）：调对了唯一合适的工具之后，
    #: `needsTool` 仍判「还要动作」（0.73），于是又调了一个语义邻居 ——
    #: 10 条 `wrong_tool` 全是这个形状。
    remaining: tuple[str, ...] = ()

    #: ★★ **调过的工具各自是干什么的** —— 已经渲染成文本,直接进帧。
    #:
    #: 为什么需要它:`needsTool` 要判「任务要求的事做完没有」,
    #: 而它原来只拿到工具**名字**::
    #:
    #:     already_done: library.search_books({'location': 'New York public library'})
    #:
    #: `library.search_books` 是一个光秃秃的标识符 —— **它不知道这个工具能做什么**,
    #: 只能从名字猜「search_books 够不够回答『找一本历史小说』」。
    #: 而 `pickTool` 那边**有**描述（`criteria` 的值）。
    #:
    #: ★ 这是**通用**的,不是 BFCL 特有的:任何数据集上,判「覆盖了没有」
    #:   都需要知道那个工具**做什么**,而不只是它**叫什么**。
    done_tools: str = ""

    #: ★★★ **工具证据** —— 已经渲染成文本,给 `canDeliver` 用。
    #:
    #: 为什么需要它（2026-09-23 查出来的「静默缺席」）:`canDeliver` 判的是
    #: 「回答有没有说**工具输出不支持**的内容」,而它的帧里**没有任何工具输出**
    #: —— 只有 `task` + `draft`。**它既没看 `last_result`、也没声明不看。**
    #:
    #: 实测（ALFWorld `pick_heat_then_place_in_recep-Apple-None-Fridge-10`）:
    #: 任务要「把**加热过的**苹果放进冰箱」,agent 只走了一步（冰箱还关着）,
    #: 然后交了「I placed the microwaved apple in the fridge.」—— **编的**,
    #: 而 `escalated=False`,没有任何东西拦它。交付闸门**本该**拦住这句,
    #: 可它看不见任何工具输出,于是那句完成报告在帧里**没有任何反证**。
    #:
    #: ★ 和 `done_tools` 同一个形状:**判一件事,就得把这件事的材料放进帧**。
    #:   但两者的形状不同 —— `done_tools` 是「这些工具是干什么的」（覆盖),
    #:   这里是「这些调用**到底返回了什么**」（核对）。所以是两个字段。
    #:
    #: ★ 它和 `excluded` 里的 `history` 不冲突:**过的是证据,不是整段历史** ——
    #:   条数、每条各自的输入/结果预算都由 `render_evidence()` 定,
    #:   而整段 `history` 会把回答（`draft`,闸门的判定对象）挤出帧。
    evidence: str = ""

    #: ★★★ **上一次交付被打回的理由** —— 只在**改道**之后的那个动作步上有值。
    #:
    #: 为什么需要它：交付闸门判出"任务没做完"时，它**知道缺什么**（它读了草稿和
    #: 任务要求），而改道把控制流送回动作路径时，那条信息原来**被扔掉了** ——
    #: 于是 `pickTool` 看到的是和之前**一模一样**的帧，它不知道刚刚有一份交付
    #: 被打回、也不知道缺的是哪一块。**那是盲改道。**
    #:
    #: ★ 和 `done_tools` / `evidence` 同一个形状：**判一件事，就得把这件事的材料
    #:   放进帧**。这里要判的是"选哪个动作能补上缺的那一块"，材料就是"缺什么"。
    #:
    #: ⚠️ 只在改道之后的**那一步**有效。动作执行完、下一次 `decide()` 重建 ctx 时
    #:   它就没了 —— 因为那时已经有了新证据，旧的驳回理由不再是当前状态。
    redirect_note: str = ""
    #: ★★★ **索引化的候选表** —— 照 `jev-ultrafast::action_space`:
    #: "One index per observed element"。**表进状态,题里只引用索引。**
    #:
    #: 我们原来是"从一串命令里挑一个字符串",于是每个候选的说明都要在题里
    #: 重写一遍,而且**候选自己没有状态**。表只讲一次。
    action_table: str = ""
    #: ★★★ **环境的动作语义**（见 `Tool.action_rules`）—— 进状态,只讲一次,
    #: 而不是在 N 道题里各重复一遍（那是 N 倍预算,而合并的判据是"共享一份状态"）。
    action_rules: str = ""

    def records(self) -> list[StepRecord]:
        return list(self.history)


def render_tool_input(arguments: Any, content: Any = "") -> str:
    """一次工具调用的输入，**给判定模型看的那个形状**。

    ★★★ 原来这里是 `str(s.action.arguments)` —— 也就是**把 dict 原样 str 出来**。
    实测（2026-10-10，把完整请求体打出来才看见）：

        already_done: {'command': 'open microwave 1'}) -> You open the microwave 1. …

    三处后果，一处比一处严重：

      ① **判官读的是 Python 语法**，不是命令。`already_done` 那一行被
         `{'command': …}` 这种字面量吃掉预算 —— 实测 `history: 400→300`，
         也就是**同样的步数会更早被截掉**。
      ② `gradeRisk` 的 `target`（`FrameField("last_input", label="target")`）
         同样是这个字面量 —— 风险判定看的是 `{'command': 'rm -rf /'}`。
      ③ ★★★ **`candidate_already_done` 这条检查对 `pickInput` 静默失效**：
         它拿 `r.input`（字典串）去和 `question.options`（命令原文）求交集，
         **永远为空**。于是一条本该报警的检查变成了死信 ——
         而"没人看的告警"正是它当初要防的东西。

    ★ 判据：**单参数用它的值**（那才是"这一步做了什么"），
      多参数用 `k=v` 对。枚举候选那一侧给的也是裸值（`options` 里就是
      `go to cabinet 1`），两边形状必须一致，交集才有意义。
    """
    if arguments:
        if len(arguments) == 1:
            return str(next(iter(arguments.values())))
        return ", ".join(f"{k}={v}" for k, v in sorted(arguments.items()))
    return str(content or "")


def ctx_from_steps(task: str, steps: Sequence[Step], *, draft: str = "",
                   earlier: str = "") -> AgentCtx:
    """从轨迹拼出一个 `AgentCtx`。

    ★ **`result` 用观察原文,不预截** —— 截多少是**帧的预算**说了算
    （`FrameField.budget`）,不是这里说了算。在两处截会得到两套口径,
    而 `canDeliver` 那次事故就是「截了但没人知道截了多少」。
    """
    # ★★★ **宿主自己的伪步骤不进帧**（2026-10-04，Ternary 实测）。
    #
    #   `run_loop` 解析不出动作时会塞一步 `__parse_error__`（好让下一轮 prompt
    #   带上纠正提示）。它**不是环境观测**,而 `records()` 返回整个历史 ⇒ 它进了
    #   `evidence` ⇒ 判官读到"Could not parse an action" ⇒ 模型如实报告
    #   "文档读取过程中有解析错误" ⇒ **闸门判它 `overclaim`**。
    #   而 `read_doc` 其实**读成功了** —— 那个解析错误是我们自己的。
    #
    #   ⇒ 一条**我们工具链的失败**,经模型的嘴,变成模型的一次编造,再被我们的闸门罚。
    #   ★ 它**仍然留在 `steps` 里、仍然进事件流** —— 那是给下一轮 prompt 用的纠正提示,
    #     不是给判官的证据。两件事不该混。
    history = tuple(
        StepRecord(step=s.index, tool=s.action.name or s.action.kind,
                   input=render_tool_input(s.action.arguments, s.action.content),
                   result=s.observation)
        for s in steps
        if not is_harness_pseudo_step(s)
    )
    last = history[-1] if history else None
    return AgentCtx(
        task=task, history=history, earlier=earlier, draft=draft,
        last_tool=last.tool if last else "",
        last_input=last.input if last else "",
        last_result=last.result if last else "",
        # ★★ **工具证据在这里就装配好** —— 不是留给调用方记得拼。
        #   第 10 轮 R2/R5 的教训是「一条不变量没人接收就等于没有」;
        #   同一条道理:一个字段要调用方**记得**填,它迟早会是空的,
        #   而空帧的判定看上去和一次正常判定一模一样（§8.10）。
        evidence=render_evidence(history),
    )


def render_evidence(history: Sequence[StepRecord], *,
                    last: int | None = None, input_chars: int | None = None,
                    result_chars: int | None = None) -> str:
    """把最近几步的**工具调用与它们的返回**渲染成 `canDeliver` 的判定材料。

    ★★ 这个名字和 `StepRecord.__str__()`（帧里的人话版）分开,因为两者回答的
    问题不同:

    - `already_done` 给的是**形状** —— 调过什么、按什么顺序（每条结果只留 60 字符,
      细节交给 `last_result`）。它服务的是「任务做完没有」。
    - 这里给的是**证据** —— 交付闸门要拿它逐句核对回答,所以**结果才是主体**:
      「回答里那句『我把苹果放进了冰箱』,哪一次调用的返回支持它?」

    ★ **预算跟着载荷走,不跟着位置走**（TS 侧 `canDeliver` 的注释里记着这次事故）:
    写操作的载荷在**输入**（`路径\\n内容`）而结果只有一句「已写入 X」;
    读操作正好反过来。输入一律 clip 到 60、或者结果一律 clip 到 200,
    都会让**唯一有信息的那半**被切掉,于是闸门**正确地**判出
    「回答里有证据不支持的内容」—— **那是帧的问题,不是回答的问题。**

    ★ 只取最后 `last` 条:再往前的调用,结论已经被后面的覆盖了,
      而多给一条就少给 `draft`（判定对象本身）一份预算。

    ★★★ **2026-10-05：`last` / 每条的字符上限全部改成"不限"（`None`）。**
      理由同 `StepRecord.__str__`：窗口 131,072 字符而我们只用 4%，
      而"只给最后 3 条、每条 200 字符"会让闸门**核不了早先那几次调用** ——
      它要回答的正是「回答里那句『我把它放进去了』是哪一次调用支持的」。
      显式传数字仍然生效（老调用点没变语义），只是默认值不再砍。
    """
    recent = list(history) if last is None else list(history)[-last:]
    out: list[str] = []
    for i, rec in enumerate(recent):
        writes = rec.tool in ("write_file", "write", "write_text")
        inp = clip_text(rec.input, 600 if writes else input_chars)
        # 最后一条给足空间:回答里的完成报告,核对的正是**最后一次**返回了什么
        cap = 60 if writes else (result_chars if i == len(recent) - 1 else 200)
        res = clip_text(rec.result, cap if result_chars is not None else None)
        out.append(f"{rec.tool}({inp}) -> {res}" if res else f"{rec.tool}({inp})")
    return "\n".join(out)


def clip_text(text: str, budget: int | None) -> str:
    """截成 `budget` 字符,**截了就留下痕迹**。`budget=None` = 原样返回。

    ★ 痕迹不能省:判定模型看不到「这里少了 900 字」,它会当成「证据就这么多」
    —— `canDeliver` 那次事故（clip 到 100 → `unsupported=0.67`）正是这个形状。
    帧那一层由 `compile_frame` 统一记账（`truncations`）,这里管的是**帧内部**
    再切一刀的两处（`history` 的每条、`evidence` 的每条）。
    """
    text = " ".join(str(text).split())
    if budget is None or len(text) <= budget:
        return text
    return text[:budget] + f"…[+{len(text) - budget}]"


@dataclass(frozen=True)
class FrameField:
    """帧里的一个字段。

    `budget` 是**字符**上限;`None` = **不限**（2026-10-05 起是默认）。
    `clip` 决定超预算怎么截,而**截了多少必须报出来**（见 `Frame.truncations`）。

    ★★★ **为什么默认从"有上限"改成"不限"**：立项时这里写着
    「判定模型的上下文只有 512/1024 token」—— **那句话错了 32 倍**。
    2026-10-05 实测 `api.typesafe.ai/v1/systemone`：
    状态 **131,072 字符**（= 2¹⁷ = 32K token）可以，**131,500 就 HTTP 400**。
    （μ 的 `decision.ts` 也写着 *"The judge has a 32K window"* —— 两边独立吻合。）

    而实测我们**真正发出去的最大请求只有 5,153 字符**，用掉窗口的 **4%**。
    那条 ALFWorld 题 27 步的观察全量 4,807 字符，按旧的 60 字符/条截断后
    4,394 —— **只省了 413 字符（9%），却把「哪一格有什么」切没了**。
    ⇒ 上限没省下东西，只是让判官看不见证据。所以逐字段上限全部去掉，
    只留**一个**请求级闸门对着那面真实的墙（见 `MAX_REQUEST_CHARS`）。
    """

    name: str          # `AgentCtx` 上的字段名
    #: 字符上限。`None` = 不限（默认）。保留这一栏是因为**截断必须报出来**
    #: 这条不变量还在用 —— 显式给了预算的地方照样会记账并进判官正文。
    budget: int | None = None
    label: str = ""    # 进给判定模型时那行字
    # tail: 留尾巴（证据通常是**后面**才是结论）；head: 留开头；list: 只留前 N 条
    clip: str = "tail"
    #: ★★ 这个字段是**判定的依据**吗?
    #:
    #: `True` = 节点判的就是它,缺了**没有对象可判**（`stepOk` 没有 `last_result`、
    #: `canDeliver` 没有 `draft`）→ 缺席要让请求**发不出去**。
    #:
    #: `False`（默认）= 它只是**上下文**,缺席是**正常状态**:第 0 步本来就没有
    #: `last_result`,`draft` 在生成之前本来就不存在。
    #:
    #: **为什么必须分开**:两类缺席混在一起报,结果是这条不变量**每一步都在响**,
    #: 而那唯一一次真的缺了依据（`canDeliver` 的证据被 clip 到 100 字符,
    #: 闸门**正确地**判出 `unsupported=0.67`）就淹没在噪声里。
    #: 「天天误报」和「没有这条检查」在效果上没有区别 —— 两种都不再有人看。
    required: bool = False


@dataclass(frozen=True)
class FrameSpec:
    """**一个节点的帧声明。** 这是 §8.2 从「注释」变成「可复查的产物」的地方。"""

    node: str
    fields: tuple[FrameField, ...]
    # ★ 「本节点故意不看什么」+ 为什么。**删掉一个字段之后没有东西记得它来过**,
    #   而三次事故里有两次就是「不该看的看了」。
    excluded: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Frame:
    """编好的帧。**它自己记得被截断和被省略的东西。**"""

    node: str
    lines: tuple[str, ...]
    # 字段名 → 截断详情。旧字段仍是 (原长, 实际长)；
    # 另存 count_truncations，避免数量与字符截断互相覆盖。
    truncations: dict[str, tuple[int, int]]
    count_truncations: dict[str, tuple[int, int]]
    # 声明了但**这次没拿到**的字段（`AgentCtx` 上是空的）
    missing: tuple[str, ...]
    # ★ 上面那些里,**判定真的靠它**的那些（`FrameField.required`）。
    #   渲染时两者一视同仁（缺了就得说）,但**只有这一份**拦请求。
    missing_required: tuple[str, ...]
    # ★ 声明里明说「不看」的字段 —— 一起进日志,这样「这一格当时看到什么」可核对
    excluded: tuple[tuple[str, str], ...]

    def render(self) -> str:
        """进给判定模型的正文。

        ★ **被截断的字段要在正文里留下痕迹。** 判定模型看不到「这里少了 900 字」,
        它会当成「证据就这么多」—— 而 `canDeliver` 那次事故正是这个形状。
        """
        out: list[str] = []
        for line in self.lines:
            out.append(line)
        if self.truncations:
            parts = [f"{k}: chars {was}→{now}" for k, (was, now) in sorted(self.truncations.items())]
            out.append(f"(truncated — {'; '.join(parts)})")
        if self.count_truncations:
            parts = [f"{k}: items {was}→{now}" for k, (was, now) in sorted(self.count_truncations.items())]
            out.append(f"(truncated — {'; '.join(parts)})")
        if self.missing:
            out.append(f"(absent — {', '.join(self.missing)})")
        return "\n".join(out)

    def digest(self) -> str:
        """帧的指纹,**进日志**。

        两次运行如果帧不一样而没人发现,那「同一个方法」这句话就不成立。
        """
        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()[:16]


# ═══════════════════════════════════════════════════════════
# 编译 —— 唯一的入口
# ═══════════════════════════════════════════════════════════

#: ★★★ **候选列表的上限删掉了（2026-10-05）。**
#:
#: 原来是 20：超过就不再列全，但**必须明说**。删它的理由和逐字段上限同一条 ——
#: 实测窗口 131,072 字符、我们最大请求 5,153（4%），
#: 而 ALFWorld 一步就有 21–32 条合法命令，**截到 20 条等于把合法动作藏起来**：
#: 判官会答"这些都不合适"，而它其实只是没看见第 21 条。
#: 留下来的 `Frame.count_truncations` 机制不变（显式给预算仍会记账）。
MAX_LISTED_CANDIDATES = None


def _clip(text: str, budget: int | None, mode: str) -> tuple[str, int]:
    """返回 (裁过的文本, 原长)。**不在这里决定要不要报** —— 报是 `compile_frame` 的事。

    `budget=None` = 不裁,原样返回（并把原长一并交回,于是不会记账）。
    """
    original = len(text)
    if budget is None or original <= budget:
        return text, original
    if mode == "head":
        return text[:budget], original
    return text[-budget:], original


def compile_frame(spec: FrameSpec, ctx: AgentCtx) -> Frame:
    """把状态投影成**有界**的帧。

    ★ 三条不变量,每一条都对应一次事故:

    1. **有界** —— 每个字段按 `budget` 截,截了就报（`canDeliver` 那条）
    2. **只给声明的字段** —— 没在 `fields` 里的**一个都不进**（`stepOk` 那条）
    3. **缺的要说** —— 声明了但 `ctx` 上是空的,记进 `missing`,**不静默留白**
       （留白会让判定模型以为「证据就这么多」）

    ★ 第 3 条要分两档（`FrameField.required`）:**判定的依据**缺了,
    这次判定没有对象;只是**上下文**的字段缺了,那本来就可能是正常状态。
    两档都渲染（缺了就得说）,但只有前一档进 `missing_required`。
    """
    lines: list[str] = []
    truncations: dict[str, tuple[int, int]] = {}
    count_truncations: dict[str, tuple[int, int]] = {}
    missing: list[str] = []
    missing_required: list[str] = []

    for spec_field in spec.fields:
        raw = getattr(ctx, spec_field.name, None)

        if raw is None or (isinstance(raw, str) and not raw.strip()):
            missing.append(spec_field.name)
            if spec_field.required:
                missing_required.append(spec_field.name)
            continue

        if isinstance(raw, (list, tuple)):
            items = list(raw)
            if MAX_LISTED_CANDIDATES is not None and len(items) > MAX_LISTED_CANDIDATES:
                # ★ 截断候选**必须明说** —— 模型会以为「就这些」
                #   （`MAX_LISTED_CANDIDATES` 现在是 `None` = 不截；这一支留给
                #     将来显式设了上限的场合，机制本身不删。）
                count_truncations[spec_field.name] = (len(items), MAX_LISTED_CANDIDATES)
                items = items[:MAX_LISTED_CANDIDATES]
            # ★ **空的列表是一个事实,不是一处空白。**
            #   `actions_left:` 后面什么都没有,和「这个字段没喂上」在渲染上
            #   长得一模一样 —— 而判定模型分不出,它会当成「这里没东西」。
            #   这正是 §8.15 那条 `Frame.missing` 的形状:报不出「没有」和
            #   「忘了喂」的检查,等于没有检查。
            body = ", ".join(str(x) for x in items) if items else "(none)"
        else:
            body = str(raw)

        body, original = _clip(body, spec_field.budget, spec_field.clip)
        if original > len(body):
            truncations[spec_field.name] = (original, len(body))
        lines.append(f"{spec_field.label}: {body}")

    return Frame(node=spec.node, lines=tuple(lines), truncations=truncations,
                 count_truncations=count_truncations,
                 missing=tuple(missing), missing_required=tuple(missing_required),
                 excluded=spec.excluded)


# ═══════════════════════════════════════════════════════════
# 七个节点的帧声明
#
# ★★★ **2026-10-05：逐字段预算全部删掉（`budget=None`）。**
#   原来这里写着「预算逐字抄自 TS 侧」，而那张表的前提
#   （「判定模型上下文只有 512/1024 token」）**错了 32 倍**。
#   实测窗口 131,072 字符、我们最大请求 5,153（4%），
#   最坏情况的一帧 6,971 字符（闸门的 5.8%）——
#   ⇒ 上限没在防任何东西，只在切掉证据。
#   保留的是**机制**：显式给了 `budget` 的地方照样记账 + 进正文提示。
# ═══════════════════════════════════════════════════════════

NODE_FRAMES: dict[str, FrameSpec] = {
    "needsTool": FrameSpec(
        node="needsTool",
        fields=(
            # 判的就是「这个任务还有没有没做的动作」—— 没有 task 就没有对象可判
            FrameField("task", label="task", required=True),
            FrameField("last_tool", label="last_tool"),
            FrameField("last_result", label="last_result"),
            # ★ 是一份**清单**,不是一个计数 —— `steps_done: 2` 那种写法分不出
            #   「读过了」和「写过了」（实测：写任务里文件从没被写出来）
            FrameField("history", label="already_done", clip="list"),
            # ★ 「调过的工具能做什么」—— 判「任务被满足了吗」的依据。
            #   名字 + 历史只说明**调过什么**,说明不了**覆没覆盖**。
            FrameField("done_tools", label="done_tools"),
            # ★★ **改道时才有值**：上一次交付被打回的理由。判"还有没有没做的动作"
            #   时，这是最直接的依据 —— 闸门刚刚说了"没做完"。空着 = 正常正向路径。
            FrameField("redirect_note", label="redirect_note"),
        ),
        excluded=(("draft", "还没生成,这时没有 draft"),),
    ),
    "pickTool": FrameSpec(
        node="pickTool",
        fields=(
            FrameField("task", label="task", required=True),
            # ⚠️ **不是** required:第 0 步本来就没有上一步的结果。
            #    标成 required 会让这条不变量每一步都响,然后被无视。
            FrameField("last_result", label="last_result"),
            # ★★★ **「还剩哪些动作」** —— 实测（2026-09-23,101 个 pickTool 判定点,
            #   逐条重放同一批请求、只换帧）:
            #
            #   | 帧 | 离 0.6 门限中位 | 贴门限(<0.15) | 答案变了 |
            #   |---|---|---|---|
            #   | `task`+`last_result`（原来）| 0.280 | **12%** | — |
            #   | + `remaining`（这一条）     | 0.350 | **2%**  | **0/101** |
            #   | + `history`                 | 0.330 | 4%    | 1/101 |
            #   | + 两个都加                   | 0.370 | 3%    | 1/101 |
            #
            #   ⇒ **把证据喂厚,判定就离开门限**:贴门限的从 12% 掉到 2%,
            #     而**答案一条没变** —— 变的不是「判什么」,是「判得多稳」。
            #     §8.17 那条「判定贴在门限边上」说的是同一个东西。
            #
            #   ★ 为什么选它而不是 `history`:`history` 的边际也有效（0.280→0.330）,
            #     但它会**翻掉一条答案**（`multiple_18 step1`:`war_details(0.71)`
            #     → `__done__(0.59)`——方向是对的,可是 0.59 低于 0.6,策略会
            #     `escalate` 而不是收工),而「两个都加」翻的那条是**坏的**
            #     （`modify_columns` → `create_backup`）。
            #     **边际大 + 零答案变化**才是能安全落地的那个。
            FrameField("remaining", label="actions_left", clip="list"),
            # ★★ **改道时才有值。** 正常正向路径上它是空的（`redirect_note` 为空），
            #   所以这一条**不改变**上面那张表量出来的结论 —— 它只在改道那一步奏效。
            FrameField("redirect_note", label="redirect_note"),
        ),
        # 候选在问题那一侧（`choice` 的选项），不占帧的字段 —— 见 §8.4「每步重建」
        excluded=(
            ("draft", "还没到生成那一步"),
            # ⚠️ 这条**是量过之后才留着的**,不是想当然:见上面 `remaining` 那张表 ——
            #    加 `history` 边际也涨,但会翻掉一条答案（方向对、幅度不够）。
            #    留 `remaining` 是**边际最大且零翻转**的那个组合。
            ("history", "候选本身已经排除了做过的动作;再给历史会翻掉答案且边际更小(实测见上)"),
        ),
    ),
    "pickInput": FrameSpec(
        node="pickInput",
        fields=(
            FrameField("task", label="task", required=True),
            # ★★★ **一张编号的候选表** —— 状态里放一次,题里只引用 `[i]`。
            #   照 `jev-ultrafast::action_space`（"dynamic, indexed action space"）。
            #   预算给得大:ALFWorld 一步 ~28 条命令,每条还要带一句说明。
            # A6 moves this longest field to the end without changing its budget.
            # ★★★ **这个世界的动作语义** —— 环境语义,不是任务脚本（见 `Tool.action_rules`）。
            #   `jev-ultrafast` 把它放在 `instructions` 里;我们放在**状态**里,
            #   因为 N 道候选题共享同一份帧 —— 放题里就是 N 倍预算。
            FrameField("action_rules", label="how_this_world_works"),
            # ★★★ **必须带上"已经做过什么"。** 实测（2026-10-02，ALFWorld）：
            #   这一格原来是空的，于是 `pickInput` 被问"下一步做什么"时
            #   **不知道自己做过什么、上一步返回了什么**。后果不是判得差一点，
            #   是**死循环**：Jev 连续 5+ 次选 `examine cabinet 1`
            #   （一个只返回信息、不改变状态的命令），直到置信度抖到 0.5 以下
            #   连撞 3 次被拒，整道题以 `declined` 结束。20 题里 13 题这样死掉。
            #   `examine safe 1` 单轮跑出现 56 次、`look` 60 次 —— 都是同一形状。
            #
            #   旧注释写的排除理由是「候选由 `candidates` 每步算出来,历史是另外的事」——
            #   那句话**把两件事混了**：候选列表说的是**什么可能**，
            #   `history` 说的是**什么试过了**。动态候选越多（ALFWorld 每步 ~28 条），
            #   后者越不可省。★ 这和 §8.2 那条「判定贴在门限边上，因为帧里证据太薄」
            #   是同一个病，只是这次它表现为循环而不是抖动。
            FrameField("history", label="already_done", clip="list"),
            # ★★★ **`last_result` 2026-10-04 补进来 —— 它是唯一一个排除它的节点。**
            #
            #   原来的排除理由是「判的是**这一调**的目标,不是上一步返回了什么」。
            #   那句话**反了**:不知道刚刚发生了什么,就选不出下一步该做什么。
            #   实测代价(TERNARY,2026-10-04):41 个候选里 40 个是 `d001…d040`,
            #   判官答"一个都不合适" **20/20**(置信度 0.62)—— **它是对的**,
            #   因为帧里没有能区分那 40 个 id 的任何东西。
            #   而 `needsTool` / `isDone` 一直都有 `last_result`,只有这个节点漏了。
            FrameField("last_result", label="last_result"),
            # ★ 改道时补上"缺什么"：ALFWorld 那一类里**同一个动词换个宾语**就是另一步
            #   （`go to X` → `go to Y`），所以参数这一步同样需要知道为什么被打回。
            FrameField("redirect_note", label="redirect_note"),
            FrameField("action_table", label="actions_on_the_table", clip="list"),
        ),
        excluded=(
            # ★ `last_result` **2026-10-04 从这里搬到了 `fields`**（见上面的说明）。
            #   排除它的理由写反了:不知道刚刚发生了什么,就选不出下一步做什么。
            ("draft", "还没到生成那一步"),
        ),
    ),
    "gradeRisk": FrameSpec(
        node="gradeRisk",
        fields=(
            # 判的是**这一调**的风险;`target` 就是这一调的参数（`task` 是背景）
            #
            # ⚠️ **不是 required** —— 判据是「有没有参数」,不是「判不判得了」:
            #    无参工具（`list_dir` / ALFWorld 的 `go to X` 那一类)
            #    的调用**本来就没有 target**,它是**正常状态**,不是缺陷。
            #    标成 required 会让每一步无参调用都撞一次 fatal ——
            #    而那正是 §8.15 那条「天天误报和没有这条检查等价」的形状。
            FrameField("last_input", label="target"),
            FrameField("task", label="task", required=True),
        ),
        excluded=(("last_result", "判的是**调用之前**的风险,这时还没有结果"),),
    ),
    "stepOk": FrameSpec(
        node="stepOk",
        fields=(
            FrameField("last_tool", label="tool"),
            FrameField("last_input", label="input"),
            # ★ 判的就是「这一步成没成」—— 唯一没有它就没法判的字段
            FrameField("last_result", label="output", required=True),
        ),
        # ★★★ **故意没有 `task`** —— 这是修出来的:
        #   以前帧带着 `task`、问题写着 "for the task"、判据写着 "what the task needed",
        #   三处一起把它拉到了任务级。实测第一步 `list_dir` 确实成功了,
        #   但没回答任务,于是 `ok=0.470` 判否 → `stop` → **整个循环结束**,
        #   任何需要多于一个工具的任务都跑不完。
        excluded=(
            ("task", "判的是**这一步**,不是这个任务 —— 带上它会被拉到任务级（实测）"),
            ("history", "同上,历史会把它拉到任务级"),
            ("draft", "还没生成"),
        ),
    ),
    "isDone": FrameSpec(
        node="isDone",
        fields=(
            FrameField("task", label="task", required=True),
            # ★ 是清单不是计数 —— 和 `needsTool` 同一条理由
            FrameField("history", label="already_done", clip="list"),
        ),
        excluded=(
            ("last_result", "判的是「任务做完没有」,不是「上一步返回了什么」"),
            # ★ 旧措辞里有半句「any further tool call would not add information」——
            #   它是个陷阱:**读任何一个还没读过的文件都会「增加信息」**,
            #   哪怕那个文件与任务无关。实测因此去读了任务不需要的 notes.md 还不肯停。
            ("_note", "判据是「任务要求的都做了」,不是「再多调一次会不会增加信息」"),
        ),
    ),
    "canDeliver": FrameSpec(
        node="canDeliver",
        fields=(
            FrameField("task", label="task", required=True),
            # ★ 900,不是 100 —— 100 那次判定**正确地**判出 `unsupported=0.67`,
            #   是帧喂少了。这一格的预算直接决定闸门准不准。
            #   ★ 而且它是 required:**没有 draft 就没有可交付的东西**。
            #   这次事故的形状正是「有 draft 但被截短了」—— 那走 `truncations`,
            #   不在这里;这里是「压根没有」。
            FrameField("draft", label="answer", required=True),
            # ★★★ **工具证据** —— 见 `AgentCtx.evidence`。
            #
            #   这是 2026-09-23 查出来的「静默缺席」的修法:闸门判的是
            #   「回答有没有超出**工具输出**的支持」,而它原来**看不到任何工具输出**。
            #   实测(ALFWorld 那题)agent 只走到冰箱门口(冰箱还关着)就交了
            #   「I placed the microwaved apple in the fridge.」—— 一句编的完成报告,
            #   而帧里没有任何反证,于是 `escalated=False`,没有任何东西拦它。
            #
            #   ★ 预算 600:证据是**被核对的对象**,而 `draft` 是被判的对象 ——
            #     两者都要放得下。实测 100 字符那次的教训是「喂少了闸门会正确地误报」,
            #     所以这一格宁大勿小(`MAX_REQUEST_CHARS` 兜底)。
            FrameField("evidence", label="evidence"),
        ),
        # ⚠️ `history` 仍然排除,但**理由变了**。原来那条写的是「历史会把回答挤掉」;
        #    现在证据是单独一栏、有自己的预算,所以真正的理由换成了:
        #    `history` 是**做过什么**的形状（每条结果只留 60 字符),
        #    而闸门要的是**返回了什么**（逐句核对的材料）。
        #    给前者等于给了一份更薄、更旧的副本,却还要占 `draft` 的预算。
        excluded=(
            ("history", "**过的是证据(`evidence`),不是整段历史** —— "
                        "`history` 每条结果只留 60 字符,是「做过什么」的形状;"
                        "闸门要逐句核对,那需要返回原文"),
        ),
    ),
}



# ═══════════════════════════════════════════════════════════
# ★★ 请求 = 帧 + 问题 —— **预算要一起算,而且超了必须有人接**
#
# 这一段是补第十轮 R2/R5 的。那一轮的两条住在帧编译里：
#
#   R5  `fileOptions` 的**选项数没有上界**,而同一个帧里的字段都老老实实截断了
#       → **帧有界、选项无界**,恰好是 §8.2 说要避免的形态
#   R2  `write_file` **永不从候选中移除**,而同文件 185 行把不变量写成了通则
#       → 不变量写成通则、实现三个工具三种待遇
#
# 两条合起来是一条五步失效链（审计原文）：
#
#   选项超限 → 校验发现 → **无人接收** → 请求照发 → **判定静默掉点**
#
# ★ 我第一版的帧模块**三处全中**：候选被推到「问题那一侧」所以这里不管它（R5）、
#   候选由调用方给所以没人检查它删没删做过的动作（R2）、
#   `truncations` 只是渲染成正文里一句注释,**没有东西失败也没有东西降级**（无人接收）。
#
# 所以这一段做三件事：**把帧和选项合起来算一次预算**、**把不变量变成可检查的**、
# **把违规变成调用方必须处理的东西,而不是一句注释**。
# ═══════════════════════════════════════════════════════════

#: 判定模型一次请求的选项上限。★ 实测 77 个候选时选中概率掉到 **0.425**（§8.2）。
#: 20 是 TS 侧 `LIMITS[*].maxOptions` 的值,这里逐字对齐。
#: ★ **选项数上限** —— 它和帧抢同一段上下文,所以在这里一起算（R5）。
#:
#: ⚠️ 这个数**被实测改过一次**（2026-09-23）:原来是 20,而 ALFWorld
#: 每步给的 `admissible_commands` 是 **28 条**,于是 `pickInput` 每一步都
#: 判成 `options_over_budget`、请求发不出去,臂直接动不了。
#:
#: 量了一下才知道 20 太保守 —— 同一道题、同一批候选,只改条数:
#:
#: ============== ==================== =======
#: 候选            选中                  top
#: ============== ==================== =======
#: **全部 28 条**  **`go to fridge 1`**  **0.880**
#: 前 20 条        `go to fridge 1`     0.890
#: 前 8 条         `go to countertop 1` 0.660
#: ============== ==================== =======
#:
#: ⇒ **28 条判得又准又果断**（任务要求「放进冰箱」,它直接选中冰箱),
#:   而**只给 8 条反而更差** —— 砍候选不是免费的。
#:
#: ★ 20 这个数**不是量出来的**,是从 TS 的 `MAX_FILE_OPTIONS = 20` 抄来的,
#:   而那个数是**文件列表的界面限制**,不是判定质量的限制。**两者混了。**
#:
#: ★ 已知的**上界**在另一边:模块头记着「实测 77 选项掉到 0.425」。
#:   32 盖得住 ALFWorld 的 28,又离那个变差的点很远。
#:   **28 到 77 之间没有量过** —— 要再往上提,先补那个测量。
MAX_OPTIONS = 32

#: 一次请求（帧 + 问题 + 选项）的字符上限。
#:
#: ★★★ **实测改过一次（2026-10-04），幅度 8 倍 —— 而旧值建立在一句没有出处的断言上。**
#:
#:   旧注释写的是「判定模型上下文只有 **512/1024 token**」,于是我们把整条请求卡在
#:   **4,000 字符（≈1,000 token）**。往 `api.typesafe.ai/v1/systemone` 实测:
#:
#:   | state 字符 | ≈token | 中位延迟 | 结果 |
#:   |---|---|---|---|
#:   | 4,000 | 1,000 | 995ms | OK |
#:   | 64,000 | 16,000 | 1,395ms | OK |
#:   | **128,000** | **32,000** | **1,942ms** | **OK** |
#:   | 256,000 | 64,000 | — | **400 Bad Request** |
#:
#:   ⇒ 窗口是 **32K token**,而那个 512/1024 的说法**错了 32 倍**。
#:     μ 的源码里写着 *"The judge has a 32K window"* —— 和实测一致。
#:     用满窗口的代价只有 **+1 秒**,而我们当时只用了窗口的 **3%**。
#:
#: ★ 取 32,000 字符（≈8K token，窗口的 25%）—— **不是取满**:
#:   满载的收益没量过,而延迟与注意力稀释是有代价的。
#:   要往上提,先补那个测量(和 `MAX_OPTIONS` 那条同一个规矩)。
#: ★ **这是整个请求的预算,不是帧的预算** —— R5 的病就是只算了帧那一半。
#:
#: ★★★ **2026-10-05 再往上提，32,000 → 120,000 —— 提到实测的墙边上。**
#:   同一天把墙的位置二分出来了（`state + questions` 的 JSON 总长）：
#:
#:   | body 字符 | 结果 |
#:   |---|---|
#:   | 131,000 | OK |
#:   | **131,072** | **OK（= 2¹⁷，就是那面墙）** |
#:   | 131,117 | **400 Bad Request** |
#:
#:   ⇒ 硬墙是 **131,072 字符 = 128 KiB = 2¹⁷**，而且它管的是**总和**
#:     （单独把体积放进 state 或放进 questions 都一样，见当天的两组探测）。
#:
#:   取 **120,000**（墙的 92%）：留 11,072 字符余量给估算误差，
#:   同时**不再是我们自己设的那个 32,000 在挡路** ——
#:   实测我们真正发出去的最大请求只有 **5,153 字符**，用掉 32,000 的 16%、
#:   用掉 120,000 的 4%。所以这一栏**平时根本不会触发**,
#:   它的作用只有一个：**别把 400 变成一次静默的判定丢失。**
#:   ★ 它**不裁内容** —— 超了是 `request_over_budget` 报出来（fatal），
#:     不是把证据切一段然后照发（切了照发正是"判官看不见证据"那条老病）。
MAX_REQUEST_CHARS = 120_000

#: 一次请求**最多带几道题**。
#:
#: ★★★ **实测改过一次（2026-10-04），3 → 96 —— 而旧值挡错了东西。**
#:
#:   旧理由写的是「挡『把七个节点一股脑塞进一次请求』那种写法」。而那个意图
#:   **现在由调用结构保证**（每个调用点只传它自己那几道题），不靠这个计数。
#:   于是这个数实际挡住的是**它本意不挡的东西**:`pickInput` 改成
#:   **一候选一题**（ALFWorld 一步 ~28 条命令 ⇒ 28 道题）之后，
#:   它会把每一步都判成 fatal。
#:
#:   而"一道请求带很多题"是正常的:`μ` 的 `tool.admission` 一次问 16 个块,
#:   `jev-ultrafast` 一次问 1 个操作 + 3 个目标 head。
#:   ★ 窗口实测是 **32K token ≈ 128K 字符**（见 `MAX_REQUEST_CHARS`），
#:     96 道短题远在窗口之内。
#:
#:   ⚠️ 真正的预算守卫是下面那个 `MAX_REQUEST_CHARS`（帧 + 问题 + 选项的总字符）。
#:     这个数只防"一个手滑写出无限道题"。
#:
#: ★★★ **2026-10-05：96 → 512。** 理由同上，只是把余量给足：
#:   实测窗口 131,072 字符，而每道题都很短；96 这个数本来也是照着
#:   32,000 字符的旧预算估的。真正拦越界的仍然是 `MAX_REQUEST_CHARS`，
#:   所以这里放宽**不会**让请求超窗 —— 超窗由那一栏报出来。
MAX_QUESTIONS = 512


@dataclass(frozen=True)
class Pointer:
    """★★★ **一个裁决必须能指向的东西，以及"指得对不对"的校验。**

    这是从 `ternary-judge` 上实测出来的那条原理的通用化
    （见 `docs/UNDECIDED-DIAGNOSIS.md`）：

        一个概率**没有办法被证明是错的**。"unsupported = 0.86" 怎么反驳？
        而一个**指认**可以："第 3 步的工具输出里写着这个数"——要么写了，要么没写。

    所以要求不是"判得更谨慎"，而是**换一种输出**：裁决要带一个指向某份产物的
    指针，而校验这个指针的必须是**判定模型之外的、确定性的**代码。

    ★ 后半句是重点。**如果校验也交给模型，那只是又加了一个意见** ——
      而"解耦但只读文本的判官和不判一样"这件事我们已经量过了
      （`docs/MEASUREMENT-gate-equivalence.md`）。

    ★★ **它不是什么**：不是"更好的 prompt"，也不是"更多的证据"。它改变的是
      裁决的**可证伪性**。模型说"第 3 步证明了它"，代码就去第 3 步的输出里找。

    ⚠️ **强度随证据通道的结构而变。** 有可枚举、可检索的产物时它能做实事
      （文档 id + 文本、步骤 + 观测）；只有自由文本时它退化成"有没有引"。
      这个分档必须跟着数字一起报 —— 和"后置条件分档"那张表是同一件事。
    """

    #: 问判定模型的话。措辞要贴着"指哪个产物"，不是"你确定吗"。
    ask: str
    #: ★ **封闭的可指认集合。** 判定模型只能从这里挑 ——
    #:   这正是判定模型的本性（穷尽枚举），也是它比生成式判官更可审计的地方。
    options: tuple[str, ...]
    #: ★★ **校验器：跑在模型之外。** 输入是被指认的选项，返回它是否真的成立。
    #:   `False` ⇒ 那条**肯定性**裁决不成立（见 `Request.check` 那条注释）。
    validate: Callable[[str], bool]
    #: 「指不出来」那一项。选它 = 承认没有可指的东西 ⇒ 裁决必须降级。
    none_option: str = ""


@dataclass(frozen=True)
class Question:
    """一个类型化问题。

    `kind` 决定 `policy` 怎么读答案:

    - `noul`：P(true)
    - `choice`：选中项的**概率**（卡阈值用它,**不是 `confidence`** —— §8.3）
    - `score`：序数

    ★ `options` 的**数量要受 `MAX_OPTIONS` 管** —— 它和帧的字段抢同一段上下文。
    """

    node: str
    kind: str
    ask: str
    options: tuple[str, ...] = ()
    #: ★★★ **这道题用哪个节点的帧。** 空 = 和 `node` 同名。
    #:
    #: 为什么需要它:两个节点是**一次判定问两件事**（`DECISION.md` 里 kind 是
    #: `mixed`)—— `grade_risk` 问 `risk` + `needs_auth`,`can_deliver` 问
    #: `deliverable` + `unsupported`。两道题共享**同一份帧**,而各自的
    #: `node` 是问题 id（判定模型看到的措辞、账上的那一行）。
    #:
    #: ★ 名字分开是**必须的**:`NODE_FRAMES` 的键是**节点**名
    #: （`gradeRisk` / `canDeliver`,和 TS 的 `loop.gradeRisk` 对齐）,
    #: 而问题 id 是 `risk` / `needs_auth` —— 那是 `vocab.ts` 里
    #: `criteria` 的键、「答案回到哪个字段」的名字。**两者混用会去查一个
    #: 不存在的帧,而且报错长得像「你节点名打错了」。**
    frame: str = ""
    #: ★ **判据**（`vocab.ts` 的 `criteria`）。
    #:
    #: - `noul` → `{"true": "什么条件下算 true", "false": "什么条件下算 false"}`
    #: - `choice` → 由 `options` 生成（键是选项本身,值是「什么条件下该选它」）
    #:
    #: ★ `vocab.ts` 的原话:「**问题 ID 不会到达模型**」—— 所以措辞和判据
    #: 是模型能看到的全部,写错了没有别的东西兜得住。
    #: 而且 `noul` 的判据「显著提升判定质量」,不给是白丢的。
    criteria: dict[str, str] = field(default_factory=dict)
    #: ★★★ **"这些选项里一个都不合适"是哪个选项。**
    #:
    #: 抄自 μ（`packages/kyrn-judge/src/policy.ts`）的原话：
    #:
    #:   > Option names that mean "nothing fits". A choice question without one is
    #:   > **forced to pick a real option even for off-topic input, and does so at
    #:   > full confidence**, so specs must include one unless the option set is
    #:   > truly closed.
    #:
    #:   而它的 `defineDecision` **没有退出口就直接抛错**，注册不上。
    #:
    #: ★★ 我们违反了这条，而且代价已经被量到了：`pickInput` 是 **28 选 1 的强制
    #:   选择**（ALFWorld 每步的 `admissible_commands`），判官**没法说"这些都不是
    #:   下一步该做的"**。于是：
    #:
    #:     · `top` 常年 0.44–0.55（概率质量摊在 28 个都合理的选项上）
    #:     · 0.5 那道门限**恰好落在众数上** —— 那个门限是畸形问题的变通办法
    #:     · 一轮里 `examine cabinet 1` 被挑了 56 次 —— 它没有"这不是进展"可答
    #:     · 仓库自己记的「77 个候选 → top 0.425」是同一个病，被记成了后端性质
    #:
    #:   ⇒ 没有退出口的 choice 问题**不是一个好问题**，而"判得不够果断"只是它的症状。
    #:
    #: ★ 构造规则：`kind == "choice"` 且有选项时**必须**给退出口，
    #:   否则 `_choice_question` 当场抛错（照 μ 的 `defineDecision`）。
    #:   确实封闭的选项集（比如工具名 + `DONE`）才允许显式豁免。
    escape: str = ""
    #: ★ 这个 choice 的选项集**真的封闭**，不需要退出口（少数情况，要写理由）。
    closed_choices: bool = False
    #: ★★★ **这个裁决必须能指向的东西**（`None` = 不要求举证）。
    #:
    #: 由**调用方**构造，而且校验器闭包在构造时就把证据绑好了 ——
    #: 于是 `_ask_many` 不需要知道证据长什么样，只负责"问、校验、降级"。
    pointer: "Pointer | None" = None
    #: **答得果不果断**的门限 —— 逐字对应 TS 的 `topGte`。
    #:
    #: ⚠️ `noul` 上判的是 `max(p, 1-p)`,**不是** `p`:一个果断的「否」也算果断。
    #: 要「答是的概率」那个门限是另一件事（TS 的 `probGte`）——
    #: `TypedController.yes` 就是它。**一道题有两个数、两个门限,别混。**
    #:
    #: ★ **每个节点可以不同** —— `DECISION.md` 里 `pick_tool` 是 0.6、
    #: `pick_input` 是 0.5。用一个全局常量会把其中一个改错。
    threshold: float = 0.5

    def option_labels(self) -> tuple[str, ...]:
        return self.options


@dataclass(frozen=True)
class Violation:
    """**一条必须有人接的违规。**

    ★ 它不是注释、不是日志 —— `Request.check()` 返回它,
    而 `Request.fatal` 为真时**调用方不许把请求发出去**
    （要么修帧、要么标 degraded、要么弃答）。

    「校验发现 → 无人接收 → 请求照发」正是 R2/R5 那条失效链的中间三步。
    """

    code: str          # options_over_budget | request_over_budget | candidate_already_done | field_missing
    detail: str
    fatal: bool = True


@dataclass(frozen=True)
class Request:
    """**一次判定请求的完整形态**:帧（状态）+ 问题（问什么、选项是什么）。

    ★ 预算必须在这个粒度上算 —— 分开算就是 R5。

    ★★ **一次请求可以带多道题**（`questions`）—— 那是判定模型的性质
    （一次前向对所有问题并行打分,见 `core/deciding.py` 的模块头),
    不是优化。七个节点接齐之后,**一批 = 一次 HTTP 往返**这条对应关系
    必须在这里成立:一次请求只装一道题的话,
    `DecisionBatchEvent.requests_in_batch / questions_in_batch` 恒等于 1,
    于是「判定有没有被合并」这件事在账上永远看不出来。

    ⚠️ `question` 是**单题**的老形状,留着是因为 `frame_ab.py` / 测试里
    还在用它单发一题。两者同时给是不允许的 —— 那会让 `render()` 里
    出现两道题而 `check()` 只校验一道。
    """

    frame: Frame
    question: Question | None = None
    #: 一次请求里的全部问题。**留空 = 用 `question` 那一道**（老形状）。
    questions: tuple[Question, ...] = ()

    def __post_init__(self) -> None:
        if self.questions and self.question is not None:
            raise ValueError("`question` 和 `questions` 只能给一个 —— "
                             "同时给会让正文里出现两道题而校验只过一道")
        if not self.questions and self.question is None:
            raise ValueError("一个请求至少要有一道题")

    @property
    def all_questions(self) -> tuple[Question, ...]:
        return self.questions or ((self.question,) if self.question is not None else ())

    def render(self) -> str:
        """判定的正文:帧 + 每道题的问题与选项编号。

        ★ 选项**带序号**列出来 —— 判定模型返回的是序号或标签,
        而「第几个」在选项被截断时仍然要指向同一个东西。

        ★ 多题时每道题带自己的 `# Question (<node>)` 小标题:不写的话
        两道题的正文会连在一起,而**问题 id 不会到达模型**（`vocab.ts`）——
        它只能靠措辞分辨哪道是哪道。
        """
        parts = [self.frame.render()]
        multi = len(self.all_questions) > 1
        for q in self.all_questions:
            parts += ["", f"# Question{' (' + q.node + ')' if multi else ''}", q.ask]
            if q.options:
                parts.append("# Options")
                parts.extend(f"{i}. {o}" for i, o in enumerate(q.options, start=1))
        return "\n".join(parts)

    def digest(self) -> str:
        """★★★ **整个请求的指纹** —— 帧 + 问题 + **选项**。

        ⚠️ 这里踩过一次,值得记:**`frame_digest` 只覆盖帧,而帧不等于请求。**

        `pickTool` 的帧只有 `task` + `last_result`（候选**故意不占帧的字段**,
        见 §8.4「每步重建」）—— 于是**换了候选集而帧指纹一动不动**。
        实测（2026-09-23,同一帧指纹 `bb30c546d43b63cd`）:

        ====================== ==================== ========
        候选                    判定                  top
        ====================== ==================== ========
        `[war, leader]`         `war_details`        **1.00**
        `[leader, war]`         `war_details`        1.00
        `[war, leader, battle]` **`battle_details`** 0.99
        `[war, leader, done]`   `war_details`        **0.71**
        ====================== ==================== ========

        ★ 我拿「帧指纹相同」当成了「请求相同」,于是把第 1 行和第 4 行的差别
        （1.00 vs 0.71）读成了**判定后端随机**,还写进了文档。
        **后端是确定的**:同一个请求原样发 12 次,12 次都是 `top=1.0000`。

        ⇒ **比「两次跑的是不是同一个判定」,要比这个,不是比 `frame_digest`。**
          帧的指纹回答的是「它看到了什么」;请求的指纹才回答「它被问了什么」。
        """
        return hashlib.sha256(self.render().encode("utf-8")).hexdigest()[:16]

    def chars(self) -> int:
        return len(self.render())

    def check(self, ctx: AgentCtx | None = None) -> list[Violation]:
        """**发请求之前**跑（§8.2 原话:「发请求之前就要校验」）。

        返回空列表 = 可以发。否则**调用方必须处理**,不许照发。

        ★★ **每一道题都要过一遍,不是只看第一道。** 多题合并成一次请求
        （见类文档）之后,「只校验 `self.question`」会让第二道题的问题
        **完全绕过校验** —— 而它的病正是「校验发现 → 无人接收 → 请求照发」。
        """
        out: list[Violation] = []

        for question in self.all_questions:
            out.extend(self._check_question(question, ctx))

        # ★ 一次请求能带几道题也要有人管 —— 它和帧、选项抢的是同一段上下文。
        #   这里**必须拦**:它不像选项数那样是「偶尔多一点」,
        #   而是调用点写错（比如想合并七个节点）时就一定越界。
        if len(self.all_questions) > MAX_QUESTIONS:
            nodes = "+".join(q.node for q in self.all_questions)
            out.append(Violation(
                code="too_many_questions",
                detail=(f"{nodes}: 一次请求 {len(self.all_questions)} 道题 > {MAX_QUESTIONS}。"
                        f"合并的判据是**证据形状相同、彼此独立**（例如 "
                        f"`stepOk`+`isDone` 都看刚刚那一步),不是能塞多少塞多少 —— "
                        f"七道题的问题与判据会挤掉帧那半边"),
            ))

        # R5 的另一半:整个请求的预算,不只是帧那一半
        #
        # ★ 多题时这一条更值钱:合并请求省的是**往返次数**,
        #   而代价是**正文变长**。两者是同一个取舍的两面,所以必须在
        #   请求这一级一起算（只算帧那一半就是 R5 的病）。
        total = self.chars()
        if total > MAX_REQUEST_CHARS:
            nodes = "+".join(q.node for q in self.all_questions)
            out.append(Violation(
                code="request_over_budget",
                detail=(f"{nodes}: 请求 {total} 字符 > {MAX_REQUEST_CHARS}"
                        f"（帧 {len(self.frame.render())} + 问题与选项）"),
            ))

        # 帧里缺字段。**分两档** —— 这是把 §8.2 那条不变量从噪声里救出来的关键:
        #
        #   required 缺 → **判定的依据不在**,这次判定没有对象。发出去只会得到一个
        #                 凭空生成的答案,而日志上它和一次正常判定长得一样（§8.10）。
        #                 → fatal,调用方必须修帧 / 标 degraded / 弃答。
        #   只是上下文缺 → 第 0 步没有 `last_result`、生成之前没有 `draft` ——
        #                 **正常状态**,不进这个列表。
        #
        # ★ **不进列表不等于不说。** 它照旧渲染成 `(absent — last_result)`、
        #   照旧记在 `Frame.missing` 上进日志 —— 信息一个字节没少,
        #   少的是「每一步都喊一次」。
        #   `Violation` 的含义是「必须处理」,把正常状态放进去就等于教会读的人跳过它。
        if self.frame.missing_required:
            nodes = "+".join(q.node for q in self.all_questions)
            out.append(Violation(
                code="field_missing",
                detail=(f"{nodes}: 帧里缺**判定依据** "
                        f"{list(self.frame.missing_required)} —— 这一次判定没有对象可判。"
                        f"（另外缺的上下文：{sorted(set(self.frame.missing) - set(self.frame.missing_required))}）"),
                fatal=True,
            ))
        return out

    def _check_question(self, question: Question, ctx: AgentCtx | None) -> list[Violation]:
        """一道题自己的那两条:选项数上限、候选里有没有做过的动作。

        ★ 这两条**只能是每题一份** —— 帧是整个请求共用的,而选项是每题各自的。
        原来把帧的字段检查也写在这里过,那样多题时同一条 `field_missing`
        会被报 N 遍,而「天天误报」和「没有这条检查」在效果上没有区别。
        """
        out: list[Violation] = []

        # R5:选项数 —— 它和帧抢同一段上下文,所以**在这里一起算**
        #
        # ⚠️ **不是 fatal** —— 它原来是,而那个 fatal 在 2026-09-23 把 ALFWorld
        #    整条臂干掉了:环境每步给 28 条 `admissible_commands`（真实合法命令),
        #    超过上限 → **每一步的请求都发不出去** → 臂动都动不了。
        #
        #    量过才知道那道闸定错了:同一题、同一批候选,只改条数::
        #
        #        全部 28 条  -> go to fridge 1       top=0.880   ← 又准又果断
        #        前 20 条    -> go to fridge 1       top=0.890
        #        前 8 条     -> go to countertop 1   top=0.660   ← 砍候选不是免费的
        #
        #    ⇒ 28 条判得好好的。而**拦下来比放过去更贵** ——
        #      放过去最坏是一次判得烂的判定（账上有记录）,
        #      拦下来是整道题作废,而且**看起来像「模型不会做」**。
        #
        # ★ 它守的仍然是一个真东西:选项共享 192/256 的 head 预算,
        #   实测 77 个候选时选中概率掉到 0.425。所以**报,但不拦** ——
        #   和下面 R2 那条同一个处理（「不是 fatal,但必须报出来;
        #   没人看这个不变量」正是 R2 的病）。
        if len(question.options) > MAX_OPTIONS:
            out.append(Violation(
                code="options_over_budget",
                detail=(f"{question.node}: {len(question.options)} 个选项 > {MAX_OPTIONS}。"
                        f"实测 77 个候选时选中概率掉到 0.425 —— "
                        f"**要裁就裁在候选提供方那一侧,不是在这里切**"),
                fatal=False,
            ))

        # R6:**这些选项彼此能区分吗?**
        #
        # ★★★ 这条是 2026-10-04 实测补的,而且它**本该在构造时就抓住**那个问题:
        #   TERNARY 的 `pickInput` 是 40 个 `d001…d040`,而判据来自一张
        #   **ALFWorld 的动词表** —— 40 个候选拿到**同一句话**。
        #   判官答"一个都不合适" **21/21**(置信度 0.62)。
        #   **它不是不会挑,是没有可挑的依据。**
        #
        # ⇒ 判据:N 个选项(去掉退出口)如果**说明全都一样**,这道题就是
        #   **无法回答的**。不该拦住(拦住整条臂动不了),但**必须报出来** ——
        #   否则它只会表现为"判官老逃/乱挑",然后被归咎于判官质量。
        if (question.kind == "choice" and len(question.criteria) >= 2
                and len(set(question.criteria.values())) == 1):
            only = next(iter(set(question.criteria.values())))
            out.append(Violation(
                code="indistinguishable_options",
                detail=(f"{question.node}: {len(question.criteria)} 个选项的说明**全是同一句**"
                        f"（{only[:60]!r}）⇒ 这道题**没有可判别的依据**,"
                        f"判官只能选退出口或乱挑。"
                        f"给每个选项一句真实的身份(`Tool.describe_candidate`),"
                        f"或者把它改成一候选一题"),
                fatal=False,
            ))

        # R2:候选里有没有**已经做过的动作**
        #
        # ★★ 这一条的判据**改过一次**（2026-10-02），因为它在 ALFWorld 上
        #    **每步都误报**：原来只比工具名（`{r.tool} ∩ options`），
        #    而 ALFWorld 只有一个工具 `act`，调过一次之后 `act` 永远在候选里
        #    ⇒ 忠实跑一轮报 187 次。**一条永远为真的告警等于没有告警**
        #    （R2 的病本来就是「没人看这个不变量」，而误报正是没人看的原因）。
        #
        #   现在**两个来源一起比**，因为光看 `kind` 分不开这两种题
        #   （`pickTool` 和 `pickInput` 都是 `choice`）：
        #     · 参数值（`pickInput` 的候选）⇒ 比"这个动作做过没有"。
        #       这才是 §8.4 那句话真正要防的：同一个动作反复做而局面没变。
        #     · 工具名（`pickTool` 的候选）⇒ 比工具名，但**带动态候选的工具
        #       不算重复** —— 它的动作空间在参数里，换个参数就是另一步；
        #       按名字去重会让 ALFWorld 的循环在第一步就收尾（`candidates()` 记了这件事）。
        if ctx is not None and question.options:
            records = ctx.records()
            live = set(ctx.candidates)
            seen = {r.input for r in records if r.input}
            seen |= {r.tool for r in records if r.tool and r.tool not in live}
            repeated = sorted(seen & set(question.options))
            if repeated:
                what = "动作" if question.node == "pickInput" else "工具"
                out.append(Violation(
                    code="candidate_already_done",
                    detail=(f"{question.node}: 候选里有做过的{what} {repeated}。"
                            f"§8.4 要求**每步重建**、把做过的删掉 —— "
                            f"固定候选会让模型去选一个已经不适用的动作（实测：写完文件后 "
                            f"`write_file` 还在候选里,模型会再选它）"),
                    # ⚠️ 不是 fatal:重读一个文件有时是合理的。
                    #    **但必须报出来** —— R2 的病正是「没人看这个不变量」。
                    fatal=False,
                ))
        return out

    @property
    def fatal(self) -> list[Violation]:
        """**必须处理的那些。** 调用方拿到非空就该：修帧 / 标 degraded / 弃答 —— 三选一。"""
        return [v for v in self.check() if v.fatal]

def frame_for(node: str) -> FrameSpec:
    """取一个节点的帧声明。**没有这个节点就炸** —— 打错名字不该静默给个空帧。"""
    if node not in NODE_FRAMES:
        raise KeyError(f"没有 {node!r} 的帧声明；有 {sorted(NODE_FRAMES)}")
    return NODE_FRAMES[node]


# ═══════════════════════════════════════════════════════════
# ★★★ 规范状态键 —— "同一个状态"到底指什么
# ═══════════════════════════════════════════════════════════
#
# 为什么要它:`request_digest` **不是**状态键。它覆盖帧的**渲染文本**,而渲染文本里
# 混着跟判定无关的东西 —— 截断提示(`(truncated — k: was→now)`)、字段顺序、
# 列表截断的位置。两个**逻辑上一样**的状态会因此得到两个指纹,于是
# 「状态重复率」被**低估**,而「有效控制熵」的分母偏小。
#
# ★ 实测(2026-10-04):用 `request_digest` 算,20 题那批的重复率是 51%;
#   而那个数**没法从旧日志重算一遍验证** —— 判定行里只有指纹,没有字段值。
#   所以这个函数既服务**以后**(记进账),也说明了**以前**的数只能叫"请求层面"的。
#
# ★★ 键从哪来:**帧的字段声明**。哪些证据是本质的,不是我们凭空列的 ——
#   它就是 `NODE_FRAMES[node].fields`。`FrameField.name` 是 `AgentCtx` 的属性名,
#   所以"这个判定的状态"= 那些属性的值。**帧声明改了,键跟着改,不会漂。**
#
# ⚠️ 两个刻意的选择:
#   · **用未截断的原值**,不是渲染出来的文本。规则要读的是状态,不是被
#     `budget` 切过的那一段。而"截断把多少不同的状态压成了同一个问题"
#     正是两个键的重复率之差能测出来的东西 —— 那是个有意义的量,不该被抹掉。
#   · **列表排序**。`already_done` 的集合顺序是拼装顺序,不是语义。

def _norm_state(v: object) -> str:
    """把一份证据归一成一个可比的字符串。**只去掉显然无关的东西。**"""
    if v is None:
        return "∅"
    if isinstance(v, str):
        # 折叠空白/换行 —— 同一个观测在不同渲染下空白不同,那是排版不是内容
        return " ".join(v.split())
    if isinstance(v, (list, tuple)):
        return "[" + ",".join(sorted(_norm_state(x) for x in v)) + "]"
    if isinstance(v, dict):
        return "{" + ",".join(f"{k}={_norm_state(val)}"
                              for k, val in sorted(v.items(), key=lambda kv: str(kv[0]))) + "}"
    return str(v)


def canonical_state(ctx: AgentCtx, question: object) -> str:
    """**这个判定在什么状态下被问的** —— 归一后取指纹。**三样都要在。**

        ① **声明的证据** —— 帧声明里那几个字段的值（未截断）
        ② **题的身份** —— 哪道题、什么形状
        ③ **选项集**（`choice` 题）—— ★★ 候选集在**题**里,**不在帧里**

    ★★★ ③ 是实测逼出来的（2026-10-04）。第一版只用了 ①:
      于是 `pickInput` 在规范键下算出 **57.3% 的翻转率** ——
      而它的题就是"从这些候选里挑一个",候选集却没进键。
      两个不同的候选集下给出不同的答案（**都对**）被算成了翻转。
      ⇒ 那是**键的缺陷,不是判官的不稳定**。

    ★ `Request.digest()` 是覆盖选项的（它当初就是为这件事建的:
      "换掉候选集而帧指纹一动不动"）。所以这里的键必须也覆盖 ——
      否则同一件事有两个口径,而"哪个口径算出的数"会变成说不清的事。
    """
    qname = str(getattr(question, "frame", "") or getattr(question, "node", ""))
    spec = frame_for(qname)
    evidence = "|".join(f"{f.name}={_norm_state(getattr(ctx, f.name, None))}"
                        for f in spec.fields)
    options = getattr(question, "options", None) or ()
    identity = "|".join((
        str(getattr(question, "node", "")),
        str(getattr(question, "kind", "")),
        _norm_state(list(options)),
        _norm_state(getattr(question, "criteria", None)),
    ))
    blob = f"{evidence}||{identity}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def candidate_provider(tool: Tool) -> Callable[[AgentCtx], list[str]] | None:
    """工具的候选从哪来。**没有候选来源的工具不能被 `pickInput` 选中。**

    ★ 这是 `AGENTS.md` §8.2 那条硬约束在帧这一层的落点:
    判定模型只能从枚举里挑,所以**一个参数没有候选来源的工具,把它的参数做成
    `choice` 是在骗自己** —— 它只能靠猜,而我们量到 77 个候选时选中概率已经掉到 0.425。

    返回 `None` = 这个工具的参数**不可枚举**（例如自由文本 query）。
    那种情况必须走「生成提候选、判定排序」,或者干脆不放进候选集。
    """
    # ★★★ **环境给的动态候选优先于静态 `enum`。**
    #   静态那份是「这个参数可能取哪些值」,动态那份是「**这一步**能取哪些值」——
    #   而判定问的永远是后者（§8.4）。ALFWorld 上两者的差别是决定性的:
    #   静态表里根本没有 `go to cabinet 1` 这种**随局面变化**的合法命令。
    if tool.live_candidates is not None:
        return lambda ctx: [str(v) for v in tool.live_candidates()]

    enum = tool.parameters.get("properties", {})
    for key, schema in (enum or {}).items():
        if isinstance(schema, dict) and schema.get("enum"):
            return lambda ctx, k=key: [str(v) for v in schema["enum"]]
    return None


__all__ = [
    "AgentCtx", "StepRecord", "Frame", "FrameField", "FrameSpec", "Pointer",
    "render_tool_input",
    "Question", "Request", "Violation", "MAX_OPTIONS", "MAX_REQUEST_CHARS",
    "MAX_QUESTIONS",
    "NODE_FRAMES", "MAX_LISTED_CANDIDATES",
    "compile_frame", "ctx_from_steps", "frame_for",
    "candidate_provider", "clip_text", "render_evidence",
]
