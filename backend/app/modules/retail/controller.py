"""零售数据管理端接口（/retail）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.config.setting import settings
from app.core.base_schema import AuthSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.exceptions import CustomException
from app.core.router_class import OperationLogRoute
from app.modules.erp.jushuitan.client import JushuitanError
from app.modules.openapi.security import CODE_PARAM_INVALID

from .query_service import RetailQueryService
from .schema import RetailBatchQueryParam, RetailOrderQueryParam
from .shop_service import sync_jushuitan_shops

RetailRouter = APIRouter(route_class=OperationLogRoute, tags=["零售数据"])


@RetailRouter.get("/periods", response_model=ResponseSchema[list[str]])
async def list_retail_periods(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_retail:order:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await RetailQueryService(db).periods()
    return SuccessResponse(data=result, msg="查询零售期间成功")


@RetailRouter.post("/shops/sync", response_model=ResponseSchema[dict])
async def sync_retail_shops(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_retail:shop:sync"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    try:
        result = await sync_jushuitan_shops(
            db, connection_id=settings.RETAIL_ORDER_SYNC_CONNECTION_ID
        )
    except ValueError as exc:
        raise CustomException(msg=str(exc), code=CODE_PARAM_INVALID, status_code=400) from exc
    except JushuitanError as exc:
        raise CustomException(msg=f"聚水潭店铺查询失败：{exc}", status_code=502) from exc
    return SuccessResponse(data=result, msg="同步店铺成功")


@RetailRouter.get("/orders/page", response_model=ResponseSchema[dict])
async def page_retail_orders(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_retail:order:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[RetailOrderQueryParam, Query()],
) -> JSONResponse:
    result = await RetailQueryService(db).page_orders(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询零售订单成功")


@RetailRouter.get("/orders/{order_id}", response_model=ResponseSchema[dict])
async def detail_retail_order(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_retail:order:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    order_id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await RetailQueryService(db).order_detail(order_id)
    return SuccessResponse(data=result, msg="查询零售订单详情成功")


@RetailRouter.get("/batches/page", response_model=ResponseSchema[dict])
async def page_retail_batches(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_retail:batch:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[RetailBatchQueryParam, Query()],
) -> JSONResponse:
    result = await RetailQueryService(db).page_batches(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询零售推送批次成功")


@RetailRouter.get("/batches/{batch_id}", response_model=ResponseSchema[dict])
async def detail_retail_batch(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_retail:batch:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    batch_id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await RetailQueryService(db).batch_detail(batch_id)
    return SuccessResponse(data=result, msg="查询零售推送批次详情成功")
