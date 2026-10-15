"""客户分析管理端接口（/customer）。"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    CustomerBuildResultSchema,
    CustomerBuildRunOutSchema,
    CustomerFieldOutSchema,
    CustomerQueryParam,
)
from .service import CustomerService, field_catalog

CustomerRouter = APIRouter(route_class=OperationLogRoute, tags=["客户分析"])


@CustomerRouter.get("/fields", response_model=ResponseSchema[list[CustomerFieldOutSchema]])
async def list_customer_fields(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_customer:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    """字段目录（CUS-xx）：前端据此动态渲染列，字段增减不改前端代码。"""
    return SuccessResponse(data=field_catalog(), msg="查询字段目录成功")


@CustomerRouter.get("/periods", response_model=ResponseSchema[list[str]])
async def list_customer_periods(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_customer:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    return SuccessResponse(data=await CustomerService(auth, db).periods(), msg="查询期间成功")


@CustomerRouter.get("/page", response_model=ResponseSchema[dict])
async def page_customer_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_customer:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[CustomerQueryParam, Query()],
) -> JSONResponse:
    result = await CustomerService(auth, db).page(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询客户分析成功")


@CustomerRouter.get("/detail/{customer_code}", response_model=ResponseSchema[dict])
async def detail_customer_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_customer:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    customer_code: Annotated[str, Path(min_length=1, max_length=64)],
) -> JSONResponse:
    result = await CustomerService(auth, db).detail(customer_code)
    return SuccessResponse(data=result, msg="查询客户详情成功")


@CustomerRouter.get("/runs", response_model=ResponseSchema[list[CustomerBuildRunOutSchema]])
async def list_customer_runs(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_customer:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> JSONResponse:
    result = await CustomerService(auth, db).runs(period_value, limit)
    return SuccessResponse(data=result, msg="查询构建批次成功")


@CustomerRouter.post("/rebuild", response_model=ResponseSchema[CustomerBuildResultSchema])
async def rebuild_customer_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_customer:def:run"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Body(embed=True, max_length=16)] = None,
) -> JSONResponse:
    result = await CustomerService(auth, db).rebuild(period_value)
    return SuccessResponse(data=result, msg="客户分析构建完成")
