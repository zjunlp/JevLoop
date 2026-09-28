# JevLoop 论文与 Decision.md 规范方向记录

> 状态：阶段性冻结，供后续论文实验、开源宣传和规范设计使用。
>
> 本文记录的是已经讨论过的方向与判断，不等于已经完成的实验结果，也不等于对行业优先权的声明。

## 1. 论文方向暂定

论文暂定研究问题：

> **机器可检查的 decision contract 能否减少工具型 Agent 的无证据完成声明（unsupported completion），并在保留有效探索能力的同时，控制额外成本？**

英文工作表述：

> *Machine-Checkable Decision Contracts for Reducing Unsupported Completion in Tool-Using Agents*

### 1.1 不再主张的内容

论文不主张以下宽泛 novelty：

- 我们首次发现 Agent 会 quiet failure；
- 我们首次提出 decision layer；
- 我们首次提出 completion gate、abstention 或 evidence verification；
- `DECISION.md` 是第一个 Agent 决策文件格式；
- JevLoop 在所有任务上都优于 Workflow 或 ReAct；
- JevLoop 能解决所有 prompt injection、sandbox escape 或 Agent 安全问题。

已有工作已经分别研究了 Agentic Abstention、evidence-carrying termination、silent-failure attribution、Agent failure taxonomy，以及 Jev 作为 typed decision layer 的选择性控制。后续论文必须正面引用并区分这些工作。

### 1.2 论文拟贡献

论文贡献暂定为三部分：

1. **问题与评估协议**：定义 `unsupported completion`，并用外部验收器区分：
   - `correct completion`：确实完成；
   - `honest failure`：明确承认失败；
   - `timely escalation`：及时交给人或上层；
   - `over-abstention`：本来可以完成却过早放弃；
   - `unsupported completion` / `quiet failure`：声称完成但外部证据不支持，且没有明确失败或升级。
2. **机器可检查的 decision contract**：把判断节点、位置、动作集合、输入 frame、明确排除的字段及理由、policy 和交付证据写成可解析、可编译、可回归测试的契约。`DECISION.md` 是当前实现。
3. **系统消融与边界**：比较终止 verifier、evidence-only termination、frame contract 和完整 contract，测量可靠性收益、正常任务能力、过度拒绝、人工升级和额外成本。

“decision contract 是否必要”必须是实验结论，而不是论文预设结论。

## 2. 论文主场景

论文主场景暂定为：

> **代码仓库中的不确定修复任务：Issue / CI failure → verified candidate patch。**

输入包括仓库、Issue 或失败日志、工具环境、测试系统、路径和权限约束。输出不是自动合并或自动部署，而是：

- 候选补丁；
- 修改文件清单；
- 真实运行过的测试及结果；
- 未解决风险；
- 是否需要人工介入。

选择这个场景的原因：

- 大厂有真实需求；
- Workflow 能覆盖固定步骤，但难以枚举陌生仓库中的探索分支；
- 裸 Agent 有工具选择、过早停止、伪完成和越权修改风险；
- 补丁、文件、exit code 和测试结果可以由外部 oracle 检查。

## 3. 数据与实验方向

### 3.1 主数据集：Decision Reliability Suite

先构建小而严的成对任务集，而不是立即追求大规模。第一版目标暂定：

- 30 个基础代码任务；
- 每个任务 5 个条件版本；
- 每个版本至少 3 次重复，理想为 5 次；
- 至少 2 个模型。

五类条件版本：

1. **正常可完成**：测能力，也防止治理层过度保守；
2. **不可完成**：缺文件、无权限、缺依赖或超出工具能力；
3. **部分完成**：部分文件完成、代码改了但测试失败、补丁存在但没有验证；
4. **工具失败**：读取、写入、命令或测试失败、超时、空输出；
5. **伪证据/不可信输出**：工具文本声称成功或夹带指令，但真实 exit code、文件状态或测试结果不支持。

主标签必须尽量来自确定性外部 oracle：文件系统状态、patch 检查、exit code、测试结果、路径白名单和 replay，而不是只让 LLM judge 阅读 Agent 的自述。

### 3.2 外部验证

- **Terminal-Bench 子集**：验证开放式终端探索和失败恢复；
- **SWE-bench Verified 子集**：验证真实 GitHub issue 的外部有效性；
- **Agentic Abstention Terminal 子集**：验证可行性揭示后的及时停止、过度停止和升级；
- **AgentDojo 子集**：仅在完成工具输出污染与 frame exclusion 实验后加入。

这些数据集承担不同作用，不能把它们混成一个“总榜”。

### 3.3 实验臂

最低配置：

- Workflow；
- ReAct；
- ReAct + termination critic / evidence verifier；
- JevLoop full contract。

理想配置增加：

- JevLoop without frame completeness；
- JevLoop termination-only。

关键比较是“只在终点验证”与“在整个工具循环中使用 decision contract”的差异。

### 3.4 主指标

