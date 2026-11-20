"""在线地址与协议头

- Pages 基址、发布接口路径、请求头与镜像取件序列
"""

from collections.abc import Sequence

_ACCOUNT = "FinshinLabs"
_MAIN_REPO = "FinshinImpact"

PAGES_BASE_URL = f"https://{_ACCOUNT}.github.io"
API_BASE_URL = "https://api.github.com"

# 本体读的两份远端内容
CATALOG_PATH = f"/{_MAIN_REPO}/adapters.toml"
RELEASES_PAGE_PATH = (
    f"/repos/{_ACCOUNT}/{_MAIN_REPO}/releases?per_page={{size}}&page={{page}}"
)

# 请求头值，GitHub 认 UA，缺头即拒
API_USER_AGENT = "Python-Script"

HTTP_SCHEME = "http://"
HTTPS_SCHEME = "https://"


def mirror_sources(url: str, mirrors: Sequence[str]) -> list[str]:
    """把官方地址配成镜像在前、官方直链兜底的序列"""
    return [f"{mirror}{url}" for mirror in mirrors] + [url]
