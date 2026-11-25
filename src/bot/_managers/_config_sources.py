"""配置来源清单

- 平台交出的来源与各已启用插件自己交出的来源拼成装配用的来源清单
- 标题跟字段表都由交出者给
- 插件装载不成的那一只不进配置
"""

from finshin_sdk.domain.config import SourceDeclaration
from system.profile_env import INSTANCE_PROFILE_NAME
from utils.config.sources import ConfigSource, SourceKind
from utils.logger import get_logger
from utils.paths import PLATFORM, PROFILE_DIR
from utils.plugin import enabled_manifests, load_plugin

from .._adapter_host import parts_for

_logger = get_logger("Config")


def config_sources() -> tuple[ConfigSource, ...]:
    """配置来源清单拼装

    - 平台、已启用插件依次成序
    - 来源顺序即面板大类的行序，段内顺序照交出者给的顺序
    """
    return (_adapter_source(), *_plugin_sources())


def _adapter_source() -> ConfigSource:
    """本平台适配器交出的来源"""
    parts = parts_for(PLATFORM)
    return ConfigSource(
        kind=SourceKind.ADAPTER,
        code=PLATFORM,
        title=parts.title,
        sections=parts.sections,
    )


def _enabled_plugin_declarations() -> tuple[tuple[str, SourceDeclaration], ...]:
    """已启用插件交出的来源声明

    - 按启用序列排，交出插件名与整份声明
    - 装载不成的那一只跳过
    """
    declarations: list[tuple[str, SourceDeclaration]] = []
    for manifest in enabled_manifests(PROFILE_DIR / INSTANCE_PROFILE_NAME):
        try:
            declared = load_plugin(manifest).source_declaration()
        except Exception as e:
            _logger.error(
                f"插件 {manifest.name} 装载失败，它交出的配置段不进配置：{type(e).__name__}"
            )
            continue
        declarations.append((manifest.name, declared))
    return tuple(declarations)


def _plugin_sources() -> tuple[ConfigSource, ...]:
    """已启用插件交出的来源

    - 按启用序列排
    """
    return tuple(
        ConfigSource(
            kind=SourceKind.PLUGIN,
            code=name,
            title=declared.title,
            sections=declared.sections,
            probe=declared.probe,
        )
        for name, declared in _enabled_plugin_declarations()
    )
