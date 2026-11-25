"""AI 接口探测的失败归类

- 状态码、超时与 2xx 非 JSON 直接按字段分，不补模型列表
- 能确定地址和密钥已通时指认模型
- 排除不了就把三项一起标红，原文逐字留在行上
- 收尾裁决三项全红换一句不知道是哪项错
"""

import asyncio
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from bundled.AI import probe  # noqa: E402
from bundled.AI.config import SOURCE, PluginKeys, PluginSections  # noqa: E402
from exceptions import (  # noqa: E402
    ConnectionFailedError,
    HTTPBodyError,
    HTTPStatusError,
    RequestTimeoutError,
)
from finshin_sdk.domain import ProbeOutcome, ProbeResult  # noqa: E402
from finshin_sdk.domain.config import ConfigPath  # noqa: E402

_FORMAT_ERROR = "接口返回的内容不是预期的格式，请检查地址"
_MODEL_NOTE = "地址和 Key 已通，问题多半在模型"
_UNKNOWN_FIELD = "不知道是哪项配置出错"
_UNKNOWN_NOTE = "不知道是哪项配置出错，请看上面的返回"
_TIMEOUT_NOTE = "请求超时，请检查地址"
_CONNECT_NOTE = "连不上接口，请检查地址"

_KEY_401 = "密钥被接口拒绝（401）"
_KEY_403 = "密钥被接口拒绝（403）"
_MISSING_404 = "接口地址或路径不对（404）"

# 直接按字段分的状态码：状态码、正文、后段中文、指认的配置项，None 即不指认
_STATUS_CASES = (
    (401, '{"error":"Invalid key"}', _KEY_401, PluginKeys.API_KEY),
    (403, '{"error":"Forbidden"}', _KEY_403, PluginKeys.API_KEY),
    (404, '{"error":"Not Found"}', _MISSING_404, PluginKeys.BASE_URL),
    (402, '{"error":"quota"}', None, None),
    (429, '{"error":"too many"}', None, None),
)


def _item(key: PluginKeys) -> ConfigPath:
    """本插件配置项的完整身份"""
    return ConfigPath(source=SOURCE, section=PluginSections.MODEL, key=key)


def _raising(error: Exception):
    """替身：照给定异常抛出"""

    def behave() -> None:
        raise error

    return behave


def _returning(body: Any):
    """替身：2xx 且正文照给定值交出"""

    def behave() -> Any:
        return body

    return behave


class _ModelsCall:
    """模型列表替身，记下有没有被叫过"""

    def __init__(self, behave) -> None:
        self.behave = behave
        self.calls = 0

    async def __call__(self, *_args: Any, **_kwargs: Any) -> Any:
        self.calls += 1
        return self.behave()


def _run(probe_behave, models_behave=None) -> tuple[ProbeResult, int]:
    """用替身跑一次探测，交出结果与模型列表调用次数"""

    async def fake_probe(_cls, *_args: Any, **_kwargs: Any) -> Any:
        return probe_behave()

    models = _ModelsCall(models_behave or _returning({"data": []}))
    with (
        patch.object(probe.AIClient, "probe", classmethod(fake_probe)),
        patch.object(probe.AIClient, "list_models", models),
    ):
        result = asyncio.run(probe._run("https://example.invalid/v1", "k", "m"))
    return result, models.calls


def _outcome(result: ProbeResult) -> ProbeOutcome:
    """把单路结果拼成一轮汇总"""
    return ProbeOutcome(results=(("ai", result),))


