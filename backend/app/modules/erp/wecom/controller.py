"""企业微信通讯录 / 打卡同步接口。"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute
from app.modules.erp.wecom.calc import DEFAULT_MARKETING_PREFIX
from app.modules.erp.wecom.schema import (
    WeComCheckinOutSchema,
    WeComConnectionCreateSchema,
    WeComConnectionOutSchema,
    WeComConnectionQueryParam,
    WeComConnectionUpdateSchema,
    WeComEmployeeOutSchema,
    WeComSyncCheckinSchema,
    WeComSyncRosterSchema,
    WeComSyncRunOutSchema,
    WeComWorktimeResultSchema,
)
from app.modules.erp.wecom.service import (
    calc_worktime,
    create_connection,
    delete_connections,
    get_connection_detail,
    list_connections,
    page_connections,
    query_checkins,
    query_employees,
    query_sync_runs,
    sync_checkin,
    sync_roster,
    test_connection,
    update_connection,
)

WeComRouter = APIRouter(route_class=OperationLogRoute, prefix="/wecom", tags=["企业微信打卡"])


# ---------------------------------------------------------------------- #
# 连接配置
# ---------------------------------------------------------------------- #
@WeComRouter.get(
    "/connection/page",
    summary="分页查询企业微信连接",
    response_model=ResponseSchema[PageResultSchema[WeComConnectionOutSchema]],
)
async def get_wecom_connection_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[WeComConnectionQueryParam, Query()],
) -> JSONResponse:
    result = await page_connections(
        db,
        page_no=page.page_no,
        page_size=page.page_size,
        name=search.name,
        status=search.status,
    )
    return SuccessResponse(data=result, msg="查询企业微信连接成功")


@WeComRouter.get(
    "/connection/list",
    summary="查询企业微信连接列表",
    response_model=ResponseSchema[list[WeComConnectionOutSchema]],
)
async def get_wecom_connection_list_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    search: Annotated[WeComConnectionQueryParam, Query()],
) -> JSONResponse:
    result = await list_connections(db, name=search.name, status=search.status)
    return SuccessResponse(data=result, msg="查询企业微信连接成功")


@WeComRouter.get(
    "/connection/detail/{id}",
    summary="查询企业微信连接详情",
    response_model=ResponseSchema[WeComConnectionOutSchema],
)
async def get_wecom_connection_detail_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="连接ID", ge=1)],
) -> JSONResponse:
    result = await get_connection_detail(db, id)
    return SuccessResponse(data=result, msg="查询企业微信连接成功")


@WeComRouter.post(
    "/connection/create",
    status_code=status.HTTP_201_CREATED,
    summary="创建企业微信连接",
    response_model=ResponseSchema[WeComConnectionOutSchema],
)
async def create_wecom_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[WeComConnectionCreateSchema, Body()],
) -> JSONResponse:
    result = await create_connection(db, data, user_id=auth.user.id or None)
    return SuccessResponse(data=result, msg="创建企业微信连接成功")


@WeComRouter.put(
    "/connection/update/{id}",
    summary="更新企业微信连接",
    response_model=ResponseSchema[WeComConnectionOutSchema],
)
async def update_wecom_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:edit"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="连接ID", ge=1)],
    data: Annotated[WeComConnectionUpdateSchema, Body()],
) -> JSONResponse:
    result = await update_connection(db, id, data, user_id=auth.user.id or None)
    return SuccessResponse(data=result, msg="更新企业微信连接成功")


@WeComRouter.delete(
    "/connection/delete",
    summary="删除企业微信连接",
    response_model=ResponseSchema[None],
)
async def delete_wecom_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body(description="连接ID列表")],
) -> JSONResponse:
    await delete_connections(db, ids, user_id=auth.user.id or None)
    return SuccessResponse(msg="删除企业微信连接成功")


@WeComRouter.post(
    "/connection/test/{id}",
    summary="测试企业微信连接",
    response_model=ResponseSchema[dict],
)
async def test_wecom_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="连接ID", ge=1)],
) -> JSONResponse:
    result = await test_connection(db, id)
    return SuccessResponse(data=result, msg="企业微信连接测试成功")


# ---------------------------------------------------------------------- #
# 数据查询
# ---------------------------------------------------------------------- #
@WeComRouter.get(
    "/employees",
    summary="查询企微人员名单",
    response_model=ResponseSchema[PageResultSchema[WeComEmployeeOutSchema]],
)
async def get_wecom_employees_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    keyword: Annotated[str | None, Query(description="姓名/工号关键字")] = None,
    status: Annotated[int | None, Query(ge=0, le=1, description="状态(0:在职 1:离职/禁用)")] = None,
    dept_code: Annotated[str | None, Query(description="主部门编码")] = None,
) -> JSONResponse:
    result = await query_employees(
        db,
        keyword=keyword,
        status=status,
        dept_code=dept_code,
        page_no=page.page_no,
        page_size=page.page_size,
    )
    return SuccessResponse(data=result, msg="查询人员名单成功")


@WeComRouter.get(
    "/checkins",
    summary="查询每人每天打卡明细",
    response_model=ResponseSchema[PageResultSchema[WeComCheckinOutSchema]],
)
async def get_wecom_checkins_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    start_date: Annotated[date, Query(description="开始日期")],
    end_date: Annotated[date, Query(description="结束日期")],
    userid: Annotated[str | None, Query(description="工号")] = None,
) -> JSONResponse:
    result = await query_checkins(
        db,
        userid=userid,
        start_date=start_date,
        end_date=end_date,
        page_no=page.page_no,
        page_size=page.page_size,
    )
    return SuccessResponse(data=result, msg="查询打卡明细成功")


@WeComRouter.get(
    "/worktime",
    summary="工时统计（正常工时/加班）",
    response_model=ResponseSchema[WeComWorktimeResultSchema],
)
async def get_wecom_worktime_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    start_date: Annotated[date, Query(description="开始日期")],
    end_date: Annotated[date, Query(description="结束日期")],
    marketing_only: Annotated[bool, Query(description="只统计营销人员")] = True,
    prefix: Annotated[str, Query(max_length=16, description="营销人员工号前缀")] = DEFAULT_MARKETING_PREFIX,
    person_source: Annotated[
        Literal["crm", "wecom"],
        Query(description="人员范围：crm=对齐 PHP 的 yg_admin；wecom=企微通讯录"),
    ] = "crm",
) -> JSONResponse:
    result = await calc_worktime(
        db,
        start_date=start_date,
        end_date=end_date,
        marketing_only=marketing_only,
        prefix=prefix,
        person_source=person_source,
    )
    return SuccessResponse(data=result, msg="工时统计成功")


@WeComRouter.get(
    "/sync/runs",
    summary="查询同步批次记录",
    response_model=ResponseSchema[PageResultSchema[WeComSyncRunOutSchema]],
)
async def get_wecom_sync_runs_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    sync_type: Annotated[str | None, Query(description="同步类型(roster/checkin)")] = None,
    status_: Annotated[str | None, Query(alias="status", description="状态")] = None,
) -> JSONResponse:
    result = await query_sync_runs(
        db,
        sync_type=sync_type,
        status=status_,
        page_no=page.page_no,
        page_size=page.page_size,
    )
    return SuccessResponse(data=result, msg="查询同步记录成功")


# ---------------------------------------------------------------------- #
# 手动同步
# ---------------------------------------------------------------------- #
@WeComRouter.post(
    "/sync/roster",
    summary="手动同步企微通讯录",
    response_model=ResponseSchema[dict],
)
async def sync_wecom_roster_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:sync"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[WeComSyncRosterSchema | None, Body()] = None,
) -> JSONResponse:
    result = await sync_roster(db, connection_id=data.connection_id if data else None)
    return SuccessResponse(data=result, msg="企微通讯录同步成功")


@WeComRouter.post(
    "/sync/checkin",
    summary="手动同步企微打卡",
    response_model=ResponseSchema[dict],
)
async def sync_wecom_checkin_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:wecom:sync"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[WeComSyncCheckinSchema, Body()],
) -> JSONResponse:
    result = await sync_checkin(
        db,
        start_date=data.start_date,
        end_date=data.end_date,
        connection_id=data.connection_id,
        userids=data.userids,
        only_marketing=data.only_marketing,
    )
    return SuccessResponse(data=result, msg="企微打卡同步成功")

