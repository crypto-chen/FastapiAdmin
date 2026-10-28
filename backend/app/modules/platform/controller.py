"""平台分析（指标中心 → 平台分析）。"""

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import PlatformAnalysisQueryParam, PlatformMetricUpsertParam
from .service import PlatformAnalysisService

PlatformAnalysisRouter = APIRouter(route_class=OperationLogRoute, tags=["平台分析"])

PERM_QUERY = "module_metric:platform:query"
PERM_DEF = "module_metric:platform:def"


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


# ── 指标配置（新增/修改平台指标不需要改代码） ─────────────────────
@PlatformAnalysisRouter.get("/metrics", response_model=ResponseSchema[dict])
async def list_platform_metrics(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_DEF]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).list_metrics()
    return SuccessResponse(data=result, msg="查询平台指标配置成功")


@PlatformAnalysisRouter.post("/metrics", response_model=ResponseSchema[dict])
async def create_platform_metric(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_DEF]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[PlatformMetricUpsertParam, Body()],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).upsert_metric(data)
    return SuccessResponse(data=result, msg="新增平台指标成功")


@PlatformAnalysisRouter.put("/metrics/{metric_id}", response_model=ResponseSchema[dict])
async def update_platform_metric(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_DEF]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    metric_id: Annotated[int, Path(ge=1)],
    data: Annotated[PlatformMetricUpsertParam, Body()],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).upsert_metric(data, metric_id)
    return SuccessResponse(data=result, msg="修改平台指标成功")


@PlatformAnalysisRouter.delete("/metrics/{metric_id}", response_model=ResponseSchema[None])
async def delete_platform_metric(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_DEF]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    metric_id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    await PlatformAnalysisService(db).delete_metric(metric_id)
    return SuccessResponse(msg="删除平台指标成功")


@PlatformAnalysisRouter.post("/metrics/reset", response_model=ResponseSchema[dict])
async def reset_platform_metrics(
    auth: Annotated[AuthSchema, Security(AuthPermission([PERM_DEF]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await PlatformAnalysisService(db).reset_defaults()
    return SuccessResponse(data=result, msg="已恢复默认平台指标")
