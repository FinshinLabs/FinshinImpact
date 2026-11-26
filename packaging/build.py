"""发布构建脚本

- 编译启动器并组装发布包
- 暂存区源码用随包嵌入式解释器预编字节码，用户解压即热
- 原料下载与发布自检各有独立脚本
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import net_channel
import pack_fetch
import pack_release
import unpack
from pack_spec import (
    APP_NAME,
    DIST,
    EXE_NAME,
    PROJECT_MANIFEST_FILE,
    ROOT,
    SDK_RELEASE_URL,
    STAGE,
    PackLayout,
    attach_source_path,
    local_version,
    release_mirrors,
    remote_sdk_digest,
    sdk_version,
    sdk_wheel_name,
)

_PACKAGING_DIR = "packaging"

# 应用图标取自 assets/app.ico，exe 与 GUI 任务栏共用这只
_ICON = ROOT / "assets" / PackLayout.ICON

# 发布 zip 白名单：只装运行必需与用户文档，devtools（含测试）、docs、packaging 不在名单天然排除
_COPY_DIRS = ("src", "assets")

# 拷贝时一并跳过的名字：`.git` 进包等于把本机路径发出去
_COPY_IGNORE = ("__pycache__", ".pytest_cache", "*.egg-info", ".git")
_COPY_FILES = (
    PROJECT_MANIFEST_FILE,
    "README.md",
    "CHANGELOG.md",
    "LICENSE",
)

# 入口脚本模板：注入源码路径后走引导层，先选实例再拉起主程序
_MAIN_PY = """import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from system.startup_guard import startup_guard

with startup_guard():
    from bootstrap import main

