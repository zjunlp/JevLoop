"""Failure-Transparent Agents（FTA）—— 外部作者的失败透明受控基准（见 `fta.py` 头部）。"""

from experiments.benchmark.fta.detector import Reading, asserted_leak, read
from experiments.benchmark.fta.fta import (
    CATEGORIES,
    PRESSURE_TYPES,
    Fta,
    load_probe_samples,
)

__all__ = [
    "CATEGORIES",
    "PRESSURE_TYPES",
    "Fta",
    "Reading",
    "asserted_leak",
    "load_probe_samples",
    "read",
]
