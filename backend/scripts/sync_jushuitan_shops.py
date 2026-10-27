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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.retail.shop_service import sync_jushuitan_shops  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

async def main() -> None:
    parser = argparse.ArgumentParser(description="同步聚水潭店铺/平台名称")
    parser.add_argument("--source-id", type=int, default=None)
    parser.add_argument("--name", default="聚水潭默认连接")
    args = parser.parse_args()

    try:
        async with async_db_session() as db, db.begin():
            result = await sync_jushuitan_shops(
                db, connection_id=args.source_id, name=args.name if not args.source_id else None
            )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
