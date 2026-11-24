"""命令权限声明的单元测试

- 覆盖帮助图描述尾部的权限说明
- 覆盖装配期的代码声明与守卫比对
- 随仓三只插件的声明与守卫对得上
"""

import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from system.profile_env import set_profile  # noqa: E402

set_profile("tg.000000")

from bundled._shared.access import require_role  # noqa: E402
from bundled._shared.filters import CommandMatch  # noqa: E402
from bundled.help import _services  # noqa: E402
from exceptions import PluginRoleError  # noqa: E402
from finshin_sdk.domain import (  # noqa: E402
    CommandHelp,
    CommandRole,
    MessageRoute,
    PluginDeclaration,
    SectionHelp,
)
from finshin_sdk.dto import PluginManifestDTO  # noqa: E402
from system.plugin_roster import BUNDLED_PLUGINS_PKG  # noqa: E402
from utils.plugin import _manifest, _register  # noqa: E402


def _manifest_of(cmd: str, role: CommandRole) -> PluginManifestDTO:
    """造一份只含单条命令声明的加载记录"""
    declaration = PluginDeclaration(
        title="演示",
        summary="演示",
        assets=(),
        help=(
            SectionHelp(
                section="工具",
                commands=(CommandHelp(cmd=cmd, desc="演示命令", role=role),),
            ),
        ),
    )
    return PluginManifestDTO(
        name="demo",
        module=f"{BUNDLED_PLUGINS_PKG}.demo",
        deps=(),
        declaration=declaration,
    )


def _routes(name: str, limit: CommandRole | None) -> tuple[MessageRoute, ...]:
    """造一条带命令头的路由，limit 为空即不带守卫"""

    async def handler(raw: object, ctx: object) -> None:
        """占位处理函数"""

    guarded = handler if limit is None else require_role(limit)(handler)
    return (MessageRoute(CommandMatch(name), guarded),)


class TestMenuRoleNote(unittest.TestCase):
    """帮助图描述尾部的权限说明"""

    def _desc(self, role: CommandRole) -> str:
        manifest = _manifest_of("md", role)
        with patch.object(_services, "enabled_manifests", lambda path: [manifest]):
            help_list, specs, _ = _services._build_help_menu()
        self.assertEqual(specs["md"].role, role)
        return help_list["md"]

    def test_owner_note_appended(self) -> None:
        self.assertEqual(self._desc(CommandRole.OWNER), "演示命令（仅主人）")

    def test_admin_note_appended(self) -> None:
        self.assertEqual(self._desc(CommandRole.ADMIN), "演示命令（需授权）")

    def test_member_note_left_out(self) -> None:
        self.assertEqual(self._desc(CommandRole.MEMBER), "演示命令")


class TestRoleCheck(unittest.TestCase):
    """装配期的代码声明与守卫比对"""

    def test_declared_owner_with_owner_guard_passes(self) -> None:
        _register._check_roles(
            _manifest_of("wipe", CommandRole.OWNER),
            _routes("wipe", CommandRole.OWNER),
        )

    def test_declared_owner_without_guard_fails(self) -> None:
        with self.assertRaises(PluginRoleError):
            _register._check_roles(
                _manifest_of("wipe", CommandRole.OWNER), _routes("wipe", None)
            )

    def test_guard_tier_below_declaration_fails(self) -> None:
        with self.assertRaises(PluginRoleError):
            _register._check_roles(
                _manifest_of("wipe", CommandRole.OWNER),
                _routes("wipe", CommandRole.ADMIN),
            )

    def test_member_declaration_with_guard_fails(self) -> None:
        with self.assertRaises(PluginRoleError):
            _register._check_roles(
                _manifest_of("wipe", CommandRole.MEMBER),
                _routes("wipe", CommandRole.ADMIN),
            )

    def test_undeclared_route_without_guard_passes(self) -> None:
        _register._check_roles(
            _manifest_of("wipe", CommandRole.MEMBER), _routes("other", None)
        )


class TestBuiltinManifests(unittest.TestCase):
    """随仓三只插件的声明与守卫对得上"""

    def test_builtin_plugins_pass_the_check(self) -> None:
        for manifest in _manifest.enabled_manifests(Path("unused")):
            module = importlib.import_module(manifest.module)
            _register._check_roles(
                manifest, _register._entry_class(manifest, module)().message_routes()
            )


if __name__ == "__main__":
    unittest.main()
