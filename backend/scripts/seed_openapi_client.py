"""新建（或查看）一个开放接口接入应用，并打印一次性密钥。

用法：
    python scripts/seed_openapi_client.py --app-id bi_report --name "BI 报表平台"
    python scripts/seed_openapi_client.py --app-id bi_report --rate-limit 1200 --org-scope 01,02

说明：
- 应用已存在时不重置密钥（避免打断正在对接的外部系统），只打印提示；
  确需换密钥请在管理界面「重置密钥」。
- 密钥仅此一次明文输出，请立即交给对接方并妥善保存。
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
    parser = argparse.ArgumentParser(description="新建开放接口接入应用")
    parser.add_argument("--app-id", required=True, help="应用标识，例如 bi_report")
    parser.add_argument("--name", default=None, help="应用名称，缺省与 app-id 相同")
    parser.add_argument("--rate-limit", type=int, default=600, help="每分钟最大请求数，默认 600")
    parser.add_argument("--token-ttl", type=int, default=7200, help="令牌有效期(秒)，默认 7200")
    parser.add_argument("--ip-whitelist", default=None, help="IP 白名单，逗号分隔，支持 192.168.1.*")
    parser.add_argument("--org-scope", default=None, help="允许的组织编码，逗号分隔，空=全部组织")
    parser.add_argument("--allow-dept-detail", action="store_true", help="允许查询部门/客户核算维度明细")
    parser.add_argument("--allow-run-calc", action="store_true", help="允许外部触发指标重算")
    args = parser.parse_args()

    app_id = args.app_id.strip()
    async with async_db_session() as db, db.begin():
        exists = (
            await db.execute(
                select(OpenClientModel).where(OpenClientModel.app_id == app_id, OpenClientModel.is_deleted == False)  # noqa: E712
            )
        ).scalars().first()
        if exists is not None:
            print(f"应用已存在，未重置密钥：app_id={app_id}（如需换密钥请在管理界面重置）")
            return

        secret = generate_app_secret()
        db.add(
            OpenClientModel(
                app_id=app_id,
                name=args.name or app_id,
                secret_hash=await hash_app_secret(secret),
                rate_limit=args.rate_limit,
                token_ttl_seconds=args.token_ttl,
                ip_whitelist=args.ip_whitelist,
                org_scope=[code.strip() for code in (args.org_scope or "").split(",") if code.strip()] or None,
                allow_dept_detail=args.allow_dept_detail,
                allow_run_calc=args.allow_run_calc,
                status=0,
            )
        )

    print("接入应用创建成功，以下密钥仅显示一次：")
    print(f"  app_id     = {app_id}")
    print(f"  app_secret = {secret}")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
