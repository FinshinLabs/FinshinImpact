"""平台凭证声明读取

- 按平台码定位适配器入口件并取凭证声明
- 清单缺席或入口没交声明一律交 None
"""

from importlib import import_module

from finshin_sdk import CredentialSpec
from finshin_sdk.domain import Platform

from .adapter_manifest import load_adapter_manifests


def credential_of(platform: Platform) -> CredentialSpec | None:
    """按平台码取凭证声明

    - 清单里没有这一平台、入口导不进或没交声明，一律交 None
    """
    manifest = load_adapter_manifests().get(platform)
    if manifest is None:
        return None

    try:
        spec = import_module(manifest.entry).parts().credential
    except (ImportError, AttributeError, TypeError):
        # 第三方适配器导不进或形状不对时交空，窗体只出一句人话
        return None

    return spec if isinstance(spec, CredentialSpec) else None
