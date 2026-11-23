"""插件依赖规则

- 启动期定本实例结算范围，把装失败的插件移出启用集
- 保存插件选择后按全局清单补缺，只加不删
"""

from finshin_sdk.domain import PluginManifestKeys
from system.plugin_roster import is_plugin_enabled
from system.plugin_state import (
    StateKeys,
    load_instance_enabled,
    save_state,
    state_path_of,
)

from .deps_keep import keep_union
from .deps_manifest import (
    catalog_digest,
    load_manifests,
    plugins_roots,
    top_package_name,
)
from .subprocess_ops import is_pin_installed


def missing_global() -> list[str]:
    """全局保留清单里本机还缺的 pin

    - 保存插件选择后按这份清单增量补装
    """
    return [pin for pin in keep_union() if not is_pin_installed(pin)]


def target_manifests(code: str) -> list[dict]:
    """取本实例应结算的插件清单

    - 范围是随包插件与本实例启用集
    - 随包插件不看勾选，读取侧恒并入
    """
    roots = plugins_roots()
    if not roots:
        return []
    enabled = load_instance_enabled(state_path_of(code), StateKeys.ENABLED)
    return [
        manifest
        for manifest in load_manifests(roots)
        if is_plugin_enabled(manifest[PluginManifestKeys.NAME], enabled)
    ]


def disable_failed(code: str, failed: list[str]) -> list[str]:
    """把安装失败的启用插件移出启用集并落盘

    - 失败项按顶层包名或资源声明命中哪个插件就禁哪个
    - 命中不了具体插件（整轮异常）时启用集全禁
    - 落盘只写启用集与目录指纹
    """
    roots = plugins_roots()
    if not roots:
        return []
    enabled = load_instance_enabled(state_path_of(code), StateKeys.ENABLED)
    if not enabled:
        return []

    manifests = load_manifests(roots)
    tops = {top_package_name(item) for item in failed}
    ordered: list[str] = []
    dropped: list[str] = []
    for manifest in manifests:
        name = manifest[PluginManifestKeys.NAME]
        if name not in enabled:
            continue
        ordered.append(name)
        deps = {top_package_name(pin) for pin in manifest[PluginManifestKeys.DEPS]}
        assets = set(manifest[PluginManifestKeys.ASSETS])
        if deps & tops or assets & set(failed):
            dropped.append(name)
    if not dropped:
        dropped = ordered

    keep = [name for name in ordered if name not in dropped]
    save_state(state_path_of(code), keep, catalog_digest(manifests))
    return dropped
