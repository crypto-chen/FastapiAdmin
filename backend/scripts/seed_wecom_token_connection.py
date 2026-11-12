"""写入/更新「PHP 兼容模式」的企业微信连接（免填 Secret）。

按旧 PHP ``QwApi::getAccessToken`` 的逻辑，token 由既有服务返回：
``http://crm.yonggubox.com/qywechat/yg_technology_app/getAccessTokens/key/...``

用法（backend 目录）：
    python scripts/seed_wecom_token_connection.py
    python scripts/seed_wecom_token_connection.py --name 企微默认 --token-url http://...
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover
        pass

from sqlalchemy import select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.wecom.model import WeComConnectionModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

DEFAULT_TOKEN_URL = os.getenv("WECOM_TOKEN_URL", "")


async def main() -> None:
    parser = argparse.ArgumentParser(description="写入 PHP 兼容模式的企业微信连接")
    parser.add_argument("--name", default="企微默认", help="连接名称，默认「企微默认」")
    parser.add_argument(
        "--token-url",
        default=None,
        help="Token 服务 URL；不传时读环境变量 WECOM_TOKEN_URL（避免把密钥提交到仓库）",
    )
    parser.add_argument("--corp-id", default="token-mode", help="企业ID；Token 模式可留默认值")
    args = parser.parse_args()
    token_url = (args.token_url or DEFAULT_TOKEN_URL).strip()
    if not token_url:
        parser.error("请通过 --token-url 或环境变量 WECOM_TOKEN_URL 提供 Token 服务 URL")

    async with async_db_session() as db, db.begin():
        obj = (
            await db.execute(
                select(WeComConnectionModel).where(
                    WeComConnectionModel.name == args.name,
                    WeComConnectionModel.is_deleted.is_(False),
                )
            )
        ).scalars().first()
        if obj is None:
            obj = WeComConnectionModel(name=args.name)
            db.add(obj)
        obj.corp_id = args.corp_id
        obj.token_url = token_url
        obj.status = 0
        obj.description = "PHP QwApi 兼容模式：token 由既有服务返回，无需填写 Secret"
        await db.flush()
        print(f"connection_id={obj.id} name={obj.name} token_url_set={bool(obj.token_url)}")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

