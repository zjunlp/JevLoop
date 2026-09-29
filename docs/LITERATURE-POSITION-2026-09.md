# JevLoop 文献定位（2026-09）

> 状态：一次**有界**检索的记录，不是系统性综述。
>
> 目的只有一个：**在动手写论文之前，把「哪些主张已经被占了、我们还剩什么」固定下来。**
> 检索方法与每一条的核验级别都写在文末，**未核实的一律标 unknown，不猜**。

## 0. 结论摘要

**整个检索里只有两篇同行评审的工作：**

| | 工作 | venue | 它占了什么 |
|---|---|---|---|
| 1 | [CaMeL / Defeating Prompt Injections by Design](https://arxiv.org/abs/2503.18813) | **SaTML 2026**（Google DeepMind + ETH） | 不可信数据**永不进入程序流** + capability 策略；AgentDojo 77% 可证明安全 |
| 2 | [Governance by Construction for Generalist Agents](https://research.ibm.com/publications/governance-by-construction-for-generalist-agents) | **ACM CAIS '26**（IBM Haifa） | 声明式 policy-as-code 挂在**活循环**的 5 个检查点上，**且测了结果变化**（46.2%→71.8%→78.2%） |

其余全部是 arXiv/Zenodo 预印本、PyPI 包、公司博客、GitHub 仓库、一份 IETF 个人 draft。**引用几乎全是 0**（唯一例外：Authority Separation 2、IBM 1、Verification Horizon 4）。

**两个推论：**

- **竞争对象不是论文，是仓库。** 策展总览 [awesome-auditable-ai](https://github.com/yzhao062/awesome-auditable-ai) 收录 **206 条 / 135 篇 arXiv / 105 个 GitHub 仓库 / 16 个标准**；138 行表格里只有 **70 行**标了发表 venue。
- **领域远没有定论。** 两篇同行评审的都是**系统/方法**论文，不是**测量**论文。几乎每条结论都还没被独立复现。

## 1. 我们唯一还站得住的复合声明

在全部约 40 个来源里，**找不到对标**的是这个复合：

> **逐判定的有界输入帧**（声明读集 + 逐格预算 + **每条排除都带理由**）
> **＋ 对状态的可机器检查总体性**（每一格要么被某道判定读了，要么被显式排除并写了理由）
> **＋ 把「形式」当作被隔离的变量**（同一位置下：声明式契约 vs 等价代码）

三个最近的邻居各差一格：

- **IBM CUGA**：有声明式策略 + 活循环 + 效果测量，但**零读帧、零排除理由、零状态覆盖检查**（其 5 个检查点是硬编码的架构阶段，不是声明出来的判定清单）。
- **Bostick, The AI Bounded Corridor**：有「声明完备性」的**定理**（15 角色下限，少给即未定义），但是**角色粒度**，不是「逐格读或被排除并写理由」。
- **ScopeJudge**：变 judge 能看到多少上下文（最接近「变帧」），但门的是**工具调用范围**，不是完成判定。

另有两格是簇②③给的：

- **位移机制**：把数值分数推过**政策门限**（而非检测器操作点、也非发指令）—— 所查 6 篇中**0 篇完整占住**。
- **外部治理者的受限 regime**：CaMeL/ScopeGate 证明**拥有 agent 时**能做到什么；HookPry 证明**控制面才是真边界**；**没人量「从外面能接管多少」**。

## 2. 被占了的主张（不要再提）

| 主张 | 被谁占 |
|---|---|
| 「提出决策层 / 决策契约」 | [Decision Provenance](https://arxiv.org/abs/1804.05741)（IEEE Access 2019）；[Auditable Agents](https://arxiv.org/abs/2604.05485)（ACM AI Leadership Summit 2026）；IBM CAIS '26 |
| 「记录完整 ≠ 忠实」 | [Tamper-Evident ≠ Trustworthy](https://zenodo.org/records/20698154)（**有定理**） |
| 「unsupported completion」的定义与测量 | [OverclaimBench](https://arxiv.org/abs/2609.20812)（从 transcript **机械判定**，比人工 oracle 干净） |
| 成对报假接受/假拒绝 | Stagnation（假拒绝 37.5%，并**主动说明** out-of-band 的 0 是定义性后果）；[Harness 分解](https://arxiv.org/abs/2609.20474)（61% vs 17%） |
| 验证反模式分类 | [dos-kernel docs/167](https://github.com/anthony-chaudhary/dos-kernel)（14 级可伪造性阶梯） |
| 「外部验证优于自报完成」 | Stagnation（位置是唯一变量）；[Authority Separation](https://zenodo.org/records/18067959) |
| 「自适应攻击者能绕过 LLM judge」 | [DERAIL](https://www.codeintegrity.ai/blog/derail)（控制路径 + 保效用）；Gaming the Judge；Control-Token Injection |
| 「fail-closed 授权门移除后果」 | [Capability Gates Are Not Authorization](https://arxiv.org/abs/2606.28679)（ScopeGate：0/48 静态、0/29 自适应、0/10 良性误拒） |
| 「用数据流/能力约束防注入」 | **CaMeL**（SaTML 2026，有证明）—— 且严格强于「约束判定输入」 |
| 「decision contract」这个词 | [autoresearch-core](https://pypi.org/project/autoresearch-core/)（MetricSpec：指标+比较器+目标）—— 已被一个弱得多的东西占住 |

## 3. 定位：不是抢地盘，是**补别人缺的那个对照**

- 文献隔离的是**位置**：判定住在生成器里 vs 住在外面（Stagnation 三臂、Authority Separation、Harness 分解）。
- 我们第一轮实验隔离的是**形式**：位置固定在「独立」时，四条臂（contract / contract-strict / ifelse-best / ifelse-naive）变量只有**契约 vs 等价代码**，结论是**等价**，且策略层可证等价。

> **文献证明了「位置」重要；我们证明「形式」不重要。合起来才是完整的一句：买到的不是你怎么写，是它住在哪。**

落地很便宜：把 `bench/gate-compare.ts` 扩成 **位置 × 形式** 的交错设计（增加「融进生成」这一维），就得到 Stagnation 缺的那一维。

## 4. 每条的 venue 与影响力

### 同行评审（2）

| 工作 | venue | 影响力 |
|---|---|---|
| CaMeL | SaTML 2026 | 强组，开源实现 |
| IBM Governance by Construction | ACM CAIS '26（DOI 10.1145/3786335.3813192） | S2 1 引用；引擎 880 star / 159 fork |

### 预印本 / 包 / 博客 / 仓库（节选，按威胁排序）

| 工作 | 类型 | 影响力 |
|---|---|---|
| [Stagnation vs Progress](https://zenodo.org/records/21672574) | Zenodo 预印本（v1 受限，v3 开放） | 214 浏览 / 60 下载 / **0 引用** |
| [OverclaimBench](https://arxiv.org/abs/2609.20812) | arXiv 预印本 | 0 引用 |
| [Tamper-Evident ≠ Trustworthy](https://zenodo.org/records/20698154) | Zenodo 自存档（元数据写 "Journal"，未写哪本） | 113 浏览 / 23 下载 / **0 引用**；代码库 404 |
| [Authority Separation](https://zenodo.org/records/18067959) | Zenodo 预印本 | **6,445 浏览 / 1,387 下载 / 2 引用** |
| [DERAIL](https://www.codeintegrity.ai/blog/derail) | 公司博客 + 开源 harness | **0 star / 4 commits / 5 月后停更** |
| [HookPry](https://arxiv.org/abs/2609.03884v2) | arXiv 预印本（BUPT/CAC/北航/浙大） | S2: `venue=""`，0 引用 |
| [Explosive Prompts](https://arxiv.org/abs/2609.22510) | arXiv 预印本（Tel Aviv） | 0 引用 |
| [ScopeGate](https://arxiv.org/abs/2606.28679) | arXiv 预印本（单作者） | 0 引用 |
| [dos-kernel](https://github.com/anthony-chaudhary/dos-kernel) | GitHub 仓库 | 20 star / 123 open issues |
| [hermes-agent #58196](https://github.com/NousResearch/hermes-agent/issues/58196) | 生产仓库 issue/PR | 仓库 **249,867 star** |
| [VOLT](https://www.ietf.org/archive/id/draft-cowles-volt-00.html) | IETF 个人 draft（无 WG/无 standing） | 无指标 |
| [Specula](https://arxiv.org/abs/2607.25333) | arXiv 预印本（cs.SE） | 0 引用；仓库 **500 star** |
| [Did We Actually Fix It?](https://arxiv.org/abs/2607.11969v2)（度量可被 game） | arXiv 预印本（stat.ML） | 无指标 |

**两条对定位有用的旁证**（不是竞争者，是弹药）：

- **Specula** 是「形式规格 + 机器检查」的**另一个用途**（给系统代码生成 TLA+ 不变量并模型检验，48 个项目、249 个 bug）—— 它威胁的是**措辞**，不是我们的机制。
- **Did We Actually Fix It?** 证明**度量本身可被 best-of-N / seed shopping 刷高**，而 **N=1 时在六个基准上没有任何替代度量可被 game**。这条对我们的实验是**方法学约束**：报告单次运行，或**披露 N**。同时它也是「契约 vs 普通代码」这类结果必须成对报告的一条外部支撑。

## 5. 检索方法与核验级别

- **分四簇并行读**：审计与取信 / 评委攻击 / 判定位置 / 声明式治理；另由主 agent 补了**防御侧**一簇（两个子检索都漏了它）。
- **指标来源**：OpenAlex、Semantic Scholar API、Zenodo API、GitHub REST API、pypistats。**Semantic Scholar 大面积 429**，所以除个别条目外引用数取自 OpenAlex；Google Scholar 不可达 ⇒ 一律 `unknown`。
- **核验级别分三档**，文中已分别标注：**全文**（IBM、Bostick 下载 PDF）、**元数据/README 级**（PyPI 包）、**摘要级**（部分 arXiv）。
- **两条已知的不一致，如实记录**：Verification Horizon 的引用数 S2=4 / OpenAlex=0；Zenodo 18728483 的**记录标题与内部 PDF 标题不一致**（我们引的是内部 PDF 那个标题）。
- **未能核实的**：HuggingFace 上 ICML-2026-agent-repro 讨论 #29 的正文（该域在本环境抓取失败）；Agent Flight Recorder（arXiv 2609.01931）的同行评审状态。

## 6. 不要做的事

- 不要以「judge 会被绕过」开场 —— 已被占。
- 不要把「unsupported completion」当自己的定义发明 —— 引 OverclaimBench。
- 不要主张「记录可验证 ⇒ 可信」 —— 有定理说反了。
- 不要把「decision contract」当新词 —— 已被一个弱对象占住，要明确指我们指的是哪一种。
- 不要用「比 X 更快/更准」当卖点 —— 两轮实验都没有支撑它。
