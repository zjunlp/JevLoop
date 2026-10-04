# 第一批跨数据集跑批 —— 跑之前写下的预期

用户 2026-10-04:「jev 很便宜,你就直接跑就行」「先尽量放开我们的思绪,多跑一些轨迹」
「多个数据集来跑」。

★ **这份文件是在看到任何结果之前写的。** 理由不是仪式:我们正在主张"判据/测量"这件事,
而**先预测后验证**正是判据和系统性能假设的区别(`docs/PAPER-STORY-2026-10.md` §9.4)。
写下来之后,对不上就是发现;不写,怎么都对。

## 跑的是什么

`/tmp/batch1.sh`,串行五段。生成模型是本地 Qwen(免费),判官是 Jev(`--decider http`)。

| # | 数据集 | 臂 | 题数 | 参数 | 它回答什么 |
|---|---|---|---|---|---|
| 1 | ALFWorld `valid_unseen` | `react-typed`(**规则先筛,typed-4**) | 20 | seed 20261003, max-steps 30 | **规则优先那一版的 A/B 缺的那一半** —— 盘上同 seed 同题数有一个 typed-3 的 run(`2026-10-03T15-38-49Z`) |
| 2 | ternary-judge `test` | `react-typed`(typed-4) | 20 | max-steps 8 | **控制承重**的数据集上,声明率/抽样/熵长什么样 |
| 3 | ternary-judge `test` | `react-termination` | 20 | max-steps 8 | 同一个数据集、同一个终点闸门,**只有"判定放几次"不同** |
| 4 | GSM8K `test` | `react-typed`(typed-4) | 20 | max-steps 4 | **空契约的阴性对照** —— 没有工具就该没有控制判定点 |
| 5 | FTA `test` | `react-termination` | 20 | max-steps 4 | 失败由构造保证 ⇒ 闸门的**诚实失败**那一侧 |

## 为什么选这五个

三个数据集的结构**差别很大**,而差别恰好落在"哪些判定点能作证"上:

| 数据集 | 工具 | 环境信号(`observation_signals`) | 后果 |
|---|---|---|---|
| ALFWorld | 1 个 `act`,声明 `base_risk=1` | ✅ 成败 + 达成 | `stepOk`/`isDone` **可作证**;`risk` 走规则 |
| ternary-judge | 2 个,声明 `base_risk=0` | ❌ 没有 | `stepOk`/`isDone` **只能问判官**;`risk` 走规则 |
| GSM8K / FTA | **0 个** | ❌ | `decide()` 走"没有工具"那条路 ⇒ **判定点为空** |

⇒ 如果判据(重复 × 稳定 × 证书)是对的,它应该**在三种结构上给出三种不同的结论**,
而不是到处都说"该编译"。**一个到处都说"该编译"的判据是坏的。**

## 跑之前写下的预期(可被推翻)

| # | 预期 | 如果对不上,说明什么 |
|---|---|---|
| 1 | ALFWorld typed-4 的 `declined` 明显低于 typed-3 那批(那批 13/20),因为读置信度的风险门限那条路**构造上没了** | 那条死法不是我诊断的那样;`ALFWORLD-ESCAPE.md` §4 需要重写 |
| 1 | typed-4 的 `rule` 占比高于 typed-3 的 **0.2%**(风险档位 + 环境信号都是规则行) | "规则先筛"没有真的把裁决搬到规则那一侧 |
| 1 | 原生分**仍然在 0–2/20** 之间 —— 控制改动不该动这个数 | 如果分数大涨,那"基准看不见控制"这条要重新想 |
| 2/3 | ternary-judge 上两个臂的**原生分有差别**,而 ALFWorld 上曾经一格不动 | 说明"控制是否承重"决定了改动能不能被看见 |
| 2 | ternary-judge 的 `deliverable::object` / `confirm` 会被问到,而且**判官会反驳** | 如果一次都没反驳,判官在这一侧是空的 |
| 3 | `react-termination` 的**判定行数远少于** `react-typed`(它只在终点问一次) | 少不下去说明中间还在插判定 |
| 4 | **GSM8K 在 typed-4 下几乎没有控制判定行**;`canDeliver` 一次都不该跑(无工具 ⇒ 无材料可核对) | **如果它问了,那是 bug**,不是发现 |
| 4 | 于是"判据"在 GSM8K 上应当报**空**:没有可编译的判定点 | 如果它报"该编译点什么",判据就是坏的 |
| 5 | FTA 的假完成少、诚实失败多 | 闸门在失败由构造保证时不管用 |
| 全部 | 每个新 run 的账上都有 `state_key`,于是**四个数都能精确重算** | 那是 stage 1 的验收条件 |

