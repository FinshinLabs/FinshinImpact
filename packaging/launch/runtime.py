"""运行环境补齐

- 接口包按钉死的版本取件，指纹对 GitHub 附件自报值
- 解压嵌入式 Python、放开 site、部署 uv、装依赖
- 已装且清单未变即免装，失败保缓存供续装命中
- 接口件同版本照装，本机更高的版本不许被压回去
"""

import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import NoReturn

import net_channel
from pack_spec import (
    SDK_RELEASE_URL,
    PackLayout,
    dependencies,
    release_mirrors,
    remote_sdk_digest,
    require_setting,
    sdk_version,
    sdk_wheel_name,
)
from packaging.version import InvalidVersion, Version
from unpack import unpack_all, unpack_entry

from . import console, dialogs

# 换源与缓存的配置键，接口件的文件名形态
_SETTING_INDEX = "uv-index-urls"
_SETTING_CACHE = "uv-cache-dir"
_WHEEL_SUFFIX = ".whl"
_WHEEL_GLOB = f"*{_WHEEL_SUFFIX}"

# 运行环境里已装件的落点与命名形态
_SITE_PACKAGES = Path("Lib") / "site-packages"
_DIST_INFO_GLOB = "*.dist-info"
_DIST_INFO_SUFFIX = ".dist-info"


def _fail_install(text: str) -> NoReturn:
    """失败详情留在控制台，看完再弹提示退出"""
    console.hold_console()
    dialogs.fail_exit(text)


def _seed_wheels(root: Path) -> list[Path]:
    """待装接口件的 wheel，按文件名升序

    - 启动器按钉死的版本取件后落在包根 `_sdk`
    """
    return sorted((root / PackLayout.SDK_WHEEL_DIR).glob(_WHEEL_GLOB))


def _name_and_version(stem: str) -> tuple[str, str]:
    """文件名头两段读成发行件名与版本，下划线归回连字符"""
    parts = stem.split("-")
    if len(parts) < 2:
        return "", ""
    return parts[0].replace("_", "-"), parts[1]


def _installed_versions(runtime: Path) -> dict[str, str]:
    """运行环境里已装的发行件名与版本，按 dist-info 目录名读"""
    found: dict[str, str] = {}
    for info in (runtime / _SITE_PACKAGES).glob(_DIST_INFO_GLOB):
        name, version = _name_and_version(info.name[: -len(_DIST_INFO_SUFFIX)])
        if name:
            found[name] = version
    return found


def _already_enough(wheel: Path, installed: dict[str, str]) -> bool:
    """接口件要的那版本机已有更高才算够，读不懂版本即算不足

    - 同版本照装：重打不抬版本号的件只靠这一步换掉
    """
    name, wanted = _name_and_version(wheel.stem)
    have = installed.get(name, "")
    if not have:
        return False
    try:
        return Version(have) > Version(wanted)
    except InvalidVersion:
        return False


def _sdk_dist(version: str) -> str:
    """接口包的发行件名"""
    wheel = sdk_wheel_name(version)
    return _name_and_version(wheel[: -len(_WHEEL_SUFFIX)])[0]


def _sdk_line(version: str, digest: str) -> str:
    """接口包在免装指纹里的那一行

    - 版本与指纹一并记下，供下次启动比对
    """
    return f"{_sdk_dist(version)}=={version}#{digest}"


def _installed_sdk_digest(lines: list[str], version: str) -> str:
    """已装标记里接口包那一行的指纹，没有同版本那行交出空串"""
    prefix = f"{_sdk_dist(version)}=={version}#"
    for line in lines:
        if line.startswith(prefix):
            return line[len(prefix) :]

    return ""


def _install_plan(root: Path) -> list[str]:
    """交给 uv 的装单

    - 接口件按路径喂 uv，本机已装高于那版才不进装单
    """
    installed = _installed_versions(root / PackLayout.RUNTIME_DIR)
    pending = _seed_wheels(root)
    wanted = [wheel for wheel in pending if not _already_enough(wheel, installed)]

    return [*dependencies(root), *(str(wheel) for wheel in wanted)]


def _drop_seeds(root: Path) -> None:
    """装成功后删掉接口件那一份

    - 整目录删，装过之后没人再读它
    - 失败路径不走到这里，留下的件供下次续装命中
    """
    shutil.rmtree(root / PackLayout.SDK_WHEEL_DIR, ignore_errors=True)


def _installed_lines(runtime: Path) -> list[str]:
    """已装标记里的清单行，没有标记交出空表"""
    stamp = runtime / PackLayout.INSTALL_STAMP
    if not stamp.exists():
        return []
    return stamp.read_text().splitlines()


def _extract_embed(runtime: Path) -> None:
    """解压嵌入式 Python 到 runtime 目录"""
    unpack_all(runtime / PackLayout.EMBED_ZIP, runtime)


def _enable_site(runtime: Path) -> None:
    """放开嵌入式包的 site-packages"""
    pth = next(iter(runtime.glob(PackLayout.PYTHON_PTH_GLOB)))
    text = pth.read_text()

    # 默认那行被注释锁死，uv 装不进第三方包
    if "#import site" in text:
        pth.write_text(text.replace("#import site", "import site"))


