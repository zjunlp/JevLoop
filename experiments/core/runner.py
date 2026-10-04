"""把 `Benchmark` × `Agent` 跑成一个矩阵。**这里不做任何领域判断。**

它只做四件事:建 log 目录、逐题跑、收账、落盘。
评分在 benchmark 里,决策在 agent 里,记账在 session 里 —— runner 只负责**顺序和边界**。

★ `framework_ms` 在这里算:`墙钟 − (模型 + 判定 + 工具)`。
不留这一行,就永远不知道差距里有多少是自己的开销。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterable, Sequence

from experiments.core.agent import Agent, AgentOutcome, Session
from experiments.core.events import AnswerEvent
from experiments.core.bench import Benchmark
from experiments.core.models import ModelClient, Thinking, describe
from experiments.core.runlog import EXPERIMENTS_DIR, RunLog, archive_hint, repo_commit
from experiments.core.spec import Cost, ModelRef, Result, RunMeta, Timing
from experiments.core.tools import ToolExecutor
from experiments.core.types import Judgment, Task, Trajectory

AgentFactory = Callable[[Task, list], Agent]
"""`(task, tools) -> Agent`。**每题一个新 agent** —— 免得上一题的状态漏进下一题。"""

NecessaryToolIds = set[str]
"""哪些工具调用算「必要」。不标就默认全部必要（`ToolExecutor.call` 的 `necessary`）。"""


@dataclass(frozen=True)
class Cell:
    """一个格子:`数据集 × arm × seed`。"""

    dataset: str
    arm: str
    seed: int


def aggregate_cost(session: Session) -> Cost:
    """从**事件流**汇总。**每个数都按 PLAN §3.2 的口径拆开。**

    ★ 输入是 `session.events` —— 一次调用一条记录。以前要 join 三个文件,
    现在读一处就够,而「token 和文本对不上」这类账目问题从结构上消失了。
    """
    llm = session.model_events()
    batches = session.decision_batches()
    necessary, exploratory = session.executor.counts()
    questions = sum(b.questions_in_batch for b in batches)

    return Cost(
        llm_calls=len(llm),
        decision_requests=len(batches),
        questions_per_request=(questions / len(batches)) if batches else 0.0,
        tool_calls=necessary + exploratory,
        tool_calls_necessary=necessary,
        tool_calls_exploratory=exploratory,
        input_tokens_cached=sum(e.usage.input_tokens_cache_read for e in llm),
        input_tokens_uncached=sum(e.usage.input_tokens_uncached for e in llm),
        output_tokens_reasoning=sum(e.usage.reasoning_tokens for e in llm),
        output_tokens_visible=sum(e.usage.output_tokens_visible for e in llm),
        usd=sum(e.usage.total_cost for e in llm),
    )


def aggregate_timing(session: Session, *, wall_ms: float) -> Timing:
    llm = session.model_events()
    model_ms = sum(e.timing.total_ms for e in llm)
    decision_ms = sum(b.latency_ms for b in session.decision_batches())
    tool_ms = session.executor.total_ms()
    retry_ms = session.retry_ms()

    # ★ 框架自身开销 = 墙钟 − 其余全部。**它可以是负的**（并发/计时误差）,
    #   负的时候如实报负 —— 夹到 0 就把「我们的开销」这件事藏起来了。
    framework_ms = wall_ms - (model_ms + decision_ms + tool_ms + retry_ms)

    return Timing(
        wall_ms=wall_ms,
        model_handshake_ms=sum(e.timing.handshake_ms for e in llm),
        model_ttft_ms=sum(e.timing.ttft_ms for e in llm),
        model_after_ttft_ms=sum(e.timing.after_ttft_ms for e in llm),
        decision_handshake_ms=0.0,  # 判定后端接进来时填（L2 接缝）
        decision_compute_ms=decision_ms,
        tool_ms=tool_ms,
        framework_ms=framework_ms,
        retry_ms=retry_ms,
        round_trips=len(llm) + len(session.decision_batches()),
    )


def run_cell(
    *,
    bench: Benchmark,
    make_agent: AgentFactory,
    cell: Cell,
    model: ModelClient,
    split: str = "test",
    limit: int | None = None,
    max_steps: int = 20,
    temperature: float = 0.0,
    max_tokens: int | None = None,
    region: str = "unknown",
    cold_start: bool = False,
    log_root: Path | None = None,
    argv: Sequence[str] = (),
    only: Sequence[str] = (),
    dump_requests: Path | None = None,
    decider: ModelRef | None = None,
    thinking: Thinking | None = None,
) -> list[Result]:
    """跑一个格子。**一个格子一个 log 目录,永不覆盖。**

    `decider` = **计划用的**那个判定后端（不是实际答话的那个 —— 那条在
    `DecisionBatchEvent.provider` 里，见那里为什么两者要分开）。
    ★ 不传 = 这一臂没有判定后端。以前这一栏**写死成 `id="none"`**，
    于是带了 Jev 的格子（`react-typed` / `react-termination`）在 `meta.json` 里
    和 `direct` 长得一模一样 —— 又一个"信息在手里、没往回传"。
    """
    # ★ `only` 是**定点重跑**:给一批 task_id 的后缀,只跑那些。
    #   为什么需要它:整批 100 题里往往只有十几题是坏的,而全量一批要几分钟、
    #   还带着 ±9 的噪声（§8.17）——**盯着已知坏的那几题看,信噪比高得多**。
    #
    # ⚠️ 给了 `only` 就**不抽样**:先把全部题取回来再筛。
    #   否则「筛出来的 16 题」取决于 `limit` 和 `seed` 怎么抽的,
    #   而调用方以为自己指定的是**确切的那些题**。
    if only:
        tasks = [t for t in bench.tasks(split=split, limit=None, seed=cell.seed)
                 if any(t.task_id.endswith(x) for x in only)]
        # ★ 点名要的题**必须真的存在** —— 打错一个后缀而静默少跑一题,
        #   和 §8.10 那条「少返回答案不报」是同一个病。
        missing = [x for x in only
                   if not any(t.task_id.endswith(x) for t in tasks)]
        if missing:
            raise SystemExit(f"★ `--tasks` 里有对不上的: {missing}\n"
                             f"  现有的题样例: {[t.task_id for t in tasks[:3]]}")
        print(f"\n★ 定点重跑 {len(tasks)} 题: "
              f"{', '.join(t.task_id.split('/')[-1] for t in tasks)}\n")
    else:
        tasks = list(bench.tasks(split=split, limit=limit, seed=cell.seed))
    commit, dirty = repo_commit(EXPERIMENTS_DIR.parent)

    # ★★★ **脏工作区要在开跑之前就说,不是在跑完之后记。**
    #
    #   实测（2026-09-22）:`dirty` 是写进 `meta.json` 的,而那份文件**跑完才写** ——
    #   于是「这一整批数字不可引用」这件事,代价**随运行时长增长**:
    #   一个 `--limit 300 × 6 臂` 的跑要 1.8 小时之后才告诉你它白跑了。
    #
    #   `repo_commit` 的文档早就写着「脏工作区跑出来的数字别人复现不了,
    #   连跑它的人自己都复现不了」——**项目知道这件事,但没有任何东西据此行动。**
    #   这和 §8.6 那条「要求写在文档里、没写在代码里」是同一个病。
    #
    #   ★ 同一个 commit 加 `dirty=True` 的两次跑**可以完全不同**:
    #   实测同一天两次 `bfcl × react-typed`,commit 都是 `5e9aee6b`、都 dirty,
    #   而一次 `framework_ms=-1670`、另一次 `=2` —— 中间的修复没提交。
    #   **从日志里分不出这两次。**
    if dirty:
        print(
            "\n" + "=" * 68 + "\n"
            f"⚠️  工作区是脏的（HEAD={commit[:8]}）—— 这一批**不可引用**\n"
            "    数字别人复现不了,连你自己也复现不了:同一个 commit 加 dirty,\n"
            "    两次跑可以完全不同。\n"
            "    → 提交之后再跑,或者明确接受这批只当**筛选**,不进表。\n"
            + "=" * 68 + "\n",
            file=sys.stderr,
        )

    with RunLog(cell.dataset, cell.arm, cell.seed, root=log_root) as log:
        log.write_cmd(argv or ("<in-process>",))
        results: list[Result] = []
        log.progress(0, len(tasks))

        # ★★ **跑到一半树变了要说出来。**
        #
        #   实测（2026-09-22）:一次 `--limit 300 × 7 臂` 的后台跑跨了 **5 个 commit** ——
        #   因为我在它跑的时候一直在提交。结果那一行的七条臂**各在一个代码版本上**,
        #   而每一格单独看都是 `commits=1`,**表上完全看不出来**。
        #
        #   「跑之前干净」已经有警告了（见上面那段）;这一段管的是**跑的中途变了** ——
        #   而那种情况更隐蔽:开始是干净的,所以第一道警告不会响。
        start_commit = commit
        mid_run_change: str | None = None
        # ★ 判定后端的降落次数与实际答过话的后端（见 `DecisionBatchEvent.provider`）。
        degraded_total = 0
        answered_by: set[str] = set()

        for i, task in enumerate(tasks, start=1):
            # ★★ **在有状态的环境里,benchmark 必须知道「现在是哪个任务」。**
            #
            #   实测（2026-09-22,接 ALFWorld 时):那类数据集的每一题是一个
            #   **可交互环境**（TextWorld),`tool_impls()` 要绑定到「这一题的那个
            #   环境实例」上。而 `tool_impls()` 的签名里没有任务 ——
            #   于是只有两条路:靠**调用顺序**碰巧对上（`tasks()` 和
            #   `tool_impls()` 交替调用）,或者把这个钩子显式化。
            #
            #   顺序那条现在确实成立,但它是**隐式约定**:哪天有人把
            #   `bench.tools()` 提到循环外、或者并行跑两题,它就静默错了 ——
            #   而错法是「A 题的动作打在 B 题的环境上」,分数照出。
            #
            #   ★ 所以钩子是**可选**的（`getattr`),静态数据集一行都不用改。
            on_task = getattr(bench, "on_task", None)
            if on_task is not None:
                on_task(task)
            # ★ 题级工具集优先 —— 见 types.Task.tools 的说明
            tools = list(task.tools) if task.tools else list(bench.tools())
            executor = ToolExecutor(tools, bench.tool_impls())
            session = Session(
                run_id=log.run_id, task=task, arm=cell.arm, tools=tools, executor=executor,
                model=model, max_steps=max_steps, temperature=temperature, max_tokens=max_tokens,
                dump_requests=dump_requests,
                # ★ 推理档位一路传下去 —— 见 `Session.call_model` 里那段实测。
                thinking=thinking,
            )

            # 每题查一次「树还是不是那个」。★ 用 `repo_commit` 而不是逐文件 stat ——
            #   它读的是 git 的状态,和我们开头那次判据**同一个**,不会两套口径。
            if mid_run_change is None and i % 10 == 1:
                now_commit, now_dirty = repo_commit(EXPERIMENTS_DIR.parent)
                if now_dirty or now_commit != start_commit:
                    mid_run_change = (
                        f"第 {i} 题时工作区已经不是开始时那个了"
                        f"（开始 {start_commit[:8]} 干净,现在 {now_commit[:8]}"
                        f"{' 脏' if now_dirty else ''}）"
                    )
                    print(
                        "\n" + "!" * 68 + "\n"
                        f"⚠️  {mid_run_change}\n"
                        "    → 这一批的**不同题跑在不同代码版本上**,不能当受控比较。\n"
                        "      跑完之前不要改仓库。\n" + "!" * 68 + "\n",
                        file=sys.stderr,
                    )

            agent = make_agent(task, tools)
            if getattr(agent, "needs_success_signal", False):
                # ★ 只有声明要的臂才接得上 —— 见 core/agent.py 的说明
                session.check_answer = _make_checker(bench, task)

            t0 = time.perf_counter()
            try:
                outcome: AgentOutcome = agent.solve(session)
            except Exception as exc:  # noqa: BLE001 —— 一题挂掉不许拖垮整轮
                # ★ 记下异常类型和原文。**不吞**:trace 里留着,失败率进表。
                outcome = AgentOutcome(error=f"{type(exc).__name__}: {exc}")
                log.stop(f"task {task.task_id}: {outcome.error}")
            wall_ms = (time.perf_counter() - t0) * 1000

            # ★ 先把答案落成事件 —— 没有它,日志不自足,重判无从下手
            session.events.append(AnswerEvent(
                run_id=log.run_id, task_id=task.task_id, step=len(outcome.steps),
                text=outcome.final_answer, escalated=outcome.escalated, error=outcome.error,
                steps=len(outcome.steps), working_start=session.clock.elapsed(),
            ))

            # ★★ **先封口,再建轨迹。** 这两行的顺序是个真 bug,修于 2026-09-22。
            #
            #   原来 `trajectory()` 在 `finish_events()` **之前** ——
            #   而 `trajectory()` 里的 `decision_records()` 是从**事件流**里读的,
            #   最后一批判定那时还躺在 `_batch_decisions` 里没进事件流。
            #
            #   所以**每一题的最后一批判定都缺席了**,而它恰恰是决策性的那批
            #   （收尾那一步:判「不用再调工具了」的那次）。
            #   `finish_events` 的文档自己就写着「不封口最后一批就会丢 ——
            #   而它常常正是决策性的那批」—— 写那句警告和写这个调用顺序的是同一份代码。
            #
            #   ★ 这和第 10 轮那些事故是**同一个形状**:东西是对的,
            #   但**没有任何东西检查「它有没有被送到该到的地方」**。
            session.finish_events()
            trajectory = session.trajectory(outcome)
            judgment = _safe_score(bench, task, trajectory, outcome)
            # ★ 闸门**打回的那一版**本来对不对 —— `gate_false_reject` 全靠它才名实相符。
            draft_correct = _draft_was_correct(bench, task, trajectory, outcome)
            # ★ 判定后端降过几次级 —— 跑完要大声报（见下面 `degraded_total`）。
            degraded_total += session.decider_degradations
            if session.decider_providers:
                answered_by.update(session.decider_providers)
            log.progress(i, len(tasks))

            # ★ **一条事件流,不是一个调用摊在三张表里。**
            #   照 Inspect 的 transcript 模型做的（见 core/events.py 头部）。
            for event in session.events:
                log.append_jsonl("events.jsonl", event)

            results.append(
                Result(
                    run_id=log.run_id,
                    meta=RunMeta(
                        dataset=cell.dataset,
                        dataset_version=bench.dataset_version,
                        split=split,
                        task_count=len(tasks),
                        arm=cell.arm,
                        generator=ModelRef(**describe(model)),
                        decider=decider or ModelRef(id="none", version="n/a", provider="n/a"),
                        thinking_budget=(f"{thinking.effort}" if thinking else "server-default"),
                        temperature=temperature,
                        top_p=1.0,
                        max_tokens=max_tokens,
                        seed=cell.seed,
                        prompt_hash=_prompt_hash(bench, cell.arm),
                        decision_spec=_decision_spec(cell.arm),
                        commit=commit,
                        dirty=dirty,
                        region=region,
                        cold_start=cold_start,
                        max_steps=max_steps,
                        timeout_s=0.0,
                    ),
                    task_id=task.task_id,
                    correct=judgment.correct,
                    score=judgment.score,
                    steps=len(trajectory.steps),
                    first_divergence_step=_first_divergence(bench, task, trajectory),
                    escalated=trajectory.escalated,
                    # ★★ 这两个指标以前是从 `failure_class` 里读 `"gate_rejected_correct"` /
                    #   `"gate_passed_wrong"` —— 而**整棵树里没有任何一处产生过这两个值**
                    #   （实测：grep 只有本文件在读它），于是两栏**恒为 False**，
                    #   读起来像"没有误伤"。信息一直在控制器手里（`Decision.gate`），
                    #   只是从来没往回传。现在按 (闸门第一次裁决 × 判分结果) 算：
                    #
                    #       闸门假拒 = 第一判 revise ∧ 最终答案是对的
                    #       闸门放过 = 第一判 deliver ∧ 最终答案是错的
                    #
                    #   ⚠️ 字段名的历史遗留：`gate_false_deny` 指的是"闸门放过了错的"
                    #      （不是"拒绝了对的"）。名字反了，但它在 spec/测试里，不动它，
                    #      只在这里写明，免得下一个人再读反一次。
                    #
                    #   ★★ 2026-10-01 修正 **`gate_false_reject` 的判据**：
                    #      判的是**闸门打回的那一版草稿**，不是改完之后那一版。
                    #      旧判据（`revise ∧ 最终 correct`）把"修订救回来了"也算成误伤 ——
                    #      实测 `fta × react-termination` 报了 27 条，全部 `failure_class=none`。
                    #      改完之后那 27 条被分成：草稿本来就坏 → `gate_corrected`
                    #      （闸门立功），草稿本来就对 → 才算 `gate_false_reject`。
                    #      ⚠️ **同一个字段名，跨 commit 语义不同** —— 好在这条 pipeline
                    #      把 `commit` 当分组键的一部分，新旧批次不会进同一张表。
                    gate_false_reject=bool(outcome.gate == "revise" and draft_correct),
                    gate_false_deny=bool(outcome.gate == "deliver" and not judgment.correct),
                    # ★ 闸门要求修订、而且**确实改好了**。没有这一栏，那 27 条修好的
                    #   就从记账里消失了 —— 只剩"误伤"一栏，看起来闸门只会帮倒忙。
                    gate_corrected=bool(
                        outcome.gate == "revise" and not draft_correct and judgment.correct
                    ),
                    # ★ **原始事实**：闸门打回去的那一版草稿本身过不过判分。
                    #   上面三个标志都是从它推出来的；它留下，是为了让
                    #   "闸门说 blocked 的那 27 次到底是保护还是误杀"可查。
                    gate_draft_correct=draft_correct,
                    failure_class=judgment.failure_class or ("none" if judgment.correct else "unclassified"),
                    # ★ **循环**的口径（这一题为什么结束），和上面那个**判分器**的
                    #   口径（判成什么）是两件事 —— 一个说"它交没交、为什么没交",
                    #   一个说"交出来的东西对不对"。实测两者不可互推。
                    stop_reason=_stop_reason(outcome, max_steps),
                    # ★ 判分器的原话要落盘。以前它只活在内存里 —— `run_cell` 手里
                    #   一直有它，结果行里却没有，于是"命中哪一条假声明 / 哪一句断言"
                    #   这种问题只能靠重跑回答（和 §11 那两个死字段同一个模式）。
                    detail=judgment.detail or "",
                    cost=aggregate_cost(session),
                    timing=aggregate_timing(session, wall_ms=wall_ms),
                    artifacts=("cmd.txt", "meta.json", "exit.json", "results.jsonl",
                               "events.jsonl"),
                )
            )

        for result in results:
            log.append_jsonl("results.jsonl", result)

        # ★ **完整的那套 RunMeta 要写进 `meta.json`**,不是一个薄壳。
        #
        #   之前这里只有 run_id / cell / tasks / commit / dirty / archive,
        #   而完整的 RunMeta（含 `split` / `task_count` / 温度 / 版本 / 地区）
        #   只重复躺在每一行 `results.jsonl` 里 —— 于是 `rescore.py` 想重建
        #   **同一批题**时拿不到 `split`,直接 KeyError（实测）。
        #
        #   这条也是 PROTOCOL §3.2 要求的:「`meta.json` 装 PROTOCOL §3.7 那一套,一个不少」。
        #   一行的身份不该靠「去第一行结果里翻」才能知道。
        first = results[0].meta if results else None
        log.write_meta(
            {
                "run_id": log.run_id,
                "cell": {"dataset": cell.dataset, "arm": cell.arm, "seed": cell.seed},
                "archive": archive_hint(log.dir),
                # 完整 RunMeta 摊平 —— 这就是「这次运行是什么」
                **({} if first is None else {
                    "dataset": first.dataset,
                    "dataset_version": first.dataset_version,
                    "split": first.split,
                    "task_count": first.task_count,
                    "arm": first.arm,
                    "generator": describe(model),
                    "temperature": first.temperature,
                    "max_tokens": first.max_tokens,
                    "seed": first.seed,
                    "prompt_hash": first.prompt_hash,
                    "commit": first.commit,
                    "dirty": first.dirty,
                    "region": first.region,
                    "cold_start": first.cold_start,
                    "max_steps": first.max_steps,
                }),
            }
        )
        # ★ 中途变过就记进 `exit.json` 的 `stop_reason` —— 归档之后那是唯一线索。
        if mid_run_change:
            log.stop(f"★ 这一批跨了多个代码版本：{mid_run_change}")
        # ★★ **判定后端降过级就必须大声报。** 判定后端是一条降级链，而正常降级
        #   以前在日志上不留痕 —— 于是"这一批跑的是真 Jev"是一个**不可证伪**的说法。
        #   实测（2026-10-01）：152 批零降级，但那是查出来的，不是推出来的。
        if degraded_total:
            msg = (
                f"★ 判定后端降级 {degraded_total} 次（回答过话的后端："
                f"{sorted(answered_by)}）—— 这些判定**不来自计划用的那个后端**，"
                f"数字要单独看"
            )
            print("\n" + "!" * 68 + f"\n⚠️  {msg}\n" + "!" * 68 + "\n")
            log.stop(f"{mid_run_change or ''}{'；' if mid_run_change else ''}{msg}")
        elif answered_by:
            print(f"  判定后端实际答话：{sorted(answered_by)}（无降级）")
        return results


def _make_checker(bench: Benchmark, task: Task):
    """把 benchmark 的 `check()` 包成一个布尔判据。**没实现就返回 None。**"""
    hook = getattr(bench, "check", None)
    if hook is None:
        return None
    return lambda answer: bool(hook(task, answer))


def _no_answer_class(outcome: AgentOutcome) -> str:
    """没有可交付答案时，**是"谁"没交出来**。

    ★★ 这一栏原来只有 `agent_error` 一个值 —— 于是三种完全不同的结局在记账里
    长得一模一样（实测 `fta × react-termination`，n=100）：

        · 闸门说 `blocked` → 退回弃答     ← **闸门在弃权**，不是我们崩了
        · 模型自己要求问人 / 步数用完      ← agent 弃权
        · `TimeoutError` 之类的真异常      ← 这才是 harness 故障

    前两种都是**弃权**，而本项目的规矩就是弃权必须单独计
    （`core/decisions.py` 那条「『我不确定』不是『我判对了』，也不是『我判错了』」）。
    混在一栏的后果是实的：那 28 次闸门弃权会被读成 28 次崩溃。

    ★ 判据用**结构字段**（`escalated` / `gate`），不靠匹配 `error` 里的中文 ——
      文案一改，匹配就静默失效。
    """
    if outcome.escalated:
        return "gate_blocked" if outcome.gate == "blocked" else "no_answer"
    return "agent_error"


def _stop_reason(outcome: AgentOutcome, max_steps: int) -> str:
    """这一题**为什么结束**。六类,不许合并（见 `spec.Result.stop_reason`）。

    ★ 判据只能在这里算 —— `Result` 里没有 `outcome.error`,事后从事件流重建
      会把"抛异常"读成"跑满预算",而这两件事一个该进分母一个不该。

    ★★ **`escalated` 一个标志盖了三件事,这里必须按结构拆开。**

      `baseline/common.py` 里三处都返回 `escalated=True`：

          ① 闸门说 `blocked`、所以退回弃答            → `blocked`
          ② 控制器要求问人（`ask`）                    → `declined`
          ③ **步数用完了**（`for _ in range(max_steps)` 跑完）→ `exhausted`

      那段代码自己的注释已经记下了这个坑（"和'步数用完了'长得一模一样"），
      所以这里**不能**只凭 `escalated` 判 —— 那正是旧账分不出
      "闸门拦下的 28 条"和"TimeoutError"的原因。

      ⚠️ 判据用 `len(outcome.steps) >= max_steps`（**结构**，不是匹配错误文本）：
        循环体只在 `len(steps) < max_steps` 时运行,所以 `ask` 那一支不可能
        在步数满时触发 —— 到那时循环已经退出去返回 ③ 了。
    """
    if outcome.escalated and outcome.gate == "blocked":
        return "blocked"
    if outcome.escalated and len(outcome.steps) >= max_steps:
        return "exhausted"
    if outcome.escalated:
        return "declined"
    if outcome.error:
        return "error"
    if (outcome.final_answer or "").strip():
        return "delivered"
    return "exhausted"


def _draft_was_correct(
    bench: Benchmark, task: Task, trajectory: Trajectory, outcome: AgentOutcome
) -> bool:
    """闸门打了 `revise` 时，**改之前那一版**本来是不是对的。

    ★★ 不判这一栏，`gate_false_reject` 就是错的。它想说的是"闸门把一个本来对的
    答案打回去了"，而 `correct` 判的是**改完之后**那一版 —— 于是
    「第一判 revise ∧ 最终正确」把两件相反的事混成一件：

        草稿是坏的 → 修订救回来了   ⇒ 闸门**立功**（新字段 `gate_corrected`）
        草稿是好的 → 修订多此一举   ⇒ 闸门**误伤**（`gate_false_reject`）

    实测那 27 条按旧判据全被记成误伤，实际一条都分不出是哪一种。

    ★ 只在闸门**真的做过裁决**（`revise` / `blocked`）且拿得到草稿时才判：
      这两条路才是"闸门把一个东西打回去了"；`deliver` 的草稿就是最终答案，另算。
    ★ 判不了就返回 `False`，**不猜** —— 没有 `check()` 又判分失败的 benchmark 上，
      这一栏退回旧行为，几个字段都不报。
    """
    if not outcome.draft or outcome.gate not in ("revise", "blocked"):
        return False
    try:
        checker = _make_checker(bench, task)
        if checker is not None:
            return bool(checker(outcome.draft))
    except Exception:  # noqa: BLE001 —— `check()` 抛不代表判不了,见下
        # ★★★ **回落,不是吞掉。** 实测（2026-10-02，ALFWorld）这个洞让两个字段
        #   整个失效：ALFWorld 的 `check()` **故意抛** `NeedsTextWorld`
        #   （成败在环境状态里,不在答案字符串里 —— 它自己的文档就这么写的）。
        #   异常被吞 ⇒ `draft_correct` **恒为 False** ⇒
        #       `gate_false_reject` 恒为 0（读起来像"闸门一次没错杀"）
        #       `gate_corrected`   退化成 `revise ∧ correct`
        #   于是**闸门在两道已经赢了的题上打回答案**这件事,
        #   被记成了"闸门改好了 2 条" —— **误杀被记成功劳**。
        #
        #   ⇒ 回落去 `score()`：它的判据是**回放轨迹**，对 ALFWorld 而言
        #     草稿和终稿动作相同 ⇒ 判分相同 ⇒ `draft_correct == correct` ⇒
        #     那两个字段才回到它们的本义。
        pass
    try:
        return bool(
            bench.score(task, replace(trajectory, final_answer=outcome.draft)).correct
        )
    except Exception:  # noqa: BLE001 —— 判草稿失败不许把整轮带走
        return False


def _safe_score(bench: Benchmark, task: Task, trajectory: Trajectory, outcome: AgentOutcome) -> Judgment:
    """评分失败不许把整轮带走 —— 但也**不许当成对**。

    当成对是最坏的一种处理:它把「判分器坏了」变成「我们赢了」。
    """
    if outcome.error:
        return Judgment(correct=False, score=0.0, detail=outcome.error,
                        failure_class=_no_answer_class(outcome))
    try:
        return bench.score(task, trajectory)
    except NotImplementedError:
        raise
    except Exception as exc:  # noqa: BLE001
        return Judgment(correct=False, score=0.0, detail=f"scorer: {exc}", failure_class="scorer_error")


def _first_divergence(bench: Benchmark, task: Task, trajectory: Trajectory) -> int:
    """第一次走偏在第几步。benchmark 没给 oracle 就返回 -1（**不是 0**）。"""
    hook = getattr(bench, "first_divergence_step", None)
    if hook is None:
        return -1
    return int(hook(task, trajectory))


def _decision_spec(arm: str) -> str:
    """类型化那几臂的**判定规格版本**（`版本@指纹`）；别的臂是空串。

    ★ 只有用 `TypedController` 的臂才有"问法可谈"。给 `direct` 也填一个，
      会让"改过问法"和"这一臂没有问法"在表里长得一样。
    """
    if "typed" not in arm and arm != "react-termination":
        return ""
    from experiments.jloop.typed import DECISION_SPEC_VERSION, decision_spec_digest

    return f"{DECISION_SPEC_VERSION}@{decision_spec_digest()}"


def _prompt_hash(bench: Benchmark, arm: str) -> str:
    import hashlib

    blob = f"{bench.name}:{bench.dataset_version}:{arm}".encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def run_matrix(
    *,
    bench: Benchmark,
    arms: dict[str, AgentFactory],
    seeds: Iterable[int],
    model: ModelClient,
    **kwargs,
) -> list[Result]:
    """`benchmark × arm × seed`。**逐格串行** —— 并行留给调用方,免得两处都在管资源。"""
    out: list[Result] = []
    for arm_name, factory in arms.items():
        for seed in seeds:
            out.extend(
                run_cell(
                    bench=bench, make_agent=factory,
                    cell=Cell(dataset=bench.name, arm=arm_name, seed=seed),
                    model=model, **kwargs,
                )
            )
    return out