## 这一批**不**回答的

- **不测 B 的第二个判官。** 判官始终是 Jev。要测"数值抖、决定不抖"是不是 Jev 的脾气,
  需要第二个判官 —— 那是下一批(可以是本地 Qwen 当判官,顺便当 claim A 的对照臂)。
- **不做替换消融。** 那是主实验,要逐判定点只改一个开关。
- **不测"另一个生成模型"。** 生成端只有本地 Qwen。换生成端会改变状态分布,
  那是另一根轴(免费,但会破坏与本批的可比性)。

## 怎么读结果

```bash
python3 -m experiments.scripts.run_diagnostics --keys <run 目录>   # 四个数 + 逐节点表
python3 -m experiments.scripts.run_diagnostics --pair <旧> <新>    # 逐题配对
```

⚠️ **不许只看总分。** 20 题的 run-to-run 标准差实测 **1.30 题**
(`docs/ALFWORLD-VARIANCE.md`),单次 run 之间的差读不出结论。
要看的是:出口分布、声明率、抽样次数、有效控制熵、逐节点翻转表、claim×truth 交叉表。

---

## 事后：证据帧这一轮改了什么，以及一个被推翻的假设

### 窗口是真的，我们的预算是假的

旧注释写「判定模型的上下文只有 **512/1024 token**」，于是整条请求卡在 **4,000 字符**。
往 `api.typesafe.ai/v1/systemone` 实测（2026-10-04）:

| state 字符 | ≈token | 中位延迟 | 结果 |
|---|---|---|---|
| 4,000 | 1,000 | 995ms | OK |
| 64,000 | 16,000 | 1,395ms | OK |
| **128,000** | **32,000** | **1,942ms** | **OK** |
| 256,000 | 64,000 | — | **400 Bad Request** |

⇒ 窗口 **32K token**，那句注释**错了 32 倍**，我们只用了窗口的 **3%**。
μ 的源码写着 *"The judge has a 32K window"* —— 和实测一致。
用满窗口只多 **+1 秒**。已改成 32,000 字符（≈8K token，25%），版本 `typed-5`。

### ★ 假设被推翻：放宽预算**没有**修好那个症状

我原来的假说是「判官饿着，所以逃」。测法：预算 8 倍 + 给 `pickInput` 补上 `last_result`，
然后重跑 TERNARY。

**退出口 21/21 → 21/21。一次都没少。假说被推翻。**

### 真正的原因：候选之间没有可判别的依据

TERNARY 的 `pickInput` 是 40 个 `d001…d040`，而判据来自一张**ALFWorld 的动词表** ——
40 个候选拿到**同一句话**。判官答「一个都不合适」21/21（置信度 0.62）。
**它不是不会挑，是没有可挑的依据。**

而任务是「Lindenthal Pharma 哪年成立」，`read_doc(d005)` 返回的第一行就是
`[d005] Aldermont Systems — company profile` —— **实体名就在那里，只是没进问题。**

修法三块，实测效果：

| | 修之前 | 修之后 |
|---|---|---|
| 退出口被选中 | **21/21 = 100%** | **4/21 = 19%** |
| 工具调用 | 23 | **37**（`react-termination` 是 57） |
| `needsTool` / `stepOk` / `isDone` 行数 | 43 / 23 / 1 | 57 / 37 / 18 |
| 原生分 | 5/20 | **5/20**（没动） |

1. **`Tool.describe_candidate`** —— 领域给每个候选一句身份。
   判据顺序也改了：**领域说明 > 通用动词表 > 兜底**。
   理由：动词表是**我们**对某个领域的猜测，`describe_candidate` 是**环境**说的事实；
   猜的不该盖过事实。
2. **TERNARY 接上文档标题。**
3. **新校验 `indistinguishable_options`** —— N 个选项的说明全一样就报出来。
   **它本该在构造时就抓住这个问题**；没有它，症状只能伪装成"判官乱挑"。

★ 顺带删掉一个**死字段**：`AgentCtx.candidate_notes` 声明了、**从来没被填过、也没人读**
—— 又一个"配了没生效"的形状。它被 `describe_candidate` 取代。

★ 还发现 `MAX_OPTIONS` 是**只写日志的守卫**：TERNARY 41 个选项 > 32，它报警然后**照发**
（`fatal=False`）。所以它从来没保护过任何东西。而且"77 个候选掉到 0.425"那个测量
**是在饿着判官的条件下做的**，用它定上限不可靠 —— 待重测。

