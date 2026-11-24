"""配置数据模型

- 定义运行期配置数据结构别名
- 定义界面渲染用的字段与页签结构体
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from finshin_sdk.domain import (
    ConfigPath,
    ConfigValue,
    ConfigValues,
    ConnectionPlan,
    FieldCondition,
    SourceCode,
)

# 一个标签页的键值表，键为配置键名
TabData = dict[str, ConfigValue]

# 完整 TOML 配置文件结构，段名为带来源前缀的点分串
AppConfigData = dict[str, TabData]

# 配置校验错误表：键为出错字段，值为提示文案
FieldErrors = dict[ConfigPath, str]

# 单段说明子表，键名与该段下的值键同名
SectionNotes = dict[str, str]

# 段名到说明子表，装配器每次按交出模板覆盖
NotesBySection = dict[str, SectionNotes]


def is_blank(value: object) -> bool:
    """必填项空值判定

    - 空白字符串与空列表视为未填写
    - 数值无空态，0 是合法填写
    """
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not value
    return False


@dataclass
class FieldSchema:
    """单个配置项的 UI 属性

    - key 为交出者写的键名
    - options 非空即枚举字段，每项为「值 文案」对
    - bounds 为闭区间，仅 float 字段生效
    - 显隐条件全部命中才显示，空元组即恒显
    - tags 为声明里带的用途标记
    """

    key: str
    label: str
    desc: str
    default: ConfigValue
    value_type: type
    options: tuple[tuple[str, str], ...] = ()
    required: bool = False
    bounds: tuple[float, float] | None = None
    visible_when: tuple[FieldCondition, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass
class TabSchema:
    """一个标签页的 UI 结构

    - group 与 group_title 定左侧大类，同大类的页并在上排页签里
    - probe 非空即本来源可做连通检测
    """

    title: str
    section: str  # 带来源前缀的点分段名，改名波及面板按段判定处
    group: str  # 左侧大类标识，值为来源身份串
    group_title: str  # 大类标题，随来源声明交出
    section_id: str  # 本页字段所属段名
    fields: list[FieldSchema] = field(default_factory=list)
    probe: Callable[[ConfigValues], ConnectionPlan] | None = None

    def path_of(self, field: FieldSchema) -> ConfigPath:
        """字段在本来源下的完整身份"""
        return ConfigPath(
            source=SourceCode(self.group), section=self.section_id, key=field.key
        )


AppSchema = list[TabSchema]  # 完整 UI 渲染结构树


def tabs_by_group(schema: AppSchema) -> dict[str, list[TabSchema]]:
    """按来源把页签归组，组序即首次出现序"""
    groups: dict[str, list[TabSchema]] = {}
    for tab in schema:
        groups.setdefault(tab.group, []).append(tab)
    return groups


def probe_of(
    tabs: Sequence[TabSchema],
) -> Callable[[ConfigValues], ConnectionPlan] | None:
    """本来源交出的检测件，同来源各段带同一份"""
    return next((tab.probe for tab in tabs if tab.probe is not None), None)


def group_values(tabs: Sequence[TabSchema], data: AppConfigData) -> ConfigValues:
    """按页签取各段当前值，键为交出者声明的段名"""
    return {tab.section_id: data.get(tab.section) or {} for tab in tabs}
