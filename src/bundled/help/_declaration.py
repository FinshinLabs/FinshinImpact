"""帮助插件声明"""

from finshin_sdk.domain import CommandHelp, CommandRole, PluginDeclaration, SectionHelp

DECLARATION = PluginDeclaration(
    title="帮助",
    summary="帮助菜单与命令查询",
    assets=(),
    help=(
        SectionHelp(
            commands=(
                CommandHelp(
                    cmd="help",
                    desc="查看帮助文档，命令后接 -h 可以单独查看该命令帮助",
                    role=CommandRole.MEMBER,
                ),
            )
        ),
    ),
)
