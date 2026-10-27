"""平台分析（指标中心 → 平台分析）。"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import PlatformAnalysisQueryParam
from .service import PlatformAnalysisService

PlatformAnalysisRouter = APIRouter(route_class=OperationLogRoute, tags=["平台分析"])

PERM_QUERY = "module_metric:platform:query"


@PlatformAnalysisRouter.get("/fields", response_model=ResponseSchema[list[dict]])
async def list_platform_fields(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_QUERY]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).fields()
    return SuccessResponse(data=result, msg="查询平台分析字段成功")


@PlatformAnalysisRouter.get("/periods", response_model=ResponseSchema[list[str]])
async def list_platform_periods(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_QUERY]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).periods()
    return SuccessResponse(data=result, msg="查询平台分析期间成功")


@PlatformAnalysisRouter.get("/platforms", response_model=ResponseSchema[list[str]])
async def list_platform_options(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_QUERY]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).platform_options()
    return SuccessResponse(data=result, msg="查询平台字典成功")


@PlatformAnalysisRouter.get("/page", response_model=ResponseSchema[dict])
async def page_platform_analysis(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_QUERY]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    search: Annotated[PlatformAnalysisQueryParam, Query()],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).page(
        search, search.page_no, search.page_size
    )
    return SuccessResponse(data=result, msg="查询平台分析成功")


@PlatformAnalysisRouter.get("/stats", response_model=ResponseSchema[dict])
async def platform_analysis_stats(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_QUERY]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    period_value: Annotated[str | None, Query(max_length=16, description="期间 YYYY-MM")] = None,
) -> JSONResponse:
    result = await PlatformAnalysisService(db).stats(period_value)
    return SuccessResponse(data=result, msg="查询平台分析汇总成功")
