"""从聚水潭拉取非淘系订单并写入零售订单表。

说明：
- 使用聚水潭「订单查询」`/open/orders/single/query`（docId=22）；
- 该接口不返回淘系/拼多多订单，淘系走奇门、拼多多走方舟；
- 结果写入 `retail_order` / `retail_order_item`，页面「开放接口 → 零售订单同步」可见；
- 默认不回放指标批次，避免与销售出库口径混在一起；需要时加 `--publish-metric`。

用法::

    cd backend
    python scripts/sync_jushuitan_orders.py --name "聚水潭默认连接" --period 2026-10
    python scripts/sync_jushuitan_orders.py --source-id 1 --begin "2026-10-01 00:00:00" \
        --end "2026-10-07 23:59:59" --date-type 0
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.jushuitan.client import TIME_FORMAT, month_range  # noqa: E402
from app.modules.erp.jushuitan.model import JushuitanConnectionModel  # noqa: E402
from app.modules.erp.jushuitan.service import build_client  # noqa: E402
from app.modules.retail.service import RetailSyncService  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def _load_connection(source_id: int | None, name: str | None) -> JushuitanConnectionModel:
    async with async_db_session() as db:
        if source_id:
            obj = await db.get(JushuitanConnectionModel, source_id)
        else:
            obj = (
                await db.execute(
                    select(JushuitanConnectionModel).where(JushuitanConnectionModel.name == name)
                )
            ).scalars().first()
        if obj is None:
            raise SystemExit(f"聚水潭连接不存在：source_id={source_id} name={name}")
        if obj.status == 1:
            raise SystemExit(f"聚水潭连接已停用：{obj.name}")
        return obj


def _resolve_range(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.recent_days is not None:
        if args.recent_days <= 0:
            raise SystemExit("--recent-days 必须大于 0")
        end = datetime.now().replace(microsecond=0)
        begin = end - timedelta(days=args.recent_days)
        return begin, end
    if args.period:
        return month_range(args.period)
    if args.begin and args.end:
        try:
            begin = datetime.strptime(args.begin, TIME_FORMAT)
            end = datetime.strptime(args.end, TIME_FORMAT)
        except ValueError as exc:
            raise SystemExit("时间格式应为 yyyy-MM-dd HH:mm:ss") from exc
        if end < begin:
            raise SystemExit("结束时间不能早于起始时间")
        return begin, end
    raise SystemExit("请传 --period YYYY-MM 或 --begin/--end")


async def main() -> None:
    parser = argparse.ArgumentParser(description="同步聚水潭非淘系订单")
    parser.add_argument("--source-id", type=int, default=None, help="聚水潭连接配置 ID")
    parser.add_argument("--name", default="聚水潭默认连接", help="聚水潭连接名称")
    parser.add_argument("--period", default=None, help="月度期间 YYYY-MM")
    parser.add_argument("--recent-days", type=int, default=None, help="最近 N 天（适合每日定时任务）")
    parser.add_argument("--begin", default=None, help="起始时间 yyyy-MM-dd HH:mm:ss")
    parser.add_argument("--end", default=None, help="结束时间 yyyy-MM-dd HH:mm:ss")
    parser.add_argument("--date-type", type=int, default=0, choices=[0, 2, 3], help="0=修改时间 2=订单日期 3=发货时间")
    parser.add_argument("--status", default=None, help="订单状态，空=全部")
    parser.add_argument("--shop-id", type=int, default=None, help="只同步某个店铺")
    parser.add_argument("--page-size", type=int, default=100, help="每页条数，最大 100")
    parser.add_argument("--max-rows", type=int, default=20000, help="本次最多拉取行数")
    parser.add_argument("--publish-metric", action="store_true", help="同时回放到 meta_sync_run")
    parser.add_argument("--dry-run", action="store_true", help="只取数，不写库")
    args = parser.parse_args()

    begin, end = _resolve_range(args)
    connection = await _load_connection(args.source_id, args.name)
    extra = {"date_type": args.date_type}
    if args.status:
        extra["status"] = args.status
    if args.shop_id is not None:
        extra["shop_id"] = args.shop_id

    rows: list[dict] = []
    async with build_client(connection) as client:
        async for row in client.iter_orders(
            begin,
            end,
            page_size=max(1, min(args.page_size, 100)),
            **extra,
        ):
            rows.append(row)
            if len(rows) >= args.max_rows:
                break

    print(
        f"拉取完成：{begin:%Y-%m-%d %H:%M:%S} ~ {end:%Y-%m-%d %H:%M:%S}，"
        f"连接={connection.name}，订单={len(rows)}，date_type={args.date_type}"
    )
    if args.dry_run:
        if rows:
            print("首单字段：" + ", ".join(sorted(rows[0].keys())[:30]))
        await async_engine.dispose()
        return

    request_id = f"jst-orders-{begin:%Y%m%d%H%M}-{end:%Y%m%d%H%M}-{datetime.now():%H%M%S}"
    async with async_db_session() as db, db.begin():
        result = await RetailSyncService(db, app_id="jushuitan_pull").pull_orders(
            rows,
            source="jushuitan",
            request_id=request_id,
            publish_metric=args.publish_metric,
        )
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str))
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