### 这一轮**没**解决什么（不许含糊）

**原生分还是 5/20，而 `react-termination` 是 14/20。** 问题可回答了，但分没动，所以
剩下的差距在别处。当时账上的两个候选原因:

- `deliverable::object` 40 次里 **39 次提出反驳**（overclaim 30 + incomplete 9）——
  闸门几乎每次都打回，不停 degrade/撤回；
- `risk_confirm` 37 次里 **29 次答"说不好"** —— 又一个几乎不携带信息的问题。

---

## 闸门到底有没有过严 —— 把输入原文打出来之后

做法:`--dump-requests` 把每次判定的**真实请求体**落盘，然后逐题读 `deliverable::object`
那一帧（`task` + `draft` + `evidence`）和判官的答案，最后对金标。

### 第一层发现：`__parse_error__` 泄漏进了证据，而且它导致了一次假编造

Ternary 的闸门输入里有这么一段:

```
search(Elmridge Robotics does not have a publicly listed CTO…) -> （没有匹配的行）
__parse_error__() -> Could not parse an action. Reply with exactly one of: Action: <tool_name>[…]
read_doc(d005) -> [d005] Elmridge Robotics — company profile … CEO is T. Okafor …
```

任务是问 **CTO**，文档里只有 **CEO** ⇒ 「语料不支持」是**对的**。
但草稿说的是「**由于文档读取过程中的解析错误**」—— **那是错的**：
`read_doc` **读成功了**，解析错误发生在**生成端**（那个 `__parse_error__`）。

**因果链是纯人工的**:`run_loop` 为了给下一轮 prompt 带纠正提示 → 往历史里塞一步
`__parse_error__` → `records()` 返回整个历史 → 它进了 `evidence` → 模型**如实报告**它
→ **闸门判它 `overclaim`**。**一条我们工具链的失败，经模型的嘴，变成模型的编造，再被我们的闸门罚。**

已修：宿主伪步骤**不再进帧**（但仍留在 `steps` 和事件流里 —— 那是给 prompt 用的，不是给判官的）。
哨兵名字收成一个常量 `HARNESS_PSEUDO_TOOLS`（原来字面量散在 `common.py` 和测试里）。

### 第二层发现（更重要）：**这道闸门在惩罚"诚实的拒绝"**

伪步骤修掉之后，输入干净了，再看:

```
q001  task: In what year was Aldermont Systems founded?
      evidence: read_doc(d001) -> [d001] Aldermont Systems … founded in 1998 …
      draft: "The corpus tools failed to retrieve usable evidence due to a parsing error
              … No specific year can be reported."
```

**这一份草稿是错的**（证据里明写着 1998，它却声称没有证据）⇒ 闸门判 `overclaim` **完全正确**。
金标也确认了:`{"type": "supported", "value": "1998"}`，而它是 `correct=False`、`draft_correct=False`
—— **不是假拒**。这一例说明闸门**没有**过严。

★ 但同一批里另一半才是问题所在。按金标分类看**打回时草稿本来就对**的那 8 题:

| 题 | 金标类型 | 正确行为是什么 | 草稿 | 闸门 | 最终 |
|---|---|---|---|---|---|
| q086 | `contradiction` | **不作答**（文档互相矛盾） | 诚实拒绝 | 打回 `overclaim` | 仍对 |
| q063 | `contradiction` | **不作答** | 诚实拒绝 | 打回 `overclaim` | 仍对 |
| q072 | `contradiction` | **不作答** | 诚实拒绝 | 打回 `overclaim` | **变错** |
| q092 | `unanswerable` | **不作答** | 诚实拒绝 | 打回 `overclaim` | **变错** |

⇒ **机制**:`contradiction` / `unanswerable` 这两类金标下，**正确的行为就是拒绝作答**。
而拒绝作答**必然要说一句关于证据/工具的话**（"语料里没有""文档互相矛盾"）。
闸门的问题是「**这份答案有没有说了工具输出不支持的东西？**」——
于是**一句诚实的拒绝，被读成了一次 overclaim。**

★ 这不是"闸门太严"，是一个**更具体**的毛病:
**这道题在惩罚一类正确行为，而它读不出"我没有作答"和"我编了一个事实"的区别。**
而它和我们已经量过的另一条是同一个病:关系型问题（"它有没有夸大？"要建模答案的意图）
而不是分类问题。

