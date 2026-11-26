"""闸门起子进程

- 仓根起子进程，回退出码与合流文本
- 长步按心跳报到一次，逐行口子每行交给回调，用于按文件报数
"""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

_RC_NOT_FOUND = 127  # shell 约定，命令找不到时的退出码
_HEARTBEAT_SECONDS = 20


def run(
    cmd: list[str],
    root: Path,
    env: dict[str, str] | None = None,
    *,
    label: str,
) -> tuple[int, str]:
    """仓根起子进程，合流回退出码与文本，超过心跳间隔先报一行进度"""
    merged = {**os.environ, **(env or {})}
    started = time.monotonic()
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=root,
            env=merged,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return _RC_NOT_FOUND, f"起不动：{error}"
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=_HEARTBEAT_SECONDS)
            break
        except subprocess.TimeoutExpired:
            waited = int(time.monotonic() - started)
            print(f"  … {label} 还在跑，已 {waited} 秒", flush=True)
    return proc.returncode, ((stdout or "") + (stderr or "")).strip()


def stream(
    cmd: list[str],
    root: Path,
    env: dict[str, str] | None,
    *,
    on_line: Callable[[str], None],
) -> tuple[int, str]:
    """仓根起子进程，合流逐行收输出，每行交给回调，回退出码与全文"""
    merged = {**os.environ, **(env or {})}
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=root,
            env=merged,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        return _RC_NOT_FOUND, f"起不动：{error}"
    if proc.stdout is None:
        return proc.wait(), ""
    lines: list[str] = []
    for line in proc.stdout:
        lines.append(line.rstrip("\n"))
        on_line(line)
    return proc.wait(), "\n".join(lines).strip()


class FileReceipts:
    """认 pytest 逐条输出里的文件，文件名一换就报上一个文件跑了多少条"""

    def __init__(self) -> None:
        self._file = ""
        self._count = 0

    def feed(self, line: str) -> None:
        """接一行输出，带节点 id 的才计数"""
        path, sep, _ = line.partition("::")
        if not sep:
            return
        if path != self._file:
            self.close()
            self._file = path
        self._count += 1

    def close(self) -> None:
        """报出当前文件累计的条数并清零"""
        if self._file:
            print(f"  … {Path(self._file).name} {self._count} 条", flush=True)
            self._file, self._count = "", 0