sys.exit(main())
"""


def _require_icon() -> bytes:
    """图标原料校验

    - 缺图标即中止构建，不静默放行
    """
    if not _ICON.is_file():
        raise SystemExit(f"缺少图标文件 {_ICON}，先生成 app.ico 再构建")
    return _ICON.read_bytes()


def _launcher_sources() -> list[Path]:
    """列出编译进启动器的全部源文件

    - 入口、共享规格、取数通道、解包与 launch 域
    """
    pkg = ROOT / "packaging"
    paths = [
        pkg / PackLayout.LAUNCHER_SCRIPT,
        pkg / PackLayout.PACK_SPEC_SCRIPT,
        pkg / "net_channel.py",
        pkg / "unpack.py",
    ]
    paths.extend(sorted((pkg / "launch").glob("*.py")))
    return paths


def _launcher_fingerprint() -> str:
    """启动器产物指纹

    - 源码与图标一并计入，只换图标也会重编译
    - 入口、共享规格与 launch 域全部计入，域代码变更同样重编译
    """
    from system.digest import bytes_digest

    # 编译动作与产物来源变更绑定
    blob = b"".join(
        f"=={p.name}==\n".encode() + p.read_bytes() for p in _launcher_sources()
    )
    return bytes_digest(blob + _require_icon())


def _build_launcher() -> Path:
    """创建启动器

    - 编译启动器源码为无控制台单目录 exe
    - 打包形态用 onedir，不解压不压缩
    - 产物指纹未变时复用已编译产物，避免用户端重复下载
    """
    out = DIST / "_launcher" / APP_NAME
    stamp = DIST / "_launcher" / ".launcher_sha"
    fp = _launcher_fingerprint()
    if (out / EXE_NAME).exists() and stamp.exists() and stamp.read_text() == fp:
        print("启动器源码与图标未变，复用已编译启动器")
        return out
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--exclude-module",
            "system",  # 别把 system 打进 exe，运行时用包根那份源码
            "--onedir",
            "--noconsole",
            "--name",
            APP_NAME,
            "--icon",
            str(_ICON),
            "--distpath",
            str(DIST / "_launcher"),
            "--workpath",
            str(DIST / "build"),
            "--specpath",
            str(DIST),
            str(ROOT / _PACKAGING_DIR / PackLayout.LAUNCHER_SCRIPT),
        ],
        check=True,
    )
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(fp)
    return out


def _write_runtime_seed(launcher_dir: Path) -> None:
    """组装运行原料

    - 启动器 exe 与依赖目录 _internal 放包根，用户双击即见
    """
    runtime = STAGE / PackLayout.RUNTIME_DIR
    runtime.mkdir(parents=True, exist_ok=True)
    shutil.copy2(launcher_dir / EXE_NAME, STAGE / EXE_NAME)
    shutil.copytree(
        launcher_dir / "_internal",
        STAGE / "_internal",
        dirs_exist_ok=True,
    )

    shutil.copy2(pack_fetch.fetch_embed(), runtime / PackLayout.EMBED_ZIP)
    payload = STAGE / PackLayout.PAYLOAD_DIR
    payload.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pack_fetch.fetch_uv(), payload / PackLayout.UV_ZIP)


def _precompile_stage() -> None:
    """预编暂存区源码字节码

    - 按内容哈希判失效
    - 构建机解释器版本与嵌入式不一致也不作废产物
    """
    with tempfile.TemporaryDirectory(prefix="finshin-embed-") as tmp:
        embed = Path(tmp) / "embed"
        unpack.unpack_all(pack_fetch.fetch_embed(), embed)
        py = embed / PackLayout.PYTHON_EXE
        targets = [STAGE / "src", STAGE / PackLayout.MAIN_SCRIPT]
        subprocess.run(
            [
                str(py),
                "-m",
                "compileall",
                "-q",
                # pyc 不认 mtime，checked-hash 才扛得住 zip 往返
                "--invalidation-mode",
                "checked-hash",
                *(str(t) for t in targets),
            ],
            check=True,
        )


def _refuse_leftovers(stage: Path) -> None:
    """发布目录里有版本控制条目即停下，并报出每一条的位置"""
    offenders = sorted(str(item.relative_to(stage)) for item in stage.rglob(".git"))
    if offenders:
        raise RuntimeError("发布物里有版本控制条目：" + "、".join(offenders))


def _check_sdk_pin() -> None:
    """核接口包钉死的版本能取到且与 GitHub 指纹一致

    - 走镜像取一次附件，核 release 自报的 sha256，不符即中止并点名版本
    """
    from system.links import mirror_sources

    version = sdk_version(ROOT)
    digest = remote_sdk_digest(version)
    if not digest:
        raise SystemExit(f"取不到接口包 v{version} 的附件指纹，检查 GitHub release")
    name = sdk_wheel_name(version)
    urls = mirror_sources(SDK_RELEASE_URL.format(ver=version), release_mirrors())
    print(f"核验接口包 v{version}…")
    with tempfile.TemporaryDirectory(prefix="finshin-sdk-") as tmp:
        try:
            net_channel.download_verified(urls, Path(tmp) / name, digest)
        except RuntimeError as e:
            raise SystemExit(f"接口包 v{version} 核验失败：{e}") from e


def _assemble(launcher_dir: Path) -> Path:
    """组装发布目录并压缩为 zip"""
    _check_sdk_pin()
    version = local_version(ROOT)
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)

    for name in _COPY_DIRS:
        src = ROOT / name
        if src.exists():
            shutil.copytree(
                src,
                STAGE / name,
                ignore=shutil.ignore_patterns(*_COPY_IGNORE),
            )
    for name in _COPY_FILES:
        src = ROOT / name
        if src.exists():
            shutil.copy2(src, STAGE / name)

    (STAGE / PackLayout.MAIN_SCRIPT).write_text(_MAIN_PY, encoding="utf-8")
    _refuse_leftovers(STAGE)
    _write_runtime_seed(launcher_dir)
    _precompile_stage()
    zip_name = DIST / f"{APP_NAME}-v{version}.zip"
    if zip_name.exists():
        zip_name.unlink()
    with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in STAGE.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(DIST))
    shutil.rmtree(STAGE)
    return zip_name


def main() -> None:
    """解析参数并执行构建流程"""
    attach_source_path(ROOT)
    parser = argparse.ArgumentParser(description="发布构建")
    parser.add_argument("--check", action="store_true", help="发布前自检")
    parser.add_argument(
        "--no-launcher", action="store_true", help="跳过编译复用现有启动器"
    )
    args = parser.parse_args()

    if args.check:
        pack_release.check_release()
        return

    pack_release.refuse_tree_tag_mismatch()
    if args.no_launcher:
        launcher_dir = DIST / "_launcher" / APP_NAME
        if not (launcher_dir / EXE_NAME).exists():
            print("找不到已有启动器，去掉 --no-launcher 重新编译")
            return
    else:
        launcher_dir = _build_launcher()
    zip_path = _assemble(launcher_dir)
    print(f"完成：{zip_path}")


if __name__ == "__main__":
    main()
