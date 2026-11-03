"""MES 对外订单接口（/open/v1/mes/orders）。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.dependencies import db_getter
from app.core.exceptions import CustomException
from app.modules.openapi.dependencies import OpenClientDep
from app.modules.openapi.route_class import OpenApiLogRoute
from app.modules.openapi.security import CODE_CLIENT_FORBIDDEN

from .schema import MesOrderItemSchema, MesOrderQueryParam
from .service import MesOrderService

OpenMesOrderRouter = APIRouter(route_class=OpenApiLogRoute, prefix="/mes/orders", tags=["开放接口-MES 订单"])


def _require_order_detail(client: Any) -> None:
    """复用订单明细权限，避免为 MES 单独增加权限列。"""
    if not getattr(client, "allow_order_detail", False):
        raise CustomException(msg="应用未开通订单查询权限", code=CODE_CLIENT_FORBIDDEN, status_code=403)


@OpenMesOrderRouter.get(
    "",
    summary="MES 读取 CRM 内外贸订单",
    response_model=ResponseSchema[dict],
)
async def page_mes_orders(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    crm_order_no: Annotated[str | None, Query(max_length=64, description="CRM 订单号（模糊）")] = None,
    customer_name: Annotated[str | None, Query(max_length=255, description="客户名称（模糊）")] = None,
    engineer_name: Annotated[str | None, Query(max_length=128, description="负责工程姓名（模糊）")] = None,
    product_series: Annotated[str | None, Query(max_length=128, description="产品系列（模糊）")] = None,
    product_model: Annotated[str | None, Query(max_length=128, description="产品型号（模糊）")] = None,
    product_size: Annotated[str | None, Query(max_length=128, description="产品尺寸（模糊）")] = None,
    trade_type: Annotated[str | None, Query(pattern="^(domestic|export)$", description="贸易类型 domestic/export")] = None,
    page_no: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=1000, description="每页数量，上限 1000")] = 200,
) -> JSONResponse:
    _require_order_detail(client)

    # 应用级订单范围优先：管理员限定 domestic/export 时，调用方不能越权查询另一侧
    scope = getattr(client, "order_scope", None) or {}
    scoped_trade_type = str(scope.get("trade_type") or "").strip() or None
    if scoped_trade_type and trade_type and trade_type != scoped_trade_type:
        raise CustomException(msg=f"应用仅允许查询 {scoped_trade_type} 订单", code=CODE_CLIENT_FORBIDDEN, status_code=403)
    trade_type = trade_type or scoped_trade_type

    search = MesOrderQueryParam(
        crm_order_no=crm_order_no,
        customer_name=customer_name,
        engineer_name=engineer_name,
        product_series=product_series,
        product_model=product_model,
        product_size=product_size,
        trade_type=trade_type,
    )
    result = await MesOrderService(db).page(search, page_no, page_size)
    result["schema_version"] = "2026-11-03"
    result["items"] = [MesOrderItemSchema(**item).model_dump(mode="json") for item in result["items"]]
    return SuccessResponse(data=result, msg="查询 MES 订单成功")
