"""实例仓储

- 扫描身份文件夹枚举已有实例
- 收身份码把凭证串与备注名落盘
"""

import shutil
import time
from typing import Any

from finshin_sdk.domain import platform_of_key
from finshin_sdk.domain.ids import ProfileKey
from system.atomic_write import write_bytes_atomic
from system.profile_env import (
    ASSET_PERSONA_EXAMPLE_NAME,
    ASSETS_DIR,
    INSTANCE_PERSONA_DIR_NAME,
    INSTANCE_PERSONA_NAME,
    INSTANCE_PROFILE_NAME,
    INSTANCES_DIR,
    TOKEN_KEY,
    profile_dir,
    read_profile_data,
    write_profile_data,
)

from .adapter_manifest import load_adapter_manifests

# 引导期身份码未定，路径常量所在的通用包一导入即按空身份码冻结，故模板路径就地拼
_PERSONA_TEMPLATE = ASSETS_DIR / ASSET_PERSONA_EXAMPLE_NAME

# 实例判定只认自描述文件，引导期必写，新建实例此刻还没有 config.toml
_INSTANCE_MARK = INSTANCE_PROFILE_NAME

# 备注名在自描述文件里的键名，token 键名另有单源常量
_REMARK_KEY = "remark"

# 最近使用时间（创建或启动）在自描述文件里的键名，选窗列表按它降序置顶
_LAST_USED_KEY = "last_used"


def list_profiles() -> list[tuple[str, str]]:
    """枚举已有实例

    - 扫实例根目录下一级身份文件夹，返回 (身份码, 备注名) 列表
    - 目录不存在时返回空列表
    - 身份码前缀不是已装适配器平台码的目录跳过
    - 按最近使用时间降序，时间缺失或相同时按身份码降序
    """
    known = frozenset(load_adapter_manifests())
    profiles: list[tuple[float, str, str]] = []

    if not INSTANCES_DIR.is_dir():
        return []

    for path in sorted(INSTANCES_DIR.iterdir()):
        if not path.is_dir() or not (path / _INSTANCE_MARK).is_file():
            continue
        if platform_of_key(ProfileKey(path.name)) not in known:
            continue
        data = read_profile_data(path.name)
        last_used = data.get(_LAST_USED_KEY)
        stamp = float(last_used) if isinstance(last_used, (int, float)) else 0.0
        profiles.append((stamp, path.name, _remark_of(data)))

    profiles.sort(key=lambda item: (item[0], item[1]))
    profiles.reverse()
    return [(code, remark) for _, code, remark in profiles]


def touch_profile(code: str) -> None:
    """记录实例最近使用时间

    - 整份读改写，文件损坏或写不进一律静默放弃，不阻断启动
    """
    data = read_profile_data(code)
    if not data:
        return
    data[_LAST_USED_KEY] = time.time()
    try:
        write_profile_data(code, data)
    except OSError:
        return


def remark_of(code: str) -> str:
    """按身份码取实例备注名"""
    return _remark_of(read_profile_data(code))


def create_profile(code: str, credential: str, remark: str) -> None:
    """新建实例文件夹

    - 只建目录、人设与自描述文件
    - 凭证串与备注名写进自描述文件
    - 创建即计入最近使用，新实例在选窗置顶
    """
    target = profile_dir(code)
    target.mkdir(parents=True, exist_ok=True)

    if _PERSONA_TEMPLATE.exists():
        persona = target / INSTANCE_PERSONA_DIR_NAME / INSTANCE_PERSONA_NAME
        persona.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(persona, _PERSONA_TEMPLATE.read_bytes())

    write_profile_data(
        code,
        {
            TOKEN_KEY: credential.strip(),
            _REMARK_KEY: remark.strip(),
            _LAST_USED_KEY: time.time(),
        },
    )


def update_profile(code: str, credential: str, remark: str) -> None:
    """就地改写已有实例

    - 只覆盖自描述文件的凭证串与备注名，目录与配置原样保留
    - 合并改写，保留最近使用时间等既有字段
    """
    data = read_profile_data(code)
    data[TOKEN_KEY] = credential.strip()
    data[_REMARK_KEY] = remark.strip()
    write_profile_data(code, data)


def delete_profile(code: str) -> bool:
    """删除实例文件夹

    - 配置、人设与数据整目录一并删除
    - 返回是否确已删除，占用导致失败时如实报告
    """
    target = profile_dir(code)
    if not target.is_dir():
        return False

    # 被占用文件会让部分删除失败，删后复查目录才算数
    shutil.rmtree(target, ignore_errors=True)
    return not target.is_dir()


def _remark_of(data: dict[str, Any]) -> str:
    """取实例备注名

    - 没填或类型不对即交空串，不阻断选择窗
    """
    return str(data.get(_REMARK_KEY, ""))
