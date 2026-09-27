# DECISION.md

这个 agent 在 loop 里要问哪些问题、每个问题归谁答。

`docs/CODE-STYLE.md` 讲的是代码怎么写，这份文件讲的是**判断怎么下**。
它是给两个消费者读的：结构块编译成判定（不花钱），`## generator`
那一段进 system prompt（花钱）。

所以下面每写一个 `kind: choice`，都是**少问大模型一次**。

判定 id 旁边的括号是 `src/decisions.ts` 里对应的实现。

---

## needs_tool

kind: noul
when: step-start —— 每个 step 的开头。判否就直接跳到生成，整个工具循环省掉

ask: The agent still has work to do before it can answer the task — an action the task requires that has not been taken yet

- true — the task still requires an action that has not happened: reading something, listing something, writing something, running something
- false — every action the task asks for has already been taken, and there is enough information to answer

frame:
  + task          400                   —— 整个判定的主体：问的是「这个任务还有没有没做的动作」
  + earlier       200    earlierMaybe   —— 多轮下「再读一遍那个文件」里的「那个」唯一能落地的地方（§8.2）
  + already_done  300    describeDone   —— ★ 必须是一份**清单**，不是一个计数。原来这里是 `steps_done: 2`，实测任务「把 alpha.ts 里的 totalOf 抄到新文件 summary.ts」读完 alpha.ts 后判了「不需要工具」，**文件从没被写出来** —— 因为「读过」和「写过」在计数里长得一样
  + files_known   15     filesMaybe     —— 任务里的「这两个文件」是一个**指代**，没有它落不到具体路径上
  + already_read  15     readMaybe      —— 分不出「读了一个还是两个」，就无法确认任务说的「这两个」读完了没有（实测 0.86 误判）
  + last          300    lastOrNone     —— 刚刚发生了什么 —— 判「还要不要动手」时最近一步的结果是主要依据
  - cwd                                 —— 路径不进判定：目标由 `target` 那一栏（gradeRisk）或候选（pickInput）表达，工作目录本身没有信息
  - canWrite                            —— 「能不能写」是**代码**按精确规则判的（§8.1 第三行），不该让判定模型再判一遍
  - lastTool                            —— 工具名单独列出来会诱导它去评判「上一个工具选得对不对」——那是 `stepOk` 的职责
  - draft                               —— 草稿是生成之后才有的东西；这一步根本还没到生成

policy:
  - prob:needs_tool >= 0.5 → use_tool
  - else → answer

★ **判据是「任务还有没有没做的动作」，不是「还有没有没拿到的信息」。**
这两个在只读任务上恰好一致，而在**写任务**上分道扬镳 —— 实测
（2026-09-21）：任务「把 alpha.ts 里的 totalOf 抄到一个新文件 summary.ts
里」，读完 alpha.ts 之后这个节点判了 `answer`（0.36），于是 loop 直接去
生成回答，**文件从没被写出来**。

它当时看到的是：任务、`already_done: "list_dir, read_file"`、以及 alpha.ts
的完整内容。**信息确实齐了** —— 按旧措辞「no tool call now would mean
answering with information it does not have yet」，答案就是「不需要工具」，
它判得没错。**是措辞把「写」这件事排除在问题之外了。**

配套：帧里必须有 `already_done`（一份**清单**，不是一个计数）——
`steps_done: 2` 那种写法分不出「读过了」和「写过了」（§8.2）。

常规 agent 也「判断」这件事，但方式是让大模型输出一段话来表达它 ——
于是这个只需一次前向的是非题，付了生成的价格。

## pick_tool

kind: choice
when: tool-choice —— 判定需要动手之后，每一步都问一次
dynamic: toolsFor(ctx) —— 候选每步重建，下面列的是默认全集

### tool

ask: Which tool should the agent call next?

- read_file — 需要文件内容才能继续，且这个文件还没读过
- list_dir — 还不知道目录里有什么
- write_file — 要写的内容已经拿到，且目标路径明确
- done — 已有足够证据回答任务，工具循环可以结束了

