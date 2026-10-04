# Ablation ladder: closing the gaps to the two peer frames

**为什么有这一页。** `docs/PEER-FRAME-CONSTRUCTION.md` §八 列出了我们在帧/决策层**不如**
`browser-use/jev-ultrafast` 和 `qybaihe/mu` 的地方。这一页逐条关掉它们 ——
**一次只改一处，改完就量，每次单独一个 commit**，因为每一步消融都要能进论文的分析实验。

★ 规矩（这一页存在的意义就是守住它）：

1. **一个 commit 只改一个地方。** 改完先提交，**在工作区干净的状态下**跑那一批。
2. **跑的时候一个字都不改仓库。** 改了就跑出一个跨代码版本的批次（这一轮已经栽过三次）。
3. **每一格都报。** 不挑好看的；变差的那一格正是论文要的那条曲线。
4. **不动 benchmark 的判分。** 那是一条硬约束，一个字都不许改。

## 标准批次（每次消融都跑这一套）

20 题、seed `20261003`、温度 0、生成 `qwen3.5-9b-local`、判定 `jev-1.13.0`。

```bash
M="--model qwen3.5-9b-local --base-url http://127.0.0.1:8001/v1 --api-key local \
   --max-tokens 2048 --decider http"

# ① TERNARY 默认臂 ×2
for i in 1 2; do
  python3 -m experiments.scripts.run --benchmark ternary-judge --split test \
    --agent react-typed --limit 20 --seed 20261003 --max-steps 8 $M
done

# ② ALFWorld 默认臂 ×1
python3 -m experiments.scripts.run --benchmark alfworld --split valid_unseen \
  --agent react-typed --limit 20 --seed 20261003 --max-steps 30 $M
```

**只在改动影响准入型题形时**，再加这两格（它们才是那类改动的落点）：

```bash
for i in 1 2; do
  python3 -m experiments.scripts.run --benchmark ternary-judge --split test \
    --agent react-typed-admission --limit 20 --seed 20261003 --max-steps 8 $M
done
python3 -m experiments.scripts.run --benchmark alfworld --split valid_unseen \
  --agent react-typed-admission --limit 20 --seed 20261003 --max-steps 30 $M
```

**为什么 TERNARY 跑两次、ALFWorld 只跑一次**：TERNARY 一题约 10 秒、ALFWorld 一题约 1 分钟。
ALFWorld 20 题的 run-to-run 标准差是 **1.30 题**（`docs/ALFWORLD-VARIANCE.md`），
所以**单次 ALFWorld 的差读不出结论** —— 这一页的 ALFWorld 列只当**筛选**，
要主张差异必须补重复批次。TERNARY 两次能看出抖动。

## 基线（`cd2bd5f`，代码与 `1fe533f` 逐字节相同 —— `git diff --name-only 1fe533f cd2bd5f -- experiments/` 为空）

| 格 | 数 |
|---|---|
| TERNARY `react-typed`（默认＝比较型） | **11, 11** / 20 |
| TERNARY `react-typed-admission`（强制准入型） | **9, 9** / 20 |
| ALFWorld `react-typed`（默认＝比较型） | **2** / 20 |
| ALFWorld `react-typed-admission`（强制准入型） | **0** / 20 |

**参照臂**（不是这一轮量的，只作上下文，出处见各自的 run 目录）：

| 臂 | TERNARY | ALFWorld |
|---|---|---|
| `react`（朴素 ReAct，无判定层） | 14 / 20 | 10.2 / 20 |

★ 注意最后这一行：**在 ALFWorld 上，加了判定层的三个臂（0~2/20）全都远低于不加判定层的 `react`（10.2/20）。**
这一页要关的是「我们不如同伴」的差距，而**那个更大的缺口是「我们不如自己的朴素基线」**。
两者不是同一件事，别让这一页的数字盖住它。

## 阶梯

每条一行；`改了没有` 记的是**行为有没有变**（有些改动是守卫，行为不变，那也是一条结论）。

| # | 改什么（缺口） | commit | TERNARY 默认 | ALFWorld 默认 | 行为变了没有 | 读法 |
|---|---|---|---|---|---|---|
| — | 基线（历史完整批次） | `b9d7df1` / `1fe533f` | 11, 11 | 2 | exact run commits listed below | ALFWorld baseline used `1fe533f`; no claim that `cd2bd5f` produced it |
| A1a | 只换回答类型：布尔 → true/false/unclear 选择题；题面、帧、0.5 门限不变 | `d874239` | 11, 11 | 3 | 准入型 TERNARY：9, 9 → 9, 9；ALFWorld：0 → 0 | 仅换回答类型没有改善；TERNARY 逐题配对无变化。ALFWorld 单次仅筛选 |
| A1b | 单独改为“够不够”问法；保留旧布尔回答类型 | `5546011` | 12, 11 | 3 | 准入型 TERNARY：9, 9 → 9, 9；ALFWorld：0 → 0 | TERNARY 无变化；ALFWorld 多行动但仍未完成，单次仅筛选 |
| A2 | 准入型的逃逸＝**平先验/取排序第一**，不再拿门限卡（缺口 2） | | | | | |
| A3 | 布尔判定点的**三区**：中间区落到调用方的默认（缺口 2） | | | | | |
| A4 | 门限**按题型分开声明**，用错题型就抛错（缺口 1） | | | | | |
| A5 | 新决策点默认 **`shadow`**（缺口 4） | | | | | |
| A6 | **长字段放最后**，让截断切在该切的地方（缺口 5a） | | | | | |
| A7 | 逃逸口改到**定义时**强制（缺口 5b） | | | | | |
| A8 | 状态与题**一起洗密钥**（缺口 5c） | | | | | |
| A9 | **候选截断进帧**（缺口 5d，这条是我们自己的缺口） | | | | | |

