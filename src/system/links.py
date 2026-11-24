"""GitHub 地址与通用协议头

- GitHub 账号、仓库、Pages 基址、发布接口路径与请求头由 GITHUB 交出
- 镜像取件序列与协议头不属 GitHub 族
"""

from collections.abc import Sequence
from dataclasses import dataclass

HTTP_SCHEME = "http://"
HTTPS_SCHEME = "https://"


@dataclass(frozen=True, slots=True)
class _GitHub:
    """GitHub 账号与地址

    - 账号与仓名是源值，Pages 基址和目录路径按它们组装
    - 请求头值 GitHub 认 UA，缺头即拒
    """

    account: str = "FinshinLabs"
    main_repo: str = "FinshinImpact"
    api_base_url: str = "https://api.github.com"
    api_user_agent: str = "Python-Script"

    @property
    def pages_base_url(self) -> str:
        """Pages 站点的基址"""
        return f"https://{self.account}.github.io"

    @property
    def catalog_path(self) -> str:
        """本体读的远端目录"""
        return f"/{self.main_repo}/adapters.toml"

    @staticmethod
    def releases_api_path(owner: str, repo: str, size: int, page: int) -> str:
        """某仓 release 列表的接口路径"""
        return f"/repos/{owner}/{repo}/releases?per_page={size}&page={page}"


GITHUB = _GitHub()


def mirror_sources(url: str, mirrors: Sequence[str]) -> list[str]:
    """把官方地址按镜像前缀拼成取件序列"""
    return [f"{mirror}{url}" for mirror in mirrors]
