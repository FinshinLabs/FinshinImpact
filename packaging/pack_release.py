"""发布状态自检

- 本地版本号、远端 tag、本地包指纹、在线版本页、发布包各源可达逐项检查
- 本地工作树与版本 tag 的树一致性
"""

import subprocess
from pathlib import Path

import net_channel
from pack_spec import (
    APP_NAME,
    BYTES_PER_MB,
    DIST,
    HDR_CONTENT_LENGTH,
    RELEASE_ZIP_URL,
    ROOT,
    local_version,
    release_mirrors,
    remote_version,
)

_PROBE_TIMEOUT = 10.0  # 发布包 HEAD 探测超时 10 秒


def check_release() -> None:
    """发布前后自检

    - 版本号、远端 tag、本地包指纹、在线版本页、发布包各源可达
    """
    from system.digest import file_digest
    from system.links import mirror_sources

    version = local_version(ROOT)
    tag_hit = subprocess.run(
        ["git", "ls-remote", "--tags", "origin", f"v{version}"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    zip_path = DIST / f"{APP_NAME}-v{version}.zip"
    local_size = zip_path.stat().st_size if zip_path.is_file() else 0
    local_digest = file_digest(zip_path) if local_size else ""
    checks = [
        ("本地版本号", f"v{version}"),
        ("git tag 远端", "已推送" if tag_hit else "缺失，先 push tag"),
        (
            "本地 zip",
            f"{local_size / BYTES_PER_MB:.1f} MB sha256={local_digest[:12]}"
            if local_size
            else "缺失，先构建",
        ),
        ("在线版本页", remote_version() or "读取失败"),
    ]
    zip_url = RELEASE_ZIP_URL.format(ver=version)
    for url in mirror_sources(zip_url, release_mirrors()):
        checks.append((url, _asset_probe(url, local_size)))
    for name, detail in checks:
        print(f"[自检] {name}: {detail}")


def refuse_tree_tag_mismatch(root: Path = ROOT) -> None:
    """构建前核工作树干净且 HEAD 树与版本 tag 的树相同"""
    version = local_version(root)
    tag = f"v{version}"
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if status.returncode:
        detail = (status.stderr or status.stdout).strip()
        raise SystemExit(f"git status --porcelain 失败：{detail}")
    if status.stdout:
        print(status.stdout, end="")
        raise SystemExit(1)

    head = subprocess.run(
        ["git", "rev-parse", "HEAD^{tree}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if head.returncode:
        detail = (head.stderr or head.stdout).strip()
        raise SystemExit(f"读取 HEAD 的树失败：{detail}")

    tagged = subprocess.run(
        ["git", "rev-parse", f"refs/tags/{tag}^{{tree}}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if tagged.returncode:
        raise SystemExit(f"目标 tag {tag} 不存在，先 fetch 或先打 tag")

    head_tree = head.stdout.strip()
    tag_tree = tagged.stdout.strip()
    if head_tree != tag_tree:
        raise SystemExit(
            f"版本 {version} 的当前树 {head_tree} 与目标 tag {tag} 的树 {tag_tree} "
            "不同，产物会含未定稿代码"
        )
    print(f"工作树干净，当前 HEAD 树与目标 tag {tag} 的树一致，核对通过")


def _asset_probe(url: str, local_size: int) -> str:
    """HEAD 探测发布包可达性与体积

    - 与本地 zip 大小一致即内容对得上，无需整包下载
    """
    if not local_size:
        return "本地无包，跳过"
    size, note = net_channel.probe_size(
        url, net_channel.openers(), HDR_CONTENT_LENGTH, _PROBE_TIMEOUT
    )
    if note:
        return f"不可达（{note}），确认已上传 release"
    if size == local_size:
        return f"可达，{size / BYTES_PER_MB:.1f} MB 与本地包一致"
    return f"可达但大小不符（远端 {size / BYTES_PER_MB:.1f} MB）"
