"""共享的迁移好模板库

- 首次调用跑一次迁移并清空 WAL，之后每例拷一份
- 模板目录挂在退出清理，临时库由调用方自建自删
"""

import atexit
import shutil
import tempfile
from pathlib import Path

from data import close_all, get_connection, run_migrations

_template: Path | None = None


async def copy_migrated_db(target: Path) -> None:
    """把迁移好的库拷到 target，模板只建一次"""
    global _template
    if _template is None:
        _template = await _build_template()
    shutil.copyfile(_template, target)


async def _build_template() -> Path:
    """建一只空库跑完迁移，清空 WAL 后留作模板"""
    root = Path(tempfile.mkdtemp(prefix="finshin-data-template-"))
    atexit.register(shutil.rmtree, root, ignore_errors=True)
    backups = root / "backups"
    backups.mkdir()
    db = root / "bot.db"
    conn = await get_connection(db)
    await run_migrations(conn, db, backups)
    await conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    await close_all()
    wal = Path(f"{db}-wal")
    if wal.exists() and wal.stat().st_size:
        raise RuntimeError("模板库 WAL 未清空，拷贝会丢表")
    for companion in (wal, Path(f"{db}-shm")):
        companion.unlink(missing_ok=True)
    return db
