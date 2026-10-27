"""同步聚水潭店铺/平台名称到 `retail_shop`。

用法::

    cd backend
    python scripts/sync_jushuitan_shops.py
    python scripts/sync_jushuitan_shops.py --name "聚水潭默认连接"
"""

from __future__ import annotations

import argparse
import asyncio
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
from app.modules.retail.shop_service import RetailShopService  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


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
    parser = argparse.ArgumentParser(description="同步聚水潭店铺/平台名称")
    parser.add_argument("--source-id", type=int, default=None)
    parser.add_argument("--name", default="聚水潭默认连接")
    args = parser.parse_args()

    connection = await _load_connection(args.source_id, args.name)
    async with build_client(connection) as client:
        shops = [row async for row in client.iter_shops()]

    async with async_db_session() as db, db.begin():
        result = await RetailShopService(db).sync_shops(shops, source="jushuitan")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
