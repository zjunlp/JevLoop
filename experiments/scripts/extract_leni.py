"""把 Leni 发布的原始运行记录摊平成 JSONL —— **这是"适配"，不是"判定"**。

══════════════════════════════════════════════════════════════
  为什么这一层在 Python 侧、而判定那一步在 TS 侧
══════════════════════════════════════════════════════════════

Leni 的数据是 CSV，而且**带超长字段和多行引号**（`intermediate_steps` 里是整条轨迹），
Python 的 `csv` 模块处理它最省事；摊平之后就是一个干净的小 JSONL。

但**判定那一步不能在这里做**。我们的尺子（`claimOf` / `evidenceOf` / `classify`）住在
`src/claim-outcome.ts`，而这条实验的全部意义就是**用我们自己的尺子去量别人的轨迹** ——
在 Python 里再实现一遍，量的就是另一把尺子，而这个仓库对"同一件事两份实现"是一直反对的
（`docs/CODE-STYLE.md` §3.1）。所以：

    experiments/scripts/extract_leni.py   ← 摊位：CSV → JSONL（本文件）
    scripts/reconcile-leni.ts             ← 尺子：JSONL → 混淆矩阵（住在尺子旁边）

产物落在 `experiments/result/_external/`（已加进 `.gitignore`）—— 它是**派生物**，不进 git。

★ 为什么**不能**放 `log/`：那里有一道门（`experiments/scripts/check.py` 的 ①），
要求 `log/` 的每个一级目录**要么是注册过的数据集名、要么在 `_superseded/` 下**。
我第一版就写在 `log/_external/`，于是那道门当场红了 —— **门是对的**：
`log/` 放的是"哪个数据集、哪条臂、哪个 seed 的一次运行"，而这不是一次运行。

══════════════════════════════════════════════════════════════
  两份数据各自的用途（★ 它们的对口感差得很远）
══════════════════════════════════════════════════════════════

**`bullshitbench`（对口）** —— 100 道**伪造前提**的题，正确答案是「质疑这个前提」。
Leni 用三个模型组成裁判团打了 0–2 分（`panel_score ≥ 1.5` 算正确拒绝）。
所以它给的是：**别人的真实回答 + 别人的独立金标**。这一份能直接量两件事：

    ① 我们的尺子判「有没有质疑」，和三个人类-facing 裁判团判的一不一致；
    ② 在**没有一次模型调用**的前提下，外部数据上的过度声称率是多少。

**`gaia`（不对口，但值得记下来）** —— ★ 实测发现我们的尺子**在这份数据上不适用**：
GAIA 的最终答案往往就是一个值（`0`、`Time-Parking 2: Parallel Universe`），
里面**没有"我完成了任务"这类措辞**，而 `claimOf` 读的正是那类措辞。
所以它在 GAIA 上基本读不出"声称"，只会读出一堆沉默。
这正是"我们的尺子只覆盖动作型任务的完成声明、不覆盖纯问答的答案断言"这个边界 ——
**边界是要报的**，把它当失败藏起来才是错的。这里照样摊平、照样跑，但结论按边界报。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

# ★ CSV 的默认字段上限是 131072，而轨迹字段远超它 —— 不抬会**直接抛错**
csv.field_size_limit(10**9)

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "experiments" / "dataset" / "leni" / "data"
OUT = REPO / "experiments" / "result" / "_external"


def _steps(raw: str) -> list[dict[str, str]]:
    """把 `intermediate_steps` 摊成 `[{tool, input, result}]`。

    ★ 形状**不统一**（实测三种）：`{steps:{steps:[…]}}`、`{steps:[…]}`、`[…]`。
      只认一种的话会静默丢掉一部分样本 —— 而"丢掉多少"必须能报出来，
      所以这里返回空表时，调用方记一条 `unparsed`。
    """
    try:
        d = json.loads(raw) if isinstance(raw, str) and raw else raw
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(d, dict):
        d = d.get("steps")
        if isinstance(d, dict):
            d = d.get("steps")
    if not isinstance(d, list):
        return []
    out: list[dict[str, str]] = []
    for s in d:
        if not isinstance(s, dict):
            continue
        a = s.get("action") if isinstance(s.get("action"), dict) else {}
        out.append(
            {
                "tool": str(a.get("tool") or a.get("type") or ""),
                "input": json.dumps(a.get("toolInput"), ensure_ascii=False)
                if a.get("toolInput") is not None
                else "",
                "result": str(s.get("observation") or ""),
            }
        )
    return out


def _response(raw: str) -> str:
    """从 `leniq_answer` 里取出**整段回答正文**。

    ★★ 第一版这里读错了字段，值得记下来：我用的是 `model_final_answer`，
      它的中位长度是 **6 个字符**（就是被抽出来的那个值，如 `0`、
      `Time-Parking 2: Parallel Universe`），于是"犹豫/做不到"这类痕迹
      **一条也认不出来**（0/210）—— 我当时把那个 0 读成了"我们的尺子在这份
      数据上不适用"，其实是我**读了一个不含这些痕迹的字段**。

      正文在 `leniq_answer` 里，是一个 JSON：`{"answer": "...全文...", "file_ids": []}`，
      中位 **663 字符**。换到它之后，回答模式（见 `scripts/reconcile-leni.ts`）
      才量得出东西来。

      **教训与 §9 那条一样：先怀疑仪器，再怀疑数据。**
    """
    if not raw:
        return ""
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw
    if isinstance(d, dict):
        for k in ("answer", "text", "content", "response"):
            v = d.get(k)
            if isinstance(v, str) and v.strip():
                return v
        return ""
    return raw if isinstance(raw, str) else ""


def extract_bullshit() -> Path:
    """BullshitBench 的 500 条运行 + 100 道题（题目用于带上 `technique`）。"""
    runs = list(csv.DictReader((DATA / "eval_runs_bullshit.csv").open(encoding="utf-8", newline="")))
    tasks = {t["id"]: t for t in csv.DictReader((DATA / "bullshitbench_tasks.csv").open(encoding="utf-8", newline=""))}
    out = OUT / "leni_bullshit.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in runs:
            t = tasks.get(r.get("task_id", ""), {})
            rec = {
                "run_id": r.get("id"),
                "task_id": r.get("task_id"),
                "bench_task_id": r.get("bench_task_id"),
                "question": t.get("question", ""),
                "technique": t.get("technique", ""),
                "domain_group": t.get("domain_group", ""),
                "answer": r.get("leniq_answer", ""),
                "steps": _steps(r.get("intermediate_steps", "")),
                # ★ 别人的金标：三裁判团 0–2 分，≥1.5 算"正确地拒绝了"
                "panel_score": r.get("panel_score", ""),
                "bucket": r.get("bucket", ""),
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out


def extract_gaia(*, scored_only: bool = True) -> Path:
    """GAIA 的 803 条运行（默认只留 218 条有 `is_correct` 的）。"""
    runs = list(csv.DictReader((DATA / "eval_runs_gaia.csv").open(encoding="utf-8", newline="")))
    tasks = {t["id"]: t for t in csv.DictReader((DATA / "gaia_tasks.csv").open(encoding="utf-8", newline=""))}
    out = OUT / "leni_gaia.jsonl"
    n_steps_unparsed = 0
    with out.open("w", encoding="utf-8") as fh:
        for r in runs:
            if scored_only and not (r.get("is_correct") or "").strip():
                continue
            t = tasks.get(r.get("task_id", ""), {})
            steps = _steps(r.get("intermediate_steps", ""))
            if not steps:
                n_steps_unparsed += 1
            fh.write(
                json.dumps(
                    {
                        "run_id": r.get("id"),
                        "task_id": r.get("task_id"),
                        "question": t.get("question", ""),
                        "gold_answer": t.get("final_answer", ""),
                        "level": t.get("level", ""),
                        # ★ 抽出来的那个值（短）
                        "answer": (r.get("model_final_answer") or "").strip(),
                        # ★ 整段正文（含推理与可能的犹豫）—— 回答模式读的是它
                        "response": _response(r.get("leniq_answer", "")).strip(),
                        "steps": steps,
                        "is_correct": (r.get("is_correct") or "").strip(),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    if n_steps_unparsed:
        print(f"  ⚠️ {n_steps_unparsed} 条轨迹解不出步骤（形状没见过的会静默丢，这里报出来）", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="把 Leni 的原始 CSV 摊平成 JSONL")
    ap.add_argument("--which", default="all", choices=["all", "bullshit", "gaia"])
    ap.add_argument("--gaia-all", action="store_true", help="GAIA 连没有 is_correct 的也导出")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    if a.which in ("all", "bullshit"):
        p = extract_bullshit()
        print(f"写了 {p}（{sum(1 for _ in p.open(encoding='utf-8'))} 条）")
    if a.which in ("all", "gaia"):
        p = extract_gaia(scored_only=not a.gaia_all)
        print(f"写了 {p}（{sum(1 for _ in p.open(encoding='utf-8'))} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
