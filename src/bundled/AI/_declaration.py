"""AI 插件声明"""

from finshin_sdk.domain import CommandHelp, CommandRole, PluginDeclaration, SectionHelp

DECLARATION = PluginDeclaration(
    title="AI 对话",
    summary="基础对话与记忆命令",
    assets=(),
    help=(
        SectionHelp(
            section="AI 部分",
            note="私聊要授权，群里喊我一声或说触发词就能聊",
            commands=(
                CommandHelp(
                    cmd="history",
                    desc="显示历史记录",
                    role=CommandRole.ADMIN,
                ),
                CommandHelp(
                    cmd="clear",
                    desc="清空记忆",
                    role=CommandRole.ADMIN,
                ),
            ),
        ),
    ),
)
