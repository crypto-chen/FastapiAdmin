"""管理端：开放接口应用配置与调用日志。"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from redis.asyncio.client import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter, redis_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    OpenApiLogOutSchema,
    OpenApiLogQueryParam,
    OpenClientCreateResultSchema,
    OpenClientCreateSchema,
    OpenClientOutSchema,
    OpenClientQueryParam,
    OpenClientUpdateSchema,
)
from .service import OpenApiLogService, OpenClientService

OpenClientRouter = APIRouter(route_class=OperationLogRoute, prefix="/client", tags=["开放接口应用"])
OpenApiLogRouter = APIRouter(route_class=OperationLogRoute, prefix="/log", tags=["开放接口日志"])


@OpenClientRouter.get("/page", response_model=ResponseSchema[PageResultSchema[OpenClientOutSchema]])
async def page_open_client(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:client:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[OpenClientQueryParam, Query()],
) -> JSONResponse:
    result = await OpenClientService(auth, db).page(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询开放应用成功")


@OpenClientRouter.get("/detail/{id}", response_model=ResponseSchema[OpenClientOutSchema])
async def detail_open_client(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:client:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await OpenClientService(auth, db).detail(id)
    return SuccessResponse(data=result, msg="查询开放应用详情成功")


@OpenClientRouter.post(
    "/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[OpenClientCreateResultSchema]
)
async def create_open_client(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:client:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[OpenClientCreateSchema, Body()],
) -> JSONResponse:
    result = await OpenClientService(auth, db).create(data)
    return SuccessResponse(data=result, msg="创建开放应用成功，请立即保存密钥（仅本次显示）")


@OpenClientRouter.put("/update/{id}", response_model=ResponseSchema[OpenClientOutSchema])
async def update_open_client(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:client:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[OpenClientUpdateSchema, Body()],
) -> JSONResponse:
    result = await OpenClientService(auth, db).update(id, data, redis)
    return SuccessResponse(data=result, msg="修改开放应用成功")


@OpenClientRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_open_client(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:client:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await OpenClientService(auth, db).delete(ids, redis)
    return SuccessResponse(msg="删除开放应用成功")


@OpenClientRouter.post("/reset-secret/{id}", response_model=ResponseSchema[OpenClientCreateResultSchema])
async def reset_open_client_secret(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:client:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    redis: Annotated[Redis, Depends(redis_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await OpenClientService(auth, db).reset_secret(id, redis)
    return SuccessResponse(data=result, msg="重置密钥成功，旧密钥与旧令牌已失效")


@OpenClientRouter.get("/org-options", response_model=ResponseSchema[list[dict]])
async def open_client_org_options(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:client:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await OpenClientService(auth, db).org_options()
    return SuccessResponse(data=result, msg="查询组织选项成功")


@OpenApiLogRouter.get("/page", response_model=ResponseSchema[PageResultSchema[OpenApiLogOutSchema]])
async def page_open_api_log(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_openapi:log:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[OpenApiLogQueryParam, Query()],
) -> JSONResponse:
    result = await OpenApiLogService(auth, db).page(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询调用日志成功")
