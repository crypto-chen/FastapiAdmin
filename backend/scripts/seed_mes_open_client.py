"""为 MES 创建开放接口接入应用（只读订单权限）。

用法：
    python scripts/seed_mes_open_client.py --app-id mes --name "MES 系统" --ip-whitelist 10.0.0.25
    python scripts/seed_mes_open_client.py --app-id mes_domestic --trade-type domestic

说明：
- 复用开放接口的 ``allow_order_detail`` 权限，MES 只能读 /open/v1/mes/orders；
- ``--trade-type`` 控制应用级范围：both（默认）/ domestic / export；
- 密钥只输出一次，应用已存在时不重置，避免打断正在运行的对接。
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.openapi.model import OpenClientModel  # noqa: E402
from app.modules.openapi.security import generate_app_secret, hash_app_secret  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    parser = argparse.ArgumentParser(description="创建 MES 开放接口应用")
    parser.add_argument("--app-id", default="mes", help="应用标识，默认 mes")
    parser.add_argument("--name", default="MES 系统", help="应用名称")
    parser.add_argument("--rate-limit", type=int, default=600, help="每分钟最大请求数，默认 600")
    parser.add_argument("--token-ttl", type=int, default=7200, help="令牌有效期(秒)，默认 7200")
    parser.add_argument("--ip-whitelist", default=None, help="调用方 IP 白名单，逗号分隔")
    parser.add_argument(
        "--trade-type",
        choices=("both", "domestic", "export"),
        default="both",
        help="允许查询的贸易类型，默认 both",
    )
    args = parser.parse_args()

    app_id = args.app_id.strip()
    scope = None if args.trade_type == "both" else {"trade_type": args.trade_type}
    async with async_db_session() as db, db.begin():
        exists = (
            (
                await db.execute(
                    select(OpenClientModel).where(
                        OpenClientModel.app_id == app_id,
                        OpenClientModel.is_deleted == False,  # noqa: E712
                    )
                )
            )
            .scalars()
            .first()
        )
        if exists is not None:
            print(f"应用已存在，未重置密钥：app_id={app_id}")
            return

        secret = generate_app_secret()
        db.add(
            OpenClientModel(
                app_id=app_id,
                name=args.name,
                secret_hash=await hash_app_secret(secret),
                rate_limit=args.rate_limit,
                token_ttl_seconds=args.token_ttl,
                ip_whitelist=args.ip_whitelist,
                allow_order_detail=True,
                order_scope=scope,
                status=0,
            )
        )

    print("MES 接入应用创建成功，以下密钥仅显示一次：")
    print(f"  app_id     = {app_id}")
    print(f"  app_secret = {secret}")
    print(f"  权限       = allow_order_detail=True, trade_type={args.trade_type}")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
