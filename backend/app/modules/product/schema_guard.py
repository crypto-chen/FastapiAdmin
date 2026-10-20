"""产品线相关表的「建表兜底」：库里缺表时，脚本按模型元数据自己补。

背景：仓库多次出现多 head + 手工 ``alembic stamp`` 把版本号指到新 head、但 DDL 没执行，
结果库版本号是新的、表却不存在，脚本一跑就 ``1146 Table ... doesn't exist``。
这里用 ``checkfirst=True`` 建表：幂等、不动已有数据，脚本因此可以自愈。
"""

from __future__ import annotations

import logging

from sqlalchemy import Table, inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from .model import CostBillWorkOrderModel, ProductLineAnalysisModel, ProductLineBuildRunModel

logger = logging.getLogger(__name__)

PRODUCT_TABLES: tuple[Table, ...] = (
    ProductLineAnalysisModel.__table__,
    ProductLineBuildRunModel.__table__,
    CostBillWorkOrderModel.__table__,
)


async def ensure_tables(engine: AsyncEngine, tables: tuple[Table, ...] = PRODUCT_TABLES) -> list[str]:
    """缺哪张建哪张，返回本次新建的表名（都已存在则为空列表）。"""
    created: list[str] = []
    async with engine.begin() as conn:
        names = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        for table in tables:
            if table.name in names:
                continue
            await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
            created.append(table.name)
    for name in created:
        logger.warning("表 %s 不存在，已按模型元数据补建；建议随后跑一次 alembic upgrade head 对齐版本号", name)
    return created


async def ensure_cost_bill_table(engine: AsyncEngine) -> list[str]:
    """只兜底成本计算单工单表（``sync_cost_bill_workorders.py`` 用）。"""
    return await ensure_tables(engine, (CostBillWorkOrderModel.__table__,))
