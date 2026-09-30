from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    MetricCalcRequestSchema,
    MetricCalcResultSchema,
    MetricDefCreateSchema,
    MetricDefOutSchema,
    MetricDefQueryParam,
    MetricDefUpdateSchema,
    MetricValueOutSchema,
    MetricValueQueryParam,
)
from .service import MetricService

MetricRouter = APIRouter(route_class=OperationLogRoute, prefix="/def", tags=["指标定义"])
MetricValueRouter = APIRouter(route_class=OperationLogRoute, prefix="/value", tags=["指标结果"])


@MetricRouter.get("/page", response_model=ResponseSchema[PageResultSchema[MetricDefOutSchema]])
async def page_metric_def(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metric:def:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MetricDefQueryParam, Query()],
) -> JSONResponse:
    result = await MetricService(auth, db).page(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询指标定义成功")


@MetricRouter.get("/detail/{id}", response_model=ResponseSchema[MetricDefOutSchema])
async def detail_metric_def(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metric:def:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetricService(auth, db).detail(id)
    return SuccessResponse(data=result, msg="查询指标定义详情成功")


@MetricRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[MetricDefOutSchema])
async def create_metric_def(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metric:def:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[MetricDefCreateSchema, Body()],
) -> JSONResponse:
    result = await MetricService(auth, db).create(data)
    return SuccessResponse(data=result, msg="创建指标定义成功")


@MetricRouter.put("/update/{id}", response_model=ResponseSchema[MetricDefOutSchema])
async def update_metric_def(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metric:def:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[MetricDefUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetricService(auth, db).update(id, data)
    return SuccessResponse(data=result, msg="修改指标定义成功")


@MetricRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_metric_def(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metric:def:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetricService(auth, db).delete(ids)
    return SuccessResponse(msg="删除指标定义成功")


@MetricValueRouter.get("/page", response_model=ResponseSchema[PageResultSchema[MetricValueOutSchema]])
async def page_metric_value(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metric:value:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MetricValueQueryParam, Query()],
) -> JSONResponse:
    result = await MetricService(auth, db).page_value(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询指标结果成功")


@MetricRouter.post("/run/{id}", response_model=ResponseSchema[MetricCalcResultSchema])
async def run_metric_calc(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metric:def:run"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[MetricCalcRequestSchema | None, Body()] = None,
) -> JSONResponse:
    result = await MetricService(auth, db).run_calc(id, data)
    return SuccessResponse(data=result, msg="指标计算完成")