class ProbeDirectFieldCase(unittest.TestCase):
    """直接看得出的字段错，不补模型列表"""

    def test_accepted(self) -> None:
        """2xx 正文带 choices：算通过"""
        result, calls = _run(
            _returning({"choices": [{"message": {"content": "pong"}}]})
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.field_errors, {})
        self.assertEqual(calls, 0)

    def test_usage_only_accepted(self) -> None:
        """2xx 正文只有 usage、choices 空着：算通过"""
        result, _ = _run(_returning({"choices": [], "usage": {"prompt_tokens": 1}}))
        self.assertTrue(result.accepted)

    def test_status_codes(self) -> None:
        """状态码档：后段中文指认字段，行上留原文"""
        for code, body, text, key in _STATUS_CASES:
            with self.subTest(code=code):
                result, calls = _run(_raising(HTTPStatusError(code, body)))

                self.assertFalse(result.accepted)
                self.assertEqual(result.detail, f"HTTP {code} {body}")
                self.assertEqual(
                    result.field_errors, {} if key is None else {_item(key): text}
                )
                self.assertEqual(calls, 0)

    def test_timeout_and_connect_mark_address(self) -> None:
        """超时、连不上：地址字段错，不补模型列表"""
        cases = (
            (RequestTimeoutError(), _TIMEOUT_NOTE, "请求超时"),
            (ConnectionFailedError(), _CONNECT_NOTE, "连不上接口"),
        )
        for error, note, detail in cases:
            with self.subTest(error=type(error).__name__):
                result, calls = _run(_raising(error))

                self.assertFalse(result.accepted)
                self.assertEqual(result.detail, detail)
                self.assertEqual(
                    result.field_errors, {_item(PluginKeys.BASE_URL): note}
                )
                self.assertEqual(calls, 0)

    def test_non_json_marks_address_with_raw_body(self) -> None:
        """2xx 正文不是 JSON：地址字段错，正文逐字留在行上"""
        result, calls = _run(_raising(HTTPBodyError("<html>登录页</html>")))

        self.assertFalse(result.accepted)
        self.assertEqual(result.detail, "<html>登录页</html>")
        self.assertEqual(
            result.field_errors, {_item(PluginKeys.BASE_URL): _FORMAT_ERROR}
        )
        self.assertEqual(calls, 0)

    def test_unknown_exception_log_hides_body(self) -> None:
        """表外异常只给一句，日志只留类名"""
        with patch.object(probe._logger, "debug") as debug:
            result, _ = _run(_raising(RuntimeError("SECRET-BODY")))

        self.assertFalse(result.accepted)
        self.assertEqual(result.detail, "请求失败")
        self.assertEqual(result.field_errors, {})
        self.assertEqual(debug.call_count, 1)
        self.assertIn("RuntimeError", str(debug.call_args))
        self.assertNotIn("SECRET-BODY", str(debug.call_args))


