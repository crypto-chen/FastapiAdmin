"""恢复服务器本地噪声迁移误删的外键（MySQL）。

背景：服务器上未跟踪的自动迁移 29bf6c113584 先 create 再 drop 同一批外键，
净效果是外键被删除。本脚本按表/列检查，只补缺失的外键，已存在则跳过。

在 backend 目录执行：

    python ..\\deploy\\metric-rule-version-20261113\\repair_fk.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import inspect, text

from app.core.database import async_engine

SET_NULL = "SET NULL"
CASCADE = "CASCADE"

TARGETS: list[tuple[str, str, str, str, str]] = [
    ("retail_order_item", "order_id", "retail_order", "id", CASCADE),
    ("retail_after_sale_item", "after_sale_id", "retail_after_sale", "id", CASCADE),
]

for table in (
    "erp_wecom_connection",
    "dwd_product_line_build_run",
    "dwd_product_line_analysis",
    "dwd_order_full_chain",
    "dwd_order_build_run",
    "dwd_customer_build_run",
    "dwd_customer_analysis",
    "dwd_cost_bill_workorder",
):
    for column in ("created_id", "updated_id", "deleted_id"):
        TARGETS.append((table, column, "sys_user", "id", SET_NULL))


async def main() -> None:
    restored = 0
    skipped = 0
    async with async_engine.begin() as conn:
        for table, column, ref_table, ref_column, ondelete in TARGETS:
            fks = await conn.run_sync(lambda c, t=table: inspect(c).get_foreign_keys(t))
            exists = any(
                fk.get("constrained_columns") == [column]
                and fk.get("referred_table") == ref_table
                for fk in fks
            )
            if exists:
                skipped += 1
                continue
            name = f"fk_{table}_{column}_{ref_table}"
            sql = (
                f"ALTER TABLE `{table}` ADD CONSTRAINT `{name}` "
                f"FOREIGN KEY (`{column}`) REFERENCES `{ref_table}` (`{ref_column}`) "
                f"ON UPDATE CASCADE ON DELETE {ondelete}"
            )
            await conn.execute(text(sql))
            restored += 1
            print(f"RESTORED {name}")
    await async_engine.dispose()
    print(f"FK_REPAIR_OK restored={restored} skipped={skipped}")


if __name__ == "__main__":
    asyncio.run(main())