frame:
  + task          400                   —— 选工具的唯一依据是任务要什么
  + earlier       200    earlierMaybe   —— 挑工具时「上文」尤其重要 ——「那个文件」要靠它才能落到具体路径
  + already_done  300    describeDone   —— ★ 用一句话讲清「已经做过什么」，不丢一个数组让模型自己解析 —— 实测只放数组时它会重复选做过的动作
  + files_known   20     filesMaybe     —— 「还有没有可读的文件」决定 read_file 还在不在候选里
  + already_read  10     readMaybe      —— 少了它会重复读同一个文件（§8.2：帧里没有的信号它判不出来）
  + last_result   300    resultMaybe    —— 上一步的结果决定下一步该做什么
  - cwd                                 —— 同 needsTool：工作目录本身没有信息，目标由候选表达
  - canWrite                            —— 「能不能写」是代码的规则，不是判定 —— 它决定 `write_file` 进不进候选，不进帧
  - lastTool                            —— ★ 候选本身**已经按做过的动作重建过**（§8.4）；再把「上一个是什么」放进来，会让「还有哪些工具」和「已经做过什么」互相打架
  - draft                               —— 还没到生成那一步

policy:
  - top >= 0.6 → call
  - else → escalate

**候选是每步重建的，上面这份只是默认全集。** 固定的候选列表会让模型去选
一个已经不适用的动作 —— 实测写完文件之后 `write_file` 还在候选里，模型会再选它。
真正发给模型的是 `toolsFor(ctx)`，它把做过的动作删掉。

同时 `top >= 0.6` 用的是**选中项的概率**，不是 `confidence`。Laya 的
`confidence` 是归一化香农熵（`p=[0.8,0.2]` → `0.269`），拿它卡阈值时
在 2 个选项和 20 个选项下含义完全不同。

## pick_input

kind: choice
when: input-choice —— 选定的工具需要参数时（`list_dir` 不需要，它没有可挑的东西）
dynamic: unreadFiles(ctx) —— 还没读过的文件，每步重建

### file

ask: Which file should this tool call target?

- 还没读过的文件 — 候选由 `unreadFiles(ctx)` 每步算出来，这里不列举

frame:
  + task          400                   —— 判「要读哪个文件」必须知道任务要什么
  + tool          40     toolOrEmpty    —— 同一个输入槽对不同工具含义不同：read_file 挑的是「读哪个」
  + already_read  10     readMaybe      —— 读过的要从候选里去掉，判定得看得见「读过哪些」才知道剩哪些
  + candidates    20     filesMaybe     —— 候选的**全集**。真正发出去的是 fileOptions 的重建结果，这一栏是让判定知道总体有多少
  - cwd                                 —— 同前：目标由候选表达，不由工作目录表达
  - history                             —— ★ 候选（`fileOptions`）本身已经是「还没读过的那些」这个闭集的投影；再给一遍历史会让「还剩哪些」和「做过什么」两个信号互相打架（§8.4 的同一个坑）
  - canWrite                            —— 写路径的候选不由这里产生 —— `write_content` 生成路径，判定不参与
  - earlier                             —— 这一步是在一个已经选定的工具内部挑参数，指代关系由 task + 候选表达就够了
  - lastResult                          —— 结果的**内容**与「挑哪个文件」无关；它是 `stepOk` 与 `canDeliver` 的依据
  - draft                               —— 还没到生成那一步

policy:
  - top >= 0.5 → use
  - else → escalate

这条以前**不存在**，工具参数是写死的代码（永远返回 `files[0]`）。
配合「做过的动作从候选里删掉」，结果是 `read_file` 在一个 agent 生命周期里
只能触发一次、且只能读第一个文件 —— 「读取目录里的**全部** TypeScript 文件」
这种任务在那个实现下不可能完成。

按三分法，「读哪个文件」是**挑选**，该问判定；「写什么内容」是**生成**，
仍由调用方提供。

## grade_risk

kind: mixed
when: before-call —— 每次真正调用工具之前

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

