"""产品线分析对外开放接口（/open/v1/product-lines）。

与 ``/open/v1/customers`` 同构：走同一套开放接口鉴权（``/open/v1/auth/token`` 换令牌），
由 ``open_client.allow_product_line_detail`` 控制是否放行，
``open_client.allow_cost_fields`` 控制成本/毛利/边际类字段是否返回。
"""

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

from .fields import FIELD_DEFS
from .schema import ProductLineQueryParam
from .service import ProductLineService, field_catalog

SCHEMA_VERSION = "2026-10-16"

OpenProductLineRouter = APIRouter(
    route_class=OpenApiLogRoute, prefix="/product-lines", tags=["开放接口-产品线分析"]
)

SENSITIVE_CODES = {
    code for code, _name, _type, _group, sensitive, _source, _status, _note in FIELD_DEFS if sensitive
}


def _require_product_line_detail(client: Any) -> None:
    if not getattr(client, "allow_product_line_detail", False):
        raise CustomException(
            msg="应用未开通产品线分析查询权限", code=CODE_CLIENT_FORBIDDEN, status_code=403
        )


def _strip_sensitive(payload: dict, allow_cost: bool) -> dict:
    """未授权成本字段时，目录与数据一起剔除敏感字段。"""
    if allow_cost:
        return payload
    payload["columns"] = [
        col for col in payload.get("columns", []) if col["field_code"] not in SENSITIVE_CODES
    ]
    for item in payload.get("items", []):
        for code in SENSITIVE_CODES:
            item.pop(code, None)
    return payload


@OpenProductLineRouter.get("/fields", summary="查询产品线分析字段目录", response_model=ResponseSchema[dict])
async def list_open_product_line_fields(client: OpenClientDep) -> JSONResponse:
    _require_product_line_detail(client)
    columns = field_catalog()
    if not getattr(client, "allow_cost_fields", False):
        columns = [col for col in columns if col["field_code"] not in SENSITIVE_CODES]
    return SuccessResponse(
        data={"schema_version": SCHEMA_VERSION, "fields": columns}, msg="查询字段目录成功"
    )


@OpenProductLineRouter.get("", summary="增量拉取产品线分析明细", response_model=ResponseSchema[dict])
async def page_open_product_lines(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16, description="期间(YYYY-MM)，缺省最新期间")] = None,
    calc_version: Annotated[int | None, Query(ge=1, description="计算版本，缺省最新版本")] = None,
    product_line: Annotated[str | None, Query(max_length=128, description="产品线大类（模糊）")] = None,
    sku: Annotated[str | None, Query(max_length=128, description="SKU（模糊）")] = None,
    salesman: Annotated[str | None, Query(max_length=64, description="业务员（模糊）")] = None,
    order_type: Annotated[str | None, Query(max_length=32, description="订单类型（模糊，如 批量）")] = None,
    platform: Annotated[str | None, Query(max_length=64, description="平台（模糊）")] = None,
    shop: Annotated[str | None, Query(max_length=64, description="店铺（模糊）")] = None,
    aggregate_level: Annotated[
        str, Query(description="返回层级：detail=产品线×SKU 明细、line=产品线小计、all=全部")
    ] = "detail",
    page_no: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=2000, description="每页数量")] = 500,
) -> JSONResponse:
    _require_product_line_detail(client)
    search = ProductLineQueryParam(
        period_value=period_value,
        calc_version=calc_version,
        product_line=product_line,
        sku=sku,
        salesman=salesman,
        order_type=order_type,
        platform=platform,
        shop=shop,
        aggregate_level=aggregate_level,
    )
    result = await ProductLineService(None, db).page(search, page_no, page_size)
    result = _strip_sensitive(result, bool(getattr(client, "allow_cost_fields", False)))
    result.pop("columns", None)
    result["schema_version"] = SCHEMA_VERSION
    result["rows"] = [
        {
            "product_line": item.get("product_line_code"),
            "sku": item.get("sku"),
            "level": int(item.get("is_aggregate") or 0),
            "fields": item,
        }
        for item in result.pop("items", [])
    ]
    result["has_more"] = result.pop("has_next", False)
    return SuccessResponse(data=result, msg="查询产品线分析成功")
