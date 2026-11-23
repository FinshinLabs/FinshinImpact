"""连接性异常文案表

- 定义接口包中性连接异常到文案的映射
"""

from finshin_sdk.exceptions import ConnectivityError, ServerUnreachableError

CONNECTIVITY_MAP = {
    ConnectivityError: "连接失败",
    ServerUnreachableError: "无法连接到服务器",
}