frame:
  + tool          40     toolOrUnknown  —— 风险的第一依据是哪个工具 —— 但**认不出来时不编一个数**
  + base_risk     12     localToolRisk  —— 工具的静态风险基线（`act-local.ts` 的 `baseRisk`）。★ 认不出的工具名**不放这一栏** —— 0 分的意思是「只读」，不能用它冒充「未知」。这就是 `absent` 与 `unfilled` 必须分开的原因：这一栏「今天不适用」是**正常状态**
  + target        200    lastInput      —— 判风险要看**这一调的目标**，不是工具名 —— `rm -rf /` 和 `ls` 的危险程度差在参数上
  + task          300                   —— 同一个动作在不同任务下风险不同（写配置文件 vs 写 /etc）
  - cwd                                 —— 工作目录由 target 的路径体现；单列出来是冗余
  - files                               —— 目录里有哪些文件与「这一次调用多危险」无关
  - readFiles                           —— 读过什么与风险无关
  - canWrite                            —— 能不能写是另一道门；这里问的是**已经决定要做的这一调**有多危险
  - earlier                             —— 多轮的上文不改变这一次调用的风险
  - lastResult                          —— ★ 上一步的**输出内容**绝不能进这一栏：它是不可信文本，而这一栏的输出会驱动授权闸门 —— 让它读工具输出，等于让工具输出有机会推动风险分
  - draft                               —— 还没到生成那一步

policy:
  - score:risk >= 2 → ask_human
  - prob:needs_auth >= 0.5 → ask_human
  - score:risk >= 1 → auto_audit
  - else → auto

**这是一个判定问两件事的例子**，所以 kind 是 `mixed`。两条闸门是**独立的**：
第一条是硬规则（风险分够高就必须授权，不接受概率绕过），第二条才是模型判断。
实测有效 —— 把风险阈值从 2 提到 3 试图绕开第一条时，第二条 `needs_auth=0.95` 兜住了。

`auto_audit` 承诺了留痕就必须真的留痕。以前这条分支和 `auto` 完全一样，
只多打一行 trace。

## step_ok

kind: noul
when: after-tool —— 每次工具执行之后

### ok

ask: This tool call itself completed and returned output this step can use. Judge only this call; whether the whole task is finished is a different question, decided elsewhere.

- true — the tool ran and returned content — no error, no empty result, and the target it names is the one that was requested
- false — the call did not work: an error, an empty result, a missing file, or output that clearly did not come from this tool

frame:
  + tool          40    toolOrUnknown  —— 判据里写着「the target it names is the one that was requested」，得知道是哪个工具
  + input        200    lastInput      —— 判据包含「返回的目标就是请求的那个」—— 没有请求就没有可比的对象
  + output       500    resultMaybe    —— 这一步的**唯一证据**
  + already_read  12    readCount      —— 一个计数就够：这一步判的是单次成功与否，不需要读过的清单
  - task                               —— ★★ 四次事故里最贵的一次。帧里带着 task、问题写着「for the task」、判据写着「what the task needed」，三处一起把**这一步**的判定拉到了**任务级**。实测任务「读一下 invoice.ts」第一步 list_dir 返回文件列表，它确实成功了，但没回答「这个文件定义了哪些函数」，于是 ok=0.470 判否 → stop → **整个循环结束**：任何需要多于一个工具的任务都跑不完。「任务完成了吗」是 is_done 的职责
  - cwd                                —— 与「这一次调用本身成没成」无关
  - files                              —— 同上：成功与否看的是这一次的输入与输出
  - canWrite                           —— 与这一步的成败无关
  - earlier                            —— ★ 上文会把判定拉向「整体进展如何」，而这一栏问的是刚刚那一次调用
  - draft                              —— 草稿在这一步之后才有

policy:
  - prob:ok >= 0.6 → continue
  - else → stop

**它判的是这一步，不是这个任务。** 决策帧里**故意没有 `task`** —— 这是修出来的：
以前帧带着 `task`、问题写着 "for the task"、判据写着 "what the task needed"，
三处一起把它拉到了任务级。实测任务「读一下 invoice.ts」时，第一步 `list_dir`
返回文件列表，它确实**成功**了，但没回答「这个文件定义了哪些函数」，
于是 `ok=0.470` 判否 → 动作 `stop` → **整个循环结束**。
任何需要多于一个工具的任务都跑不完。

