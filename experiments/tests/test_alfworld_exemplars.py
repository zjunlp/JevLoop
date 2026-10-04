"""ALFWorld 的 few-shot 示范 —— **它没接上过一次，而且代价被量到了。**

★ 这个文件最值钱的两条：

  `test_the_react_arm_actually_accepts_exemplars`
      基准声明了示范、臂却不接受 ⇒ 静默丢掉 ⇒ 跑出来的数和没有示范一样，
      而日志上看不出区别。**"配了没生效"是这个项目的老毛病**
      （`thinking` 那一格刚栽过一回：`Thinking` 类型在 `models.py` 里躺了很久，
      而 `Session.call_model` 从来没传它）。

  `test_the_exemplars_teach_the_two_things_we_measured`
      示范不是装饰，它对着两个**实测到的**失败：

        ① 6/10 撞满 30 步从没调 `finish`（"stuck in a loop trying to move cup 1"）
        ② 3/10 草率 `finish`（"successfully moved the saltshaker 1 ... completing the task"）

      所以示范里必须既有**交互形状**、又有**收尾前要见到证据**。少任何一条，
      这份测试就红 —— 免得以后有人把它删成一两行"示例"。
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.benchmark.alfworld.alfworld import (  # noqa: E402
    ALFWORLD_EXEMPLARS,
    AlfWorld,
)


def test_alfworld_declares_exemplars() -> None:
    text = AlfWorld().exemplars()
    assert text.strip(), "ALFWorld 必须给出示范 —— 空的等于没接"
    assert text == ALFWORLD_EXEMPLARS


def test_the_react_arm_actually_accepts_exemplars() -> None:
    """★★ 签名里没有 `exemplars` ⇒ `make_agent` 会静默不传 ⇒ 示范白写。"""
    from experiments.scripts.run import _BUILTIN_ARMS

    params = inspect.signature(_BUILTIN_ARMS["react"]).parameters
    assert "exemplars" in params, (
        "react 臂不收 exemplars —— `run.py::make_agent` 会静默丢掉它，"
        "而跑出来的数和没有示范一模一样"
    )


def test_every_arm_that_should_carry_exemplars_can_receive_them() -> None:
    """★★★ **同一族的臂要么都拿得到示范、要么都不拿 —— 不许一半一半。**

    ★ 这条是实测撞出来的（2026-10-02，ALFWorld × seed20261003）：

      `run.py::make_agent` 按**签名**判断要不要把 `bench.exemplars()` 传下去。
      `react` 是裸类，签名里有 `exemplars` ⇒ 拿到（prompt 3939 字符）；
      `react-termination` 当时是 `lambda: ReAct(...)`，**一个参数都不收**
      ⇒ 示范被**静默丢掉**（prompt 1690 字符）。

      后果不是"少了个提示"，是**整批对比作废**：
      `react` 10/20 vs `react-termination` 3/20，而两者的 prompt 差着一段示范 ——
      差值里混进了一个**和自变量无关的东西**。
      旁证：两臂从**第 0 步**就分叉（20 题只有 7 题前两步相同），
      而闸门只在终点运行，**它不可能影响第 0 步**。

    ★ 那个签名检查防的是 TypeError，**防不住静默丢参数** ——
      所以这里逐个钉住"该拿到的臂拿得到"。
    """
    import inspect

    from experiments.scripts.run import typed_arms

    class _Decider:
        name = "stub"

    for name in ("react-typed", "act-typed", "react-termination", "react-selfcheck"):
        factory = typed_arms(_Decider())[name]
        params = inspect.signature(factory).parameters
        assert "exemplars" in params, (
            f"{name} 的工厂不收 exemplars —— `make_agent` 会静默丢掉基准给的示范，"
            f"这一臂和同族其它臂就不再是同一个提示了"
        )


def test_other_benchmarks_are_not_touched() -> None:
    """★★ 示范是 **(基准 × 臂)** 的属性。别的基准不该凭空多出一份 ALFWorld 示范 ——
    那会把它们的 react 基线悄悄改掉。"""
    from experiments.benchmark.gsm8k.gsm8k import Gsm8k

    assert not hasattr(Gsm8k(), "exemplars"), "只有声明了它的基准才该有"


def test_the_exemplars_teach_the_two_things_we_measured() -> None:
    """★ 对着两个实测失败各教一条，缺一条就红。"""
    t = ALFWORLD_EXEMPLARS

    # ① 交互形状：变换要先走到对的电器那儿
    for verb in ("act[go to", "act[open", "act[take", "act[clean", "act[put"):
        assert verb in t, f"示范里缺这个动作形状：{verb}"
    for appliance, verb in (("sinkbasin", "clean"), ("microwave", "heat"),
                            ("fridge", "cool")):
        assert appliance in t and verb in t, f"缺「{verb} 要用 {appliance}」"

    # ② 收尾前要见到证据 —— 直接对着那 3 题草率 finish
    low = t.lower()
    assert "observation" in low and "finish" in low
    assert "confirmed" in low, "必须写明**见到确认之后**才能收尾"

    # ③ 卡住了要换做法 —— 对着那 6 题死循环
    assert "nothing happens" in low, "必须提醒「没变化就换个做法」"

    # ④ ★★ **必须拿着物体再变换，不能先放进去** —— 实测最大的一个坑：
    #    `move apple 1 to microwave 1` 之后 `heat ...` 恒返回 Nothing happens，
    #    模型于是反复 close/heat（6 次 close microwave 1）直到撞满 30 步。
    #    这是"人的直觉"与 ALFWorld 动词语义不一致的地方，示范里不明说推不出来。
    assert "holding the object" in low or "in your hand" in low
    assert "do not put the object into the appliance" in low, (
        "必须明说「不要先放进去再变换」—— 那是这个环境最常见的卡死方式"
    )


def test_the_exemplars_do_not_contradict_the_format_rule() -> None:
    """格式说明写着「不要自己写 Observation」，示范里就不能出现 Observation 行 ——
    自相矛盾的 prompt 会让模型两件事都不听。"""
    from experiments.baseline.common import FORMAT_WITH_THOUGHT

    assert "do not write the Observation" in FORMAT_WITH_THOUGHT
    for line in ALFWORLD_EXEMPLARS.splitlines():
        assert not line.strip().startswith("Observation:"), line
