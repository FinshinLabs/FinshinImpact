"""按来源保存

- 按左侧大类取表单段、算差异与合并磁盘现值
- 保存或复验请求携带本类值和已通过的检测记录
"""

from copy import deepcopy
from dataclasses import dataclass, field

from ._differ import compare_configs
from .models import AppConfigData, AppSchema


@dataclass(frozen=True, slots=True)
class ProbeRecord:
    """来源检测通过记录"""

    reuse_key: object
    resolved_proxy: str | None = None


@dataclass(frozen=True, slots=True)
class SourceSaveRequest:
    """单类保存或复验请求"""

    group: str
    candidate: AppConfigData
    write: bool
    probes: dict[str, ProbeRecord] = field(default_factory=dict)


def changed_groups(
    schema: AppSchema, disk: AppConfigData, values: AppConfigData
) -> list[str]:
    """列出表单现值与磁盘现值不同的大类"""
    return [
        group
        for group in dict.fromkeys(tab.group for tab in schema)
        if compare_configs(schema, disk, values, group=group)[0]
    ]


def changed_sections(
    schema: AppSchema, disk: AppConfigData, values: AppConfigData
) -> list[str]:
    """列出表单现值与磁盘现值不同的页签段"""
    changes, _ = compare_configs(schema, disk, values)
    return list(dict.fromkeys(tab.section for tab in schema if tab.section in changes))


def _source_tabs(schema: AppSchema, group: str) -> AppSchema:
    """取本来源的页签"""
    return [tab for tab in schema if tab.group == group]


def _source_form_values(
    schema: AppSchema, group: str, values: AppConfigData
) -> AppConfigData:
    """只取本来源声明过的段与字段"""
    return {
        tab.section: {
            field.key: deepcopy((values.get(tab.section) or {})[field.key])
            for field in tab.fields
            if field.key in (values.get(tab.section) or {})
        }
        for tab in _source_tabs(schema, group)
    }


def merge_source_config(
    schema: AppSchema,
    disk: AppConfigData,
    group: str,
    values: AppConfigData,
) -> AppConfigData:
    """以磁盘现值为底替换本来源的段"""
    merged = deepcopy(disk)
    merged.update(_source_form_values(schema, group, values))
    return merged