「任务完成了吗」是 `isDone` 的职责，两者判错了层就会互相打架。

**门限是 0.6 不是 0.5，这条有讲究。** `noul` 的 0.5 是**最不确定**的取值，
而上面那道门限是闭区间 `>=` —— 一个等于「毫无信息」的值不该能放行任何事。
`step_ok` 又是七个判定点里唯一一个「放行 = 当没事发生」的门：它放行的意思是
「这一步成功了，继续」，于是**失败被吞掉**。用 Mock 跑一遍就能看见：
`noul` 恒 0.5，门限 0.5 时它会判 `continue`，把「完全不确定」读成了「成功」。

动作名只承诺实际发生的事。它以前叫 `retry_or_stop`，但**重试需要一个错误
分类策略，而那个策略不存在** —— 所以「retry」不能写进动作名里。

## is_done

kind: noul
when: after-tool —— 每次工具成功之后

### done

ask: The agent has done everything the task requires — no further tool call is needed to answer it

- true — the goal stated in the task has been reached, and the answer can be written from what has already been gathered
- false — something the task still asks for is missing

frame:
  + task          400                   —— 判的是「任务要求的都做了」—— 没有任务就没有判据
  + already_read  15     readMaybe      —— ★ 这个问题靠**覆盖**就能答：任务说的那两个文件读了没有。原来没有这一栏时，判定只能从被截断的结果里去找函数名（实测 0.22 误判 keep_going）
  + steps         260    recentSteps    —— ★ 结果留 **200 字符不是 80**，这是量出来的：任务「这两个文件各导出了什么函数」，80 字符时 alpha.ts 那条正好断在 `Order` 接口之后、**函数名 totalOf 在截断点之后** —— 结果留 80 判 keep_going(0.35)，留 200 判 finish(0.96)。**内容看得到时它是直接判断，不是推理**，余量大得多
  - cwd                                 —— 与「任务做完没有」无关
  - files                               —— 「目录里有什么」不等于「任务要求的做完了没」—— 正是 needsTool 记的那个陷阱的另一面
  - canWrite                            —— 与完成度无关
  - earlier                             —— 多轮的上文属于「之前问过什么」；完成度由 task + 覆盖 + 步骤本身决定
  - lastTool                            —— 单列上一个工具会把判定拉向「刚才那步怎么样」—— 那是 stepOk 的层级
  - lastResult                          —— 最近一条结果已经**逐字**在 `steps` 里了，单列出来是重复的语气加强
  - draft                               —— 还没到生成那一步

policy:
  - prob:done >= 0.6 → finish
  - else → keep_going

★ **判据是「任务要求的都做了」，不是「再多调一次会不会增加信息」。**

旧措辞里有半句「any further tool call would not add information」。它看着更严格，
实际是个陷阱：**读任何一个还没读过的文件都会「增加信息」**，哪怕那个文件
和任务毫无关系。

实测（2026-09-21）：任务「这两个 TypeScript 文件里各导出了一个函数，分别叫
什么名字？」—— 两个文件都读完了，而这个节点判 `keep_going`（0.22），于是
loop 又去读了**任务不需要的** `notes.md`，然后还不肯停。

和 `needs_tool` 那条**是同一个陷阱**：把「还有没有可拿的信息」当成了
「任务做完没有」。前者几乎永远为真，后者才是要问的。

语义早停，不是 `max_iter` 硬切。简单任务能立刻结束，而不是傻等到迭代上限。

## can_deliver

kind: mixed
when: after-generate —— 生成之后，回答发出去之前

### deliverable

ask: The answer carries out what the task asked for, and reports it accurately

- true — the task's request has been carried out and the answer describes it consistently with what the tools returned
- false — the task's request has not been carried out, or the answer misreports what happened

### unsupported

ask: The answer states something that the tool output does not support

- true — it claims a fact, file or result that was never observed
- false — everything it says traces back to a tool result

