"""开放接口依赖：令牌校验、应用状态校验、IP 白名单、限流。"""

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import db_getter, redis_getter
from app.core.exceptions import CustomException
from app.modules.openapi.model import OpenClientModel
from app.modules.openapi.security import (
    CODE_CLIENT_FORBIDDEN,
    CODE_UNAUTHORIZED,
    check_rate_limit,
    decode_open_token,
    ensure_client_usable,
    extract_bearer_token,
    ip_allowed,
    is_token_active,
)
from app.utils.ip_local_util import get_client_ip


async def get_open_client(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
) -> OpenClientModel:
    """校验开放令牌并返回调用方应用，并写入 ``request.state`` 供日志与业务读取。"""
    token = extract_bearer_token(request.headers.get("Authorization"))
    payload = decode_open_token(token)
    app_id = str(payload.get("app_id") or "")
    jti = str(payload.get("jti") or "")
    if not app_id or not jti:
        raise CustomException(msg="访问令牌无效", code=CODE_UNAUTHORIZED, status_code=401)

    if not await is_token_active(redis, app_id, jti):
        raise CustomException(msg="访问令牌已失效，请重新获取", code=CODE_UNAUTHORIZED, status_code=401)

    client = (
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
    if client is None:
        raise CustomException(msg="应用不存在或已删除", code=CODE_UNAUTHORIZED, status_code=401)

    ensure_client_usable(client)

    client_ip = get_client_ip(request)
    if not ip_allowed(client_ip, client.ip_whitelist):
        raise CustomException(
            msg=f"调用方 IP {client_ip} 不在白名单内",
            code=CODE_CLIENT_FORBIDDEN,
            status_code=403,
        )

    await check_rate_limit(redis, client)

    request.state.open_client = client
    request.state.open_client_ip = client_ip
    return client


OpenClientDep = Annotated[OpenClientModel, Depends(get_open_client)]
