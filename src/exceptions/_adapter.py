"""适配器异常族

- 定义适配器缺失、安装、版本与引用范围几类异常
"""

from finshin_sdk.exceptions import BotError


class AdapterError(BotError):
    """适配器异常基类

    - 整族致命等级置真
    """

    fatal = True


_PLATFORM_MISSING_TEXT = "没有可用的平台适配器\n请先装一个平台适配器，再重新打开本程序"


class PlatformMissingError(AdapterError):
    """身份码缺平台段"""

    def __str__(self) -> str:
        return _PLATFORM_MISSING_TEXT


class AdapterMissingError(AdapterError):
    """平台适配器未安装"""

    def __init__(self, platform: str) -> None:
        self.platform = platform
        super().__init__()


class AdapterNotInstalledError(AdapterError):
    """适配器包不在环境里"""

    def __init__(self, platform: str, module: str) -> None:
        self.platform = platform
        self.module = module
        super().__init__()


class AdapterOutOfDateError(AdapterError):
    """适配器要的接口版本与本机不符"""

    def __init__(self, platform: str, requires: str, sdk: str) -> None:
        self.platform = platform
        self.requires = requires
        self.sdk = sdk
        super().__init__()


class AdapterImportError(AdapterError):
    """外部适配器引了本体内部或界面库"""

    def __init__(self, platform: str, target: str, where: str) -> None:
        self.platform = platform
        self.target = target
        self.where = where
        super().__init__()


ADAPTER_MAP = {
    PlatformMissingError: _PLATFORM_MISSING_TEXT,
    AdapterMissingError: "{platform} 平台的适配器还没装\n装完请重新打开本程序",
    AdapterNotInstalledError: (
        "{platform} 平台的适配器没装进环境：找不到 {module}\n装完请重新打开本程序"
    ),
    AdapterOutOfDateError: (
        "{platform} 平台的适配器要接口包 {requires}，本机接口包是 {sdk}\n"
        "在平台组件面板装与接口包匹配的适配器版本，装完重新打开本程序"
    ),
    AdapterImportError: "{platform} 平台的适配器不许引本体内部或界面库（{target}，{where}）",
}
