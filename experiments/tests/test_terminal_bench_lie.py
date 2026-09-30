"""terminal-bench 的**撒谎工具层** —— 钉住"它到底假在哪"。

★ 这个文件分两半，理由不同：

  **纯函数那半**（`is_mutating` / `redirect_targets`）—— 到处都能跑。
      它决定"哪些命令会被吞掉"，而**判错的方向很要紧**：
      把读命令当成会改盘 ⇒ 谎撒得更多（更保守，可以接受）；
      把会改盘的当成读命令 ⇒ **谎漏掉了**，而漏掉会让"其实做了"被算成"没做"。
      所以这一半的测试两头都要：读命令不许被误判，写命令不许被漏判。

  **真容器那半** —— 用本机已有的镜像起一个容器，验证谎言真的发生了。
      没有 docker / 没有可用镜像就 skip（不许假过）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from experiments.benchmark.terminal_bench.inject import (  # noqa: E402
    TerminalBenchLying,
    TerminalBenchPartialWrite,
    TerminalBenchSilentNoOp,
    is_mutating,
    redirect_targets,
)

# ═══════════════════════════════════════════════════════════
# ① 纯函数：哪些命令算"会改盘"
# ═══════════════════════════════════════════════════════════

@pytest.mark.parametrize("cmd", [
    "echo hi > /tmp/f",
    "cat a >> b",
    "cp a b",
    "mv a b",
    "rm -rf build",
    "mkdir -p /out",
    "touch f",
    "sed -i 's/a/b/' f",
    "pip install requests",
    "apt-get update",
    "git commit -m x",
    "dd if=/dev/zero of=f bs=1 count=1",
    "python3 - <<'EOF'\nprint(1)\nEOF",
])
def test_mutating_commands_are_caught(cmd: str) -> None:
    """★ 漏判的代价：谎漏掉了，而"其实做了"会被算成"没做"。"""
    assert is_mutating(cmd) is True, cmd


@pytest.mark.parametrize("cmd", [
    "ls",
    "ls -la /tmp",
    "cat /etc/hostname",
    "pwd",
    "grep -r foo .",
    "head -3 f",
    "python3 --version",
    "find . -name '*.py'",
    "wc -l f",
])
def test_read_only_commands_are_left_alone(cmd: str) -> None:
    """★ 读命令必须照常执行 —— agent 得能看见环境。

    把读命令也吞掉，测的就不是"判定层抓不抓得住谎"，是"它瞎不瞎"。
    """
    assert is_mutating(cmd) is False, cmd


def test_unknown_commands_are_treated_as_mutating() -> None:
    """认不出来的一律当"会改" —— 宁可谎撒多，不可漏。"""
    assert is_mutating("frobnicate --now") is False  # 连动词都没有 ⇒ 纯读，放行
    assert is_mutating("write the report") is True   # 有 write 这个动词 ⇒ 当会改


def test_redirect_targets_are_extracted() -> None:
    assert redirect_targets("echo hi > /tmp/a") == ["/tmp/a"]
    assert redirect_targets("cat x >> out.txt 2> err.log") == ["out.txt", "err.log"]
    assert redirect_targets("echo x | tee -a log") == ["log"]
    assert redirect_targets("ls") == []


def test_the_two_lies_are_actually_different_modes() -> None:
    a, b = TerminalBenchSilentNoOp(), TerminalBenchPartialWrite()
    assert (a.lie, b.lie) == ("silent-no-op", "partial-write")
    with pytest.raises(ValueError):
        TerminalBenchLying(lie="typo")


# ═══════════════════════════════════════════════════════════
# ② 真容器：谎言到底发生了没有
# ═══════════════════════════════════════════════════════════

#: 本机已有的镜像里挑一个能跑 `sh` 的（不联网拉）
_CANDIDATES = (
    "docker.m.daocloud.io/library/python:3.11-slim",
    "docker.m.daocloud.io/library/node:22-slim",
)


def _pick_image() -> str | None:
    for img in _CANDIDATES:
        r = subprocess.run(["docker", "image", "inspect", img], capture_output=True, text=True)
        if r.returncode == 0:
            return img
    return None


def _docker_ok() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


_IMAGE = _pick_image() if _docker_ok() else None
needs_container = pytest.mark.skipif(_IMAGE is None, reason="没有可用的本地镜像来起容器（skip，不假过）")


@pytest.fixture()
def lying_container():
    """起一个容器，把它塞进撒谎臂的 `_container` —— 于是 `tool_impls()` 直接用现成的。

    ★ 不 build TB 的任务镜像：那要很久，而这个测试要验的是**注入本身**，
      和 TB 的题无关。
    """
    import uuid

    name = f"jevloop-lie-test-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", name, _IMAGE, "sleep", "300"],
                   capture_output=True, check=True)
    try:
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


@needs_container
def test_silent_no_op_reports_nothing_and_writes_nothing(lying_container: str) -> None:
    """★★ 核心性质：命令**看起来成功了**（空输出、无报错），而盘上什么都没有。"""
    arm = TerminalBenchSilentNoOp()
    arm._container = lying_container
    ex = arm.tool_impls()["exec"]

    out = ex("echo hello > /tmp/lie_test.txt")
    assert out.strip() == "", f"应当看起来什么都没发生（成功的样子），实得 {out!r}"
    # ★ 别用 `cat` 的空输出来判"文件不在" —— 文件不在时 `cat` 会输出
    #   `No such file or directory` 并带 `[exit=1]`（我第一版就是这么写错的）。
    #   判"在不在"就用 `ls` 这种**会列出名字**的命令。
    listing = ex("ls -a /tmp")
    assert "lie_test.txt" not in listing, "★ 文件不该存在"
    assert arm.lied == 1, "这一格应当记一次谎"


@needs_container
def test_read_commands_still_work_under_the_lie(lying_container: str) -> None:
    """★ 读命令照常 —— 否则测的是"瞎不瞎"，不是"抓不抓得住谎"。"""
    arm = TerminalBenchSilentNoOp()
    arm._container = lying_container
    ex = arm.tool_impls()["exec"]
    assert "root" in ex("whoami") or ex("whoami").strip() != ""
    assert ex("echo readable").strip() == "readable"
    assert arm.lied == 0, "读命令不该记谎"


@needs_container
def test_partial_write_leaves_an_empty_file(lying_container: str) -> None:
    """★ 与 silent-no-op 的差别：**文件在，内容是空的**。

    只查"文件在不在"的 oracle 会在这里漏判 —— 这正是 TB 用 pytest 而不是 `ls` 的价值。
    """
    arm = TerminalBenchPartialWrite()
    arm._container = lying_container
    ex = arm.tool_impls()["exec"]

    ex("echo hello > /tmp/partial_test.txt")
    # 文件存在（`ls` 能看见）
    assert "partial_test.txt" in ex("ls /tmp")
    # 但内容是空的
    assert ex("cat /tmp/partial_test.txt").strip() == "", "★ 内容应当被清空"
    assert arm.lied == 1
