"""**终点验证**这条臂 —— 论文那句话里的"只在终点验证"。

══════════════════════════════════════════════════════════════
  它和 `react-typed` 只差一件事，而那一件事就是原计划的"关键比较"
══════════════════════════════════════════════════════════════

`docs/RESEARCH-AND-STANDARD-DIRECTION-2026-09.md` §3.3 最后一行：

> 关键比较是「**只在终点验证**」与「**在整个工具循环中使用 decision contract**」的差异。

两条臂**共用**同一个 `run_loop`、同一个 `build_prompt`、同一批工具、**同一个交付闸门**
（`TypedController._can_deliver`，逐字复用，没有第二份实现）。差别只有一处:

    react-typed        每个岔路口都问判定模型：还需不需要动手 / 挑哪个工具 / 挑哪个输入 /
                       风险几级 / 这一步成了吗 / 做完了吗 / 能交付吗（七个节点）
    react-termination  **前面六个全由生成模型自己决定**（`LLMController`），
                       只有最后那一个（能不能交付）问判定模型

★ 所以这两个格子之间的差**只可能来自"判定放在哪、放几次"** —— 不是声明，是构造。
  和 `baseline/README.md` 那条纪律一致：臂与臂之间只许差在自变量上。

──────────────────────────────────────────────────────────────
  ★ 一个必须先说清的语义：这道闸门**不是拦截器**
──────────────────────────────────────────────────────────────

`_finish` 的原话是「**上限 1 次**：第二次还不合格就**如实交出去**并说明」。
也就是说全契约里 `canDeliver` 的作用是**触发一次修订**，不是拒绝交付。
这条臂照抄同一套（连上限都一样），否则比的就变成了"会不会拒答"，而不是"判定放在哪"。

于是这两个指标的算法是（`runner.py` 里实现）:

    闸门假拒 = 闸门第一判说 revise ∧ 最终答案**是对的**   ← 它拦了一个好答案
    闸门放过 = 闸门第一判说 deliver ∧ 最终答案**是错的** ← 它放了一个坏答案

★ 取**第一次**裁决，不是最后一次：修订后再判的那个数已经被闸门影响过了，
  拿它算"闸门错没错"是循环论证。

⚠️ **已知的粗**：`闸门放过` 把"放走了一个答错的"和"放走了一个如实认输的"算在一起。
   要分开需要"这句话有没有声称完成"的判据，而 Python 侧没有那把尺子
   （尺子在 TS 侧，`src/claim-outcome.ts`）。所以它是**上界**，报告里要这么写。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experiments.baseline.common import LLMController
from experiments.core.agent import Session
from experiments.core.controller import Decision, DecisionView
from experiments.jloop.typed import TypedController, ctx_from_steps


@dataclass
class TerminationOnlyController:
    """生成模型决定一切；**只有最后那次交付**交给判定模型。"""

    #: 里面那个"未解耦"的控制器。默认 `LLMController`（决定藏在生成里）。
    inner: object = field(default_factory=LLMController)
    #: 交付闸门 —— **直接复用全契约那一个**，不是另写一套。
    gate: TypedController = field(default_factory=TypedController)
    name: str = "react-termination"
    #: 闸门第一次给出的裁决（`deliver` / `revise` / `blocked` / `""` 没跑）
    first_verdict: str = ""

    def decide(self, session: Session, view: DecisionView) -> Decision:
        d = self.inner.decide(session, view)  # type: ignore[attr-defined]

        # 不是最终答案 ⇒ 原样放行，这一臂**不在循环中间插任何判定**
        if d.kind != "answer" or not d.answer:
            return d

        # ★ 到终点了 —— 这里才开始做判定。帧和全契约**同一个构造方式**。
        ctx = ctx_from_steps(view.task_prompt, list(view.history))
        ctx.draft = d.answer
        verdict, feedback = self.gate._can_deliver(session, view, ctx)
        if not self.first_verdict:
            self.first_verdict = verdict  # ★ 只记第一次

        if verdict == "revise":
            # 和 `_finish` 一样：**上限 1 次**，第二次仍不合格就如实交出去
            revised = self.gate._answer_text(session, view, revise=feedback)
            ctx.draft = revised
            again, _ = self.gate._can_deliver(session, view, ctx)
            if again == "deliver":
                verdict = "deliver"
            return Decision(kind="answer", answer=ctx.draft,
                            thought=f"生成答案（终点验证：revise → 修订一次，第二次={again}）",
                            syntax="generated", gate=self.first_verdict)

        if verdict == "blocked":
            # 闸门发不出去（帧缺依据 / 超预算）⇒ 如实弃答，不当成"通过了"
            return Decision(kind="ask", thought="终点验证：闸门 blocked（帧缺依据）",
                            answer="", gate="blocked")

        return Decision(kind="answer", answer=d.answer,
                        thought="生成答案（终点验证：deliver）",
                        syntax=d.syntax or "generated", gate=self.first_verdict)


__all__ = ["TerminationOnlyController"]
