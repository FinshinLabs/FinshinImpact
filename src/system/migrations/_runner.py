"""迁移执行器

- 按文件名顺序跑本目录下的脚本，跑不跑由脚本自己看实例形状决定
- 脚本名形如 `_0001_说明.py`，四位编号只决定先后，缺号不补
- 脚本读写同一份实例：实例目录与 config.toml 读出的表，文件不在即空表
- 配置文档有改动才写回，写回前留 .bak，已有则保留首次那份
- 渲染读回对不上或写盘失败都保持原文件
- 单份实例或单份脚本出错只跳过这一段，不拦启动
"""

import copy
import importlib
import shutil
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

from ..atomic_write import write_text_atomic
from ._toml import render

# 迁移对象、备份后缀与脚本文件名
_CONFIG_NAME = "config.toml"
_BACKUP_SUFFIX = ".bak"
_SCRIPT_GLOB = "_[0-9]*.py"


@dataclass(frozen=True, slots=True)
class MigrationInstance:
    """一份实例上可动的东西

    - root 是实例目录，脚本要搬的文件都从它下面找
    - document 是 config.toml 读出的表，文件不在即空表
    """

    root: Path
    document: dict[str, Any]


class _MigrationScript(Protocol):
    """一份迁移脚本对外要交的东西"""

    def matches(self, instance: MigrationInstance) -> bool: ...

    def apply(self, instance: MigrationInstance) -> tuple[bool, list[str]]:
        """应用迁移，交出「有没有动成」与逐条说明"""
        ...


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
    """迁移一份实例，返回是否动过盘"""
    config = instance_dir / _CONFIG_NAME
    document: dict[str, Any] = {}
    if config.is_file():
        try:
            document = tomllib.loads(config.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as e:
            report(f"{instance_dir.name}：配置读不出，未动（{e}）")
            return False

    original = copy.deepcopy(document)
    instance = MigrationInstance(root=instance_dir, document=document)
    name = instance_dir.name
    moved = False
    for script in _scripts():
        try:
            if not script.matches(instance):
                continue
            changed, notes = script.apply(instance)
        except Exception as e:  # noqa: BLE001  单份脚本出错不拦启动
            label = getattr(script, "__name__", "迁移脚本")
            report(f"{name}：{label} 未跑成，整份跳过（{e}）")
            return False
        if changed:
            moved = True
        for line in notes:
            report(f"{name}：{line}")

    if document == original:
        return moved

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
