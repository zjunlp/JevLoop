"""★ 结果 schema —— **缺字段的结果不收**。

这是整个 pipeline 里最重要的一份文件,理由在 `docs/PROTOCOL-experiments-*.md`:
七个人各写各的,最后合不起来**不报错**,只是第 4 周发现七套 CSV 拼不到一起。

**怎么做到「不收」**:必填字段在 dataclass 里**没有默认值**。
于是少一个字段 = 构造时 `TypeError`,**在写盘之前就炸** ——
比事后校验强,因为它不给「先写下来回头补」留余地。

字段来源:`docs/PLAN-confidence-*.md` §3(成本 / 时间 / 置信度三节)。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

# ═══════════════════════════════════════════════════════════
# 元数据 —— PLAN §3.7「每一行都要带」
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class ModelRef:
    """模型身份。**版本必须记** —— 「刷爆」是相对模型和时间说的。"""

    id: str
    version: str
    provider: str


@dataclass(frozen=True)
class RunMeta:
    """这一行是**怎么跑出来的**。缺任何一项,这个数字别人就复现不了。"""

    dataset: str
    dataset_version: str
    split: str
    task_count: int
    arm: str
    generator: ModelRef
    decider: ModelRef
    thinking_budget: str
    temperature: float
    top_p: float
    max_tokens: int
    seed: int
    prompt_hash: str
    commit: str
    # ★ 脏工作区跑出来的数字,连跑它的人都复现不了 —— 所以必须盖章
    dirty: bool
    # ★ 同一件事我们量到 254ms vs 65–90ms,取决于对端
    region: str
    cold_start: bool
    max_steps: int
    timeout_s: float
    #: ★★★ **判定规格的 `版本@指纹`** —— 见 `jloop/typed.py::decision_spec_digest`。
    #:
    #: 为什么它不是 `prompt_hash` 的重复：那个只覆盖
    #: `benchmark:dataset_version:arm`，**问法的字、门限、兜底表它一个都不覆盖**。
    #: 于是"那两批是同一个方法吗"在盘上答不出来 —— 而两张表并排放在一起的前提
    #: 正是这句话成立。空串 = 这一臂没有类型化判定（`direct` / `react` 那一类）。
    decision_spec: str = ""


# ═══════════════════════════════════════════════════════════
# 成本 —— PLAN §3.2
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Cost:
    """★ 几个必须**拆开**的数,理由都是踩过的:

    - `input_tokens_cached` / `uncached`:不分列,谁重复上下文谁的数字就失真
    - `output_tokens_reasoning`:分出来才能和「思考程度」那个轴对齐
    - `tool_calls_necessary` / `exploratory`:有的评分器**明确不惩罚探索性调用**,
      不拆的话,我们的调用数和惩罚探索的评分器根本不可比
    """

    llm_calls: int
    decision_requests: int
    questions_per_request: float
    tool_calls: int
    tool_calls_necessary: int
    tool_calls_exploratory: int
    input_tokens_cached: int
    input_tokens_uncached: int
    output_tokens_reasoning: int
    output_tokens_visible: int
    usd: float


# ═══════════════════════════════════════════════════════════
# 时间 —— PLAN §3.3「拆到和我们一样细」
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Timing:
    """★ `framework_ms` 和 `retry_ms` **必须有**。

    不留这两行,就永远分不清差距里有多少是自己的开销、多少是对面在退避。
    我们踩过:`generate` 那步墙钟 21.8s,meter 只记 11.0s,
    差掉的一半被误读成「JevLoop 慢 10 倍」。
    """

    wall_ms: float
    model_handshake_ms: float
    model_ttft_ms: float
    model_after_ttft_ms: float
    decision_handshake_ms: float
    decision_compute_ms: float
    tool_ms: float
    framework_ms: float
    retry_ms: float
    round_trips: int


# ═══════════════════════════════════════════════════════════
# 一次运行的结果
# ═══════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Result:
    """一道题 × 一个 arm × 一个 seed 的结果。

    ⚠️ **所有字段都没有默认值** —— 这是故意的,见模块头。
    """

    # —— 身份
    run_id: str
    meta: RunMeta
    task_id: str
    # —— 效果（PLAN §3.1）
    correct: bool
    score: float
    steps: int
    first_divergence_step: int
    escalated: bool
    gate_false_reject: bool
    gate_false_deny: bool
    #: ★ 闸门要求修订、而且**确实改好了**（草稿本来不对，改完对了）。
    #:
    #: 为什么需要它：`gate_false_reject` 修正之后只统计"草稿本来是对的却被打了回去"，
    #: 于是"闸门改好了"这一类会**从记账里消失** —— 只剩误伤一栏，读起来像闸门
    #: 只会帮倒忙。实测（`fta × react-termination`，n=100）那一批有 27 条走了
    #: 修订路径，不分出这一栏就分不清它们去哪了。
    #:
    #: ★ **不进 `REQUIRED_RESULT_FIELDS`**（和 `detail` 同一个理由）：
    #:   那张表是读回时拒收用的，加进去会让此前所有批次变成残缺行。
    #:   旧批次这一栏读不到 ⇒ 当 `False`，也就是"没记"，不是"没有发生过"。
    gate_corrected: bool
    #: ★ **闸门打回去的那一版草稿，本身过不过判分。** 这是**原始事实**，
    #: 上面那几个 `gate_*` 标志都是从它 + 最终判分推出来的。
    #:
    #: 为什么必须有它：闸门说 `blocked` 之后，我们既不知道那一版是编的还是
    #: 诚实的，也就分不出闸门是**保护**了我们（草稿在编）还是**误杀**了一个
    #: 好答案（草稿本来是诚实的）—— 一个说明闸门有用，一个说明闸门有害。
    #: 实测（`fta × react-termination`，n=100）那 27 次弃权在旧账里两者都读不出来。
    #:
    #: 只在闸门真的做过裁决（`revise` / `blocked`）且拿得到草稿时才有意义；
    #: 其余情况为 `False`，意思是**没测**，不是"草稿错了"。
    gate_draft_correct: bool
    failure_class: str
    #: ★★ **这一题为什么结束。** 六类之一，**不许合并**：
    #:
    #:     delivered  —— 交出了一个答案（`escalated=False`、正文非空）
    #:     declined   —— 这一臂**自己决定**不交（升级/弃答，非闸门拦的）
    #:     blocked    —— 闸门拦下，没有交付
    #:     exhausted  —— 步数用满，**不是**一个"决定"
    #:     error      —— 抛异常（模型/后端/环境），**不是**能力结果
    #:     parse_failure —— 输出读不出来，**不是**一个"决定"
    #:
    #: ★ 为什么是一个一等字段，而不是事后从 `answer` 事件重建：
    #:   实测（2026-10-02，重建 alfworld/fta 两批）证明**事后重建必然出错** ——
    #:   `Result` 里没有 `outcome.error`，于是一条 `agent_error` 被重建成
    #:   `exhausted`（"跑满预算"），而它其实是"抛异常"。两者的含义、
    #:   该不该进任务分母，**完全相反**。
    #:
    #: ★ 为什么必须有它（而不是继续只看 `failure_class`）：
    #:   准确率可以因式分解成 `交付率 × 交付正确率`，而**乘法把两种完全不同的
    #:   失败混成一个数**：没停下 vs 停下但停错了。不拆开，就看不出是哪一种在动。
    #:   `failure_class` 是**判分器**的口径，这个是**循环**的口径，两者不可互推：
    #:   实测 `alfworld × react` 那 2 条空答案是**升级弃答**（`declined`），
    #:   而它们和"跑满预算"在旧账里长得一模一样。
    #:
    #: ★★ **刻意不放进 `REQUIRED_RESULT_FIELDS`**：理由同 `detail` ——
    #:    那张表是读回时拒收用的，加进去会让此前所有批次变成残缺行。
    #:    旧批次读不到 ⇒ 当空串，意思是**这一栏没记**，不是"它交不出答案"。
    stop_reason: str
    #: ★ **判分器为什么这么判**（`Judgment.detail` 的原样落盘）。
    #:
    #: 以前这个字段**算出来了但没往回传** —— `run_cell` 手里一直有它，
    #: 而结果行里没有，于是"哪一条假声明被判中了"这种问题只能靠重跑才答得上来。
    #: 和 §11 记录的 `gate_false_reject` / `gate_false_deny` 是**同一个模式**：
    #: 信息在控制器手里，只是从来没往回传。
    #:
    #: ★★ **刻意不放进 `REQUIRED_RESULT_FIELDS`**：那张表是**读回来时拒收**用的，
    #:    加进去会让**之前所有批次**的 results.jsonl 全部变成"残缺行"而被丢掉 ——
    #:    为了一个诊断字段废掉已有的数据，正是本模块最反对的那种交换。
    #:    写盘一侧仍然强制（没有默认值 ⇒ 少传就 TypeError），所以新批次一定带它。
    detail: str
    # —— 成本与时间
    cost: Cost
    timing: Timing
    # —— 这次运行产出的文件（相对 run 目录）
    artifacts: tuple[str, ...]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, sort_keys=True)


# ═══════════════════════════════════════════════════════════
# 逐条记录 —— 写进 trace.jsonl / usage.jsonl
# ═══════════════════════════════════════════════════════════


#: ★★★ **一次控制是谁做的** —— `DecisionRecord.source` 的取值域。
#:
#: 四个值,而且**只有 `"judge"` 是「生成模型判的」**。论文第一根轴
#: （「控制不是生成」）量的是 `"judge"` 这一档占多少 —— 没有这一列就量不出来。
#:
#:   `"rule"`     —— **精确代码判的**,模型压根没被问。候选只剩一个 /
#:                   工具自己声明了风险 / 观测里有环境给的成败信号。
#:                   ★ 这一档**越多越好**:§8.1 说能由规则定的不交给模型。
#:   `"judge"`    —— 模型**从枚举里挑**（`choice` / `noul` / `score`）,
#:                   而且**过了门限**。这一档才是判定模型真的在管事。
#:   `"generate"` —— 自由文本,**只能生成**:模型写出来的,不是从候选里挑的。
#:                   ⚠️ 它不是判定 —— 把它算进"判定准确率"是在给一个
#:                   不可枚举的动作贴判定的标签（§8.2）。
#:   `"fallback"` —— **判定没成立,降级路径兜的底**（`fallback` 栏写名字）。
#:                   两种来路:① 后端没给 / 给了畸形的;② 给了但没过门限。
#:                   ★ 兜底本身不是错 —— `pickInput` 必须兜（否则重发相同请求,
#:                     那是抽奖,见 `BELOW_THRESHOLD_POLICY`）。**静默兜底才是错。**
DECISION_SOURCES: tuple[str, ...] = ("rule", "judge", "generate", "fallback")


@dataclass(frozen=True)
class DecisionRecord:
    """★ **一行一条判定**,不是一行一个任务。

    `confidence` 和 `correct` 必须在同一行 —— 分桶 / ECE / Brier / AUC /
    分离度 / 风险–覆盖 **全部**从这一对算出来。少了任何一个,RQ2 就是空的。

    `batch` 也要有:一次请求判多路时**按批计时**,按记录求和会多算几倍
    （我们踩过,`decisionMs` 一度比整轮墙钟还大）。
    """

    run_id: str
    task_id: str
    step: int
    node: str
    answer: str
    confidence: float
    correct: bool
    batch: int
    latency_ms: float
    #: ★ **帧的指纹**（§8.14:「`Frame.digest()` 每次都记」）。
    #:
    #: 两次运行帧不一样而没人发现,「同一个方法」这句话就不成立。
    #: 它覆盖 `Frame.render()` 的全文,而全文里**带着截断和缺失的痕迹** ——
    #: 所以这一个短串同时回答了「这一格看到了什么」和「少了什么」。
    frame_digest: str = ""
    #: ★★★ **整个请求的指纹**（帧 + 问题 + 选项）—— `Request.digest()`。
    #:
    #: ⚠️ **别用 `frame_digest` 判「两次跑的是不是同一个判定」** —— 它只覆盖帧,
    #: 而 `choice` 的**选项不在帧里**。实测:换掉候选集而帧指纹一动不动,
    #: `top` 从 1.00 掉到 0.71。拿帧指纹去比,会把这个差别读成「后端随机」。
    request_digest: str = ""
    #: ★ **这次判定为什么没成立**（空 = 一切正常）。
    #:
    #: 第 10 轮 R2/R5 那条失效链是「校验发现 → **无人接收** → 请求照发 → 静默掉点」。
    #: 违规写进内存里的一个 list 不算有人接收 —— **进了事件流才算**,
    #: 因为只有那里是跑完之后还读得到的。
    note: str = ""
    #: ★★★ **这一次判定是在什么状态下被问的** —— `frame.canonical_state()`。
    #:
    #: ⚠️ **别拿 `frame_digest` / `request_digest` 当状态键。** 它们覆盖帧的**渲染文本**,
    #:   而渲染文本里混着跟判定无关的东西(截断提示、字段顺序、列表截断位置)。
    #:   两个逻辑上一样的状态会因此得到两个指纹 ⇒ **状态重复率被低估**,
    #:   而"有效控制熵"的分母偏小。
    #:
    #: ★ 为什么必须进账:2026-10-04 第一次算这个量时,判定行里**只有指纹、没有字段值**,
    #:   于是那个数**没法从盘上重算一遍** —— 一个不能复核的数不能进论文。
    #:   这一栏是那件事的修法。
    state_key: str = ""
    #: ★★★ **这一次控制到底是谁做的** —— 见 `DECISION_SOURCES`。
    #:
    #: ⚠️ 加这一列之前,「判定模型做了这个决定」这句话**在账上不可证伪**:
    #: 一个查表得到的 `base_risk`、一个"只有一个候选所以不问"的收尾、
    #: 一次低于门限但被采用的猜测,在 `trace.jsonl` 里**长得和一次真判定一样**。
    #: 于是「多少控制是被判出来的」只能靠读代码数 —— 而那正是论文第一根轴。
    source: str = "judge"
    #: ★★ **`source="fallback"` 时,是哪一条降级路径兜的底**（否则为空）。
    #:
    #: 抄 μ（`kyrn-judge` 的 `Decision.fallback`）:它的 `DecisionSpec` **必须**
    #: 写一个 `fallback`,判定不出来就**照它执行,并记 `source:"fallback"`**。
    #: 它的理由不是"优雅",是**不许静默**:兜底可以发生,但必须留下名字。
    #: 名字表见 `jloop/typed.py` 的 `FALLBACK_POLICY`。
    fallback: str = ""


# ★ `UsageRecord` **已删** —— 它被 `core/events.py` 的 `ModelCallEvent` 取代了。
#
#   理由:一次调用的用量、时间和文本**分成三张表靠序号 join**,任何一处漏写
#   都会让那次调用看起来像没发生过。现在是一条事件装齐。
#   （这个改动是照 Inspect 的 transcript 模型做的,见 `core/events.py` 头部。）


# ═══════════════════════════════════════════════════════════
# 校验 —— 给「从盘上读回来」用
# ═══════════════════════════════════════════════════════════

REQUIRED_RESULT_FIELDS: tuple[str, ...] = (
    "run_id",
    "meta",
    "task_id",
    "correct",
    "score",
    "steps",
    "first_divergence_step",
    "escalated",
    "gate_false_reject",
    "gate_false_deny",
    "failure_class",
    "cost",
    "timing",
    "artifacts",
)

REQUIRED_TRACE_FIELDS: tuple[str, ...] = (
    "run_id",
    "task_id",
    "step",
    "node",
    "answer",
    "confidence",
    "correct",
    "batch",
    "latency_ms",
)


def missing_fields(record: dict[str, Any], required: tuple[str, ...]) -> list[str]:
    """缺哪些字段。返回空列表 = 完整。

    `summarize` 用它拒收残缺的行 —— **不许猜、不许补默认值**。
    一个补过默认值的数字,和编出来的没有区别。
    """
    return [f for f in required if f not in record]
