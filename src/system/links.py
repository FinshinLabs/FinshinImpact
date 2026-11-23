"""在线地址与协议头

- Pages 基址、发布接口路径、请求头与镜像取件序列
"""

from collections.abc import Sequence

ACCOUNT = "FinshinLabs"
MAIN_REPO = "FinshinImpact"

PAGES_BASE_URL = f"https://{ACCOUNT}.github.io"
API_BASE_URL = "https://api.github.com"

# 本体读的远端目录
CATALOG_PATH = f"/{MAIN_REPO}/adapters.toml"

# 请求头值，GitHub 认 UA，缺头即拒
API_USER_AGENT = "Python-Script"

HTTP_SCHEME = "http://"
HTTPS_SCHEME = "https://"


def releases_api_path(owner: str, repo: str, size: int, page: int) -> str:
    """某仓 release 列表的接口路径"""
    return f"/repos/{owner}/{repo}/releases?per_page={size}&page={page}"


def mirror_sources(url: str, mirrors: Sequence[str]) -> list[str]:
    """把官方地址按镜像前缀拼成取件序列"""
    return [f"{mirror}{url}" for mirror in mirrors]
