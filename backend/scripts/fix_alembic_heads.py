"""收敛 alembic 多头，再把数据库升级到最新。

背景：dev 环境的「自动迁移哨兵」会按模型差异生成**未跟踪**的迁移文件；
当仓库既有迁移链（如 ``c057b1112026``）和本地新链同时在时，``alembic heads`` 会返回
两个 head，启动时的 ``alembic upgrade head`` 直接抛
``Multiple head revisions are present``，后端起不来。

处理顺序（幂等）：

1. 删掉 **未被 git 跟踪** 的 head 文件（哨兵生成的重复迁移，删了下次启动会按需重新生成）；
2. 若仍有多个 head → ``alembic merge`` 合并成一个；
3. 清理 ``alembic_version`` 里指向已不存在文件的版本号；
4. ``alembic upgrade heads``。

用法：
    python scripts/fix_alembic_heads.py            # 只体检
    python scripts/fix_alembic_heads.py --apply    # 处理并升级
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Windows 控制台默认 GBK，打印 ✅/⚠️ 会 UnicodeEncodeError
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.script import ScriptDirectory  # noqa: E402

ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


def is_tracked(path: Path | None) -> bool:
    """git 是否跟踪该文件；git 不可用时按「已跟踪」处理（不删任何文件）。"""
    if path is None:
        return True
    try:
        rel = path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError:
        return True
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", str(rel)],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        )
    except FileNotFoundError:
        return True
    return result.returncode == 0


def head_files(cfg: Config) -> list[tuple[str, Path | None, bool]]:
    script = ScriptDirectory.from_config(cfg)
    rows: list[tuple[str, Path | None, bool]] = []
    for rev in script.get_heads():
        obj = script.get_revision(rev)
        path = Path(obj.path) if getattr(obj, "path", None) else None
        rows.append((rev, path, is_tracked(path)))
    return rows


def ddl_hint(path: Path | None, limit: int = 4) -> str:
    """列出该迁移 upgrade() 里的操作行，便于判断「这条能不能直接删」。"""
    if path is None or not path.exists():
        return ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    body = text.split("def upgrade", 1)[-1].split("def downgrade", 1)[0]
    ops = [line.strip() for line in body.splitlines() if "op." in line]
    if not ops:
        return "空迁移"
    more = f" …共 {len(ops)} 条" if len(ops) > limit else ""
    return "; ".join(ops[:limit]) + more


async def purge_stale_versions(cfg: Config) -> tuple[set[str], int]:
    """删掉库里记录、但仓库已无对应文件的版本号（``alembic current`` 此时会直接 FAILED）。

    返回 ``(被清理的版本号, 清理后剩余行数)``；剩余 0 行说明版本历史已丢，
    调用方必须 stamp 到当前 head，否则 ``upgrade`` 会从 base 重放全部迁移。
    """
    from sqlalchemy import inspect, text

    from app.core.base_model import MappedBase
    from app.core.database import async_engine
    from app.utils.import_util import ImportUtil

    ImportUtil.find_models(MappedBase)
    known = {rev.revision for rev in ScriptDirectory.from_config(cfg).walk_revisions()}
    stale: set[str] = set()
    async with async_engine.begin() as conn:
        if not await conn.run_sync(lambda c: inspect(c).has_table("alembic_version")):
            return stale, 0
        rows = {row[0] for row in (await conn.execute(text("SELECT version_num FROM alembic_version"))).all()}
        for rev in rows - known:
            await conn.execute(text("DELETE FROM alembic_version WHERE version_num = :rev"), {"rev": rev})
            stale.add(rev)
    await async_engine.dispose()
    return stale, len(rows - stale)


async def report_tables(names: tuple[str, ...]) -> dict[str, bool]:
    """升级后回看关键表在不在（新手最容易忽略「版本号对了但表没建」）。"""
    from sqlalchemy import inspect

    from app.core.base_model import MappedBase
    from app.core.database import async_engine
    from app.utils.import_util import ImportUtil

    ImportUtil.find_models(MappedBase)
    async with async_engine.connect() as conn:
        existing = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
    await async_engine.dispose()
    return {name: name in existing for name in names}


def main() -> None:
    parser = argparse.ArgumentParser(description="收敛 alembic 多头并升级")
    parser.add_argument("--apply", action="store_true", help="真正删除/合并并执行 upgrade（默认只体检）")
    args = parser.parse_args()

    cfg = Config(str(ALEMBIC_INI))
    print("=" * 78)
    print("alembic 多头体检")
    print("=" * 78)

    rows = head_files(cfg)
    print(f"  head 数量：{len(rows)}")
    for rev, path, tracked in rows:
        mark = "git 跟踪" if tracked else "未跟踪（哨兵生成）"
        print(f"    {rev}  {path.name if path else '-'}  [{mark}]")
        hint = ddl_hint(path)
        if hint:
            print(f"      DDL: {hint}")

    if not args.apply:
        if len(rows) > 1:
            print("\n  需要收敛：python scripts/fix_alembic_heads.py --apply")
        return

    removed: list[str] = []
    for rev, path, tracked in rows:
        if not tracked and path is not None:
            path.unlink()
            removed.append(f"{rev} ({path.name})")
    for item in removed:
        print(f"  已删除未跟踪 head：{item}")

    rows = head_files(cfg)
    if len(rows) > 1:
        heads = [rev for rev, _p, _t in rows]
        print(f"  仍有 {len(heads)} 个 head，执行 merge：{heads}")
        command.merge(cfg, heads, message="自动合并多头")
        rows = head_files(cfg)
        print(f"  合并后 head：{[rev for rev, _p, _t in rows]}")

    stale, remaining = asyncio.run(purge_stale_versions(cfg))
    if stale:
        print(f"  已清理失效版本记录：{sorted(stale)}")
    if remaining == 0:
        heads = [rev for rev, _p, _t in rows]
        command.stamp(cfg, heads if len(heads) > 1 else heads[0])
        print(f"  alembic_version 已空，直接 stamp 到 {heads if len(heads) > 1 else heads[0]}")

    command.upgrade(cfg, "heads")
    print("  已执行 alembic upgrade heads")
    command.current(cfg)
    state = asyncio.run(
        report_tables(("dwd_product_line_analysis", "dwd_product_line_build_run", "dwd_cost_bill_workorder"))
    )
    for name, exists in state.items():
        print(f"    {name:<32} {'存在 ✅' if exists else '缺失 ❌'}")


if __name__ == "__main__":
    main()
