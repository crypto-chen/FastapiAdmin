from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    JushuitanConnectionCreateSchema,
    JushuitanConnectionOutSchema,
    JushuitanConnectionQueryParam,
    JushuitanConnectionUpdateSchema,
    JushuitanMonthlyQuerySchema,
    JushuitanMonthlySummarySchema,
    JushuitanSalesOutboundQuerySchema,
    JushuitanSalesOutboundResultSchema,
)
from .service import JushuitanService

JushuitanRouter = APIRouter(route_class=OperationLogRoute, prefix="/jushuitan", tags=["聚水潭数据源"])


@JushuitanRouter.get(
    "/page", summary="分页查询聚水潭连接", response_model=ResponseSchema[PageResultSchema[JushuitanConnectionOutSchema]]
)
async def get_jushuitan_connection_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[JushuitanConnectionQueryParam, Query()],
) -> JSONResponse:
    result: PageResultSchema[JushuitanConnectionOutSchema] = await JushuitanService(auth, db).page(
        search=search,
        page_no=page.page_no,
        page_size=page.page_size,
        order_by=page.order_by,
    )
    return SuccessResponse(data=result, msg="查询聚水潭连接成功")


@JushuitanRouter.get("/list", summary="查询聚水潭连接列表", response_model=ResponseSchema[list[JushuitanConnectionOutSchema]])
async def get_jushuitan_connection_list_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    search: Annotated[JushuitanConnectionQueryParam, Query()],
) -> JSONResponse:
    result: list[JushuitanConnectionOutSchema] = await JushuitanService(auth, db).get_list(search=search)
    return SuccessResponse(data=result, msg="查询聚水潭连接成功")


@JushuitanRouter.get(
    "/detail/{id}", summary="查询聚水潭连接详情", response_model=ResponseSchema[JushuitanConnectionOutSchema]
)
async def get_jushuitan_connection_detail_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="聚水潭连接ID", ge=1)],
) -> JSONResponse:
    result: JushuitanConnectionOutSchema = await JushuitanService(auth, db).detail(id=id)
    return SuccessResponse(data=result, msg="查询聚水潭连接详情成功")


@JushuitanRouter.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="创建聚水潭连接",
    response_model=ResponseSchema[JushuitanConnectionOutSchema],
)
async def create_jushuitan_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[JushuitanConnectionCreateSchema, Body(description="聚水潭连接创建参数")],
) -> JSONResponse:
    result: JushuitanConnectionOutSchema = await JushuitanService(auth, db).create(data=data)
    return SuccessResponse(data=result, msg="创建聚水潭连接成功")


@JushuitanRouter.put(
    "/update/{id}", summary="修改聚水潭连接", response_model=ResponseSchema[JushuitanConnectionOutSchema]
)
async def update_jushuitan_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="聚水潭连接ID", ge=1)],
    data: Annotated[JushuitanConnectionUpdateSchema, Body(description="聚水潭连接修改参数")],
) -> JSONResponse:
    result: JushuitanConnectionOutSchema = await JushuitanService(auth, db).update(id=id, data=data)
    return SuccessResponse(data=result, msg="修改聚水潭连接成功")


@JushuitanRouter.delete("/delete", summary="删除聚水潭连接", response_model=ResponseSchema[None])
async def delete_jushuitan_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body(description="聚水潭连接ID列表")],
) -> JSONResponse:
    await JushuitanService(auth, db).delete(ids=ids)
    return SuccessResponse(msg="删除聚水潭连接成功")


@JushuitanRouter.post("/test/{id}", summary="测试聚水潭连接", response_model=ResponseSchema[dict])
async def test_jushuitan_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="聚水潭连接ID", ge=1)],
) -> JSONResponse:
    result: dict = await JushuitanService(auth, db).test_connection(id=id)
    return SuccessResponse(data=result, msg="连接成功")


@JushuitanRouter.post(
    "/sales-outbound/query",
    summary="查询销售出库单（默认已出库、按出库时间）",
    response_model=ResponseSchema[JushuitanSalesOutboundResultSchema],
)
async def query_jushuitan_sales_outbound_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[JushuitanSalesOutboundQuerySchema, Body(description="销售出库查询参数")],
) -> JSONResponse:
    result: JushuitanSalesOutboundResultSchema = await JushuitanService(auth, db).query_sales_outbound(data=data)
    return SuccessResponse(data=result, msg="查询销售出库单成功")


@JushuitanRouter.post(
    "/sales-outbound/monthly",
    summary="零售出库未税总金额（月度指标）",
    response_model=ResponseSchema[JushuitanMonthlySummarySchema],
)
async def monthly_jushuitan_untaxed_amount_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:jushuitan:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[JushuitanMonthlyQuerySchema, Body(description="月度未税金额取数参数")],
) -> JSONResponse:
    result: JushuitanMonthlySummarySchema = await JushuitanService(auth, db).monthly_summary(data=data)
    return SuccessResponse(data=result, msg="统计零售出库未税总金额成功")
