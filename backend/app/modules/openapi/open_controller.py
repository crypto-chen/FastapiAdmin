"""对外开放接口（前缀 /open/v1）：换令牌、指标目录、批量取数、组织字典、触发重算。"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Request
from fastapi.responses import JSONResponse
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.dependencies import db_getter, redis_getter
from app.core.exceptions import CustomException
from app.modules.openapi.dependencies import OpenClientDep
from app.modules.openapi.model import OpenClientModel
from app.modules.openapi.route_class import OpenApiLogRoute
from app.modules.openapi.schema import (
    OpenMetricQuerySchema,
    OpenMetricRunResultSchema,
    OpenOrgOutSchema,
    OpenTokenOutSchema,
    OpenTokenRequestSchema,
)
from app.modules.openapi.security import (
    CODE_UNAUTHORIZED,
    check_rate_limit,
    create_open_token,
    ensure_client_usable,
    ip_allowed,
    store_token,
    verify_app_secret,
)
from app.modules.openapi.service import OpenApiService
from app.utils.ip_local_util import get_client_ip

OpenAuthRouter = APIRouter(route_class=OpenApiLogRoute, prefix="/auth", tags=["开放接口-认证"])
OpenMetricRouter = APIRouter(route_class=OpenApiLogRoute, prefix="/metrics", tags=["开放接口-指标"])
OpenOrgRouter = APIRouter(route_class=OpenApiLogRoute, prefix="/orgs", tags=["开放接口-组织"])


@OpenAuthRouter.post("/token", summary="获取访问令牌", response_model=ResponseSchema[OpenTokenOutSchema])
async def issue_open_token(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    data: Annotated[OpenTokenRequestSchema, Body()],
) -> JSONResponse:
    """应用凭证换令牌（client_credentials）。密钥错误与密钥过期返回同一提示，避免探测应用是否存在。"""
    client = (
        (
            await db.execute(
                select(OpenClientModel).where(
                    OpenClientModel.app_id == data.app_id.strip(),
                    OpenClientModel.is_deleted == False,  # noqa: E712
                )
            )
        )
        .scalars()
        .first()
    )
    if client is None or not await verify_app_secret(data.app_secret, client.secret_hash):
        raise CustomException(msg="app_id 或 app_secret 不正确", code=CODE_UNAUTHORIZED, status_code=401)

    ensure_client_usable(client)
    client_ip = get_client_ip(request)
    if not ip_allowed(client_ip, client.ip_whitelist):
        raise CustomException(
            msg=f"调用方 IP {client_ip} 不在白名单内",
            code=CODE_UNAUTHORIZED,
            status_code=401,
        )
    # 换令牌与业务调用分开计数：密钥校验本身有 PBKDF2 成本，这里再限制单应用每分钟换令牌次数
    await check_rate_limit(redis, client, limit_override=30, scope="token")

    token, ttl, jti = create_open_token(client.app_id, client.token_ttl_seconds)
    await store_token(redis, client.app_id, jti, ttl)
    request.state.open_client = client
    request.state.open_client_ip = client_ip
    return SuccessResponse(
        data=OpenTokenOutSchema(access_token=token, expires_in=ttl).model_dump(),
        msg="获取令牌成功",
    )


@OpenMetricRouter.get("", summary="查询可读指标目录", response_model=ResponseSchema[dict])
async def page_open_metrics(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    keyword: Annotated[str | None, Query(max_length=64, description="按编码/名称模糊查询")] = None,
    page_no: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=200, description="每页数量")] = 50,
) -> JSONResponse:
    result = await OpenApiService(db).page_metrics(keyword, page_no, page_size)
    return SuccessResponse(data=result, msg="查询指标目录成功")


@OpenMetricRouter.post("/query", summary="批量查询指标结果", response_model=ResponseSchema[dict])
async def query_open_metrics(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[OpenMetricQuerySchema, Body()],
) -> JSONResponse:
    result = await OpenApiService(db).query_metrics(client, data)
    msg = "查询成功" if not result.get("errors") else "部分指标不可读，请查看 errors"
    return SuccessResponse(data=result, msg=msg)


@OpenMetricRouter.post(
    "/{code}/run", summary="触发指标重算", response_model=ResponseSchema[OpenMetricRunResultSchema]
)
async def run_open_metric(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    code: Annotated[str, Path(min_length=1, max_length=128, description="指标编码")],
    period_value: Annotated[str | None, Query(max_length=32, description="期间值，缺省当前期间")] = None,
) -> JSONResponse:
    result = await OpenApiService(db).run_metric(client, code, period_value)
    return SuccessResponse(data=result, msg="指标重算完成")


@OpenOrgRouter.get("", summary="查询可见组织字典", response_model=ResponseSchema[list[OpenOrgOutSchema]])
async def list_open_orgs(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await OpenApiService(db).list_orgs(client)
    return SuccessResponse(data=result, msg="查询组织字典成功")
