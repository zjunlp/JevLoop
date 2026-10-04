"""`log/<数据集>/<臂>/<run>/` → **一张分层报告**，包括"这次控制是谁做的"。

跑法（在 `JevLoop/` 下）::

    python3 -m experiments.scripts.run_diagnostics experiments/log/alfworld/react-typed/<run>
    python3 -m experiments.scripts.run_diagnostics --pair <旧run> <新run>

## 为什么要有它

`summarize.py` 出的是**跨 run 的总表**（一个格子一个数），而报告里需要的是
**一次 run 内部的构成** —— 尤其是下面这三样，它们此前只能靠临时写脚本捞：

1. **`判定占比`**（`docs/METRIC-CATALOG.md` Layer 5b）—— `source="judge"` 的行占多少。
   这是"控制不是生成"那根轴的头条数，而它在加 `source` 那一列之前**根本读不出来**。
2. **兜底构成** —— 哪些是"答了但不够果断"（`*_below_bar`），
   哪些是"压根没答"（`FALLBACK_POLICY` 的名字）。**两者的补救方向相反。**
3. **动作重复** —— 同一个命令在一道题里被挑了多少次。
   `examine cabinet 1` 一轮 56 次那类症状，只有在这里看得见。

★ `--pair` 做**逐题配对**：两个 run 只有同一批 `task_id` 时才算对，
  并打印两边都做对 / 都做错 / 各自独有的**计数**。
  ⚠️ 它**不算 p 值** —— n=20 的 run-to-run 标准差实测 1.30 题（`docs/ALFWORLD-VARIANCE.md`），
  单次 run 之间的差**读不出结论**。要主张差异必须用重复批次的多数票，见
  `docs/ALFWORLD-LADDER-RESULT.md` 的做法。

## 它不做什么

**不改分数、不重算判分。** 原生分直接读 `results.jsonl` 里已经写好的那一栏 ——
按 `AGENTS.md` 那条硬约束，benchmark 自己的判分逻辑一个字都不许动，
所以这个脚本是**只读的观察工具**，不参与打分。
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any

#: 控制流出口（Layer 0）。**必须先看它再看分数** —— 一个 0/20 可能是因为
#: 判官不会做，也可能是因为根本没跑起来，这两件事在总分上长得一样。
STOP_ORDER = ("delivered", "gate_blocked", "step_exhausted", "parse_failure",
              "backend_error", "env_unavailable", "error")


def _rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def decisions(run: Path) -> list[dict[str, Any]]:
    """所有判定行，按发生顺序摊平。"""
    return [d for e in _rows(run / "events.jsonl")
            if e.get("type") == "decision_batch"
            for d in e.get("decisions", [])]


def tool_calls(run: Path) -> list[dict[str, Any]]:
    return [e for e in _rows(run / "events.jsonl") if e.get("type") == "tool"]


def _arg_text(call: dict[str, Any]) -> str:
    """一次工具调用的**可读命令** —— `ToolEvent.arguments` 渲染出来。

    ⚠️ 字段叫 `arguments`（复数），**不是** `input`。
      第一版写了 `input`，于是每一行都渲染成 `'None'` —— 而重复计数
      在那种情况下**看起来完全正常**（每题最大重复 = 1，很"健康"）。
      ★ 这正是 §8.10 那一类错：一个错的数和一个对的数在表面上没有区别。

    ⚠️ 值是 dict（ALFWorld 的 `{"command": "go to safe 1"}`）。
      **别 `str(dict)`** —— 那会带上花括号和引号，于是"同一个命令"看起来有
      两种写法，重复计数同样会失真（`frame.py::render_tool_input` 修的是同一个病）。
    """
    args = call.get("arguments")
    if isinstance(args, dict):
        vals = [str(v) for v in args.values() if v not in (None, "")]
        return " ".join(vals) if vals else str(call.get("name") or "?")
    return str(args if args is not None else call.get("name") or "?")


THRESHOLDS = {"needsTool": 0.5, "stepOk": 0.6, "isDone": 0.6, "needs_auth": 0.5,
              "deliverable": 0.6, "unsupported": 0.5, "pickInput": 0.5, "pickTool": 0.6}
RECORD_CODES = {"candidate_already_done", "field_missing", "options_over_budget",
                "request_over_budget", "too_many_questions"}


def _is_record(d: dict) -> bool:
    """记录行不是判定。⚠️ **两种都要认**:新 run 的 `::violation` 后缀,
    和旧 run 里那个括号答案 —— 只认前者会让旧日志的统计被污染(实测差 43 倍)。"""
    return (str(d.get("node", "")).endswith("::violation")
            or str(d.get("answer")) in {f"({c})" for c in RECORD_CODES})


def _decision_outcome(d: dict) -> str:
    """这道题**决定**了什么。★ 不是原始数值 —— `noul` 看的是过没过门限。"""
    node, ans, conf = str(d.get("node")), str(d.get("answer")), float(d.get("confidence") or 0)
    if node in ("pickInput", "pickTool", "risk"):
        return ans
    if node in ("deliverable::confirm", "deliverable::object", "risk_confirm"):
        return ans
    p = conf if conf >= 0.5 else 1 - conf          # noul: top()=max(p,1-p)
    return f"true={p >= THRESHOLDS.get(node, 0.5)}"


def _approx_state_key(node: str, task: str, step: int, tools: list[dict]) -> str:
    """**近似**状态键 —— 从 `tool` 事件重建,只用于旧日志。

    每个判定点看的证据不同,所以键也不同(这正是"规范"的意思):
      · `risk` / `needs_auth`  看**这一调**(本步要执行的那个动作)
      · `stepOk` / `isDone`    看**上一步**(执行完了什么、返回了什么)
      · 动作选择类             看**到目前为止**(做过什么 + 上一次观测)
    """
    def rendered(t: dict) -> str:
        args = t.get("arguments") or {}
        vals = " ".join(str(v) for v in args.values()) if isinstance(args, dict) else str(args)
        return " ".join(f"{t.get('name')} {vals}".split())

    def obs(t: dict) -> str:
        return " ".join(str(t.get("observation") or "").split())[:200]

    # ★★ **`task` 必须在键里。** 第一版漏了它,于是两个不同任务里
    #    「同样的历史 + 同样的观测」被算成同一个状态 —— 重复率算出 753%(分母还错着)。
    #    ALFWorld 的任务描述就是状态的一部分。
    t0 = f"{node}|{task}"
    if node in ("risk", "needs_auth"):
        here = [t for t in tools if t["step"] == step]
        return f"{t0}|{'|'.join(sorted(rendered(t) for t in here))}"
    if node in ("stepOk", "isDone"):
        prev = [t for t in tools if t["step"] == step - 1]
        return f"{t0}|{'|'.join(f'{rendered(t)}->{obs(t)}' for t in prev)}"
    if node in ("needsTool", "pickTool", "pickInput"):
        done = sorted(rendered(t) for t in tools if t["step"] < step)
        last = [t for t in tools if t["step"] == step - 1]
        return f"{t0}|{','.join(done)}|{obs(last[0]) if last else ''}"
    return ""      # 交付闸门那一类:草稿不在日志里,旧 run 算不出来


def state_key_report(run: Path) -> dict:
    """同一批判定行,两个键各算一遍:重复率、决定翻转率、翻转暴露。"""
    rows = _rows(run / "events.jsonl")
    dec = [d for e in rows if e.get("type") == "decision_batch"
           for d in e.get("decisions", [])]
    real = [d for d in dec if not _is_record(d)]
    tools_by_task: dict[str, list[dict]] = collections.defaultdict(list)
    for e in rows:
        if e.get("type") == "tool":
            tools_by_task[str(e.get("task_id"))].append(e)
    for v in tools_by_task.values():
        v.sort(key=lambda t: t["step"])
    tasks = len({d["task_id"] for d in dec}) or 1

    out: dict[str, dict] = {}
    for label in ("ledger", "digest", "approx"):
        groups: dict[tuple, list[str]] = collections.defaultdict(list)
        rows_with_key = 0
        for d in real:
            if label == "ledger":
                k = str(d.get("state_key") or "")
                if not k:
                    continue
            elif label == "digest":
                k = str(d.get("request_digest") or "")
            else:
                k = _approx_state_key(str(d["node"]), str(d["task_id"]),
                                      int(d["step"]),
                                      tools_by_task.get(str(d["task_id"]), []))
                if not k:
                    continue
            rows_with_key += 1
            groups[(d["node"], k)].append(_decision_outcome(d))
        judged = [d for d in real if d.get("source") == "judge"]
        rep = {k: v for k, v in groups.items() if len(v) >= 2}
        n_rep = sum(len(v) for v in rep.values())
        flips = 0
        for v in rep.values():
            mode = collections.Counter(v).most_common(1)[0][0]
            flips += sum(1 for y in v if y != mode)
        # ★ 分母是**拿到了键的行数**,不是组数 —— 第一版写成组数,
        #   于是 1461/194 算成 753%。一个 753% 的比率本该当场露馅,而它没有。
        out[label] = {
            "rows": rows_with_key,
            "groups": len(groups),
            "in_repeats": n_rep,
            "flips": flips,
            "repeat_rate": n_rep / rows_with_key if rows_with_key else 0.0,
            "entropy": flips / n_rep if n_rep else 0.0,
            "exposure": flips / tasks,
            "judge_rows": len(judged),
        }
    return out


#: 每个判定点的键**缺了什么** —— 这一列是人写的判断,但它是读那张表的关键:
#: 翻转率高的节点,先问"键完整吗",再问"判官稳不稳"。
#: ★ 不写这一列的话,`pickInput` 的 57.3% 会被读成"判官不稳定",而它是键的缺陷。
KEY_GAPS = {
    "stepOk": "", "isDone": "",
    "risk": "不含 base_risk(但它本来就是规则给的)",
    "needs_auth": "",
    "needsTool": "不含候选集/工具说明",
    "pickTool": "不含候选集",
    "pickInput": "★ 不含候选集 —— 而它的题就是「从候选里挑一个」",
    "deliverable": "★ 旧日志没有草稿 → 键算不出来",
    "unsupported": "★ 旧日志没有草稿 → 键算不出来",
}


def by_node_report(run: Path, label: str) -> None:
    """逐节点的重复率 / 翻转率 / 键缺口 —— **论文里那张表就是这个形状。**

    ★ 必须逐节点看。合起来看会得到"有效控制熵 8.8%"这种数,而它把
      "四个节点 0 翻转" 和 "一个节点 118 翻转" 平均成了一个中间值 ——
      **一个把两件不同的事混起来的数,读不出任何东西。**
    """
    rows = _rows(run / "events.jsonl")
    dec = [d for e in rows if e.get("type") == "decision_batch"
           for d in e.get("decisions", [])]
    real = [d for d in dec if not _is_record(d)]
    tools_by_task: dict[str, list[dict]] = collections.defaultdict(list)
    for e in rows:
        if e.get("type") == "tool":
            tools_by_task[str(e.get("task_id"))].append(e)
    for v in tools_by_task.values():
        v.sort(key=lambda t: t["step"])

    def key_of(d: dict) -> str:
        if label == "ledger":
            return str(d.get("state_key") or "")
        if label == "digest":
            return str(d.get("request_digest") or "")
        return _approx_state_key(str(d["node"]), str(d["task_id"]), int(d["step"]),
                                 tools_by_task.get(str(d["task_id"]), []))

    print(f"\n逐节点（键 = {label}）")
    print(f"  {'节点':<22}{'行':>5}{'不同状态':>9}{'重复率':>8}{'翻转':>6}{'有效控制熵':>11}  键缺什么")
    for node in sorted({d["node"] for d in real}):
        g: dict[str, list[str]] = collections.defaultdict(list)
        for d in real:
            if d["node"] != node:
                continue
            k = key_of(d)
            if k:
                g[k].append(_decision_outcome(d))
        n = sum(len(v) for v in g.values())
        if not n:
            continue
        rep = {k: v for k, v in g.items() if len(v) >= 2}
        nr = sum(len(v) for v in rep.values())
        fl = sum(sum(1 for y in v if y != collections.Counter(v).most_common(1)[0][0])
                 for v in rep.values())
        print(f"  {node:<22}{n:>5}{len(g):>9}{nr/n:>8.0%}{fl:>6}"
              f"{(fl/nr if nr else 0):>11.1%}  {KEY_GAPS.get(node, '?')}")


def print_state_keys(run: Path) -> None:
    rep = state_key_report(run)
    print(f"状态键对比  {run.name}")
    print(f"  {'键':<12}{'可算行数':>8}{'不同状态':>9}{'落在重复状态':>13}{'重复率':>8}{'决定翻转':>9}{'有效控制熵':>11}{'暴露/题':>9}")
    names = {"ledger": "账上键(规范)", "digest": "请求指纹", "approx": "近似键(旧日志)"}
    for label in ("ledger", "digest", "approx"):
        r = rep[label]
        if not r["rows"]:
            print(f"  {names[label]:<12}{'—':>8}   （这个 run 没有这一栏）")
            continue
        print(f"  {names[label]:<12}{r['rows']:>8}{r['groups']:>9}{r['in_repeats']:>13}"
              f"{r['repeat_rate']:>8.0%}{r['flips']:>9}{r['entropy']:>11.1%}{r['exposure']:>9.2f}")
    d, a = rep["digest"], rep["approx"]
    if d["rows"] and a["rows"]:
        print(f"  ⇒ 两个键的重复率差 **{a['repeat_rate'] - d['repeat_rate']:+.0%}**"
              f"（近似键把多少被渲染差异掩盖的状态算了回来）")
    # ★ 逐节点是**必须**的:合起来那个数会把"四个节点 0 翻转"和
    #   "一个节点 118 翻转"平均成中间值,而那种数读不出任何东西。
    for label in ("ledger", "digest", "approx"):
        if rep[label]["rows"]:
            by_node_report(run, label)
            break


def report(run: Path, *, top_repeats: int = 5) -> dict[str, Any]:
    """一次 run 的分层构成。**纯统计，不做任何判断。**"""
    results = _rows(run / "results.jsonl")
    dec = decisions(run)
    calls = tool_calls(run)

    by_stop: collections.Counter[str] = collections.Counter()
    for r in results:
        by_stop[str(r.get("stop_reason") or "?")] += 1

    # ★★★ **记录行必须先剔掉。** `::violation`(新 run)和括号答案(旧 run)是
    #   **我们自己的自查记录**,不是判定。不剔的后果实测过两次:
    #   一次让 `pickTool` 的节点计数 240→436,一次让"有效控制熵"从 0.1% 变 30.3%(43 倍)。
    #   ⚠️ 这个函数和 `state_key_report` 必须**用同一个过滤器** ——
    #     两条路各写一份过滤就是"同一个概念两处实现",迟早分叉。
    dec = [d for d in dec if not _is_record(d)]
    by_source = collections.Counter(str(d.get("source") or "?") for d in dec)
    by_fallback = collections.Counter(str(d.get("fallback")) for d in dec if d.get("fallback"))
    by_node = collections.Counter(str(d.get("node")) for d in dec)

    # ★ 退出口被选中几次 —— 我们加的 `none_of_the_available_actions`。
    #   它被选中 = 判官**有了一个以前没有的答案**。选不中 = 那道理由还在，
    #   只是这次没撞上（不是"退出口没用"，这两件事要分开读）。
    escapes = sum(1 for d in dec if str(d.get("answer", "")).startswith("none_of_the_"))

    # ★ 动作重复：按 task 分组，取每题里**同一个命令**的最大出现次数。
    per_task: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    for c in calls:
        per_task[str(c.get("task_id", "?"))][_arg_text(c)] += 1
    worst = sorted(((max(c.values()) if c else 0, t, c.most_common(1)[0][0])
                    for t, c in per_task.items()), reverse=True)

    # `decision_spec` 从 meta.json 读 —— 它不在 results.jsonl 的顶层
    spec = ""
    if results:
        spec = str((results[0].get("meta") or {}).get("decision_spec") or "")

    # ★★★ **规则 ↔ 判官 的联表** —— 这是规则优先那一版新拿到的数
    #   （`docs/GATES-RULES-FIRST.md`）。判官的立场**不另记一行**：
    #   它就在那道题自己那一行里，和同一 (task, step) 的**规则行**联起来
    #   才是"规则拦对了没有"的证据。
    #
    #   ⚠️ 联表的键是 `(task_id, step)`：规则行和确认题是**同一步**问的，
    #     而"一条判定只记一行"保证了两边各只有一行。
    by_step: dict[tuple[str, int], dict[str, str]] = collections.defaultdict(dict)
    for d in dec:
        key = (str(d.get("task_id")), int(d.get("step") or 0))
        by_step[key][str(d.get("node"))] = str(d.get("answer", ""))

    cert_hits = collections.Counter()
    confirm_stances = collections.Counter()
    objections = collections.Counter()
    risk_stances = collections.Counter()
    for d in dec:
        node, ans = str(d.get("node")), str(d.get("answer", ""))
        if node in ("deliverable::grounding", "deliverable::empty",
                    "deliverable::no_evidence"):
            cert_hits[node] += 1
        elif node == "deliverable::confirm":
            confirm_stances[ans] += 1
        elif node == "deliverable::object":
            objections[ans] += 1
        elif node == "risk_confirm":
            risk_stances[ans] += 1
    # 规则拦下的那些步里，判官**否定了**几次 —— 分组是同一步上的两行
    judge_disagreements = 0
    for _key, per in by_step.items():
        if any(n in per for n in ("deliverable::grounding", "deliverable::empty",
                                  "deliverable::no_evidence")) \
                and per.get("deliverable::confirm") == "does_not_hold":
            judge_disagreements += 1
    n_certs = sum(cert_hits.values())

    scored = [r for r in results if r.get("correct") is not None]
    n = len(scored)
    n_correct = sum(1 for r in scored if r.get("correct"))
    return {
        "run": str(run),
        "run_id": (results[0].get("run_id") if results else run.name),
        "decision_spec": spec,
        "tasks": n,
        "native_correct": n_correct,
        "native": f"{n_correct}/{n}",
        "stop_reasons": dict(by_stop),
        "decision_rows": len(dec),
        "sources": dict(by_source),
        # 判定占比 —— Layer 5b 的头条数。分母是**所有**判定行。
        "judge_share": (by_source.get("judge", 0) / len(dec)) if dec else 0.0,
        "fallbacks": dict(by_fallback),
        "nodes": dict(by_node),
        "escape_chosen": escapes,
        "escape_rate_of_pickInput": (
            escapes / by_node["pickInput"] if by_node.get("pickInput") else 0.0
        ),
        # ★ 规则优先那一版的四个数（判官产生裁决那一版全是 0）
        "certificates": dict(cert_hits),
        "confirm_stances": dict(confirm_stances),
        "judge_disagreements": judge_disagreements,
        "judge_objections": dict(objections),
        "risk_stances": dict(risk_stances),
        "tool_calls": len(calls),
        "worst_repeat": [{"task": t, "same_command": k, "times": c}
                         for c, t, k in worst[:top_repeats]],
        "repeat_ge_10": sum(1 for c, _t, _k in worst if c >= 10),
    }


def print_report(rep: dict[str, Any]) -> None:
    print(f"run  {rep['run_id']}")
    if rep["decision_spec"]:
        # ★ 「同一个方法吗」的那一栏 —— 见 `docs/MU-CONFLICT.md` 第 6 行。
        #   空 = 这一臂没有类型化判定。
        print(f"  判定规格 {rep['decision_spec']}")
    print(f"  原生  {rep['native']}      出口  {rep['stop_reasons']}")
    print(f"  判定行 {rep['decision_rows']}   "
          f"判定占比 {rep['judge_share']:.3f}   {rep['sources']}")
    if rep["fallbacks"]:
        print(f"  兜底  {rep['fallbacks']}")
    print(f"  节点  {rep['nodes']}")
    print(f"  退出口被选中 {rep['escape_chosen']} 次"
          f"（占 pickInput 的 {rep['escape_rate_of_pickInput']:.3f}）")
    if rep["certificates"] or rep["confirm_stances"] or rep["risk_stances"]:
        # ★★ 规则优先那一版的账。三个数分开，因为它们回答三个不同的问题：
        #   证书 = 规则**拦**了几次；立场 = 判官对着规则的结论说了什么；
        #   反驳 = 判官对"规则放行"提出的问题（它唯一能产生结果的权力）。
        n = sum(rep["certificates"].values())
        print(f"  规则证书 {n} 次 {rep['certificates']}")
        if rep["confirm_stances"]:
            print(f"    判官确认 {rep['confirm_stances']}"
                  f"   其中否定规则 {rep['judge_disagreements']} 次"
                  f"（**否定不放行** —— 那是规则质量的证据）")
        if rep["risk_stances"]:
            print(f"    风险档位确认 {rep['risk_stances']}"
                  f"（只抬不降：`too_low` 抬档，`too_high` 不降）")
    # ★ 反驳那一行**不能**挂在上面那个条件里:一个只有 `deliverable::object`
    #   的 run(比如 `react-termination`)会因此**一行都不打** —— 而它恰恰
    #   是"判官唯一能产生结果的权力",最该被看见。
    if rep["judge_objections"]:
        print(f"  判官反驳（规则放行时）{rep['judge_objections']}")
    print(f"  工具调用 {rep['tool_calls']}   同一命令重复 ≥10 次的题 {rep['repeat_ge_10']}")
    for w in rep["worst_repeat"]:
        print(f"    {w['times']:>3}×  {w['same_command'][:48]!r}  in {w['task'][:40]}")


# ═══════════════════════════════════════════════════════════
# 规范状态键 vs 请求指纹 —— **两个键算出来的数差多少**
# ═══════════════════════════════════════════════════════════
#
# ★★ 为什么必须两个都算:`request_digest` 覆盖的是帧的**渲染文本**,里面混着
#   跟判定无关的东西(截断提示、字段顺序)。所以「状态重复率」用它算会被**低估**,
#   而"有效控制熵"的分母偏小。
#
# ⚠️ **旧 run 里没有字段值** —— 判定行只存了指纹。所以对旧日志只能用
#   **近似键**:从 `tool` 事件重建"这一步的输入和观测"。这和真键不是一回事,
#   差多少本身就是要报的量。
#
# ★ 而 `state_key` 那一栏(2026-10-04 起)让**新 run 可以精确重算**。
#   所以这个函数对两种日志都工作:有 `state_key` 就用它,没有就退回近似键。

def pair(old: Path, new: Path) -> None:
    """逐题配对。**只报计数，不报显著性** —— 理由见模块头。"""
    o = {r["task_id"]: r for r in _rows(old / "results.jsonl")}
    n = {r["task_id"]: r for r in _rows(new / "results.jsonl")}
    shared = sorted(set(o) & set(n))
    if not shared:
        print("两个 run 没有共同 task_id —— 不是同一批题，配对无意义")
        return
    both = sum(1 for t in shared if o[t].get("correct") and n[t].get("correct"))
    only_o = sum(1 for t in shared if o[t].get("correct") and not n[t].get("correct"))
    only_n = sum(1 for t in shared if n[t].get("correct") and not o[t].get("correct"))
    neither = sum(1 for t in shared if not o[t].get("correct") and not n[t].get("correct"))
    print(f"配对 {len(shared)} 题：旧 {sum(1 for t in shared if o[t].get('correct'))}"
          f"/{len(shared)}  新 {sum(1 for t in shared if n[t].get('correct'))}/{len(shared)}")
    print(f"  都对 {both}   都错 {neither}   只有旧对 {only_o}   只有新对 {only_n}")

    # ★★ **出口分布也要配对看。** 分数那一格是噪声最大的（±1.30 题 / n=20），
    #   而 `declined`（判官弃答）和 `delivered`（真的交出去了）**不是**同一种噪声：
    #   逃逸口那个改动要影响的第一件事就是这里，它比总分灵敏得多。
    for label, rs in (("旧", o), ("新", n)):
        c = collections.Counter(str(rs[t].get("stop_reason") or "?") for t in shared)
        print(f"  {label} 出口  {dict(c)}")
    print("  ⚠️ 分数那两格**不是**显著性检验。n=20 的 run-to-run 标准差是 1.30 题，"
          "单次 run 的差读不出结论（用重复批次的多数票，见 "
          "docs/ALFWORLD-LADDER-RESULT.md）。出口分布比分数稳定，但也不是没有噪声。")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("run", nargs="*", type=Path, help="run 目录（可给多个）")
    ap.add_argument("--pair", nargs=2, type=Path, default=None,
                    metavar=("OLD", "NEW"), help="逐题配对两个 run")
    ap.add_argument("--keys", action="store_true",
                    help="两个状态键各算一遍,看键的选择改变多少结论")
    args = ap.parse_args()

    if args.keys:
        for run in args.run:
            print_state_keys(run)
        return
    if args.pair:
        pair(*args.pair)
        return
    if not args.run:
        ap.error("给一个 run 目录，或者 --pair OLD NEW")
    for i, run in enumerate(args.run):
        if i:
            print()
        print_report(report(run))


if __name__ == "__main__":
    main()
