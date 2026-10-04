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
| — | 基线 | `cd2bd5f` | 11, 11 | 2 | — | — |
| A1 | 候选题从布尔改成**带类别的选择题**（μ `suffices`；缺口 3） | | | | | |
| A2 | 准入型的逃逸＝**平先验/取排序第一**，不再拿门限卡（缺口 2） | | | | | |
| A3 | 布尔判定点的**三区**：中间区落到调用方的默认（缺口 2） | | | | | |
| A4 | 门限**按题型分开声明**，用错题型就抛错（缺口 1） | | | | | |
| A5 | 新决策点默认 **`shadow`**（缺口 4） | | | | | |
| A6 | **长字段放最后**，让截断切在该切的地方（缺口 5a） | | | | | |
| A7 | 逃逸口改到**定义时**强制（缺口 5b） | | | | | |
| A8 | 状态与题**一起洗密钥**（缺口 5c） | | | | | |
| A9 | **候选截断进帧**（缺口 5d，这条是我们自己的缺口） | | | | | |

## 这一页不做什么

- **不改 benchmark 的判分**（硬约束）。
- **不改 `NODE_FRAMES` 的逐节点声明、`excluded` 的排除理由、`required` 的两类缺失、
  `canonical_state` 的状态键。** 这四样是我们比两家都细的地方，换掉是退步。
- **不照抄 `cacheImpact` / `latency` 分级。** 我们还没有那个缓存/并行架构，
  抄字段名不会带来任何东西。
