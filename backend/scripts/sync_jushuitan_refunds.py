"""从聚水潭拉取非淘系售后单（退货退款）并写入零售售后表。

说明：
- 使用聚水潭「售后单查询」``/open/refund/single/query``（docType=9&docId=38）；
- 该接口不返回淘系售后单（拼多多仅近 3 个月），淘系走奇门推送
  ``POST /open/v1/retail/aftersales/sync``；
- 时间窗最长 7 天、每页最多 50 条，脚本已自动分段与翻页；
- 结果写入 ``retail_after_sale`` / ``retail_after_sale_item``，页面
  「开放接口 → 零售订单同步 → 退款售后」可见。

用法::

    cd backend
    python scripts/sync_jushuitan_refunds.py --period 2026-10
    python scripts/sync_jushuitan_refunds.py --recent-days 7
    python scripts/sync_jushuitan_refunds.py --begin "2026-10-01 00:00:00" \
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
from app.modules.retail.aftersale_service import RetailAfterSaleSyncService  # noqa: E402
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
    raise SystemExit("请传 --period YYYY-MM、--recent-days N 或 --begin/--end")


async def main() -> None:
    parser = argparse.ArgumentParser(description="同步聚水潭非淘系售后单")
    parser.add_argument("--source-id", type=int, default=None, help="聚水潭连接配置 ID")
    parser.add_argument("--name", default="聚水潭默认连接", help="聚水潭连接名称")
    parser.add_argument("--period", default=None, help="月度期间 YYYY-MM")
    parser.add_argument("--recent-days", type=int, default=None, help="最近 N 天")
    parser.add_argument("--begin", default=None, help="起始时间 yyyy-MM-dd HH:mm:ss")
    parser.add_argument("--end", default=None, help="结束时间 yyyy-MM-dd HH:mm:ss")
    parser.add_argument(
        "--date-type", type=int, default=0, choices=[0, 1, 2], help="0=修改时间 1=创建时间 2=确认时间"
    )
    parser.add_argument("--status", default=None, help="售后状态，空=全部")
    parser.add_argument("--type", default=None, help="售后类型，如 退货退款/仅退款")
    parser.add_argument("--shop-id", type=int, default=None, help="只同步某个店铺")
    parser.add_argument("--max-rows", type=int, default=20000, help="本次最多拉取行数")
    parser.add_argument("--dry-run", action="store_true", help="只取数，不写库")
    args = parser.parse_args()

    begin, end = _resolve_range(args)
    connection = await _load_connection(args.source_id, args.name)
    extra: dict = {"date_type": args.date_type}
    if args.status:
        extra["status"] = args.status
    if args.type:
        extra["type"] = args.type
    if args.shop_id is not None:
        extra["shop_id"] = args.shop_id

    rows: list[dict] = []
    async with build_client(connection) as client:
        async for row in client.iter_refunds(begin, end, **extra):
            rows.append(row)
            if len(rows) >= args.max_rows:
                break

    print(
        f"拉取完成：{begin:%Y-%m-%d %H:%M:%S} ~ {end:%Y-%m-%d %H:%M:%S}，"
        f"连接={connection.name}，售后单={len(rows)}，date_type={args.date_type}"
    )
    if args.dry_run:
        if rows:
            print("首单字段：" + ", ".join(sorted(rows[0].keys())[:30]))
        await async_engine.dispose()
        return

    request_id = f"jst-as-{begin:%Y%m%d%H%M}-{end:%Y%m%d%H%M}-{datetime.now():%H%M%S}"
    async with async_db_session() as db, db.begin():
        result = await RetailAfterSaleSyncService(db, app_id="jushuitan_pull").pull_refunds(
            rows,
            source="jushuitan",
            request_id=request_id,
        )
    print(json.dumps(result.model_dump(), ensure_ascii=False, indent=2, default=str))
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
