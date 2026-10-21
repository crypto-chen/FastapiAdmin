"""回滚 orderAnalyze type=3（零售）本次变更写入的数据库对象。

只删除本次上线时间点之后创建的数据，保留历史版本：
- type=3 来源对象 / 同步任务 / 批次；
- dwd_order_full_chain、dwd_customer_analysis、dwd_product_line_analysis 新版本；
- 受影响业务员指标的新 metric_value 版本；
- metric_def 恢复为 db_before.json 里的定义。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2] / "backend"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import delete, select, text  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, MetaSyncRunModel, SourceObjectModel  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

RETAIL_OBJECT = "/hs/order/orderAnalyze?type=3"
HERE = Path(__file__).resolve().parent
BEFORE_FILE = HERE / "db_before.json"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2026-10-21 09:50:00", help="上线开始时间（本地时间）")
    args = parser.parse_args()
    since = datetime.strptime(args.since, "%Y-%m-%d %H:%M:%S")

    before = json.loads(BEFORE_FILE.read_text(encoding="utf-8"))
    async with async_db_session() as db, db.begin():
        # 1) 删除 type=3 来源对象 / 任务 / 批次
        object_ids = (
            await db.execute(select(SourceObjectModel.id).where(SourceObjectModel.code == RETAIL_OBJECT))
        ).scalars().all()
        job_ids = (
            await db.execute(select(MetaSyncJobModel.id).where(MetaSyncJobModel.source_object_id.in_(object_ids)))
        ).scalars().all() if object_ids else []
        if job_ids:
            await db.execute(delete(MetaSyncRunModel).where(MetaSyncRunModel.job_id.in_(job_ids)))
            await db.execute(delete(MetaSyncJobModel).where(MetaSyncJobModel.id.in_(job_ids)))
        if object_ids:
            await db.execute(delete(SourceObjectModel).where(SourceObjectModel.id.in_(object_ids)))

        # 2) 删除本次构建的新版本（按 created_time）
        for table in ("dwd_order_full_chain", "dwd_customer_analysis", "dwd_product_line_analysis"):
            await db.execute(text(f"DELETE FROM {table} WHERE created_time >= :since"), {"since": since})

        # 3) 删除受影响指标本次重算的新结果
        metric_ids = [int(item["id"]) for item in before.get("metric_def", [])]
        if metric_ids:
            await db.execute(
                delete(MetricValueModel).where(
                    MetricValueModel.metric_id.in_(metric_ids),
                    MetricValueModel.created_time >= since,
                )
            )

        # 4) 恢复指标定义
        for item in before.get("metric_def", []):
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == item["code"]))
            ).scalars().first()
            if metric is None:
                continue
            for key in ("name", "formula", "measures", "excel_code", "category", "description"):
                setattr(metric, key, item.get(key))

    await async_engine.dispose()
    print("数据库回滚完成：已删除 type=3 批次与本次新版本，指标定义已恢复。")


if __name__ == "__main__":
    asyncio.run(main())
