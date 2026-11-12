"""对外开放接口：企微人员月度工时。"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.dependencies import db_getter
from app.core.exceptions import CustomException
from app.modules.erp.wecom.service import query_monthly_worktime, recent_month_periods
from app.modules.openapi.dependencies import OpenClientDep
from app.modules.openapi.model import OpenClientModel
from app.modules.openapi.route_class import OpenApiLogRoute
from app.modules.openapi.schema import (
    OpenWorktimeByPeriodSchema,
    OpenWorktimeByUserSchema,
)
from app.modules.openapi.security import CODE_METRIC_FORBIDDEN

OpenWorktimeRouter = APIRouter(
    route_class=OpenApiLogRoute,
    prefix="/wecom/worktime",
    tags=["开放接口-企微工时"],
)


def _ensure_person_detail(client: OpenClientModel) -> None:
    if not client.allow_person_detail:
        raise CustomException(
            msg="该应用未开放人员明细权限，请在开放接口应用里开启「业务员明细」",
            code=CODE_METRIC_FORBIDDEN,
            status_code=403,
        )


@OpenWorktimeRouter.post(
    "/by-period",
    summary="按年月查询企微人员工时",
    response_model=ResponseSchema[dict],
)
async def query_worktime_by_period(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[OpenWorktimeByPeriodSchema, Body()],
) -> JSONResponse:
    _ensure_person_detail(client)
    result = await query_monthly_worktime(
        db,
        periods=data.periods,
        userids=data.userids,
        include_zero=data.include_zero,
        exclude_backup_accounts=data.exclude_backup_accounts,
    )
    msg = "查询成功" if not result.get("warning") else "查询完成，请查看 warning"
    return SuccessResponse(data=result, msg=msg)


@OpenWorktimeRouter.post(
    "/by-user",
    summary="按工号查询企微人员月度工时",
    response_model=ResponseSchema[dict],
)
async def query_worktime_by_user(
    client: OpenClientDep,
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[OpenWorktimeByUserSchema, Body()],
) -> JSONResponse:
    _ensure_person_detail(client)
    result = await query_monthly_worktime(
        db,
        periods=data.periods or recent_month_periods(12),
        userids=data.userids,
        include_zero=data.include_zero,
        exclude_backup_accounts=data.exclude_backup_accounts,
    )
    msg = "查询成功" if not result.get("warning") else "查询完成，请查看 warning"
    return SuccessResponse(data=result, msg=msg)

