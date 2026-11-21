"""迁移执行器

- 按文件名顺序跑本目录下的脚本，跑不跑由脚本自己看配置形状决定
- 写回前留 .bak，已有则保留首次那份，渲染读回对不上或写盘失败都保持原文件
- 单份实例失败只跳过这一份，不拦启动
"""

import importlib
import shutil
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

from ..atomic_write import write_text_atomic
from ._toml import render

# 迁移对象、备份后缀与脚本文件名
_CONFIG_NAME = "config.toml"
_BACKUP_SUFFIX = ".bak"
_SCRIPT_GLOB = "_[0-9]*.py"


class _MigrationScript(Protocol):
    """一份迁移脚本对外要交的东西"""

    FROM_RELEASE: str
    TO_RELEASE: str

    def matches(self, document: dict[str, Any]) -> bool: ...

    def apply(self, document: dict[str, Any]) -> list[str]: ...


def _report_line(line: str) -> None:
    """往控制台播一句，无控制台的启动器里静默"""
    if sys.stdout is not None:
        print(line)


def run_all(instances_dir: Path, report: Callable[[str], None] = _report_line) -> int:
    """扫过 instances 下每个实例，返回有改动的份数"""
    if not instances_dir.is_dir():
        return 0
    return sum(
        1
        for entry in sorted(instances_dir.iterdir())
        if entry.is_dir() and run_instance(entry, report=report)
    )


def run_instance(
    instance_dir: Path,
    *,
    report: Callable[[str], None] = _report_line,
) -> bool:
    """迁移一份实例配置，返回是否写盘"""
    config = instance_dir / _CONFIG_NAME
    if not config.is_file():
        return False

    name = instance_dir.name
    try:
        document = tomllib.loads(config.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        report(f"{name}：配置读不出，未动（{e}）")
        return False

    changed = False
    for script in _scripts():
        try:
            if not script.matches(document):
                continue
            notes = script.apply(document)
        except Exception as e:  # noqa: BLE001  单份脚本出错不拦启动
            label = getattr(script, "__name__", "迁移脚本")
            report(f"{name}：{label} 未跑成，整份跳过（{e}）")
            return False
        changed = True
        report(f"{name}：{script.FROM_RELEASE} → {script.TO_RELEASE}")
        for line in notes:
            report(f"{name}：{line}")

    if not changed:
        return False

    try:
        text = render(document)
        if tomllib.loads(text) != document:
            raise ValueError("渲染读回与原数据不一致")
        backup = config.with_name(config.name + _BACKUP_SUFFIX)
        if not backup.exists():
            shutil.copyfile(config, backup)
        write_text_atomic(config, text)
    except (OSError, TypeError, ValueError) as e:
        report(f"{name}：未写盘（{e}）")
        return False

    report(f"{name}：已写回，备份 {config.name}{_BACKUP_SUFFIX}")
    return True


def _scripts() -> tuple[_MigrationScript, ...]:
    """按文件名顺序取本目录下的迁移脚本"""
    folder = Path(__file__).parent
    return tuple(
        cast(_MigrationScript, _import(path))
        for path in sorted(folder.glob(_SCRIPT_GLOB))
    )


def _import(path: Path) -> ModuleType:
    return importlib.import_module(f"{__package__}.{path.stem}")
