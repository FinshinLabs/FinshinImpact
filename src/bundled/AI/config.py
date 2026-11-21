"""AI 配置

- 固定取值落在类属性上
- 配置中心字段按访问实时读取
"""

from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

from bot.error_guard import error_guard
from finshin_sdk import ConnectionPlan
from finshin_sdk.domain import (
    ConfigKey,
    ConfigPath,
    ConfigSection,
    FieldCondition,
    FieldSpec,
    SectionSpec,
    SourceDeclaration,
)
from utils import config_manager
from utils.paths import RECORDS_DIR
from utils.persona import build_persona

from .utils import build_message

T = TypeVar("T")

# 配置中心按天/按小时填，运行期换算成秒
_HOUR_SECONDS = 60 * 60
_DAY_SECONDS = 24 * _HOUR_SECONDS

# 上下文档位与上限换算
_K_TOKENS = 1024
_CUSTOM_K = "custom"


class AISection(StrEnum):
    """本插件自己认的段名

    - 段名照盘上旧值，不做数据迁移
    """

    MODEL = "model"
    CHORE = "chore"


class AIKey(StrEnum):
    """本插件自己认的键名

    - 键名照盘上旧值，不做数据迁移
    """

    BASE_URL = "base_url"
    API_KEY = "api_key"
    MODEL = "model"
    CONTEXT_K = "context_k"
    CONTEXT_CUSTOM_K = "context_custom_k"
    OWNER = "owner"
    TRIGGERS = "triggers"
    LOST_LINES = "lost_lines"


def _path(key: AIKey, section: AISection) -> ConfigPath:
    """拼出本插件配置项的完整身份"""
    return ConfigPath(source="plugin.AI", section=section, key=key)


_MODEL_SECTION = SectionSpec(
    section=AISection.MODEL,
    title="模型",
    fields=(
        FieldSpec(
            section=AISection.MODEL,
            key=AIKey.BASE_URL,
            value_type=str,
            default="",
            label="接口地址（OpenAI 兼容）",
            desc="接口方给的根地址，如 OpenAI 官方 https://api.openai.com/v1",
            required=True,
        ),
        FieldSpec(
            section=AISection.MODEL,
            key=AIKey.API_KEY,
            value_type=str,
            default="",
            label="API Key",
            desc="接口方给的密钥",
            required=True,
        ),
        FieldSpec(
            section=AISection.MODEL,
            key=AIKey.MODEL,
            value_type=str,
            default="",
            label="模型名",
            desc="接口方要求的模型标识",
            required=True,
        ),
        FieldSpec(
            section=AISection.MODEL,
            key=AIKey.CONTEXT_K,
            value_type=str,
            default="16",
            label="上下文上限（K）",
            desc="超过上限从最旧一组问答开始丢，1K=1024",
            options=("8", "16", "32", "64", _CUSTOM_K),
            option_labels=("8K", "16K", "32K", "64K", "自定义"),
        ),
        FieldSpec(
            section=AISection.MODEL,
            key=AIKey.CONTEXT_CUSTOM_K,
            value_type=float,
            default=16.0,
            label="自定义上限（K）",
            desc="取值范围 1~64",
            bounds=(1.0, 64.0),
            visible_when=(FieldCondition(AIKey.CONTEXT_K, (_CUSTOM_K,)),),
        ),
    ),
)

_CHORE_SECTION = SectionSpec(
    section=AISection.CHORE,
    title="主人与触发",
    fields=(
        FieldSpec(
            section=AISection.CHORE,
            key=AIKey.OWNER,
            value_type=str,
            default="",
            label="主人",
            desc="具有最高权限的用户 ID（注意实例对应的平台）",
            required=True,
        ),
        FieldSpec(
            section=AISection.CHORE,
            key=AIKey.TRIGGERS,
            value_type=list,
            default=[],
            label="触发词",
            desc="用户消息包含关键词触发 AI 回复，不区分大小写",
            required=True,
        ),
        FieldSpec(
            section=AISection.CHORE,
            key=AIKey.LOST_LINES,
            value_type=list,
            default=[],
            label="停机交代话术",
            desc="重启时对遗失对话补一句说明，随机取一条，留空交给 AI 现写",
        ),
    ),
)


def _probe_plan() -> ConnectionPlan | None:
    """交出保存轮那次接口探测的计划

    - 插件探测件要读本模块的配置单例，调用时才导入，避免循环
    """
    from .probe import build_probe

    return build_probe()


CONFIG_SOURCE = SourceDeclaration(
    title="AI 设置",
    sections=(_MODEL_SECTION, _CHORE_SECTION),
    probe=_probe_plan,
)


class _DynamicAIConfig:
    """配置取用出口

    - 配置中心字段每次访问现读
    """

    # 路径配置
    record_dir: Path = RECORDS_DIR

    # 硬编码模型行为
    temperature: float = 0.7
    request_path: str = "/chat/completions"

    @error_guard("AI 配置读取", reraise=True)
    def _read(self, item: ConfigPath, expected: type[T]) -> T:
        """按配置项身份取配置中心的原始值"""
        return config_manager.get(item, expected)

    def __getattr__(self, name: str) -> Any:
        """不存在的属性名一律拦下"""
        raise AttributeError(f"AIConfig 对象没有属性 '{name}'")

    @property
    def base_url(self) -> str:
        """OpenAI 兼容接口的 base URL"""
        return self._read(_path(AIKey.BASE_URL, AISection.MODEL), str)

    @property
    def api_key(self) -> str:
        """模型密钥"""
        return self._read(_path(AIKey.API_KEY, AISection.MODEL), str)

    @property
    def model_name(self) -> str:
        """模型名"""
        return self._read(_path(AIKey.MODEL, AISection.MODEL), str)

    @property
    def context_tokens(self) -> int:
        """上下文上限的 token 数"""
        mode = self._read(_path(AIKey.CONTEXT_K, AISection.MODEL), str)
        k = (
            self._read(_path(AIKey.CONTEXT_CUSTOM_K, AISection.MODEL), float)
            if mode == _CUSTOM_K
            else float(mode)
        )
        return int(k * _K_TOKENS)

    @property
    def group_triggers(self) -> tuple[str, ...]:
        """群聊触发词"""
        return tuple(self._read(_path(AIKey.TRIGGERS, AISection.CHORE), list))

    @property
    def lost_lines(self) -> tuple[str, ...]:
        """停机交代话术"""
        lines = self._read(_path(AIKey.LOST_LINES, AISection.CHORE), list)
        return tuple(line for line in lines if line.strip())

    @property
    def keep_seconds(self) -> float:
        """记录保留时长"""
        days = self._read(ConfigKey.RECORD_KEEP.path("core", ConfigSection.DATA), float)
        return days * _DAY_SECONDS

    @property
    def waiting_time(self) -> float:
        """清理轮间隔"""
        hours = self._read(ConfigKey.WAITING.path("core", ConfigSection.DATA), float)
        return hours * _HOUR_SECONDS

    @property
    def init(self) -> tuple[dict[str, str], ...]:
        """当前人设那条系统轮"""
        owner = self._read(_path(AIKey.OWNER, AISection.CHORE), str)
        return (build_message("system", build_persona(owner)),)


ai_config = _DynamicAIConfig()  # 全局配置单例
