"""发布说明取数

- 按仓分页拉 release 正文，组件版本窗只收正式版，剔掉发布包直链行、裸链接补成可点
- 同一仓当天的正文落本机缓存，隔天整份重取
- 最新一版标签与本地版本比对
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, NoReturn, cast

from exceptions import (
    HTTPStatusError,
    LocalVersionError,
    NetworkError,
    NewVersionError,
    RemoteVersionError,
    describe_error,
)
from skin.messages import VersionMessage
from system.links import ACCOUNT, MAIN_REPO, releases_api_path
from system.tool_settings import declaration
from system.versions import is_upgrade
from utils.network import GitClient

from .env_setup.toolchain import RUNTIME_DIR

_TIMEOUT_RELEASE = 10.0  # release 正文读取超时 10 秒

# release 标签前缀
_TAG_PREFIX = "v"

# 未认证 API 单页最多 100 条，多出的量换页取
_RELEASE_PAGE_SIZE = 100

# 翻页收口保护，短页即到底，正常到不了这一页
_RELEASE_MAX_PAGES = 10

_DOWNLOAD_MARK = "releases/download/"  # 发布包直链所在行的标记

# 裸链接会在版本号的小数点处被截断，只剩前半段可点
_BARE_URL = re.compile(r"(?<![(<])(https?://\S+)")

# 发布直链里认的仓路径，只收 github.com 的 release 地址
_REPO_URL = re.compile(
    r"^https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/releases(?:/|$)"
)

# 正文缓存的目录名与文件键位
_NOTES_DIR_NAME = "release-notes"
_CACHE_DATE = "date"
_CACHE_NOTES = "notes"
_CACHE_TAG = "tag"
_CACHE_BODY = "body"


@dataclass(frozen=True, slots=True)
class _Repo:
    """一只 GitHub 仓

    - 属主与仓名都从发布直链的路径段取
    """

    owner: str
    name: str


@dataclass(frozen=True)
class ReleaseNote:
    """单版发布说明

    - body 已剔掉发布包直链行，裸链接补成尖括号
    """

    tag: str
    body: str


_MAIN = _Repo(ACCOUNT, MAIN_REPO)


def _repo_of(url: str) -> _Repo | NoReturn:
    """从发布直链解出仓的属主与仓名

    - 不是 github.com 的 release 地址即按远程内容读不懂报错
    """
    found = _REPO_URL.match(url)
    if found is None:
        raise RemoteVersionError(VersionMessage.REMOTE_ADDRESS)

    owner, name = found.groups()
    return _Repo(owner, name)


def _get_local_version() -> str | NoReturn:
    """读取本地版本号"""
    try:
        data = declaration()
        if not data:
            raise LocalVersionError(VersionMessage.LOCAL_MISS) from None
        project = data.get("project")
        local_version = project.get("version") if isinstance(project, dict) else None
        if not isinstance(local_version, str) or not local_version:
            raise LocalVersionError(VersionMessage.LOCAL_BROKEN) from None
        return local_version
    except Exception as e:
        raise LocalVersionError(VersionMessage.LOCAL_BROKEN) from e


async def _fetch(path: str, timeout: float) -> Any | NoReturn:
    """读取远程内容指定路径"""
    try:
        return await GitClient.get_api(path, timeout)
    except HTTPStatusError as e:
        raise RemoteVersionError(describe_error(e)) from e
    except NetworkError as e:
        raise RemoteVersionError(describe_error(e)) from e
    except Exception as e:
        raise RemoteVersionError(VersionMessage.REMOTE_BROKEN) from e


def _drop_download_lines(body: str) -> str:
    """release 正文剔掉发布包直链所在行"""
    return "\n".join(
        line for line in body.splitlines() if _DOWNLOAD_MARK not in line
    ).strip()


def _autolink_bare_urls(body: str) -> str:
    """release 正文的裸链接改写为尖括号自动链接"""
    return _BARE_URL.sub(r"<\1>", body)


def _to_note(row: dict[str, Any]) -> ReleaseNote:
    """release 条目转发布说明"""
    return ReleaseNote(
        tag=str(row.get("tag_name") or ""),
        body=_autolink_bare_urls(_drop_download_lines(str(row.get("body") or ""))),
    )


def _is_formal(row: dict[str, Any]) -> bool:
    """草稿与预发布不算正式 release"""
    return not row.get("draft") and not row.get("prerelease")


async def _repo_notes(repo: _Repo, formal_only: bool) -> tuple[ReleaseNote, ...]:
    """按页拉一只仓的发布说明

    - 新在前，短页即到底
    - formal_only 为真即只收正式 release
    """
    notes: list[ReleaseNote] = []
    for page in range(1, _RELEASE_MAX_PAGES + 1):
        rows = cast(
            Any,
            await _fetch(
                releases_api_path(repo.owner, repo.name, _RELEASE_PAGE_SIZE, page),
                _TIMEOUT_RELEASE,
            ),
        )
        if not isinstance(rows, list):
            raise RemoteVersionError(VersionMessage.REMOTE_BROKEN)

        notes.extend(
            _to_note(row)
            for row in rows
            if isinstance(row, dict) and (not formal_only or _is_formal(row))
        )
        if len(rows) < _RELEASE_PAGE_SIZE:
            break

    if not notes:
        raise RemoteVersionError(VersionMessage.REMOTE_BROKEN)

    return tuple(notes)


def _notes_path(repo: _Repo) -> Path:
    """一只仓的正文缓存文件"""
    return RUNTIME_DIR / _NOTES_DIR_NAME / f"{repo.owner}.{repo.name}.json"


def _read_cache(repo: _Repo, day: str) -> tuple[ReleaseNote, ...] | None:
    """读当天那份缓存

    - 文件不在场、读不出、不是今天的都按没有缓存处理
    """
    try:
        data = json.loads(_notes_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get(_CACHE_DATE) != day:
        return None
    rows = data.get(_CACHE_NOTES)
    if not isinstance(rows, list) or not rows:
        return None

    notes: list[ReleaseNote] = []
    for row in rows:
        tag = row.get(_CACHE_TAG) if isinstance(row, dict) else None
        body = row.get(_CACHE_BODY) if isinstance(row, dict) else None
        if not isinstance(tag, str) or not isinstance(body, str):
            return None
        notes.append(ReleaseNote(tag, body))

    return tuple(notes)


def _write_cache(repo: _Repo, notes: tuple[ReleaseNote, ...], day: str) -> None:
    """把这一天的正文落盘

    - 写不进即不记，下一次照常重取
    """
    data = {
        _CACHE_DATE: day,
        _CACHE_NOTES: [
            {_CACHE_TAG: note.tag, _CACHE_BODY: note.body} for note in notes
        ],
    }
    try:
        path = _notes_path(repo)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
    except OSError:
        return


async def release_history() -> tuple[ReleaseNote, ...] | NoReturn:
    """按页拉取本体全部版本的发布说明"""
    return await _repo_notes(_MAIN, formal_only=False)


async def component_notes(
    release_url: str, *, today: str | None = None
) -> tuple[ReleaseNote, ...] | NoReturn:
    """取一只组件仓当天的全部正式 release 正文

    - 当天缓存直接交回，隔天整份重取
    - 缓存读不出按没有缓存处理
    """
    repo = _repo_of(release_url)
    day = today or date.today().isoformat()
    cached = _read_cache(repo, day)
    if cached is not None:
        return cached

    notes = tuple(
        note for note in await _repo_notes(repo, formal_only=True) if note.tag
    )
    if not notes:
        raise RemoteVersionError(VersionMessage.REMOTE_BROKEN)
    _write_cache(repo, notes, day)

    return notes


def version_of_tag(tag: str) -> str:
    """release 标签去掉前缀的版本号"""
    return tag.removeprefix(_TAG_PREFIX)


def check_latest(notes: Sequence[ReleaseNote]) -> str | NoReturn:
    """最新一版是否比本机新

    - 取最新一条标签去掉前缀与本地版本比对
    - 读不懂的版本串按远程内容损坏报错
    """
    local_version = _get_local_version()
    remote_version = version_of_tag(notes[0].tag)

    newer = is_upgrade(local_version, remote_version)
    if newer is None:
        raise RemoteVersionError(VersionMessage.REMOTE_BROKEN)
    if newer:
        raise NewVersionError(local_version, remote_version)

    return local_version