## 有效配置记录回归（`00afd69`）

这次提交只改变运行元数据，不改变 controller 行为。它让每个 run 落盘实际 controller 配置及 digest。
有效回归结果：TERNARY 默认 10/20、10/20；准入 9/20、9/20；suffices 9/20、9/20。
配置 digest 分别为 `b5a60af92540f3c1`、`57a173e74780c5a9`、`9dc5803915a06982`，不再共用一个有效配置身份。
ALFWorld 默认批次有 1 次降级，故只作筛选；两个准入批次无降级，均为 0/20。

## 后端 provenance 回归（`9292345`）

这次改动只增加结构化 `actual_provider` / `fallback_chain`，不改变 controller 行为。
TERNARY：默认 10/10，准入 9/9，suffices 9/9；ALFWorld：默认 2/20，准入 0/20，suffices 1/20。
完整批次 dirty=false、无降级。正常批次的 actual provider 是 `http:jev-1.13.0`；规则/非后端批次的 actual provider 可为空，不能误读成 Mock。

## 双重截断元数据回归（`a6418e8`）

只改变帧截断信息的表达，不改变候选、题面或工具策略。有效结果：
TERNARY 默认 12/11，准入 9/9，suffices 9/9；ALFWorld 默认 1，准入 0，suffices 0。
所有 run dirty=false、无降级、正常结束。该改动未产生可读出的行为差异，收益是帧证据不再丢失。

## A1a 结果及运行出处

有效运行均来自 `d87423988193519cc01112a7762911f0c62b8d2b`，dirty=false，exit.stop_reason=null，无判定降级。

| 数据集 / 臂 | run 时间戳（均 seed20261003） | 任务正确数 |
|---|---|---|
| TERNARY 默认 | 2026-10-04T14-51-26Z / 14-55-15Z | 11/20 / 11/20 |
| TERNARY 布尔准入 | 2026-10-04T14-59-07Z / 15-02-52Z | 9/20 / 9/20 |
| TERNARY 选择准入 | 2026-10-04T15-06-37Z / 15-10-22Z | 9/20 / 9/20 |
| ALFWorld 默认 | 2026-10-04T15-48-03Z | 3/20 |
| ALFWorld 布尔准入 | 2026-10-04T16-10-09Z | 0/20 |
| ALFWorld 选择准入 | 2026-10-04T16-16-19Z | 0/20 |

TERNARY 两次配对：布尔独对=0，选择独对=0；两种准入型均为 29 次工具调用。
这支持一个窄结论：在相同题面、帧及 0.5 策略下，换回答类型未改善这批任务。
它不证明概率校准相同，也不证明更换门限或问法无效。

ALFWorld 首批 15-14-06Z / 15-37-46Z / 15-41-47Z 分别有 5 / 15 / 6 条 agent_error，
exit.stop_reason 为 Connection refused。三格均排除，不把日志填满 20 行视作有效完成。
重跑三格才列入上表。单次 ALFWorld 只作筛选，不作显著性结论。

全局 spec digest 目前不能区分控制器字段 admission_answer_kind；本次靠明确臂名、提交、
同帧同题面的回归测试及请求 digest 区分。后续先补有效配置记录和真实后端出处，再做论文汇总。

## A1b 结果及运行出处

有效运行均来自 `5546011feab14e59c26a2dd74b5590a2503bfc42`，dirty=false，exit.stop_reason=null，无判定降级。

| 数据集 / 臂 | run 时间戳（均 seed20261003） | 任务正确数 |
|---|---|---|
| TERNARY 默认 | 2026-10-04T16-36-39Z / 16-40-32Z | 12/20 / 11/20 |
| TERNARY 布尔准入 | 2026-10-04T16-44-22Z / 16-48-07Z | 9/20 / 9/20 |
| TERNARY suffices 准入 | 2026-10-04T16-51-50Z / 16-55-32Z | 9/20 / 9/20 |
| ALFWorld 默认 | 2026-10-04T16-59-16Z | 3/20 |
| ALFWorld 布尔准入 | 2026-10-04T17-20-11Z | 0/20 |
| ALFWorld suffices 准入 | 2026-10-04T17-26-13Z | 0/20 |

A1b 的 TERNARY 准入两臂都是 29 次工具调用。ALFWorld 布尔准入 23 次，suffices 准入 34 次；
它多行动，但没有多完成任务。这个 ALFWorld 单次差异只作筛选。

## A1a 协议补充

- 旧布尔臂 `react-typed-admission` 保持原样；新增 `react-typed-admission-choice`。
- 只改变回答类型。新题使用原 true/false 判据，增加 unclear 出口。
- 排序读 P(true)，**不能读被选中项的概率**。0.5 门限和原收尾策略不动。
- 没有概率分布时不补成确定答案；P(true) 按 0 处理，沿用原保守收尾。
- 默认比较型不受影响。仍测默认 TERNARY 两次、ALFWorld 一次作为回归格。
- 两个准入臂各测 TERNARY 两次、ALFWorld 一次，作同提交内的回答类型对照。
- 不把同一题集的重复 run 当成新的独立样本；保留逐 run 和逐题配对结果。

## 这一页不做什么

- **不改 benchmark 的判分**（硬约束）。
- **不改 `NODE_FRAMES` 的逐节点声明、`excluded` 的排除理由、`required` 的两类缺失、
  `canonical_state` 的状态键。** 这四样是我们比两家都细的地方，换掉是退步。
- **不照抄 `cacheImpact` / `latency` 分级。** 我们还没有那个缓存/并行架构，
  抄字段名不会带来任何东西。
