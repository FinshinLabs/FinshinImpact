"""权限授权插件声明"""

from finshin_sdk.domain import CommandHelp, CommandRole, PluginDeclaration, SectionHelp

DECLARATION = PluginDeclaration(
    title="权限授权",
    summary="管理命令的授权名单",
    assets=(),
    help=(
        SectionHelp(
            section="授权部分",
            commands=(
                CommandHelp(
                    cmd="grant",
                    desc="授予该 id 管理员权限",
                    args="用户 id",
                    role=CommandRole.OWNER,
                ),
                CommandHelp(
                    cmd="ungrant",
                    desc="撤销该 id 管理员权限",
                    args="用户 id",
                    role=CommandRole.OWNER,
                ),
                CommandHelp(
                    cmd="admin",
                    desc="查看授权名单",
                    role=CommandRole.OWNER,
                ),
            ),
        ),
    ),
)