### 这一轮**改了四处**，所以归属不了

`risk_confirm` 条件化（声明档位时不问）· `indistinguishable_options` 校验 ·
`Tool.describe_candidate`（退出口 100%→0–11%）· 宿主伪步骤不进帧。
同 seed 同 20 题的三次跑:

| | 修前（typed-4） | 中间（typed-5） | 修后（typed-5） |
|---|---|---|---|
| 原生分 | 5/20 | 5/20 | **3/20** |
| 退出口被选中 | 100% | 19% | **0%** |
| `draft_correct` | 5 | — | **8** |
| `gate_false_reject` | 5 | — | **8** |
| `gate_corrected` | 2 | — | **0** |
| `risk_confirm` 行数 | 37 | 37 | **0** |

⚠️ 20 题的 run-to-run 标准差是 **1.30 题**（`docs/ALFWORLD-VARIANCE.md`），
5→5→3 读不出结论。**而"这一轮一次改了四处"是我该避免的** ——
下一轮必须**一次只改一个**。

### 下一步（一次一个变量）

1. **给 `deliverable::object` 加一个「诚实拒绝」类。**
   现在的选项是 `no_objection / overclaim / incomplete / unsure`，
   拒绝作答只能落进 `overclaim`。加 `honest_refusal`（并说明判据），
   让"我没作答"和"我编了一个事实"能分开 —— 这是分类题，不是关系题。
2. **把四处改动拆开重跑**，把上面那张表的每一格归到一处改动上。

---

## `honest_refusal`：单变量，而且机制被验证

### 改动（**只有这一处是行为改动**）

`OBJECT_ALLOW_CRITERIA` 加一类 `honest_refusal`，并在提问里点出它。
它的判据**两个条件必须同时成立**，否则这个类会变成逃生口:

1. **不作答** —— 它对世界没有任何断言;
2. **理由与证据一致** —— ★ 而这一半是关键:`q001` 的草稿声称"工具失败了"，
   而证据里明写着 `read_doc(d001) … founded in 1998 …`，**工具读成功了**。
   那是**编了一个原因**，是 `overclaim`。所以 `overclaim` 的判据里补了一句
   「**或者给出了证据反驳的理由**」。

### 四次跑的对照（同 seed 同 20 题）

| | 原生 | 打回时草稿本来就对 | 改好了 | 退出口 | 闸门立场 |
|---|---|---|---|---|---|
| `typed-4`（修前） | 5/20 | 9 | 0 | 20 | `overclaim` 25 · `incomplete` 5 · `no_objection` 6 |
| `typed-5`（`describe_candidate`） | 5/20 | 5 | 2 | 4 | `overclaim` 30 · `incomplete` 9 |
| `typed-5`（四处一起改） | 3/20 | 8 | 0 | 0 | `overclaim` 33 · `incomplete` 1 |
| **`typed-6`（只加 `honest_refusal`）** | **8/20** | **0** | 0 | 0 | `overclaim` 20 · **`honest_refusal` 8** |

★ 第 3 行到第 4 行**只差这一个变量** ⇒ **3/20 → 8/20，假拒 8 → 0。**
（20 题 SD=1.30，+5 约 3.8σ —— 但仍是**单次** run，要重复才算数。）

### 机制验证：新类**只**在该触发的地方触发

| 金标类型 | 题数 | 判官标 `honest_refusal` | 最终答对 |
|---|---|---|---|
| `contradiction` | 5 | **5** | **5/5** |
| `unanswerable` | 4 | **3** | **3/4** |
| `redundancy` | 2 | 0 | 0/2 |
| **`supported`** | 9 | **0** | **0/9** |

⇒ 精确率 **8/8**：没有一道 `supported` / `redundancy` 被误标成诚实拒绝。
拒绝类整体 **8/9 答对**。**"分类题"那条判断被验证了**:把"我没作答"从
"我编了一个事实"里分出来,判官分得很干净。

### 剩下的瓶颈（现在很明确）

**`supported` 那 9 题:0/9。** 语料**支持**答案的那一类,这一臂**一道都答不出**。
而这就是 8/20 和 `react-termination` 14/20 之间的差距所在。

机制（读输入看到的）:它拿**自然语言问题当搜索词**
（`search(chief technology officer Kestrel Aero)`）⇒ 没有匹配 ⇒ 读一篇文档 ⇒ 拒绝。
**问题在生成端（搜索策略），不在闸门。** 这是下一步，而且它又是一个单变量。

