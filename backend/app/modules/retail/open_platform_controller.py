"""对外开放：平台渠道分析指标读取（PLT-08/09/11/12/13/37）。

鉴权：开放令牌 ``Authorization: Bearer <access_token>``，且应用需开启
``allow_platform_analysis``；未开启返回 403 / 业务码 40102。
"""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.dependencies import db_getter
from app.core.exceptions import CustomException
from app.modules.openapi.dependencies import OpenClientDep
from app.modules.openapi.route_class import OpenApiLogRoute
from app.modules.openapi.security import CODE_METRIC_FORBIDDEN

from .query_service import RetailQueryService

OpenRetailPlatformRouter = APIRouter(
    route_class=OpenApiLogRoute,
    prefix="/retail/platform",
    tags=["开放接口-平台渠道分析"],
)


def _ensure_allowed(client) -> None:
    if not getattr(client, "allow_platform_analysis", False):
        raise CustomException(
            msg="当前应用未开通「平台渠道分析指标」读取权限，请联系管理员在「开放接口应用」中开启",
            code=CODE_METRIC_FORBIDDEN,
            status_code=403,
        )


@OpenRetailPlatformRouter.get(
    "/analysis",
    summary="查询平台渠道分析指标（接单/出货/退货/净额/结算收入）",
    response_model=ResponseSchema[dict],
)
async def platform_analysis(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[
        str | None, Query(max_length=16, description="期间 YYYY-MM，缺省=全部期间")
    ] = None,
    shop_id: Annotated[int | None, Query(ge=0, description="店铺编号，缺省=全部店铺")] = None,
) -> JSONResponse:
    """按「期间 × 店铺」返回平台渠道分析指标。

    字段口径见 ``docs/平台渠道分析指标开放接口对接说明.md``：

    - ``intake_untaxed`` PLT-08 接单未税；
    - ``shipment_untaxed`` PLT-09 货物出货未税（订单状态已发货）；
    - ``return_untaxed`` PLT-11 退货退款（负数，取消单 + 发货后售后）；
    - ``net_shipment_untaxed`` PLT-12 对外出货净额；
    - ``settlement_income_untaxed`` PLT-13 营销结算收入（×10%）；
    - ``return_rate`` PLT-37 退货率（小数，0.2 = 20%）。
    """
    _ensure_allowed(client)
    result = await RetailQueryService(db).analysis_summary(period_value, shop_id)
    result["app_id"] = client.app_id
    result["generated_at"] = datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    return SuccessResponse(data=result, msg="查询平台渠道分析指标成功")
