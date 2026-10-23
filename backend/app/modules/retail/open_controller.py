"""零售数据同步开放接口（/open/v1/retail）。

该接口面向外部系统的直接推送场景，不校验开放平台令牌；建议在网关层按来源
IP 做白名单与限流。单次请求的订单数/体积上限由服务层控制。
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.dependencies import db_getter
from app.core.exceptions import CustomException
from app.modules.openapi.route_class import OpenApiLogRoute
from app.modules.openapi.security import CODE_PARAM_INVALID

from .schema import RetailSyncPayload
from .service import MAX_REQUEST_BYTES, RetailSyncService

OpenRetailRouter = APIRouter(
    route_class=OpenApiLogRoute,
    prefix="/retail",
    tags=["开放接口-零售数据"],
)

@OpenRetailRouter.post(
    "/orders/sync",
    summary="接收零售订单数据（奇门/聚水潭）",
    response_model=ResponseSchema[dict],
)
async def sync_retail_orders(
    request: Request,
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[RetailSyncPayload | list[dict[str, Any]], Body()],
) -> JSONResponse:
    """外部系统主动推送零售订单，按唯一键幂等写入。

    - 无需 Authorization，直接提交聚水潭/奇门返回体即可（``orders``/``datas``/``data``/裸数组）；
    - ``request_id`` 或请求头 ``X-Request-ID`` 作为幂等键；同一键重复提交返回首次结果；
    - 同一订单按 ``shop_id + so_id``（缺省 ``o_id``）更新，上游 ``modified`` 更旧时跳过；
    - 存在「零售数据-外部推送」任务（或配置 ``RETAIL_SYNC_JOB_ID``）时，同时把该期间
      订单回放到 ``meta_sync_run``，现有零售出库指标可直接取数。
    """
    raw_body = await request.body()
    if len(raw_body) > MAX_REQUEST_BYTES:
        raise CustomException(
            msg=f"请求体过大：{len(raw_body)} 字节，上限 {MAX_REQUEST_BYTES} 字节",
            code=CODE_PARAM_INVALID,
            status_code=413,
        )
    result = await RetailSyncService(db, app_id="public").sync(
        data,
        request_id=request.headers.get("X-Request-ID"),
        raw_body=raw_body,
    )
    if result.duplicate:
        msg = "重复请求，返回首次处理结果"
    elif result.failed:
        msg = "同步完成，部分订单处理失败，请查看 errors"
    elif result.has_next:
        msg = "同步完成，请继续推送下一页"
    else:
        msg = "零售订单同步完成"
    return SuccessResponse(data=result.model_dump(), msg=msg)