def _place_uv(root: Path, runtime: Path) -> Path:
    """复制随包 uv 到 runtime"""
    exe = runtime / PackLayout.UV_EXE
    if not exe.exists():
        # runtime 在升级保留名单、payload 不在，副本取完即删省磁盘
        unpack_entry(
            root / PackLayout.PAYLOAD_DIR / PackLayout.UV_ZIP,
            PackLayout.UV_EXE,
            runtime,
        )
    shutil.rmtree(root / PackLayout.PAYLOAD_DIR, ignore_errors=True)
    return exe


def _uv_with_index_retry(
    root: Path, uv: Path, python: Path, deps: list[str], cache: Path
) -> None:
    """换源重试安装依赖"""
    base = [
        str(uv),
        "pip",
        "install",
        "--python",
        str(python),
        "--link-mode",
        "copy",
        "--no-progress",
        "--cache-dir",
        str(cache),
    ]

    # uv 索引按序轮询国内镜像
    index_urls = list(require_setting(root, _SETTING_INDEX))
    for i, index in enumerate(index_urls):
        if i:
            print(f"换源重试（第 {i} 次）：{index}")
            print("上方报错无需处理，程序正在自动切换镜像源。\n\n")
        try:
            subprocess.run([*base, "--index-url", index, *deps], check=True)
            return
        except subprocess.CalledProcessError:
            print("\n\n")
            if i == len(index_urls) - 1:
                raise


def _fetch_sdk(root: Path, version: str, digest: str) -> str:
    """把钉死的接口包取到包根 `_sdk`，交出核过的指纹

    - 盘上有同指纹的件就复用
    - 逐源下载并核指纹，不符换下一源
    - 指纹取不到或全源坏时提示恢复网络后续装
    """
    from system.digest import file_digest
    from system.links import mirror_sources

    name = sdk_wheel_name(version)
    target = root / PackLayout.SDK_WHEEL_DIR / name
    if digest and target.is_file() and file_digest(target) == digest:
        print(f"接口包 {name} 已在，跳过下载")
        return digest
    if not digest:
        _fail_install("取不到接口包附件的指纹\n恢复网络后重新双击即可续装")

    # 旧件留着会和新件一起喂给 uv，同包两版装不进同一个环境
    shutil.rmtree(root / PackLayout.SDK_WHEEL_DIR, ignore_errors=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    print(f"下载接口包 {name}")
    urls = mirror_sources(SDK_RELEASE_URL.format(ver=version), release_mirrors(root))
    try:
        net_channel.download_verified(urls, target, digest)
    except RuntimeError:
        _fail_install(
            "接口包下载失败，请查看进度窗口末尾输出\n恢复网络后重新双击即可续装"
        )
    print(f"接口包指纹核验通过（{digest[:12]}）")
    return digest


def ensure_runtime(root: Path) -> None:
    """补齐运行环境

    - 依次：取接口包、解压嵌入式 Python、放开 site、部署 uv、装依赖
    - 只追加安装，删掉的库由引导层同步环境收口
    - 装包缓存不在此清，留到引导层同步落定后收口
    - 接口包装成功即从包根删掉，装失败留着下次续装命中
    - 安装详情留在控制台，等待由启动主流程统一收口
    """
    runtime = root / PackLayout.RUNTIME_DIR

    # 装包期缓存放包内，不落用户目录
    cache = runtime / str(require_setting(root, _SETTING_CACHE))
    core = dependencies(root)
    version = sdk_version(root)
    lines = _installed_lines(runtime)
    installed = _installed_sdk_digest(lines, version)
    remote = remote_sdk_digest(version)
    sdk_ok = bool(installed) and (not remote or remote == installed)

    # 待装件在场即说明有一趟待装，指纹相同也要跑
    if (
        not _seed_wheels(root)
        and (runtime / PackLayout.PYTHON_EXE).exists()
        and lines[: len(core)] == core
        and sdk_ok
    ):
        return
    console.open_console()
    try:
        print("[1/4] 获取接口包…")
        digest = installed if sdk_ok else _fetch_sdk(root, version, remote)
        if sdk_ok:
            print(f"接口包 {version} 已装，跳过下载")
        deps = _install_plan(root)
        print("[2/4] 解压嵌入式 Python…")
        if not (runtime / PackLayout.PYTHON_EXE).exists():
            _extract_embed(runtime)
        print("[3/4] 放开 site-packages…")
        _enable_site(runtime)
        print("[4/4] 准备安装器 uv 并装依赖（下方为 uv 实时输出）…")
        uv = _place_uv(root, runtime)
        _uv_with_index_retry(root, uv, runtime / PackLayout.PYTHON_EXE, deps, cache)
        print("环境安装完成")
    except subprocess.CalledProcessError:
        # 失败不删缓存，续装直接命中省下载
        _fail_install(
            "依赖安装失败，请查看进度窗口末尾输出\n恢复网络后重新双击即可续装"
        )
    except FileNotFoundError as e:
        _fail_install(f"安装文件缺失：{e}\n发布包可能损坏，请重新下载")
    except zipfile.BadZipFile:
        _fail_install(
            "内嵌运行环境包损坏（发布包不完整）\n请到 Releases 页重新下载最新发布包"
        )

    stamp = [*core, _sdk_line(version, digest)]
    (runtime / PackLayout.INSTALL_STAMP).write_text("\n".join(stamp))
    _drop_seeds(root)
