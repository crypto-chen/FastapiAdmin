"""查询聚水潭已接入店铺（平台 + 店铺 + 授权状态）。

用法::

    cd backend
    python scripts/list_jushuitan_shops.py
    python scripts/list_jushuitan_shops.py --name "聚水潭默认连接" --json
    python scripts/list_jushuitan_shops.py --name "聚水潭默认连接" --output shops.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.jushuitan.model import JushuitanConnectionModel  # noqa: E402
from app.modules.erp.jushuitan.service import build_client  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SESSION_STATUS = {0: "未授权", 1: "已过期", 2: "已授权", 3: "无需授权"}
FIELDS = [
    "shop_id",
    "shop_name",
    "shop_site",
    "platform_shop_name",
    "session_status",
    "session_expired",
    "co_id",
    "nick",
    "group_name",
]


async def _load_connection(source_id: int | None, name: str) -> JushuitanConnectionModel:
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


async def main() -> None:
    parser = argparse.ArgumentParser(description="查询聚水潭接入店铺")
    parser.add_argument("--source-id", type=int, default=None)
    parser.add_argument("--name", default="聚水潭默认连接")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument("--output", default=None, help="导出 CSV 文件路径")
    args = parser.parse_args()

    connection = await _load_connection(args.source_id, args.name)
    async with build_client(connection) as client:
        shops = [row async for row in client.iter_shops()]

    output = []
    for row in shops:
        output.append(
            {
                "shop_id": row.get("shop_id"),
                "shop_name": row.get("shop_name"),
                "shop_site": row.get("shop_site"),
                "platform_shop_name": row.get("platform_shop_name"),
                "session_status": row.get("session_status"),
                "session_expired": row.get("session_expired"),
                "co_id": row.get("co_id"),
                "nick": row.get("nick"),
                "group_name": row.get("group_name"),
            }
        )

    if args.output:
        with Path(args.output).open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(output)
        print(f"已导出 {len(output)} 个店铺到 {args.output}")
        await async_engine.dispose()
        return

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"店铺数：{len(output)}")
        for row in output:
            status = SESSION_STATUS.get(row["session_status"], row["session_status"])
            print(
                f"{row['shop_id']} | {row['shop_name']} | {row['shop_site']} | "
                f"{row['platform_shop_name'] or '-'} | {status}"
            )
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
