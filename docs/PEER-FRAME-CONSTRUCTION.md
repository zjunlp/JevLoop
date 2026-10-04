# 别人的帧是怎么构造的

**为什么写这一页。** 你说「动作选择这部分和我们的帧处理有很大的关系，多从别人那里看看别人的设计」。
我先前的做法是：把别人的一条结论（「一候选一题」）直接实现进 `pickInput`，然后跑 A/B。
那是把顺序做反了 —— 结果是量出一条负结果，再把默认改回去（`docs/PICKINPUT-SHAPE.md`）。
这一页做的是那件本来该先做的事：**读他们的帧构造**，再决定我们的帧动不动。

**读了什么。** 都是现读的源码，不是二手总结。

| 仓库 | 版本 | 关键文件 |
|---|---|---|
| [`browser-use/jev-ultrafast`](https://github.com/browser-use/jev-ultrafast) ⭐21,934 | `1231850a`（2026-09-18） | `jev_ultrafast/model.py`(198) · `browser.py`(194) · `agent.py`(174) · `questions.py`(26) · `snapshot.js`(107) |
| [`qybaihe/mu`](https://github.com/qybaihe/mu) ⭐344 | `8dfebe36`（2026-09-30） | `packages/kyrn-judge/src/decision.ts`(446) · `policy.ts` · `types.ts` · `decisions/{browser-step,tool-admission,file-locate,turn-drift}.ts` |
| μ 的实测记录 | 同上 | `kyrn/docs/09-test-log-admission.md` |

★ μ 的 `browser.step` **自己声明它是照 `jev-ultrafast` 写的**（源码注释里写了 MIT 和版权）。
所以下面两家在**帧的形状**上可以当成一个设计看，而 μ 多出来的那部分（`decision.ts` 的引擎契约）是它自己的。

---

## 一、帧就是一个纯函数，而且它只有三个键

两家送出去的 `state` 是同一个形状：

```python
# jev-ultrafast, model.py::choose
"state": {
    "page": {k: state[k] for k in ("url", "title", "text")},
    "elements": elements,                     # 候选表（带索引）
    "recent_actions": [{k: h.get(k) for k in ("action","kind","text","page_changed")}
                       for h in history[-10:]],
}
```

```ts
// μ, decisions/browser-step.ts
buildState(input: BrowserStepInput) {
  return plain({ page: input.page, elements: input.elements, recent_actions: input.recentActions });
}
```

**三个键。** 没有 goal（goal 在题的 `instructions` 里），没有 plan，没有 status，没有预算计数器。

μ 把这条写成了引擎级的契约（`decision.ts::DecisionSpec`）：

```ts
/** Digest the input into a small state.
 *  The judge has a 32K window: send summaries and metadata, not bulk text. */
buildState(input: In): JudgeInput;
```

⇒ **帧 = `buildState(input)`，一个纯函数**；判官看不到任何调用方自己的簿记。
jev-ultrafast 的 `agent.py` 里其实有十来个状态字段（`plan`、`plan_index`、`decisions`、`text_calls`、
`elapsed_ms`、`status`……），但 `choose()` **只挑三个送出去**。它另有一个 `snapshot()` 把其余字段
一起送出去 —— 那是给 **demo 界面**看的，不是给判官。

**我们的样子。** `NODE_FRAMES` 逐节点声明字段 + 预算 + **排除理由**：

| 节点 | 字段 |
|---|---|
| `needsTool` | task · last_tool · last_result · history · done_tools · redirect_note |
| `pickTool` | task · last_result · remaining · redirect_note |
| `pickInput` | task · action_table · action_rules · history · last_result · redirect_note |
| `gradeRisk` | task · last_input |
| `stepOk` | last_tool · last_input · last_result |
| `isDone` | task · history |
| `canDeliver` | task · draft · evidence |

★ 两边的**取舍不同，但都对**：他们用「一个纯函数 + 三个键」把帧压到最小，我们用「逐节点声明 + 排除理由」
把帧**约束住**。我们的机制多两样他们没有的东西 —— `required`（区分「环境没有」和「我们没带上」）
和 `excluded`（写下**为什么**某个字段不在这一帧）。这两样是这一页里我们**不该换掉**的部分。

★ 真正的差距在**字段顺序**：μ 的 `tool.admission` 明写

> The chunk is the long field, so it goes last: a bounded-window judge cuts the tail.

我们没有任何一处考虑过「哪个字段先被截断」。我们的预算是一刀切的每字段上限，
而**截断从尾巴发生** —— 所以长字段放前面和放后面，后果完全不同。

---

## 二、候选放哪：**看它有多大**

这是这一页最实用的一条。两家都用过两种放法，而且**按候选的大小分**：

| 决策点 | 候选放哪 | 状态 |
|---|---|---|
| μ `files.locate` | **题面里**（`Is this file likely to contain \`query\`? ${path}`） | 只有 `{query}` |
| μ `tool.admission`（批量） | **状态里**，编号 `c1…cN`，每题问 `k1…kN` | `{call, c1…cN}` |
| jev-ultrafast `browser.step` | **状态里**（`elements`），题里引用索引 `[i]` | `{page, elements, recent_actions}` |

μ 在引擎层把这个选择写成了 `questionsFor` 的存在理由：

> Questions built from the input, **one per candidate** (a skill, a memory, a file path), for
> decisions over a list whose length is only known at run time. **Carrying the candidate in the
> question keeps one state for all of them**, which a large-window judge answers in a single request.

**★ 注意这一句：一个状态给所有候选。** 一候选一题**不等于**一候选一帧 —— 帧是所有候选共享的，
变的只有题。这正是我们 `pickInput` 现在的做法（`action_table` 在帧里，题引用 `[i]`），
**这一处我们已经对了。**

μ 的日志准入那一条把预算也写清楚了（`09-test-log-admission.md` §二.6）：
**最多 24 个问题、状态 14K 字符**，优先问最大的候选，**问不到的保留**。

### 他们量过的 token 代价（这一条我们没量过）

> `tokens ≈ 0.279 × 状态字符 + 0.277 × 问题字符 + 317`（123 次请求，平均误差 48）。
> 状态只计一次；**问题文本与状态同价**，12 个问题时问题文本比状态还长。
> 把选项说明挪进状态（`lean`）省 19% tokens，但果断性下降，不值。

⇒ 两件事:**① 候选说明放题里还是放帧里，代价差不多**（同价），所以别为了省 token 挪；
**② 候选数一多，题文本会超过帧。** 我们上一轮 40 个候选时正是这个形状。

---

## 三、逃逸口**强制**，而且在定义时就拦

μ 的 `policy.ts`：

```ts
/** Option names that mean "nothing fits". A choice question without one is forced
 *  to pick a real option even for off-topic input, and does so at full confidence,
 *  so specs must include one unless the option set is truly closed. */
export const ESCAPE_OPTIONS = ["none", "other", "unclear", "unknown"] as const;
```

`defineDecision` 在**定义决策点时**就抛错：

```ts
if (!spec.allowChoicesWithoutEscape) {
  for (const [questionId, question] of Object.entries(spec.questions)) {
    if (question.type === "choice" && !hasEscapeOption(question)) {
      throw new TypeError(`Choice question "${questionId}" in decision "${spec.id}" has no escape option`);
    }
  }
}
```

**我们是一样的机制**（`_choice_question(escape=…, closed=…)`），只有一处不同：
他们拦在**定义时**，我们拦在**调用时**。定义时更早 —— 一个写错的决策点在进程起来时就红，
而不是跑到那一题才红。这一条值得抄。

---

## 四、门限：三区，而且**中间区落到调用方的默认 —— 不是拒绝**

μ 的 `policy.ts`：

```ts
export type Verdict = "yes" | "no" | "unsure";
export const DEFAULT_THRESHOLDS: Thresholds = { no: 0.2, yes: 0.8 };

/** The middle zone exists so a wrong-but-confident reading is the only way the judge
 *  can cause harm: anything the model is unsure about falls through to the caller's default. */
export function threeZone(answer, thresholds = DEFAULT_THRESHOLDS): Verdict {
  if (answer.probability >= thresholds.yes) return "yes";
  if (answer.probability <= thresholds.no)   return "no";
  return "unsure";
}
```

`pickChoice` 同样是「不够就返回 `undefined`」，而 `undefined` 的含义是**调用方的默认**：

```ts
/** The picked option, or undefined when it is an escape option or not probable enough. */
export function pickChoice(answer, options = {}) {
  if (isEscapeOption(answer.choice)) return undefined;
  const probability = answer.probabilities?.[answer.choice];
  if (probability !== undefined && probability < (options.minProbability ?? 0.6)) return undefined;
  return answer.choice;
}
```

⇒ **「不确定」的出口是「按没有判官时怎么办」，不是「拒绝」。**
这正是 μ 的 `files.locate` 兜底写成**平先验**的原因 —— 也是我们上一轮 ALFWorld 塌掉的直接原因。
我们的 `BELOW_THRESHOLD_POLICY` 只有 `drop` / `accept` 两档，而**中间区没有第三档**。

### ★★★ 而且他们量过一条，正好命中我上一轮的错误

> **布尔概率被压缩。** 同样清楚的情形，布尔题给 0.14–0.17 和 0.83–0.86，
> 选择题给 0.01 和 0.99。**阈值不能在题型之间照搬。**

我把选择题的门限 `NODE_THRESHOLDS["pickInput"] = 0.5` 用在了**一候选一题的布尔题**上。
我们那批 40 个候选拿到的正是 **0.23–0.31** —— 落在他们量出来的「布尔被压缩」那一档，
所以**没有任何一个能过 0.5**，逃逸每次都触发。这不是我的题形设想错，
是**把两种题型的刻度当成了同一个刻度**。他们把这句话写下来了，我没读到。

### ★★ 还有一条：问「够不够」，不要问「相不相关」

同一份记录里，他们换过四种问法。**调整用样本**上（28 个可选噪音候选）：

| 问法 | 可选噪音省略 | 误删 |
|---|---|---|
| `suffices`（**默认**） | **19/28** | 0 |
| `policy`（草稿问法） | 17/28 | 0 |
| `needed` | 14/28 | 0 |
| `asks`（布尔） | **2/28** | 0 |

★ 这四档是在**调整用样本**上比出来的，所以另做了一组没见过的留出样本。
留出集只重测了 `suffices`（14/15）和 `policy`（13/15），**方向一致但边际很窄** ——
`asks` 那种布尔问法没有在留出集上重测。这一条要跟着这个限定读。

> **问法要问「够不够」，不要问「相不相关」。** `needed` 问「候选里有没有目标问到的东西」；
> 目标是「测试过了吗」时，通过记录在**话题上相关**，Jev 给 0.58–0.65，**全部保留**。
> `suffices` 先说明汇总与失败无论如何都会保留，再问这个候选还要不要，同类目标上给 **0.98+**。

**「话题上相关的东西全都被保留」= 我们的病。** 我们的候选题是

```python
PICK_INPUT_CANDIDATE_ASK = "Is `{ref}` an action this task needs next? …"
PICK_INPUT_CANDIDATE_CRITERIA = {"true": "doing this now is required by the task, or is a necessary step towards it", …}
```

这是纯关系型（「是不是下一步要做的」）。实测结果和他们一模一样：**三篇候选全给 0.25 / 0.29 / 0.31，
分不出来**。他们给出的修法是：**先声明哪些东西无论如何都会保留**，再问「这个还要不要」，
刻度就从 0.6 挪到了 0.98。

★ 还有一条负结果值得记：**`unclear` 从未被选**（概率恒 0.00，不确定性摊在两个实选项上）。
⇒ 一个判官**从来不会去选**的逃逸选项等于没有。这和我们的 `PICK_INPUT_ESCAPE` 是同一个形状。

---

## 五、出处、落地值、失败：三件事分开

μ 的 `Decision` 把「判官说了什么」和「我该做什么」做成两个字段：

```ts
export interface Decision<Out> {
  readonly outcome: Out;          // 调用方必须照它做
  readonly source: "judge" | "fallback";
  readonly reason?: string;
  readonly judged?: Out;          // 判官那条路产出的值；弃答或失败时 undefined
  readonly answers?: Record<string, Answer>;
  readonly latencyMs?: number; readonly usage?: JudgeUsage; readonly warnings?: …;
  readonly tiers?: readonly JudgeTierReport[];   // 级联时是哪几个判官答的
  readonly ledgerId?: string;
}
```

而且**失败一律 fail-open**：

> Runs decisions fail-open: `decide` never rejects because of the judge.
> Timeouts, outages, invalid answers and abstentions all yield the spec's fallback.

**★ 出处不只在账上，它会改变行为。** `AnswerSignals` 里带 `judge`，而 `browser.step` 的策略：

```ts
// A neutral stand-in from the cascade is not a decision: nobody capable looked at the page.
if (operation.judge === "untrusted" || operation.judge === "unavailable") return ABSTAIN;
```

⇒ 级联里一个**替身**给的答案**不算判定**，直接弃答。我们的 `DecisionRecord.source` 只用来记账，
不会让一个 fallback 答案失去效力。这一条他们更严。

---

## 六、预算、截断、隐私、账

| 事 | 他们 | 我们 |
|---|---|---|
| 窗口口径 | 32K，「送摘要和元数据，不送整段文本」 | `MAX_REQUEST_CHARS = 32000`（实测 128K 字符可用） |
| 候选数上限 | jev-ultrafast **250**，`omitted_actions` 算出来了 —— **但只给调用方，没进判官状态**（`choose()` 只送 `page/elements/recent_actions`） | `MAX_LISTED_CANDIDATES = 20`；`MAX_OPTIONS = 32`（**只是告警**，超了照发） |
| 文本上限 | jev-ultrafast 页面文本 **6000** 字符（视口内文本节点） | 每字段预算，逐节点不同 |
| 历史窗口 | 判官 **10** 条；写文本的小模型 **6** 条 | `history` 字段预算 4000 字符 |
| 密钥 | `redactJson(state, knownSecrets)` —— **状态和题一起洗** | 无 |
| 账 | `stateDigest = sha256(state)`；`recordState` **默认关**（「状态里可能有用户内容」）；批量写**一条**，`size ≤ 8` 才留每题答案 | 每条判定一行，含 `request_digest` / `frame_digest` / `state_key` |
| 缓存 | 每个决策点声明 `cacheImpact: none / append-only / prefix-mutating` | 无 |
| 延迟分级 | `latency: inline / parallel / background` | 无（全部 inline） |
| 环检测 | **规则**：连续 3 条 `page_changed=false` 且非 wait ⇒ `blocked` | 待办里有一个 `drift` 判定点 |

★ 两条最值得记：**① 状态和题一起洗密钥**（这一条是抄他们的，和判官质量无关，是安全问题）；
**② 候选数的截断要进判官状态** —— 这一条**不是抄他们，他们也没做**：
jev-ultrafast 把 `omitted_actions` 算出来了，但只给调用方，判官看不到。
我们有 `MAX_LISTED_CANDIDATES = 20` 和 `MAX_OPTIONS = 32` 两处候选截断，
**两处都只在账上报字段截断，没在帧里告诉判官「候选被砍过」**。
一个看不见自己被砍过的判官会把「只剩 20 个候选」读成「只有 20 个候选」。

---

## 七、对照表：我们放什么 / 他们放什么 / 差在哪

| 维度 | 他们 | 我们 | 判断 |
|---|---|---|---|
| 帧的声明 | `buildState(input)` 纯函数 | `NODE_FRAMES` 逐节点字段 + 预算 + **排除理由** + `required` | **我们更好，不换** |
| 帧的大小 | 3 个键 | 3–6 个字段 | 相当 |
| 候选放哪 | 小候选进题 / 大候选进状态编号 | `action_table` 进帧 + 题引用 `[i]` | **一致** |
| 一帧多题 | `questionsFor` 明写「一个状态给所有候选」 | 一个请求多题共享一帧 | **一致** |
| 逃逸口 | 定义时强制 | 调用时强制 | 抄「定义时」 |
| 不确定的出口 | 三区 ⇒ **落到调用方默认** | `drop` / `accept` 两档 | **差距，且已付代价** |
| 题型刻度 | 实测「布尔被压缩，阈值不能跨题型照搬」 | `pickInput` 一个 0.5 用在两种题型上 | **差距，正是上一轮的病灶** |
| 问法 | 「够不够」，先声明不变式 | 「相不相关」 | **差距，正是上一轮的病灶** |
| 新决策点 | 默认 **`shadow`**，和结果比过才 `active` | 直接进默认路径 | **差距明显** |
| 出处 | 在答案上，且改变行为 | 只在账上 | 差距（安全/严格性） |
| 落地值 | `outcome` 与 `judged` 两字段 | `source` 标签 + `fallback` 名字 | 等价 |
| 失败 | fail-open → fallback | `FALLBACK_POLICY` | 一致 |
| 长字段顺序 | 「最长的放最后，窗口小从尾巴切」 | 没考虑过 | **差距，便宜** |
| 候选截断 | 算出来并送出去 | 只报字段截断 | **差距，便宜** |
| 密钥洗白 | 状态 + 题 | 无 | 差距，便宜 |
| 环检测 | 规则 | 判定点（待办） | 他们是规则，只有 3 行 |

---

## 八、结论：该动的是哪几处

按「有实测支撑」排，**不按新鲜感排**：

1. **门限分题型。** 布尔题和选择题各有自己的刻度。μ 量到布尔被压缩到 0.14–0.17 / 0.83–0.86，
   选择题是 0.01 / 0.99。我们的 `NODE_THRESHOLDS` 现在是一个 dict 里混着两种量。
   **这一条是上一轮失败的真正病灶**，改它不需要新机制。
2. **「不确定」要有第三档：落到调用方的默认。** 现在只有 drop / accept，
   而 μ 的三区把「中间」明确定义成「按没有判官时怎么办」。ALFWorld 塌成一步就是这个缺口。
3. **候选题的问法：先声明不变式，再问「还要不要」。** 把关系型（「是不是下一步」）
   换成「够不够」。他们在调整用样本上量过：四种问法里 `suffices` 19/28，布尔型 `asks` 2/28；
   留出样本上 `suffices` 14/15、草稿问法 13/15。**方向一致，但留出集只重测了两种问法**，
   所以这条的把握是「有实测支撑」，不是「已定案」。
4. **新决策点默认 `shadow`。** 我上一轮把一个新的决策点**直接设成默认**，跑完才知道它更差。
   μ 的做法是：新决策点先在 shadow 里只记录不落地，和结果比过才 `active`。
   ★ 这条是流程上的，成本极低，而且是这一页里唯一能**防住我上一轮那个错**的机制。
5. **便宜的四处**：长字段放最后（抄）、状态和题一起洗密钥（抄）、
   逃逸口改到定义时强制（抄）、**候选截断进帧**（我们自己的缺口，他们也没做）。

**不该动的**：`NODE_FRAMES` 的逐节点声明、`excluded` 的排除理由、`required` 的两类缺失、
`canonical_state` 的状态键。这四样是我们比他们细的地方，换掉是退步。

**还没搞清楚的**：`cacheImpact` 和 `latency` 分级只在他们的缓存/并行架构里有意义。
我们还没有那个架构，照抄字段名不会带来任何东西 —— 记在这里，不动。
