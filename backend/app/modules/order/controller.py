"""订单全链路管理端接口（/order）。"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    OrderBuildResultSchema,
    OrderBuildRunOutSchema,
    OrderFieldOutSchema,
    OrderQueryParam,
)
from .service import OrderService, field_catalog

# 域名前缀由 api/v1/routers.py 的 "/order" 提供，这里不再重复，避免 /order/order/*
OrderRouter = APIRouter(route_class=OperationLogRoute, tags=["订单全链路"])


@OrderRouter.get("/fields", response_model=ResponseSchema[list[OrderFieldOutSchema]])
async def list_order_fields(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_order:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    """字段目录：前端据此动态渲染列，字段增减不需要改前端代码。"""
    return SuccessResponse(data=field_catalog(), msg="查询字段目录成功")


@OrderRouter.get("/periods", response_model=ResponseSchema[list[str]])
async def list_order_periods(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_order:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await OrderService(auth, db).periods(), msg="查询期间成功")


@OrderRouter.get("/page", response_model=ResponseSchema[dict])
async def page_order_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_order:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[OrderQueryParam, Query()],
) -> JSONResponse:
    result = await OrderService(auth, db).page(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询订单全链路成功")


@OrderRouter.get("/detail/{order_number}", response_model=ResponseSchema[dict])
async def detail_order_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_order:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    order_number: Annotated[str, Path(min_length=1, max_length=64)],
) -> JSONResponse:
    result = await OrderService(auth, db).detail(order_number)
    return SuccessResponse(data=result, msg="查询订单详情成功")


@OrderRouter.get("/runs", response_model=ResponseSchema[list[OrderBuildRunOutSchema]])
async def list_order_runs(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_order:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    result = await OrderService(auth, db).runs(period_value, limit)
    return SuccessResponse(data=result, msg="查询构建批次成功")


@OrderRouter.post("/rebuild", response_model=ResponseSchema[OrderBuildResultSchema])
async def rebuild_order_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_order:def:run"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Body(embed=True, max_length=16)] = None,
) -> JSONResponse:
    result = await OrderService(auth, db).rebuild(period_value)
    return SuccessResponse(data=result, msg="订单全链路构建完成")
