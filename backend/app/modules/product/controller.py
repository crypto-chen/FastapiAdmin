"""产品线分析管理端接口（/product）。"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    ProductLineBuildResultSchema,
    ProductLineBuildRunOutSchema,
    ProductLineFieldOutSchema,
    ProductLineQueryParam,
)
from .service import ProductLineService, field_catalog

ProductLineRouter = APIRouter(route_class=OperationLogRoute, tags=["产品线分析"])


@ProductLineRouter.get("/fields", response_model=ResponseSchema[list[ProductLineFieldOutSchema]])
async def list_product_line_fields(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_product:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    """字段目录（PRD-xx）：前端据此动态渲染列，字段增减不改前端代码。"""
    return SuccessResponse(data=field_catalog(), msg="查询字段目录成功")


@ProductLineRouter.get("/periods", response_model=ResponseSchema[list[str]])
async def list_product_line_periods(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_product:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await ProductLineService(auth, db).periods(), msg="查询期间成功")


@ProductLineRouter.get("/product-lines", response_model=ResponseSchema[list[str]])
async def list_product_lines(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_product:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16)] = None,
) -> JSONResponse:
    """产品线大类候选（前端下拉，来自已构建结果）。"""
    result = await ProductLineService(auth, db).product_lines(period_value)
    return SuccessResponse(data=result, msg="查询产品线大类成功")


@ProductLineRouter.get("/stats", response_model=ResponseSchema[dict])
async def product_line_stats(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_product:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16)] = None,
) -> JSONResponse:
    """期间汇总 + 产品线 TopN（前端指标卡与排行榜）。"""
    result = await ProductLineService(auth, db).stats(period_value)
    return SuccessResponse(data=result, msg="查询产品线汇总成功")


@ProductLineRouter.get("/page", response_model=ResponseSchema[dict])
async def page_product_line_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_product:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[ProductLineQueryParam, Query()],
) -> JSONResponse:
    result = await ProductLineService(auth, db).page(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询产品线分析成功")


@ProductLineRouter.get("/runs", response_model=ResponseSchema[list[ProductLineBuildRunOutSchema]])
async def list_product_line_runs(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_product:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    result = await ProductLineService(auth, db).runs(period_value, limit)
    return SuccessResponse(data=result, msg="查询构建批次成功")


@ProductLineRouter.post("/rebuild", response_model=ResponseSchema[ProductLineBuildResultSchema])
async def rebuild_product_line_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_product:def:run"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Body(embed=True, max_length=16)] = None,
) -> JSONResponse:
    result = await ProductLineService(auth, db).rebuild(period_value)
    return SuccessResponse(data=result, msg="产品线分析构建完成")
