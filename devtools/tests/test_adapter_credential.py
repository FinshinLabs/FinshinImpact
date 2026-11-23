"""平台凭证声明读取的单元测试

- 假声明换标签、提示与身份推导，读取口原样取出
- 清单缺席、入口导不进、入口没交声明，一律交 None
"""

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from finshin_sdk import CredentialSpec  # noqa: E402
from finshin_sdk.domain import ConfigPath, PlatformCode  # noqa: E402
from finshin_sdk.dto import AdapterManifestDTO  # noqa: E402
from services import adapter_credential as credential_mod  # noqa: E402

_SPEC = CredentialSpec(
    label="假凭证",
    desc="这行是输入框下的提示",
    invalid="这行是认不出时的提示",
    item=ConfigPath(source="adapter.fake", section="credential", key="token"),
    identity=lambda text: f"fake.{text}" if text else "",
)

_CARD = AdapterManifestDTO(
    platform=PlatformCode("tg"), deps=(), requires_sdk="", entry="fake_entry"
)


class TestAdapterCredential(unittest.TestCase):
    """按平台码取凭证声明"""

    def _take(self, entry_module: object) -> CredentialSpec | None:
        """装着假入口件取一次声明"""
        with (
            patch.object(
                credential_mod,
                "load_adapter_manifests",
                lambda: {PlatformCode("tg"): _CARD},
            ),
            patch.object(credential_mod, "import_module", lambda _name: entry_module),
        ):
            return credential_mod.credential_of(PlatformCode("tg"))

    def test_declaration_comes_out_whole(self) -> None:
        """假声明的标签、提示、非法提示与身份推导原样取出"""
        entry = SimpleNamespace(parts=lambda: SimpleNamespace(credential=_SPEC))
        spec = self._take(entry)
        self.assertIs(spec, _SPEC)
        self.assertEqual(spec.label, "假凭证")
        self.assertEqual(spec.desc, "这行是输入框下的提示")
        self.assertEqual(spec.invalid, "这行是认不出时的提示")
        self.assertEqual(spec.identity("abc"), "fake.abc")
        self.assertEqual(spec.identity(""), "")

    def test_unlisted_platform_gives_none(self) -> None:
        """清单里没有这一平台即交 None"""
        with patch.object(credential_mod, "load_adapter_manifests", lambda: {}):
            self.assertIsNone(credential_mod.credential_of(PlatformCode("qq")))

    def test_entry_without_parts_gives_none(self) -> None:
        """入口模块没交 parts 即交 None"""
        self.assertIsNone(self._take(SimpleNamespace()))

    def test_entry_import_failure_gives_none(self) -> None:
        """入口模块导不进即交 None"""

        def _boom(_name: str) -> object:
            raise ImportError("fake 包不在环境里")

        with (
            patch.object(
                credential_mod,
                "load_adapter_manifests",
                lambda: {PlatformCode("tg"): _CARD},
            ),
            patch.object(credential_mod, "import_module", _boom),
        ):
            self.assertIsNone(credential_mod.credential_of(PlatformCode("tg")))


if __name__ == "__main__":
    unittest.main()