主指标：

> **Unsupported Completion Rate**

次指标：

- task success；
- honest failure；
- timely escalation；
- over-abstention；
- unauthorized edit；
- evidence validity；
- premature termination；
- invalid tool call；
- decision/generation/tool 成本；
- token 和延迟。

不要把 wall-clock 作为主要卖点。JevLoop 的决策往返可能产生部署成本，论文应报告 reliability–cost trade-off。

## 4. Decision.md 规范目标

开源宣传的重点不是“又一个 Agent 框架”，而是推动 `DECISION.md` 成为一种可被不同 Agent runtime 理解的**决策契约约定**。

### 4.1 规范必须表达什么

一个可移植的 Decision contract 至少应能声明：

- 判断节点是什么；
- 判断发生在什么位置；
- 可返回哪些动作；
- 判断能看到哪些上下文；
- 哪些上下文被明确排除，以及为什么；
- 每个输入的预算或边界；
- 哪些 policy 是硬约束；
- 何时必须升级；
- 什么证据才能判定完成或交付。

### 4.2 成为行业规范的必要条件

仅有 Markdown 语法不够。需要逐步形成：

1. **稳定的规范语义**：核心字段、位置、动作和错误语义不能随意漂移；
2. **机器检查器**：坏规范在解析或编译阶段拒绝，而不是运行时静默忽略；
3. **参考实现**：JevLoop 作为 reference implementation，而不是唯一消费者；
4. **版本与兼容性**：声明 schema version、规范版本、兼容策略和迁移方式；
5. **可观测事件格式**：记录 node、position、frameDigest、requestDigest、policy、answer、margin 和 evidence；
6. **测试夹具**：规范仓库中有坏文件、边界文件、阴性对照和 conformance tests；
7. **适配接口**：允许现有 Workflow、Coding Agent 和其他 runtime 只接入部分决策节点；
8. **可复现 replay**：给出 trace、输入 frame 和版本后，能够重放或解释一次决策；
9. **与 runtime 解耦**：别人可以使用 checker、schema 或 benchmark，而不必采用完整 JevLoop；
10. **规范治理**：公开 RFC、变更记录、兼容规则和社区贡献流程。

### 4.3 宣传时的正确定位

不说：

> `DECISION.md` 会让 Agent 自动开发任何应用。

说：

> `DECISION.md` 把原本藏在 prompt、回调和 if-else 中的关键 Agent 判断，变成可审查、可测试、可版本控制、可在加载期拒绝的工程契约。

核心宣传句暂定为：

> **Workflow 负责确定性步骤，Decision.md 负责不确定性中的受控判断。**

面向 Coding Agent 的版本：

> **让 Agent 保持探索能力，但不能仅凭自己的判断宣布任务完成。**

面向平台团队的版本：

> **不要求重训模型，也不要求替换现有 Agent；先把工具选择、授权、完成判断和交付验收变成可审计的契约。**

## 5. 行业影响力假设

我们暂不假设方法名称本身会产生影响力。可能被引用和采用的资产应分成三个彼此独立的产物：

1. **论文**：研究 decision contract 对 unsupported completion 的影响、边界和成本；
2. **benchmark / evaluator**：不绑定 JevLoop，任何 Agent 都能参加；
3. **reference implementation / checker**：用于解析、编译、回放和审计 Decision contract。

长期影响力的信号不是只有 GitHub star，而是：

- 其他 Agent 论文复用 benchmark；
- 其他 runtime 使用 checker 或 schema；
- 研究者引用 `unsupported completion` 的定义与协议；
- 工业团队把 Decision contract 接入现有 Agent、CI、权限和观测系统。

## 6. 当前明确不做的事情

在下一阶段宣传前，暂不把以下内容作为核心承诺：

- 替代所有 Workflow；
- 自动合并或自动部署生产变更；
- 解决所有 prompt injection 或 sandbox escape；
- 宣称比所有 Agent 更快、更准确；
- 宣称 Decision.md 是行业第一个决策文件；
- 为了增加语法而继续扩展 DSL，除非有明确的 conformance 或实验需求。

## 7. 下一阶段顺序

1. 固定 `unsupported completion`、`honest failure`、`over-abstention` 和 `timely escalation` 的标签定义；
2. 用现有 `bench/tasks.ts` 做 10–15 个任务的 pilot；
3. 验证四种行为是否可由外部 oracle 稳定区分；
4. 冻结 Decision Reliability Suite 的 schema、trace 和 evaluator；
5. 做 termination-only、frame、full contract 消融；
6. 再扩展到 Terminal-Bench / SWE-bench 子集；
7. 以 `DECISION.md` 的稳定语义、checker、reference implementation 和 demo 作为开源宣传核心。

> 当前结论：论文方向已经暂定；开源项目下一步不追求“让 Agent 更像 Workflow”，而是把 `Decision.md` 做成可移植、可检查、可观测、可复用的 Agent 决策契约。
