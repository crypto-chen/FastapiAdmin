"""订单全链路对外开放接口（/open/v1/orders）。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.dependencies import db_getter
from app.core.exceptions import CustomException
from app.modules.openapi.dependencies import OpenClientDep
from app.modules.openapi.route_class import OpenApiLogRoute
from app.modules.openapi.security import CODE_CLIENT_FORBIDDEN

from .build import SCHEMA_VERSION
from .fields import FIELD_DEFS
from .schema import OrderQueryParam
from .service import OrderService, field_catalog

OpenOrderRouter = APIRouter(route_class=OpenApiLogRoute, prefix="/orders", tags=["开放接口-订单全链路"])

SENSITIVE_CODES = {code for code, _name, _type, _group, sensitive, _excel in FIELD_DEFS if sensitive}


def _require_order_detail(client: Any) -> None:
    if not getattr(client, "allow_order_detail", False):
        raise CustomException(
            msg="应用未开通订单全链路查询权限", code=CODE_CLIENT_FORBIDDEN, status_code=403
        )


def _strip_sensitive(payload: dict, allow_cost: bool) -> dict:
    """未授权成本字段时，目录与数据一起剔除敏感字段。"""
    if allow_cost:
        return payload
    payload["columns"] = [col for col in payload.get("columns", []) if col["field_code"] not in SENSITIVE_CODES]
    for item in payload.get("items", []):
        for code in SENSITIVE_CODES:
            item.pop(code, None)
        item.pop("total_cost", None)
    return payload


@OpenOrderRouter.get("/fields", summary="查询订单全链路字段目录", response_model=ResponseSchema[dict])
async def list_open_order_fields(client: OpenClientDep) -> JSONResponse:
    _require_order_detail(client)
    columns = field_catalog()
    if not getattr(client, "allow_cost_fields", False):
        columns = [col for col in columns if col["field_code"] not in SENSITIVE_CODES]
    return SuccessResponse(
        data={"schema_version": SCHEMA_VERSION, "fields": columns}, msg="查询字段目录成功"
    )


@OpenOrderRouter.get("", summary="增量拉取订单全链路明细", response_model=ResponseSchema[dict])
async def page_open_orders(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16, description="期间(YYYY-MM)，缺省最新期间")] = None,
    calc_version: Annotated[int | None, Query(ge=1, description="计算版本，缺省最新版本")] = None,
    order_number: Annotated[str | None, Query(max_length=64, description="订单号（模糊）")] = None,
    trade_type: Annotated[str | None, Query(max_length=16, description="贸易类型 domestic/export")] = None,
    page_no: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=2000, description="每页数量")] = 500,
) -> JSONResponse:
    _require_order_detail(client)
    scope = getattr(client, "order_scope", None) or {}
    if scope.get("trade_type") and not trade_type:
        trade_type = str(scope["trade_type"])
    search = OrderQueryParam(period_value=period_value, calc_version=calc_version, order_number=order_number, trade_type=trade_type)
    result = await OrderService(None, db).page(search, page_no, page_size)
    result = _strip_sensitive(result, bool(getattr(client, "allow_cost_fields", False)))
    result.pop("columns", None)
    result["schema_version"] = SCHEMA_VERSION
    result["rows"] = [{"order_number": item.get("order_number"), "fields": item} for item in result.pop("items", [])]
    result["has_more"] = result.pop("has_next", False)
    return SuccessResponse(data=result, msg="查询订单明细成功")


@OpenOrderRouter.get("/{order_number}", summary="查询单个订单全链路", response_model=ResponseSchema[dict])
async def detail_open_order(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    order_number: Annotated[str, Path(min_length=1, max_length=64, description="订单号")],
) -> JSONResponse:
    _require_order_detail(client)
    result = await OrderService(None, db).detail(order_number)
    result = _strip_sensitive({"items": [result["item"]], "columns": result["columns"]}, bool(getattr(client, "allow_cost_fields", False)))
    return SuccessResponse(
        data={"schema_version": SCHEMA_VERSION, "item": result["items"][0], "columns": result["columns"]},
        msg="查询订单详情成功",
    )
