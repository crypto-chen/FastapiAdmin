"""补齐产品线 schema 并校准 alembic 版本（幂等，用于「多 head + stamp 跳过 DDL」后的修复）。

**适用场景**：仓库里 alembic 出现多个 head → 有人直接 ``alembic stamp <head>`` 把数据库版本
指到了新 head，但**迁移的 DDL（建表/加列）从没执行过** → 跑订单全链路构建时报
``Unknown column 'order_id' in 'field list'``，或产品线页面报表不存在。

本脚本做三件事：

1. 体检：4 类对象在不在 —— 两张产品线表、``dwd_order_full_chain.order_id/ship_qty``、
   ``open_client.allow_product_line_detail``（含索引）；
2. ``--apply`` 时**只补缺的那部分**（建表用模型元数据 ``checkfirst``，加列先查
   ``information_schema``，已存在就跳过，可反复跑）；
3. 若 alembic 只剩一个 head，把数据库版本 ``stamp`` 到它（版本与文件拓扑对齐，
   之后 ``upgrade head`` 就是空操作）；多 head 时只提示怎么合并，不动手。

用法：
    python scripts/fix_product_line_schema.py            # 只体检
    python scripts/fix_product_line_schema.py --apply    # 补齐并校准版本
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

EXPECTED_HEAD = "27578c7b66b6"

ORDER_COLUMNS: tuple[tuple[str, str, str], ...] = (
    ("order_id", "INT NULL", "CRM 订单ID（orderAnalyze.id，发货明细靠它关联）"),
    ("ship_qty", "DECIMAL(18,4) NULL", "出货数量（发货明细 send_qty 汇总，发货时间口径优先）"),
)


def alembic_heads() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        print((result.stdout or "") + (result.stderr or ""))
        raise SystemExit(result.returncode)
    return [line.split()[0] for line in result.stdout.splitlines() if "(head)" in line]


def alembic_current() -> str:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "current"],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    text = (result.stdout or "") + (result.stderr or "")
    for line in text.splitlines():
        if line.strip():
            return line.split()[0]
    return ""


def alembic_stamp(revision: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "stamp", revision],
        cwd=str(PROJECT_ROOT), capture_output=True, text=True,
    )
    if result.returncode != 0:
        print((result.stdout or "") + (result.stderr or ""))
        raise SystemExit(result.returncode)
    print(f"  已 stamp：{revision}")


async def inspect_and_fix(apply: bool) -> None:
    from sqlalchemy import inspect, text

    from app.core.base_model import MappedBase
    from app.core.database import async_engine
    from app.modules.product.model import ProductLineAnalysisModel, ProductLineBuildRunModel
    from app.utils.import_util import ImportUtil

    ImportUtil.find_models(MappedBase)
    missing_tables: list = []
    missing_columns: list[str] = []
    missing_indexes: list[str] = []

    async with async_engine.begin() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        print("  ① 产品线表：")
        for table in (ProductLineAnalysisModel.__table__, ProductLineBuildRunModel.__table__):
            exists = table.name in names
            print(f"     {table.name:<32} {'存在 ✅' if exists else '缺失 ❌'}")
            if not exists:
                missing_tables.append(table)

        print("  ② dwd_order_full_chain 列：")
        if "dwd_order_full_chain" not in names:
            print("     ⚠️ 整张表都不存在，请先跑订单全链路迁移（alembic upgrade）")
        else:
            cols = {
                row[0]
                for row in (
                    await conn.execute(
                        text(
                            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'dwd_order_full_chain'"
                        )
                    )
                ).all()
            }
            for column, _ddl, _comment in ORDER_COLUMNS:
                exists = column in cols
                print(f"     {column:<32} {'存在 ✅' if exists else '缺失 ❌'}")
                if not exists:
                    missing_columns.append(column)
            indexes = await conn.run_sync(
                lambda c: {idx["name"] for idx in inspect(c).get_indexes("dwd_order_full_chain")}
            )
            if "ix_dwd_order_full_chain_order_id" not in indexes and "order_id" in cols:
                missing_indexes.append("ix_dwd_order_full_chain_order_id")

        print("  ③ open_client.allow_product_line_detail：")
        if "open_client" not in names:
            print("     ⚠️ open_client 表不存在")
        else:
            flag = (
                await conn.execute(
                    text(
                        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'open_client' "
                        "AND COLUMN_NAME = 'allow_product_line_detail'"
                    )
                )
            ).all()
            print(f"     {'存在 ✅' if flag else '缺失 ❌'}")
            if not flag:
                missing_columns.append("allow_product_line_detail")

        if not apply:
            return

        print("\n  --apply：开始补齐缺失部分")
        for table in missing_tables:
            await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
            print(f"     已建表：{table.name}")
        for column in missing_columns:
            if column == "allow_product_line_detail":
                await conn.execute(
                    text(
                        "ALTER TABLE open_client ADD COLUMN allow_product_line_detail "
                        "TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否允许查询产品线分析明细(默认不开放)'"
                    )
                )
            else:
                ddl, comment = next((d, c) for col, d, c in ORDER_COLUMNS if col == column)
                await conn.execute(
                    text(f"ALTER TABLE dwd_order_full_chain ADD COLUMN {column} {ddl} COMMENT '{comment}'")
                )
            print(f"     已加列：{column}")
        for index in missing_indexes:
            await conn.execute(
                text(f"CREATE INDEX {index} ON dwd_order_full_chain(order_id)")
            )
            print(f"     已建索引：{index}")
        if not (missing_tables or missing_columns or missing_indexes):
            print("     无需补齐（4 类对象都已在库里）")

    await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="补齐产品线 schema 并校准 alembic 版本")
    parser.add_argument("--apply", action="store_true", help="真正补齐（默认只体检）")
    args = parser.parse_args()

    print("=" * 78)
    print("产品线 schema 体检 / 修复")
    print("=" * 78)
    heads = alembic_heads()
    print(f"  alembic 文件侧 head：{heads}")
    print(f"  数据库当前版本    ：{alembic_current()}")
    if len(heads) != 1:
        print(f"\n  ❌ 文件侧有 {len(heads)} 个 head，先解决它（二选一）：")
        print("     · 保留两条链 → 合并：")
        print(f"         python -m alembic merge -m \"merge heads\" {' '.join(heads)}")
        print("     · 确认多余那条是本机自动生成的重复迁移 → 备份后删掉它的文件")
        print("  处理完再跑本脚本；本脚本只有在 head 唯一时才自动 stamp。")
    print()

    asyncio.run(inspect_and_fix(args.apply))

    heads = alembic_heads()
    print()
    if args.apply and len(heads) == 1:
        alembic_stamp(heads[0])
        print(f"  数据库版本已对齐到唯一 head：{heads[0]}")
    elif len(heads) == 1:
        print(f"  （未加 --apply，未改动数据库；当前唯一 head = {heads[0]}）")
    print()
    print("=" * 78)
    print("完成")
    print("=" * 78)


if __name__ == "__main__":
    main()
