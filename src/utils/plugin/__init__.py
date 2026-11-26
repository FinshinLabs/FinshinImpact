"""插件工具门面

- 代发加载记录读取、启用名单与注册表
"""

from ._manifest import enabled_manifests
from ._register import load_plugin, register_plugins
