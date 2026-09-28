# JevLoop

**你的 agent loop 里每一个岔路口都是一次完整的大模型调用。而它们没有一个是「生成」。**

*要不要动手？用哪个工具？读哪个文件？这个操作安全吗？成功了吗？做完了吗？这个回答能发出去吗？* —— 常规 agent 对每一个的回答方式，都是让大模型写一段话，再由代码解析回来。但这七件事分别是**挑选、打分、是非题**：一次前向传播，在固定的候选集上给出答案，约 10–40 ms，不生成任何 token。

JevLoop 把它们交给判定模型（[Jev](https://typesafe.ai) / [Laya](https://github.com/NandaKishorM/laya)），把大模型留给它唯一不可替代的那件事：**写**。

它是一个**跑得起来的 harness**，不是 demo：loop、两条后端缝、记账、一个 Web 界面 —— 全部在一条命令里，零依赖、零构建、不用 key。

JevLoop 是一个独立项目，与 TypeSafe AI 没有隶属关系，也未获其背书 —— 名字只是指向它所路由的那个模型，仅此而已。

[English](README.md) · **中文**

![JevLoop：一次 demo 运行 —— 对话、判定轨迹、以及编译出来的 DECISION.md](docs/demo.gif)

*一次会话，三屏：对话、判定轨迹、编译出来的 `DECISION.md`。界面目前是中文，英文版在做。*

```
$ npm run demo          # 全新 clone：无 key、无网络、不用 npm install

JevLoop · demo
  decision  : laya→rule-judge
  generator : scripted — set DEEPSEEK_API_KEY for a real LLM

  ── loop trace ──────────────────────────────────────────
  ▲ laya: TRANSPORT, retrying in 258ms
  ▲ laya unavailable (laya is unreachable: fetch failed), falling back to rule-judge
  cleared: list_dir (auto)
  cleared: read_file (auto)

  ── every decision ──────────────────────────────────────
  step 1
   ~ decide  loop.needsTool         use_tool           4.9ms  needs_tool=0.95
   ~ decide  loop.pickTool          call               4.9ms  tool=list_dir
   ~ decide  loop.gradeRisk         auto               4.7ms  risk=0.0 needs_auth=0.05
   ~ decide  loop.stepOk            continue           4.3ms  ok=0.92
   ~ decide  loop.isDone            keep_going         4.0ms  done=0.10
  ...
  step 3
   ~ decide  loop.canDeliver        deliver            4.5ms  deliverable=0.90 unsupported=0.08
     model   generate (scripted)                       600ms

  ── accounting ──────────────────────────────────────────
  decisions  12     53ms (4.4ms each)
  model       1     600.2ms

  decisions : model = 12.0:1   decisions are 8.2% of wall clock
```

> `~` 表示这个答案是 degraded 的 —— 自带的判定器是规则表，所以它给的每个判定都带这个标记。墙钟占比会在不同运行之间浮动一两个百分点。

零依赖、零构建步骤、无 key 无网络也能跑完整条 loop。

> 上面这次运行的判定来自**规则表，不是模型** —— 它演示的是 loop 的**形状**，不是判定的质量。
> 真实后端与它们的实际开销见 [诚实的数字](#诚实的数字)。

---

## 问题在哪

拿一个需要几次工具调用的任务来说。**两个 loop 做的是同一批工具调用 —— 区别只在环里坐的是谁。**

```
常规 loop —— 模型在环里

   ┌─────────────────────────────────────────┐
   │                                         │
   ▼                                         │
[ LLM 调用 ] ── 选一个工具 ──▶ [ 工具 ] ─────┘
   │
   └──▶ 回答


JevLoop —— 模型在环外

   ┌─────────────────────────────────────────┐
   │                                         │
   ▼                                         │
[ Jev ] ── 判定 ──▶ [ 工具 ] ────────────────┘
   │
   └──▶ [ LLM 调用 ] ── 写 ──▶ [ Jev ] ── 闸门 ──▶ 回答
```

常规 agent 在环的每一圈都要问模型一次 —— *要不要动手？用哪个工具？安全吗？成功了吗？做完了吗？* —— 而每个答案都付一次完整生成的钱。JevLoop 把这些在环里答掉，模型**只在最后被调用一次**，用来写。

| loop 要问的问题 | 常规 agent | JevLoop |
|---|---|---|
| 现在需要动手吗？ | 大模型调用 | 判定 |
| 用哪个工具？ | 大模型调用 | 判定 |
| 这个调用安全吗？ | 大模型调用，或者干脆不问 | 判定 |
| 成功了吗？ | 大模型调用 | 判定 |
| 做完了吗？ | `max_iter` 计数器 | 判定 |
| 这个回答能发出去吗？ | **什么都没有** | 判定 |

**你一直在用生成的价格，买判定的答案。**

## 快速开始

需要 **Node ≥ 22.6** —— 它直接跑 TypeScript，没有构建步骤。

```bash
git clone https://github.com/zjunlp/JevLoop && cd JevLoop
```

**离线跑完整条 loop** —— 离线判定器随 examples 一起走：

```bash
npm run demo
```

**看这些判定被编译成了什么** —— 不用 key、不用网络：

```bash
node --experimental-strip-types src/cli.ts spec
```

**打开界面**（http://127.0.0.1:7799）：

```bash
npm run serve
```

**拿它干活** —— 这一条需要判定后端：

```bash
node --experimental-strip-types src/cli.ts run "列出目录里的文件并说明它们是做什么的" --cwd ./你的项目
```

它会自己解析后端：设了 `TYPESAFE_API_KEY` 就用托管 Jev，否则用本地 `:7789` 上的 Laya。两个都没有时，它会**说清楚它想要哪个**，然后每一步都 escalate —— 它不猜。

**让一个「不是 JevLoop」的宿主来消费这份契约** —— 离线、无 key、不用大模型：

```bash
npm run external-host     # 最小外部宿主：解析 → 判定 → 执行，自带 state 和图
npm run adapter-test      # 反向夹具：未知投影、未处理的 action……
```

> **关于 npm 状态。** `jevloop` 已经在 npm 上，但最新已发布版本（`0.2.0`）声明的仓库是 `github.com/Xubqpanda/JevLoop`，而本仓库是 `zjunlp/JevLoop`，`package.json` 还停在 `0.1.0`。所以那个已发布的 tarball **不是**这个 revision。要拿这一份，从 git 装 —— `npm install github:zjunlp/JevLoop` —— 或者直接 clone。`npx jevloop …` 只是上面那些 CLI 命令的简写。

**让 demo 走真实的判定模型：**

```bash
npm run demo -- --laya     # 本地 Laya sidecar（:7789，开放权重，免费）
npm run demo -- --jev      # 官方 Jev API（需要 TYPESAFE_API_KEY）
```

## DECISION.md —— 被编译的决策文件

每一代 agent 框架都会留下一个 `.md`。`AGENTS.md` 放约定，`SKILL.md` 放能力 —— 而这两者都是**给大模型读的散文**。模型每轮都为此付 token，它可以不听，而且没有任何东西会告诉你它到底听没听。

`DECISION.md` 是**被编译**的那一个。

> **它不是 decision *record*。** 记录（record）是事后写下来解释 agent 做过什么的。`DECISION.md` 声明的是这条 loop **将要**下哪些判断，由程序把它编译成发给判定模型的问题。

一份文件，两个消费者：

```
结构块  →  问题 + 策略  →  判定模型（几十毫秒，不花 token）
散文    →  system prompt  →  大模型（整个 loop 唯一贵的一步）
```

**帧也声明在文件里。** 每个判定还需要一段**帧**：agent 状态里哪几个字段给模型、各截多长，以及同样承重的另一面 —— **哪些字段被故意不看，以及为什么**。它在文件里是一条 `frame:` 块：

```markdown
frame:
  + task          400                   —— 判「要读哪个文件」必须知道任务要什么
  + tool          40     toolOrEmpty    —— 同一个输入槽对不同工具含义不同
  - history                             —— 候选集**本身**就是投影；再给历史两个信号会打架
```

**以前做不了的那道检查，现在跑起来了。** [`scripts/conformance.ts`](scripts/conformance.ts) 证明 `AgentCtx` 的**每一格**要么被某个判定读了，要么被显式排除并写了理由。把 `- cwd —— …` 那一行删掉，它会失败并点名那一格 —— 而在它存在之前，四层全绿，`cwd` 就这么从声明里消失了。界是**逐栏**的硬要求，所以帧也没法悄悄退化成「把整个上下文塞进去」。

仍然留在代码里的是投影的**实现**（`ctx` → 某个具名投影的值）和宿主自己的词汇表 —— state 格名、候选提供者、位置与动作处理器。这条缝就是下一节要讲的东西。

文件同样没法悄悄腐烂：它在加载时被解析，任何问题 —— 动作名不在封闭词汇表里、谓词指向了错误的问题类型 —— 都会带着行号抛出来，而不是编译成一条永不命中的规则。

所以它是**减法**：每搬一个块进文件，就是少问大模型一个问题。[`headline()`](src/decisiondoc.ts) 会**从文件本身**把它们数出来 —— 改一个 `kind`，那句话就跟着变。

（这句话以前写的是「tests 双向断言它和代码是同一件事」—— 那个说法现在**反了**：文件是正本，没有第二份可供比对。原来那条对账测试留下的是仍然成立的那部分：原语类型、`score` 的档位标签、`noul` 的 true/false 说明。）

```markdown
## grade_risk
kind: mixed
when: 每次真正调用工具之前

### risk
ask: How risky is this tool call?
- read-only
- reversible write
- irreversible
- destructive

### needs_auth
ask: This call must be explicitly authorised by a human before it runs
- true — it can destroy data, spend money, or leave the machine
- false — it only reads or writes inside the working directory

policy:
  - score:risk >= 2 → ask_human
  - prob:needs_auth >= 0.5 → ask_human
  - score:risk >= 1 → auto_audit
  - else → auto
```

**问题的原语类型靠选项的写法推出来，从不声明。** 两个选项叫 `true` / `false` 就是 `noul`；全都带名字就是 `choice`；全都不带名字就是 `score`；混着写会**报错而不是猜**。然后 `kind` 必须和写法推出来的结果对得上。

**谓词是封闭词汇表。** `else`、`top >= n` / `top < n`（仅限只有一个问题的块）、`prob:<id>`（用在 `noul` 上）、`score:<id> >= n`（用在 `score` 上）、`picked:<id> = <选项>`（用在 `choice` 上）。故意不支持 `>` 和 `<=`：**写不出来的条件，就是该写进代码的信号。**

**谓词写错了问题类型会被拒绝，而不是被编译。** 放着不管的话它会变成一条**永不命中的规则** —— 作者以为自己写了一道闸门，实际没有，而且它是 fail open 的。动作名同样是封闭表，写错会带行号报出来。文件里没有任何东西会被静默丢弃：认不出来的一律进 `problems`，并附上它来自哪一行。

## 它是怎么工作的

```
 step ─┬─ loop.needsTool   ↗ 需要动手吗？  ──否──▶ 生成
       │
       ├─ loop.pickTool    ↗ 用哪个工具？（候选每步重建）
       │
       ├─ loop.pickInput   ↗ 读哪个文件？（只在工具确实要参数时）
       │
       ├─ loop.gradeRisk   ↗ 这个操作多危险？  ──▶ 问人
       │
       ├─ [ 工具执行 ]      ← 全流程唯一产生真实副作用的地方
       │
       ├─ loop.stepOk      ↗ 成功了吗？
       │
       └─ loop.isDone      ↗ 做完了吗？  ──否──▶ 下一个 step
                            │
                            ▼
                       [ 大模型生成 ]   ← 唯一昂贵的一次调用
                            │
                       loop.canDeliver  ↗ 这个回答能发出去吗？  ──revise──▶ 再生成一次
```

**那张图是参考 loop** —— 七个节点，声明成 [`DECISION.md`](DECISION.md) 里的七个块，由 [`src/decisions.ts`](src/decisions.ts) 接线。它不是格式的上限：宿主可以声明十个、三十个甚至更多节点，用自己那张图把它们接起来。见[换成你自己的 agent loop](#换成你自己的-agent-loop)。

### 一个判定由三样东西组成

```ts
export const pickTool = defineDecision({
  id: 'loop.pickTool',

  // ① 帧：模型可以在哪几个**有界**的状态切片上做判断。
  //    以 DECISION.md 里的 `frame:` 为准；FRAME_PICK_TOOL 是代码里的
  //    回退，而「不是 JevLoop」的宿主提供自己的投影。
  ...framed(FRAME_PICK_TOOL, 'pick_tool'),

  // ② 类型化的问题。**问法来自 DECISION.md**；候选不能来自文件，
  //    因为 Markdown 装不下一个函数 —— 文件里写 `dynamic: toolsFor(ctx)`
  //    就是在声明这件事。
  questions: (ctx: AgentCtx) => ({
    tool: choice(askOf('pick_tool', ['tool']), toolsFor(ctx)),
  }),

  // ③ 策略：答案 → 动作。**同样来自 DECISION.md**，编译之后是纯代码，没有模型参与。
  ...policyOf('pick_tool'),
});
```

三个原语，直接来自 Jev 的线协议：

| 原语 | 答案 | 用来做 |
|---|---|---|
| `noul` | P(true)，0–1 | **闸门** —— 放行 / 拦住 |
| `choice` | 一个选项 + 每个选项的概率 | **路由** —— 走哪条路 |
| `score` | 有序刻度上的期望档位 | **评级** —— 有多糟 |

### 两件值得偷走的东西

**候选每一步都重建。** 固定的候选列表会让模型去选一个已经不适用的动作 —— 写完文件之后 `write_file` 不该还在候选里。所以 `questions` 可以是上下文的函数。

**绝不让概率绕过授权。** 风险闸门是硬规则，不是阈值：

```ts
policy: [
  // 不可逆 ⇒ 必须显式授权。没有任何置信度能覆盖这一条。
  { when: scoreGte("risk", 2), action: "ask_human" },
  // 模型自己的判断是第二道、独立的闸门
  { when: probGte("needs_auth", 0.5), action: "ask_human" },
  { action: "auto" },
]
```

判定模型可以决定**要不要问人**。它绝不能决定**要不要跳过授权**。

## 诚实的数字

同一条 loop 跑在三种判定后端上。真正重要的比值是「判定 : 模型调用」，而让我们意外的是判定占了多少墙钟时间。

| 判定后端 | 每次判定 | 判定 : 模型 | 判定占墙钟 | 质量 |
|---|---:|---:|---:|---|
| `examples/rule-judge.ts`（离线 demo） | 4 ms | 12 : 1 | **~8 %** | 规则表，不是模型 |
| Laya `typed-decisions`，本地 A100 | 30–85 ms | 8 : 1 | ~38 % | **零样本不够用**（见下） |
| Jev `jev-latest`，托管 API | ~390 ms | 13 : 1 | **79 %** | 每个判定都果断且正确 |

两条我们不会软化的结论：

- **整个主张在「本地部署判定模型」时成立。** 30 ms 一次的判定，让这条 loop 的思考相对于一次生成调用基本免费。
- **走托管 API 时不成立。** 每次判定约 390 ms 是网络往返，13 次判定换 1 次生成，判定就成了墙钟的大头。它仍然比一次前沿大模型调用快 5–8 倍、便宜几个数量级，但在那个延迟下说「判定不要钱」就是撒谎。

明显的甜点是本地部署的强判定模型。我们测过的两个都不是：一个快但不够准，一个准但要走网络。

### 两个我们踩过的坑

两个都是拿真实 Laya 权重在 A100 上跑出来的，不是读文档读出来的。

**`confidence` 不是选中项的概率。** Laya 对 choice 的 `confidence` 是归一化香农熵（`1 - H(p)/log(k)`）—— `p = [0.80, 0.20]` 算出来是 `confidence = 0.269`。所以同一个阈值在 2 个选项和 20 个选项下含义完全不同。请改用**选中项的概率**来卡 `choice`，也就是 `topGte()`。（[官方文档](https://docs.typesafe.ai/confidence)把 `confidence` 定位成「够用的默认值」，并把完整的 `probabilities` 一并给你，正是为了这种情况。）

**基座 checkpoint 做不了没见过的判定任务。** 问它「下一步用哪个工具」，`laya-typed-decisions` 在 step 2 以 **0.660** 选了 `done`，而 step 1 的正确答案只有 **0.646** —— 错的比对的还高，而且四个判定点的答案全落在 0.55–0.66 这个带子里，毫无区分度。**没有阈值能修这个**，这是能力缺口。开放权重的 checkpoint 是一个**用来微调的快速基座**，不是一个开箱即用的判定器。

两条其实是同一个教训，来自 [Jev Engineering](https://madewithjev.com/what-is-jev-engineering)：*调用是最简单的一步 —— 功夫全在你送进去的 state，和你据以行动的那个阈值。*

## 换成你自己的后端

**判定后端** —— 任何能回答 `{state, questions} → {answers}` 的东西：

```ts
import { Decider, HttpProvider, FallbackProvider, MockProvider } from 'jevloop';

const decider = new Decider({
  provider: new FallbackProvider([
    new HttpProvider({ baseUrl: "https://api.typesafe.ai", apiKey: process.env.TYPESAFE_API_KEY, name: "jev" }),
    new HttpProvider({ baseUrl: "http://127.0.0.1:7789", name: "laya" }),
    new MockProvider(),   // 永不失败
  ]),
});
```

**生成后端** —— 任何能把 prompt 变成文本的东西：

```ts
import { HttpGenerator } from 'jevloop';
// 任何 OpenAI 兼容的 /chat/completions 端点
new HttpGenerator({ baseUrl: "https://api.openai.com/v1", apiKey, model: "gpt-5" });
new HttpGenerator({ baseUrl: "http://localhost:11434/v1", model: "qwen3" });  // ollama
```

换掉任何一个都只动一个文件。loop 和判定规格一步都不用挪。

要把它当库依赖：用 `npm install github:zjunlp/JevLoop`，`prepare` 脚本会替你构建 `dist/`。npm 上那个 tarball 是另一条发布线 —— 见[快速开始](#快速开始)下面那段说明。

## 换成你自己的 agent loop

JevLoop 是**参考运行时**，不是唯一的消费方。`DECISION.md` 就是设计给你那条 loop 消费的 —— 用你的状态、你的工具、你的控制流。

分界是这样的：

```
可移植内核（在文件里）                宿主适配器（在你的运行时里）
─────────────────────────────       ────────────────────────────────────
节点 id                              state 格名：类型、来源、可信度
kind: choice | noul | score | …      投影：earlierMaybe、toolOrEmpty……
位置（when:）                        动态候选：toolsFor(ctx)……
问题、选项、判据                      位置处理器：每个位置处理哪些动作
策略规则                             动作处理器：use_tool、call、ask_human……
帧字段、界、排除项及理由              证据提供者
生成器指令                           事件落盘 + 指纹
```

这些名字是在你的适配器里才获得行为的。文件里没有任何东西假定 `AgentCtx`、JevLoop 那四个本地工具，或者 JevLoop 的 loop 分支。

**图是你的，不是我们的。** 参考 loop 大致线性、七个节点宽，但宿主可以声明几十个节点并随便接线 —— 分支、重试、升级、嵌套 loop、多个终止状态。[`examples/external-host.ts`](examples/external-host.ts) 就是一个这样的最小宿主，它**没有** import `agent.ts`、`decisions.ts` 或 `AgentCtx`：

```bash
npm run external-host
#   needs_tool: fields=6, action=use_tool, rule=0
#   …
#   external host: custom graph reached done after 1 retry
#   external host: graph trace classify_issue --inspect--> inspect_repository | … | --deliver--> done
```

它那张图是 分诊 → 巡检 → 计划 → 测试 → 归因 → 备好候选 → 完成，带一条重试边和一条人工升级边；它的节点来自 [`examples/custom-graph.DECISION.md`](examples/custom-graph.DECISION.md)，用的是 `host:` 位置命名空间 —— 也就是说，**不是**那七个参考节点。

**认不出的声明会在动作执行之前被拒绝，而不是记一条日志。** [`src/adapter.ts`](src/adapter.ts) 拿宿主声明出来的能力去核对文件，对未注册的投影、缺失的 state 格、未处理的 action、位置处理不了该 action、缺失的动态候选提供者，逐条给出带源位置的报错。[`tests/adapter.test.ts`](tests/adapter.test.ts) 把每一条都钉成反向夹具 —— 所以一个不完整的适配器会大声失败，而不是静默跳过某个判定。

`npm run adapter-test` 跑它们。夹具发布出来的能力报告在 [`examples/external-host.capabilities.json`](examples/external-host.capabilities.json)。

**我们不主张什么。** `DECISION.md` 有一个可移植的声明式内核，以及一个 JevLoop 参考适配器。但「任何 runtime 都能不加改动地执行这份文件」「投影与谓词语义已经冻结」「replay 已经可移植」这些**都还不成立** —— 它们是 [`docs/DECISION-CONTRACT.md`](docs/DECISION-CONTRACT.md) 里列着的开放项，那份文档同时放着合规检查表。[`docs/SKILL-DECISION-ADAPTER.md`](docs/SKILL-DECISION-ADAPTER.md) 是一份逐步指南，教你改造一个已有的运行时，包括怎么盘点一个形状和我们的不一样的宿主图。

## 界面

`npm run serve` 会在 **http://127.0.0.1:7799** 打开一个三栏界面 —— 本页顶部那张图就是它跑一次的样子。

| 栏 | 显示什么 |
|---|---|
| 左 | 工作区与历史会话，从 `~/.jevloop/sessions/` 读 |
| 中 | 对话、完整的判定轨迹、以及编译后的 `DECISION.md` 规格 |
| 右 | 记账 —— 判定与模型调用的对比、各自的耗时，以及两块上下文预算和它们的折叠线 |

**轨迹那栏最值得看**：这条 loop 做过的每一次判定、代码拿答案做了什么、花了多久。

```bash
npm run serve                                  # 默认工作目录是一个临时演示目录
CWD_ROOT=./你的项目 PORT=7800 npm run serve
```

它**没有鉴权**，默认只监听本机。`HOST=0.0.0.0` 的意思是「这个网络上的任何人都能让它在这台机器上跑任务」。

> 已发布的 CLI 把这三个换成命令行参数：`npx jevloop serve --cwd … --port … --host …`。

## 它不是什么

- **不是大模型的替代品。** 起草、写代码、总结仍然需要它。
- **不是「零幻觉」。** 判定模型给不出你问的类型之外的答案，但答案仍然可能是错的。阈值就是为这个准备的。
- **不是准确率上的优势。** 上面那次和 ReAct 的对比是 7 条任务、各跑 1 遍、单一模型 —— 本 loop 被验收 6/7，ReAct 是 7/7。
- **没有做过生产加固。** 工具沙箱只覆盖路径逃逸。把它指向任何你在乎的东西之前，先读 [`src/act-local.ts`](src/act-local.ts)。
- **还不是可移植的运行时。** 契约是可移植的，**执行**不是。别的 agent runtime 需要写适配器 —— state 格、投影、候选提供者、动作处理器 —— 而且 `DECISION.md` 的谓词与投影语义还没冻结。见[换成你自己的 agent loop](#换成你自己的-agent-loop)。

## 目录结构

装着全部主张的那几个文件，按阅读顺序：

| 文件 | 是什么 |
|---|---|
| [`DECISION.md`](DECISION.md) | ★ 这些判定，写成一份运行时编译的文档 |
| [`src/decisions.ts`](src/decisions.ts) | ★ 参考 loop 的七个节点，以及它们背后的帧声明 |
| [`src/agent.ts`](src/agent.ts) | ★ 问它们的那条 loop |
| [`src/decide.ts`](src/decide.ts) | 一次判定走的六个步骤 |
| [`src/policy.ts`](src/policy.ts) | 答案 → 动作，纯代码 |
| [`src/meter.ts`](src/meter.ts) | ★ 判定与模型调用的对账 |
| [`src/adapter.ts`](src/adapter.ts) | 宿主能力的接缝：state 格、投影、提供者、动作 |
| [`examples/external-host.ts`](examples/external-host.ts) | 一个不是 JevLoop 的宿主，自带一张图 |
| [`docs/DECISION-CONTRACT.md`](docs/DECISION-CONTRACT.md) | 可移植内核 / 宿主适配器的分界与合规检查表 |
| [`docs/SKILL-DECISION-ADAPTER.md`](docs/SKILL-DECISION-ADAPTER.md) | 逐步改造一个已有运行时 |

其余都是接线。最可能想换掉的那几块：

| 想改什么 | 去哪 |
|---|---|
| 判定由谁回答 | [`src/seam-provider.ts`](src/seam-provider.ts) 定义接口；`provider-http` / `provider-mock` / `provider-fallback` 实现它 |
| 用什么写回答 | [`src/llm.ts`](src/llm.ts) |
| 工具能做什么 | [`src/act-local.ts`](src/act-local.ts)；它们必须满足的契约在 [`src/act.ts`](src/act.ts) |
| 这份文件还诚不诚实 | [`scripts/conformance.ts`](scripts/conformance.ts) —— `npm run conformance` |
| 界面 | [`web/`](web/) 和 [`src/server.ts`](src/server.ts) |
| 命令行 | [`src/cli.ts`](src/cli.ts) |

[`examples/demo.ts`](examples/demo.ts) 离线可跑，用的是 [`examples/rule-judge.ts`](examples/rule-judge.ts) 那个确定性判定器。完整目录跑 `ls src/` —— 这一节是索引，不是清单，因为四十四个文件的清单一天就会过期。

## 参与贡献

先读 [`CONTRIBUTING.md`](CONTRIBUTING.md)（英文）—— 里面写了我们收什么样的改动、什么样的会直接关掉。

[`TODO.md`](TODO.md)（英文）是还没做完的部分，按「什么卡住了那个主张」排序，不按难度：工具面只有四个工具、判定帧没有缓存策略、循环跑不长。每一项都写了为什么重要、从哪里下手。

## License

Apache-2.0
