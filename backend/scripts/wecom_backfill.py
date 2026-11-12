"""企业微信通讯录 / 打卡历史补数。

用法（在 backend 目录执行）：

    python scripts/wecom_backfill.py --start 2026-07-01 --end 2026-07-31
    python scripts/wecom_backfill.py --skip-roster --start 2026-07-01 --end 2026-07-31
    python scripts/wecom_backfill.py --skip-checkin
    python scripts/wecom_backfill.py --only-marketing --start 2026-11-01 --end 2026-11-12

首次部署先跑一次 ``--skip-checkin`` 同步通讯录，再按 30 天分段补打卡。
"""

import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.erp.wecom.service import sync_checkin, sync_roster  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"日期格式应为 YYYY-MM-DD: {value}") from exc


async def main() -> None:
    parser = argparse.ArgumentParser(description="企业微信通讯录/打卡补数")
    parser.add_argument("--start", type=_parse_date, help="打卡开始日期 YYYY-MM-DD")
    parser.add_argument("--end", type=_parse_date, help="打卡结束日期 YYYY-MM-DD")
    parser.add_argument("--connection-id", type=int, default=None, help="连接配置ID")
    parser.add_argument("--skip-roster", action="store_true", help="跳过通讯录同步")
    parser.add_argument("--skip-checkin", action="store_true", help="跳过打卡同步")
    parser.add_argument("--only-marketing", action="store_true", help="只同步 YG20 开头的营销人员")
    parser.add_argument("--userid", default=None, help="指定工号，多个用逗号分隔")
    args = parser.parse_args()

    if not args.skip_checkin and (args.start is None or args.end is None):
        parser.error("同步打卡时必须同时传 --start 和 --end")
    if args.start and args.end and args.end < args.start:
        parser.error("--end 不能早于 --start")

    summary: dict[str, object] = {}
    async with async_db_session() as db, db.begin():
        if not args.skip_roster:
            summary["roster"] = await sync_roster(db, connection_id=args.connection_id)
        if not args.skip_checkin:
            userids = [item.strip() for item in (args.userid or "").split(",") if item.strip()] or None
            summary["checkin"] = await sync_checkin(
                db,
                start_date=args.start,
                end_date=args.end,
                connection_id=args.connection_id,
                userids=userids,
                only_marketing=args.only_marketing,
            )

    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    logger.info(f"企业微信补数完成：{summary}")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

