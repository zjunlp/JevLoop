"""**零资源自检**这条臂 —— SelfCheckGPT 那个思路在"交付判定"上的移植。

══════════════════════════════════════════════════════════════
  它是文献里"自己查自己"的标准做法，而且**不碰金标、不用判定后端**
══════════════════════════════════════════════════════════════

出处：Manakul, Liusie & Gales, *SelfCheckGPT: Zero-Resource Black-Box Hallucination
Detection for Generative Large Language Models*, EMNLP 2023。
核心想法一句话：**同一段提示多采几次；模型真知道的事会前后一致，编的事会发散。**
它不需要外部知识库、不需要金标、不需要另训一个模型 —— 所以它是最常被拿来当
"自检"对照的那一个（公开实现见 `wangxinyufighting/selfcheckgpt`）。

──────────────────────────────────────────────────────────────
  ★★ 我们的移植，以及**必须一起报的偏离**
──────────────────────────────────────────────────────────────

原方法判的是**自由文本里的事实性**（拿 NLI / BERTScore / n-gram 比多次采样）。
我们判的是**任务做完没有**，而证据是同一批工具输出。所以这里的做法是：

    在内层控制器给出最终答案之后，用**同一份 (任务 + 已发生的工具历史)**
    再采 `k` 次答案，算它与原答案的平均两两一致度（`token_f1`，逐字复用
    `benchmark/rewoo_port.py` 里那个，不另写一份）。
    一致度低于 `threshold` ⇒ 判 `revise`；否则 `deliver`。

**三条偏离，报告里必须跟着数字一起写：**

1. **它的判据是"自洽"不是"正确"。** 一个**稳定地**犯同一个错的模型会拿高分。
   这是这个方法公开的已知弱点，也是这一格要量的东西。
2. **它要花 `k` 次额外生成**（这里是 3 次）。所以成本必须记进去 ——
   它省掉的是判定后端的钱，不是模型的。
3. **它看不见工具输出的真假。** 它比的是"我再说一遍还这么说吗"，
   而"我说的这句有没有被证据支持"它无从判断。⇒ 在**工具撒谎**那一类条件上，
   它**结构上抓不到**（预言：`unsupported` 那一侧的捕获率应当接近 0）。
   这条预测是这一格存在的理由之一 —— 它是可以被证伪的。

★ 它和 `react-termination` 落在**同一根轴的同一点**（终点判定），所以两者
  可以逐格对比：同一个循环、同一批工具、同一个终点，只有**验证者**不同：
  `react-termination` = 判定模型读有界帧；`react-selfcheck` = 生成模型自查自洽。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from experiments.baseline.common import LLMController
from experiments.benchmark.rewoo_port import token_f1
from experiments.core.agent import Session
from experiments.core.controller import Decision, DecisionView

#: `Answer again` 那一次的提示。**只用帧里已有的东西**（任务 + 已发生的步骤），
#: 不加任何新信息 —— 加了就不是"同一段提示多采几次"了。
RESAMPLE_ASK = (
    "\n\nAnswer the task above again, on your own. "
    "Reply with ONLY your final answer, no explanation, no preamble."
)


@dataclass
class SelfCheckController:
    """零资源自检：多采几次，看它自己前后一致不一致。"""

    inner: object = field(default_factory=LLMController)
    #: 额外采几次（原方法也是这个数量级）
    k: int = 3
    #: 平均两两 `token_f1` 低于它 ⇒ 判不合格。0.5 是**拍的**，见 `threshold_note`
    threshold: float = 0.5
    name: str = "react-selfcheck"
    #: 第一次裁决（`deliver` / `revise`），进 `AgentOutcome.gate`
    first_verdict: str = ""
    #: 实测到的一致度，随轨迹留下来（报告里要能看见它判的依据）
    consistency: float = -1.0

    def decide(self, session: Session, view: DecisionView) -> Decision:
        d = self.inner.decide(session, view)  # type: ignore[attr-defined]
        if d.kind != "answer" or not d.answer:
            return d

        samples = [self._resample(session, view) for _ in range(max(0, self.k))]
        samples = [s for s in samples if s]
        if not samples:
            # 一次都没采出来 ⇒ **不许**当成"通过"（那会把"没做成"读成"没事"）
            return Decision(kind="ask", thought="零资源自检：一次都没采出答案",
                            answer="", gate="blocked")

        self.consistency = sum(token_f1(s, d.answer) for s in samples) / len(samples)
        verdict = "deliver" if self.consistency >= self.threshold else "revise"
        if not self.first_verdict:
            self.first_verdict = verdict

        if verdict == "revise":
            # 和另两条臂同一条纪律：**上限 1 次**，第二次仍不合格就如实交出去。
            revised = self._resample(session, view) or d.answer
            second = sum(token_f1(s, revised) for s in samples) / len(samples)
            if second >= self.threshold:
                self.consistency = second
                return Decision(kind="answer", answer=revised,
                                thought=f"零资源自检：revise → 修订一次后自洽 {second:.2f}",
                                syntax="generated", gate=self.first_verdict)
            return Decision(kind="answer", answer=revised,
                            thought=(f"零资源自检：两次都不自洽（{self.consistency:.2f} / "
                                     f"{second:.2f}），如实交出去"),
                            syntax="generated", gate=self.first_verdict)

        return Decision(kind="answer", answer=d.answer,
                        thought=f"零资源自检：自洽 {self.consistency:.2f} ≥ {self.threshold}",
                        syntax=d.syntax or "generated", gate=self.first_verdict)

    def _resample(self, session: Session, view: DecisionView) -> str:
        """再要一个答案。**走 `session.call_model`** —— 于是这几次生成会被记账。

        ★ 必须走 `session`，不许绕过它直接打后端：绕过的那几次不进账本，
          "这个方法便宜"就会变成一个假的结论（它一次判定都不花，但要花生成）。
        """
        from experiments.core.models import Message

        prompt = view.prompt + RESAMPLE_ASK
        return (session.call_model([Message(role="user", content=prompt)]).text or "").strip()


__all__ = ["SelfCheckController", "RESAMPLE_ASK"]
