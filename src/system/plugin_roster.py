"""本体插件名册

- 随包名单、加载档位与包树布局
- 外部插件挂载点
- 在场判定与命令名抢占
"""

from collections.abc import Sequence

from finshin_sdk.domain import CommandTaken, PluginClaim, PluginPriority

# 包树布局
BUNDLED_PLUGINS_PKG = "bundled"  # 随包插件树顶层包名，扫描与导入共用同值
INSTALLED_PLUGINS_DIR = "finshin/plugin"  # 外部插件挂载点
INSTALLED_PLUGINS_PKG = "plugin"  # 外部插件的顶层包名，导入前缀与挂载共用同值

# 随包名单与档位
BUNDLED_PLUGINS: frozenset[str] = frozenset({"help", "grant", "AI"})

BUNDLED_PRIORITY_TABLE: dict[str, PluginPriority] = {
    "help": PluginPriority.FIRST,
    "AI": PluginPriority.LAST,
}


def is_plugin_enabled(name: str, enabled: frozenset[str] | None) -> bool:
    """判定插件本次在场

    - 随包插件恒在场
    - 启用集为 None 表示实例从未保存过选择，非随包插件一律不在场
    """
    return name in BUNDLED_PLUGINS or (enabled is not None and name in enabled)


def resolve_claims(
    claims: Sequence[PluginClaim],
    enabled: frozenset[str] | None,
) -> tuple[frozenset[str], dict[str, tuple[CommandTaken, ...]]]:
    """解开插件之间的命令名抢占

    - 交出放行的插件名与被抢走的命令名，后者按插件名归组，装载与面板共用这一份
    - 只有在场的插件拿走命令名
    - 一个命令名只有一只在场时它拿走，多只在场时随包件拿走
    - 同一命令名多只非随包插件同时在场即整组作废，本次一起禁用且不记冲突
    - 不在场但命令名被拿走的照记冲突，面板据此禁掉勾选
    - 随包插件恒放行也不记冲突，随包件互抢归本体安排
    - 插件任一命令名被抢走即整只不放行
    """
    holders: dict[str, list[str]] = {}
    for claim in claims:
        if not is_plugin_enabled(claim.name, enabled):
            continue
        for cmd in claim.commands:
            holders.setdefault(cmd, []).append(claim.name)

    owners: dict[str, str] = {}
    voided: set[str] = set()
    for cmd, names in holders.items():
        bundled = [name for name in names if name in BUNDLED_PLUGINS]
        if len(names) == 1 or bundled:
            owners[cmd] = bundled[0] if bundled else names[0]
            continue
        voided.update(names)

    allowed: set[str] = set()
    conflicts: dict[str, tuple[CommandTaken, ...]] = {}
    for claim in claims:
        if claim.name in BUNDLED_PLUGINS:
            allowed.add(claim.name)
            continue

        # 路由由插件整只交出，摘不掉单独一条
        taken = tuple(
            CommandTaken(cmd, owners[cmd])
            for cmd in claim.commands
            if owners.get(cmd, claim.name) != claim.name
        )
        if taken:
            conflicts[claim.name] = taken
        elif is_plugin_enabled(claim.name, enabled) and claim.name not in voided:
            allowed.add(claim.name)

    return frozenset(allowed), conflicts