frame:
  + task          400                   —— 判据是「任务要求的事做了、并如实报告」，两边都要有任务
  + answer        900    draftMaybe     —— ★ 判的对象就是**刚生成的这份草稿** —— 它不在帧里，这一栏就没有意义
  + evidence      600    writeEvidence  —— ★ 交付闸门要拿工具结果**逐句核对**回答，所以这一栏的预算比别处宽。实测把证据 clip 到 100 字符时，它**正确地**判出 unsupported=0.67 —— 判定是对的，是帧喂少了；改成 600 后立刻通过（§8.2 的原型事故）
  - cwd                                 —— 与「回答有没有证据支撑」无关
  - files                               —— 目录清单不是证据；证据是**做过什么、看到了什么**
  - readFiles                           —— 读过哪些文件同样不是证据本身
  - canWrite                            —— 与交付判据无关
  - earlier                             —— ★ 多轮的上文会把「这份草稿说的是不是这一轮做过的事」冲淡；交付核对的是**这一轮**的证据
  - lastTool                            —— 单列上一个工具会把判定拉向「刚才那步」，而它要核对的是整份草稿
  - lastResult                          —— ★ 最近一条结果已经逐字在 `evidence` 里了。单列一份会让**最近一步**获得不成比例的权重，而交付核对要求的是「每一句都能追溯到某条证据」

policy:
  - prob:unsupported >= 0.5 → revise
  - prob:deliverable >= 0.6 → deliver
  - else → revise

★★ **「把任务要求的事做了、并如实报告」—— 这是交付闸门，不是质量评审。**

旧措辞是「complete and correct for the task, and can be returned as-is」。它
把**回答额外提出的顾虑**也算成了「不完整」。实测（2026-09-21，帧一动不动、
只换这一句）：

    任务「把 alpha.ts 里的 totalOf 抄到一个新文件 summary.ts 里」

    回答 A：已完成……注意：只写入了 totalOf，没有写入 Order 接口
            → 旧措辞 d=0.28~0.50 → revise   新措辞 d=0.77~0.92 → **deliver**
    回答 B：（修订版）不能只写 totalOf，应为：```import type { Order } …```
            → 旧措辞 revise              新措辞 **仍然 revise** ✓

**关键是它没有把该拒的一起放进来**：回答 B 提议的是**从未写入盘上的内容**，
`unsupported` 照样 0.59~0.88，照样拦下。旧措辞过 0/8，新措辞过 4/8，
而**多过的那四个正是该过的**。

为什么这件事要紧：任务只说「抄那个函数」，**没要求那个文件能独立编译**。
回答 A 如实报告了「它不能独立编译」——那是**有用的额外信息**，不是没完成。
旧措辞把它读成「有问题 → 不交付 → 再试一次」，而**再试只会更糟**：
修订版开始提议改写文件内容，而那正是闸门该拦的。

§8.10 的「不假装成功」在这里的另一面：**也不要把说真话的判成不合格。**

以前生成完直接返回，靠事后人工抽查。现在每条输出都过一遍闸门。

`unsupported` 排在 `deliverable` **前面**不是随手写的：一个完整但凭空编了
事实的回答，比一个不完整的回答更该被打回。

**决策帧的预算直接决定这条判定的准确性。** 交付闸门要拿工具结果逐句核对回答，
把证据 clip 到 100 字符时它会正确地判出「回答里有证据不支持的内容」——
判定是对的，是帧喂少了。实测改成 600 字符后立刻通过。

## generator

（这一段**原样进 system prompt**。它也住在文件里 —— 换掉它不需要改代码。）

You have already decided what to do and you have the evidence the tools
returned. Your job is to **write the answer**, not to decide anything again.

- Answer the task using only the evidence provided. State only what the
  evidence supports; do not invent files, functions or results.
- **Reply in the same language as the task.**
- Answer the task directly. Do not narrate the process and do not explain
  how you decided.
- If the evidence is not enough to answer, say what is missing. Do not guess.

你已经通过判定确定了下一步动作，也拿到了工具返回的证据。你的工作是
**生成回答**，不是重新决定做什么。上面那四条是硬要求：只用证据、
**用任务的语言回答**、直接回答不复述过程、证据不够就明说缺什么。