### 顺带修掉的一个**藏了很久的 bug**：指纹一直只覆盖了 7 / 34 项

给 `OBJECT_ALLOW_CRITERIA` 加了 `honest_refusal`（一个真的语义改动）之后，
**指纹一点没动**。查下去发现:

```python
holder = frame_mod if hasattr(frame_mod, name) else globals()
getattr(holder, name, "<missing>")     # ← globals() 是 dict,getattr 取不到任何东西
```

⇒ **`typed.py` 那 27 个常量全部被记成 `'<missing>'`。** 那个指纹实际上
**只覆盖了 `frame.py` 那 7 个**（帧字段与预算），而它声称覆盖的问法、判据、
门限、兜底表**一个都没进去**。`docs/MU-CONFLICT.md` §6 里"改了问法就红"
那条保证，**一直是空头支票**。

已修（用 `sys.modules[__name__]`，模块对象上 `getattr` 是好的），并加了一条守卫
`test_every_registered_spec_part_is_actually_found`:**任何一个 part 取不到就红**。
★ 发现它的路径本身是论据:**如果没有那次语义改动，这个 bug 会继续藏着。**

---

## 生成端看不见证据 —— 整条臂最大的一个洞

### 发现它的路径

一路查 `supported` 0/9，先怀疑"搜索词不对"，然后用数据**否掉**了自己
（9 道里 **8 道答案就在工具输出里**）。既然证据里有答案却答不出来，
下一步就该问"**写答案的那一次调用拿到了什么**"。答案是:**什么也没有。**

```
# Task             In what year was Lindenthal Pharma founded? …
# What was done    search; read_doc          ← ★ 只有工具**名字**
```

而 `call_model` 是**无状态**的（一次调用 = 一条全新消息）。
⇒ **写答案的模型看不见自己搜集到的证据。**

★ 而 `react-termination` 的内层是 `LLMController`（ReAct 的提示词带完整 scratchpad）
⇒ **它的生成端看得见证据**。**这就是 8/20 与 14/20 之间的全部差距。**

### 修法（两处，而且必须是同一个投影器）

`_answer_text`（第一次生成）**和** `_degrade_text`（闸门打回后的重写）都要证据。
后者更糟：它的指令是「**报告发生了什么**」—— 让一个看不见证据的模型报告发生了什么，
它只能猜，而猜出来就是那句"工具失败了、没有可用证据"。
**那句不是编造，是一个盲眼的模型唯一能得出的结论。**

⇒ 抽成 `_evidence_block(view)`，一个投影器两个调用点
（两处各拼一份必然分叉，§8.15）。它**跳过宿主伪步骤**（`__parse_error__`）。

### 效果：双向的，而且机制被逐类验证

| 金标类型 | 题数 | 生成端看不见证据 | 生成端拿到证据 |
|---|---|---|---|
| **`supported`** | 9 | **0/9** | **8/9** |
| `unanswerable` | 4 | 3/4 | 3/4 |
| `redundancy` | 2 | 0/2 | 1/2 |
| **`contradiction`** | 5 | **5/5** | **0/5** |

**修好了 `supported`（0→8），弄坏了 `contradiction`（5→0）。净 +4。**

### 单变量链条（同 seed 同 20 题）

| 改动 | 原生 |
|---|---|
| `typed-5`（四处一起改） | 3/20 |
| **+ `honest_refusal`** | **8/20** |
| **+ 生成端拿到证据** | **12/20** |
| （参考）`react-termination` | 14/20 |

### `contradiction` 那 5 道到底怎么死的（读输入才看清）

语料里**确实**有两个冲突的数:

```
[d003] In 2025, Caldera Metrics reported revenue of 156 million USD.
[d015] According to a market bulletin, Caldera Metrics posted revenue of 201 million USD in 2025 …
```

而这一轮它**只搜了一次，搜的是自己的结论**:

```
search('No value found. The provided corpus does not contain information regarding the 2025 revenue of Caldera Metrics.')
→ （没有匹配的行）
```

⇒ **它把结论当搜索词搜了一遍，什么都没找到，然后如实报告"语料里没有"。**
**`contradiction` 的死因不是生成端误读，是检索根本没发生。**

★ 而这也纠正了我自己的一个反复:我先说"搜索是瓶颈"，然后基于 `supported` 的数据
**否定**了自己（"8/9 证据里都有答案"）。现在 `contradiction` 把它证实了 ——
在 `supported` 里它是**读了文档但看不见**，在 `contradiction` 里它是**根本没读**。
**两处都是"生成端拿到的信息不对"，而两次的表现完全不同。**

