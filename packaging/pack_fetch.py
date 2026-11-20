"""构建原料下载

- 嵌入式 Python 与 uv 安装包多源下载并落 dist 缓存
- zip 条目校验，uv 包加 sha256 比对，坏包自动换源
"""

from pathlib import Path

import net_channel
from pack_spec import CACHE, DOWNLOAD_HOST, release_mirrors
from unpack import zip_entries_ok

# 构建原料下载源
_EMBED_VERSION = "3.11.9"
_EMBED_FILE = f"python-{_EMBED_VERSION}-embed-amd64.zip"
_EMBED_URL_SUFFIX = f"python/{_EMBED_VERSION}/{_EMBED_FILE}"
_EMBED_URLS = (
    f"https://registry.npmmirror.com/-/binary/{_EMBED_URL_SUFFIX}",
    f"https://mirrors.huaweicloud.com/{_EMBED_URL_SUFFIX}",
    f"https://npmmirror.com/mirrors/{_EMBED_URL_SUFFIX}",
)

# uv 随包下发给启动器装依赖，取用方在启动器的 payload 解包
_UV_VERSION = "0.12.23"
_UV_URL_SUFFIX = (
    f"astral-sh/uv/releases/download/{_UV_VERSION}/uv-x86_64-pc-windows-msvc.zip"
)
_UV_OFFICIAL_URL = f"{DOWNLOAD_HOST}/{_UV_URL_SUFFIX}"
_UV_CACHE_NAME = f"uv-{_UV_VERSION}.zip"

# 官方发布页校验值，升 _UV_VERSION 必须同步换值
_UV_SHA256 = "75d05de6762778c31ee183398de7dd15093fad0ed90b1f236d8205ea5ec00c90"


def _uv_urls() -> list[str]:
    """uv 安装包的多源取件地址"""
    from system.links import mirror_sources

    return mirror_sources(_UV_OFFICIAL_URL, release_mirrors())


def fetch_embed() -> Path:
    """取用嵌入式 Python 原料"""
    return _fetch_to_cache(list(_EMBED_URLS), _EMBED_FILE)


def fetch_uv() -> Path:
    """取用 uv 安装包原料"""
    return _fetch_to_cache(_uv_urls(), _UV_CACHE_NAME, sha256=_UV_SHA256)


def _fetch_to_cache(urls: list[str], name: str, *, sha256: str = "") -> Path:
    """构建原料取用缓存

    - 原料跨构建复用
    - 清 dist 目录即清缓存
    """
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / name
    if cached.exists():
        print(f"命中缓存 {name}")
        return cached
    net_channel.download_verified(urls, cached, sha256, verify=zip_entries_ok)
    return cached