class ProbeExclusionCase(unittest.TestCase):
    """说不清的失败补一次模型列表再归类"""

    def test_models_ok_marks_model(self) -> None:
        """对话请求失败但模型列表通：指认模型，原文照留"""
        result, calls = _run(
            _raising(HTTPStatusError(400, '{"error":"model missing"}')),
            _returning({"data": [{"id": "m"}]}),
        )

        self.assertFalse(result.accepted)
        self.assertEqual(result.detail, 'HTTP 400 {"error":"model missing"}')
        self.assertEqual(result.field_errors, {_item(PluginKeys.MODEL): _MODEL_NOTE})
        self.assertEqual(calls, 1)

    def test_models_key_rejected(self) -> None:
        """模型列表报密钥错：指认密钥，两段原文都留"""
        result, _ = _run(
            _raising(HTTPStatusError(500, '{"error":"server"}')),
            _raising(HTTPStatusError(401, '{"error":"Invalid key"}')),
        )

        self.assertEqual(
            result.detail,
            'HTTP 500 {"error":"server"}\nHTTP 401 {"error":"Invalid key"}',
        )
        self.assertEqual(result.field_errors, {_item(PluginKeys.API_KEY): _KEY_401})

    def test_models_address_missing(self) -> None:
        """模型列表报 404：指认地址"""
        result, _ = _run(
            _raising(HTTPStatusError(500, '{"error":"server"}')),
            _raising(HTTPStatusError(404, '{"error":"Not Found"}')),
        )

        self.assertEqual(
            result.field_errors, {_item(PluginKeys.BASE_URL): _MISSING_404}
        )

    def test_models_timeout_and_connect_mark_address(self) -> None:
        """模型列表超时、连不上：地址字段错"""
        cases = (
            (RequestTimeoutError(), _TIMEOUT_NOTE),
            (ConnectionFailedError(), _CONNECT_NOTE),
        )
        for error, note in cases:
            with self.subTest(error=type(error).__name__):
                result, _ = _run(
                    _raising(HTTPStatusError(500, '{"error":"server"}')),
                    _raising(error),
                )

                self.assertEqual(
                    result.field_errors, {_item(PluginKeys.BASE_URL): note}
                )

    def test_models_unclear_marks_all_three(self) -> None:
        """模型列表也说不清：三项一起标红"""
        cases = (
            (
                _raising(HTTPBodyError("<html></html>")),
                'HTTP 500 {"error":"server"}\n<html></html>',
            ),
            (_raising(HTTPStatusError(503, '{"error":"down"}')), None),
            (_raising(RuntimeError("SECRET-BODY")), None),
            (_returning({"error": "boom"}), None),
        )
        for index, (models_behave, expected_detail) in enumerate(cases):
            with self.subTest(models=index):
                result, calls = _run(
                    _raising(HTTPStatusError(500, '{"error":"server"}')),
                    models_behave,
                )

                self.assertFalse(result.accepted)
                self.assertEqual(
                    result.field_errors,
                    {
                        _item(PluginKeys.BASE_URL): _UNKNOWN_FIELD,
                        _item(PluginKeys.API_KEY): _UNKNOWN_FIELD,
                        _item(PluginKeys.MODEL): _UNKNOWN_FIELD,
                    },
                )
                self.assertEqual(calls, 1)
                if expected_detail is not None:
                    self.assertEqual(result.detail, expected_detail)

    def test_models_unknown_exception_log_hides_body(self) -> None:
        """模型列表抛表外异常：日志只留类名"""
        with patch.object(probe._logger, "debug") as debug:
            _run(
                _raising(HTTPStatusError(500, '{"error":"server"}')),
                _raising(RuntimeError("SECRET-BODY")),
            )

        self.assertEqual(debug.call_count, 1)
        self.assertIn("RuntimeError", str(debug.call_args))
        self.assertNotIn("SECRET-BODY", str(debug.call_args))

    def test_error_body_goes_through_exclusion(self) -> None:
        """2xx 正文带 error：算失败，再补模型列表"""
        result, calls = _run(_returning({"error": "boom"}), _returning({"data": []}))

        self.assertFalse(result.accepted)
        self.assertEqual(result.detail, '{"error": "boom"}')
        self.assertEqual(result.field_errors, {_item(PluginKeys.MODEL): _MODEL_NOTE})
        self.assertEqual(calls, 1)


class ProbeFinishCase(unittest.TestCase):
    """收尾裁决只交标红的配置项"""

    def test_field_error_kept_without_detail(self) -> None:
        """有字段错：只交字段错，结论句留空归本体出"""
        errors = {_item(PluginKeys.API_KEY): _KEY_401}
        result = ProbeResult(accepted=False, detail="HTTP 401 x", field_errors=errors)
        verdict = probe._finish(_outcome(result))
        self.assertEqual(verdict.failure_detail, "")
        self.assertEqual(verdict.field_errors, errors)

    def test_all_fields_red_uses_unknown_note(self) -> None:
        """三项全红：结论句换不知道是哪项错"""
        errors = {
            _item(PluginKeys.BASE_URL): _UNKNOWN_FIELD,
            _item(PluginKeys.API_KEY): _UNKNOWN_FIELD,
            _item(PluginKeys.MODEL): _UNKNOWN_FIELD,
        }
        result = ProbeResult(accepted=False, detail="x", field_errors=errors)
        verdict = probe._finish(_outcome(result))
        self.assertEqual(verdict.failure_detail, _UNKNOWN_NOTE)
        self.assertEqual(verdict.field_errors, errors)

    def test_no_field_error_gives_empty_verdict(self) -> None:
        """一句字段错都没有：裁决两项都空"""
        result = ProbeResult(accepted=False, detail="HTTP 500 x")
        verdict = probe._finish(_outcome(result))
        self.assertEqual(verdict.failure_detail, "")
        self.assertEqual(verdict.field_errors, {})


if __name__ == "__main__":
    unittest.main()
