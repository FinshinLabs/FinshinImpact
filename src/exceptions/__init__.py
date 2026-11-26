"""异常聚合包

- 代发全部自定义异常族
- 代发异常文案查询
"""

from ._adapter import (
    AdapterError,
    AdapterImportError,
    AdapterMissingError,
    AdapterNotInstalledError,
    AdapterOutOfDateError,
    PlatformMissingError,
)
from ._config import (
    ConfigAttrError,
    ConfigError,
    ConfigInputError,
    ConfigMissingError,
    ConfigOutputError,
    ConfigPathMissingError,
    ProfileMissingError,
)
from ._describe import describe_error
from ._gui import (
    DashboardWriteError,
    FontError,
    FontFamilyError,
    FontLoadError,
    FontMissingError,
    FontRegisterError,
    GUIError,
)
from ._network import (
    ConnectionFailedError,
    HTTPBodyError,
    HTTPStatusError,
    NetworkError,
    RequestTimeoutError,
)
from ._plugins import (
    PluginDependencyError,
    PluginEntryError,
    PluginImportError,
    PluginLoadError,
    PluginMissingError,
    PluginRoleError,
    PluginsError,
    PluginsMissingError,
)
from ._version import (
    LocalVersionError,
    NewVersionError,
    RemoteVersionError,
    VersionError,
)