### 下一步（单变量）

`search.query` 是**生成**的（`provider=None` ⇒ `_generate_argument`），
而给它的一句提示是「Give only the value for `query` — nothing else」——
**没有一个字说它要的是"语料里真的出现的短语"**。

⇒ 修法是**让工具自己声明它想要什么样的参数**（和 `describe_candidate` 同一层:
领域的事实由环境说，不由引擎猜）:给 `Tool` 加 `argument_hints`，
TERNARY 的 `search.query` 声明「1–3 个词，必须是语料里字面出现的（实体名，或
`revenue` 这样的一栏）；不是一句话，也不是一个结论」。
然后量 `contradiction` 能不能回到 5/5 而不弄坏 `supported`。

---

## `argument_hints`：检索词修好了，但分数没动 —— 以及一条参照线

### 改动与效果

`Tool.argument_hints`（**环境自己声明这一栏要什么形状的值**，和 `describe_candidate`
同一层）+ TERNARY 的 `search.query` 声明。搜索词的变化是干净利落的:

| | 搜索词长什么样 |
|---|---|
| 修之前 | `search('No value found. The provided corpus does not contain information regarding the 2025 revenue of Caldera Metrics.')` |
| 第一次修（说"用关键词"） | `search('Caldera Metrics 2025 revenue')` ← 仍然匹配不到 |
| 说准之后 | `search('Lindenthal Pharma')` · `search('Kestrel Aero')` · `search('Falken Optics')` |

★ 中间那一格是**我漏掉的一半**:这个 `search` 是**逐句的字面子串匹配**，
所以 `Caldera Metrics 2025 revenue` **匹配不到任何东西** ——
尽管每个词都在语料里。语料的句子是
`In 2025, Caldera Metrics reported revenue of 156 million USD.`
而 `Caldera Metrics` 和 `revenue` **各自**都匹配。
⇒ 提示里必须说"**别把不相邻的词拼起来**",否则"用关键词"这句建议是空的。

| 金标类型 | 修前 | 说"用关键词" | 说准之后 |
|---|---|---|---|
| `contradiction` | 0/5 | 1/5 | **2/5** |
| `supported` | 8/9 | 7/9 | **6/9** |
| `unanswerable` | 3/4 | 3/4 | 3/4 |
| `redundancy` | 1/2 | 1/2 | 1/2 |
| **合计** | **12/20** | 12/20 | **12/20** |

⇒ **检索词修对了，而总分一格没动。** 这是一个诚实的负面结果:
**检索不再是最小的一环了。**

### 参照线（同 seed、同 20 题、同模型、同 max-steps）

| 臂 | 原生 | 它说明什么 |
|---|---|---|
| `direct`（不用工具，直接答） | **8/20** | 工具本身值 **+6** |
| `react`（ReAct 工具循环） | **14/20** | 这个 9B 模型**能做到 14** |
| `react-termination`（只在终点放一次判官） | **14/20** | ★ 终点闸门**一分不加** |
| **`react-typed`（完整类型化控制器）** | **12/20** | ★ **比最朴素的 ReAct 还差 2** |

### 这三行合起来说明什么

1. **模型不是天花板。** `react` 用同一个 9B 模型拿到 14 ⇒ 14 是可达的。
2. **工具是承重的**（8→14），**而终点闸门不承重**（14→14）。这和 ALFWorld 上
   "闸门对动作打分的指标不可见"是一致的。
3. ★ **我们还落后最朴素的 ReAct 2 题，而差距在中间那些动作选择判定上**
   （`needsTool` / `pickTool` / `pickInput` / `stepOk` / `isDone`），
   不在闸门、也不在检索。**这和 ALFWorld 上的结论是同一个**
   （那里 `react` 10.2/20 vs `react-typed` 1.0/20）。

⇒ 项目的诚实现状:**引擎、契约、账、判据都已经能用，而"用中间判定换掉生成"这件事
在两个数据集上都还没有赢**。而两个数据集都指向同一处:动作选择那几道题。

### 这一整轮的单变量链条（TERNARY，同 seed 同 20 题）

| 改动 | 原生 |
|---|---|
| `typed-5` 四处一起改 | 3/20 |
| + `honest_refusal`（交付闸门加一类） | 8/20 |
| + 生成端拿到工具输出 | **12/20** |
| + `argument_hints`（检索词） | 12/20（检索词变对，分数不动） |
| 参照：`react` / `react-termination` | **14/20** |
