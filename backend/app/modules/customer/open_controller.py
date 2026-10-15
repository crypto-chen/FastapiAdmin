"""客户分析对外开放接口（/open/v1/customers）。"""

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

from .fields import FIELD_DEFS
from .schema import CustomerQueryParam
from .service import CustomerService, field_catalog

SCHEMA_VERSION = "2026-10-14"

OpenCustomerRouter = APIRouter(
    route_class=OpenApiLogRoute, prefix="/customers", tags=["开放接口-客户分析"]
)

SENSITIVE_CODES = {code for code, _name, _type, _group, sensitive, _source, _note in FIELD_DEFS if sensitive}


def _require_customer_detail(client: Any) -> None:
    if not getattr(client, "allow_customer_detail", False):
        raise CustomException(
            msg="应用未开通客户分析查询权限", code=CODE_CLIENT_FORBIDDEN, status_code=403
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


@OpenCustomerRouter.get("/fields", summary="查询客户分析字段目录", response_model=ResponseSchema[dict])
async def list_open_customer_fields(client: OpenClientDep) -> JSONResponse:
    _require_customer_detail(client)
    columns = field_catalog()
    if not getattr(client, "allow_cost_fields", False):
        columns = [col for col in columns if col["field_code"] not in SENSITIVE_CODES]
    return SuccessResponse(
        data={"schema_version": SCHEMA_VERSION, "fields": columns}, msg="查询字段目录成功"
    )


@OpenCustomerRouter.get("", summary="增量拉取客户分析明细", response_model=ResponseSchema[dict])
async def page_open_customers(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16, description="期间(YYYY-MM)，缺省最新期间")] = None,
    calc_version: Annotated[int | None, Query(ge=1, description="计算版本，缺省最新版本")] = None,
    customer_code: Annotated[str | None, Query(max_length=64, description="客户编码（模糊）")] = None,
    customer_name: Annotated[str | None, Query(max_length=128, description="客户名称（模糊）")] = None,
    salesman_code: Annotated[str | None, Query(max_length=64, description="业务员编码")] = None,
    order_type: Annotated[str | None, Query(max_length=64, description="订单类型（模糊）")] = None,
    product_line: Annotated[str | None, Query(max_length=64, description="产品线大类（模糊）")] = None,
    include_aggregate: Annotated[bool, Query(description="是否返回合计行")] = True,
    page_no: Annotated[int, Query(ge=1, description="页码")] = 1,
    page_size: Annotated[int, Query(ge=1, le=2000, description="每页数量")] = 500,
) -> JSONResponse:
    _require_customer_detail(client)
    search = CustomerQueryParam(
        period_value=period_value,
        calc_version=calc_version,
        customer_code=customer_code,
        customer_name=customer_name,
        salesman_code=salesman_code,
        order_type=order_type,
        product_line=product_line,
        include_aggregate=include_aggregate,
    )
    result = await CustomerService(None, db).page(search, page_no, page_size)
    result = _strip_sensitive(result, bool(getattr(client, "allow_cost_fields", False)))
    result.pop("columns", None)
    result["schema_version"] = SCHEMA_VERSION
    result["rows"] = [
        {"customer_code": item.get("customer_code"), "fields": item}
        for item in result.pop("items", [])
    ]
    result["has_more"] = result.pop("has_next", False)
    return SuccessResponse(data=result, msg="查询客户分析成功")


@OpenCustomerRouter.get("/{customer_code}", summary="查询单个客户分析", response_model=ResponseSchema[dict])
async def detail_open_customer(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    customer_code: Annotated[str, Path(min_length=1, max_length=64, description="客户编码")],
) -> JSONResponse:
    _require_customer_detail(client)
    result = await CustomerService(None, db).detail(customer_code)
    stripped = _strip_sensitive(
        {"items": [result["item"]], "columns": result["columns"]},
        bool(getattr(client, "allow_cost_fields", False)),
    )
    return SuccessResponse(
        data={
            "schema_version": SCHEMA_VERSION,
            "period_value": result.get("period_value"),
            "item": stripped["items"][0],
            "columns": stripped["columns"],
        },
        msg="查询客户详情成功",
    )
