"""AI 接口探测的失败归类

- 2xx 非 JSON 归接口地址字段错，文案逐字
- 401 归密钥字段错
- 超时与连不上只给一句，不指认字段
"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

import httpx  # noqa: E402

from bundled.AI import probe  # noqa: E402
from bundled.AI.config import SOURCE, PluginKeys, PluginSections  # noqa: E402
from exceptions import (  # noqa: E402
    ConnectionFailedError,
    HTTPStatusError,
    RequestTimeoutError,
)
from finshin_sdk import ProbeResult  # noqa: E402
from finshin_sdk.domain import ConfigPath  # noqa: E402
from utils.network import BaseClient  # noqa: E402

_ADDRESS_ERROR = "接口返回的内容不是预期的格式，请检查地址"


def _item(key: PluginKeys) -> ConfigPath:
    """本插件配置项的完整身份"""
    return ConfigPath(source=SOURCE, section=PluginSections.MODEL, key=key)


def _raising(error: Exception):
    """替身响应：照给定异常抛出"""

    def behave() -> None:
        raise error

    return behave


def _non_json():
    """替身响应：200 但正文不是 JSON，走 httpx 原生解析"""
    return httpx.Response(200, content=b"<html></html>").json()


def _accepted_json():
    """替身响应：2xx 且正文是 JSON"""
    return {"choices": [{"message": {"content": "pong"}}]}


def _run(behave) -> ProbeResult:
    """用替身响应跑一次探测"""

    async def fake_post(cls, **kwargs):
        return behave()

    with patch.object(BaseClient, "post_json", classmethod(fake_post)):
        return asyncio.run(probe._run("https://example.invalid/v1", "k", "m"))


class ProbeFailureCase(unittest.TestCase):
    """探测失败按形状归类"""

    def test_json_accepted(self) -> None:
        """2xx 且正文是 JSON：算通过"""
        result = _run(_accepted_json)
        self.assertTrue(result.accepted)
        self.assertEqual(result.field_errors, {})

    def test_non_json_marks_address(self) -> None:
        """2xx 正文不是 JSON：地址字段错，文案逐字"""
        result = _run(_non_json)
        self.assertFalse(result.accepted)
        self.assertEqual(result.detail, _ADDRESS_ERROR)
        self.assertEqual(
            result.field_errors, {_item(PluginKeys.BASE_URL): _ADDRESS_ERROR}
        )

    def test_unauthorized_marks_key(self) -> None:
        """401：密钥字段错"""
        result = _run(_raising(HTTPStatusError(401, "Unauthorized")))
        self.assertFalse(result.accepted)
        self.assertEqual(
            result.field_errors,
            {_item(PluginKeys.API_KEY): "密钥被接口拒绝（401）"},
        )
        self.assertIn("401", result.detail)

    def test_no_connection_only_detail(self) -> None:
        """超时与连不上：只给一句，不指认字段"""
        cases = (
            (RequestTimeoutError(), "请求超时"),
            (ConnectionFailedError(), "连不上接口"),
        )
        for error, detail in cases:
            with self.subTest(error=type(error).__name__):
                result = _run(_raising(error))
                self.assertFalse(result.accepted)
                self.assertEqual(result.detail, detail)
                self.assertEqual(result.field_errors, {})


if __name__ == "__main__":
    unittest.main()
