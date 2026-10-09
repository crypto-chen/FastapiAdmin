from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute
from app.modules.masterdata.schema import MappingQueryParam, OrgMappingOutSchema, PersonMappingOutSchema
from app.modules.metadata.schema import FieldMappingOutSchema, FieldMappingQueryParam

from .schema import (
    AutoMatchSchema,
    DeptBindSchema,
    DeptMappingCreateSchema,
    DeptMappingOutSchema,
    DeptMappingQueryParam,
    DeptMappingUpdateSchema,
    MasterDeptOptionSchema,
    OrgBindSchema,
    PersonBindSchema,
    PersonOrgBindSchema,
    SysDeptBindSchema,
    SysDeptBusinessMappingOutSchema,
    SysDeptUnbindSchema,
)
from .service import MappingService

SystemMappingRouter = APIRouter(route_class=OperationLogRoute, prefix="", tags=["系统映射管理"])


@SystemMappingRouter.get("/org/page", response_model=ResponseSchema[PageResultSchema[OrgMappingOutSchema]])
async def page_org_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:org:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MappingQueryParam, Query()],
) -> JSONResponse:
    result = await MappingService(auth, db).page_org(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询组织映射成功")


@SystemMappingRouter.get("/person/page", response_model=ResponseSchema[PageResultSchema[PersonMappingOutSchema]])
async def page_person_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:person:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MappingQueryParam, Query()],
) -> JSONResponse:
    result = await MappingService(auth, db).page_person(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询人员映射成功")


@SystemMappingRouter.get("/dept/page", response_model=ResponseSchema[PageResultSchema[DeptMappingOutSchema]])
async def page_dept_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[DeptMappingQueryParam, Query()],
) -> JSONResponse:
    result = await MappingService(auth, db).page_dept(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询部门映射成功")


@SystemMappingRouter.post("/dept/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[DeptMappingOutSchema])
async def create_dept_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[DeptMappingCreateSchema, Body()],
) -> JSONResponse:
    result = await MappingService(auth, db).create_dept(data)
    return SuccessResponse(data=result, msg="创建部门映射成功")


@SystemMappingRouter.put("/dept/update/{id}", response_model=ResponseSchema[DeptMappingOutSchema])
async def update_dept_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[DeptMappingUpdateSchema, Body()],
) -> JSONResponse:
    result = await MappingService(auth, db).update_dept(id, data)
    return SuccessResponse(data=result, msg="修改部门映射成功")


@SystemMappingRouter.delete("/dept/delete", response_model=ResponseSchema[None])
async def delete_dept_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MappingService(auth, db).delete_dept(ids)
    return SuccessResponse(msg="删除部门映射成功")


@SystemMappingRouter.get("/field/page", response_model=ResponseSchema[PageResultSchema[FieldMappingOutSchema]])
async def page_field_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:field:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[FieldMappingQueryParam, Query()],
) -> JSONResponse:
    result = await MappingService(auth, db).page_field(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询字段映射成功")


@SystemMappingRouter.post("/dept/auto-match", response_model=ResponseSchema[dict[str, int]])
async def auto_match_dept(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[AutoMatchSchema, Body()],
) -> JSONResponse:
    result = await MappingService(auth, db).auto_match_dept(data)
    return SuccessResponse(data=result, msg="部门自动匹配完成")


@SystemMappingRouter.post("/field/auto-match", response_model=ResponseSchema[dict[str, int]])
async def auto_match_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:field:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[AutoMatchSchema, Body()],
) -> JSONResponse:
    result = await MappingService(auth, db).auto_match_field(data)
    return SuccessResponse(data=result, msg="字段自动匹配完成")


@SystemMappingRouter.get("/unmapped/org", response_model=ResponseSchema[list[dict]])
async def unmapped_orgs(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:org:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    source_type: Annotated[str | None, Query(max_length=32)] = None,
) -> JSONResponse:
    result = await MappingService(auth, db).unmapped_orgs(source_type)
    return SuccessResponse(data=[item.model_dump() for item in result], msg="查询未绑定组织成功")


@SystemMappingRouter.get("/unmapped/dept", response_model=ResponseSchema[list[dict]])
async def unmapped_depts(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    source_type: Annotated[str | None, Query(max_length=32)] = None,
) -> JSONResponse:
    result = await MappingService(auth, db).unmapped_depts(source_type)
    return SuccessResponse(data=result, msg="查询未绑定部门成功")


@SystemMappingRouter.get("/unmapped/person", response_model=ResponseSchema[list[dict]])
async def unmapped_persons(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:person:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    source_type: Annotated[str | None, Query(max_length=32)] = None,
) -> JSONResponse:
    result = await MappingService(auth, db).unmapped_persons(source_type)
    return SuccessResponse(data=[item.model_dump() for item in result], msg="查询未绑定人员成功")


@SystemMappingRouter.get("/options/org", response_model=ResponseSchema[list[dict]])
async def org_options(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:org:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await MappingService(auth, db).org_options()
    return SuccessResponse(data=result, msg="查询内部组织选项成功")


@SystemMappingRouter.get("/options/dept", response_model=ResponseSchema[list[MasterDeptOptionSchema]])
async def dept_options(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    org_id: Annotated[int | None, Query(ge=1)] = None,
) -> JSONResponse:
    result = await MappingService(auth, db).dept_options(org_id)
    return SuccessResponse(data=result, msg="查询内部部门选项成功")


@SystemMappingRouter.get("/options/person", response_model=ResponseSchema[list[dict]])
async def person_options(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:person:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await MappingService(auth, db).person_options()
    return SuccessResponse(data=result, msg="查询内部人员选项成功")


@SystemMappingRouter.get("/source-types", response_model=ResponseSchema[list[dict]])
async def source_types(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    result = await MappingService(auth, db).source_types()
    return SuccessResponse(data=result, msg="查询来源类型成功")


@SystemMappingRouter.post("/sync/crm-org", summary="手动同步 CRM 人员架构", response_model=ResponseSchema[dict[str, int]])
async def sync_crm_org(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:sync:org"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    """手动任务（无定时）：拉取 CRM 组织/部门树写入来源组织与来源部门。"""
    result = await MappingService(auth, db).sync_crm_org()
    return SuccessResponse(data=result, msg="同步 CRM 人员架构完成")


@SystemMappingRouter.post("/sync/crm-person", summary="手动同步 CRM 人员", response_model=ResponseSchema[dict[str, int]])
async def sync_crm_person(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:sync:person"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
) -> JSONResponse:
    """手动任务（无定时）：拉取 CRM 人员写入来源人员表。"""
    result = await MappingService(auth, db).sync_crm_person()
    return SuccessResponse(data=result, msg="同步 CRM 人员完成")


@SystemMappingRouter.get("/sys-dept/bindings", response_model=ResponseSchema[list[SysDeptBusinessMappingOutSchema]])
async def sys_dept_bindings(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:bind:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    sys_dept_id: Annotated[int, Query(ge=1)],
) -> JSONResponse:
    result = await MappingService(auth, db).sys_dept_bindings(sys_dept_id)
    return SuccessResponse(data=result, msg="查询权限部门绑定成功")


@SystemMappingRouter.get("/sys-dept/options", response_model=ResponseSchema[list[dict]])
async def master_dept_business_options(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:bind:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    source_type: Annotated[str | None, Query(max_length=32)] = None,
    org_id: Annotated[int | None, Query(ge=1)] = None,
    keyword: Annotated[str | None, Query(max_length=128)] = None,
) -> JSONResponse:
    result = await MappingService(auth, db).master_dept_business_options(source_type, org_id, keyword)
    return SuccessResponse(data=result, msg="查询业务标准部门选项成功")


@SystemMappingRouter.post("/sys-dept/bind", response_model=ResponseSchema[None])
async def bind_sys_dept(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:bind:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[SysDeptBindSchema, Body()],
) -> JSONResponse:
    await MappingService(auth, db).bind_sys_dept(data)
    return SuccessResponse(msg="权限部门绑定成功")


@SystemMappingRouter.post("/sys-dept/unbind", response_model=ResponseSchema[None])
async def unbind_sys_dept(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:bind:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[SysDeptUnbindSchema, Body()],
) -> JSONResponse:
    await MappingService(auth, db).unbind_sys_dept(data)
    return SuccessResponse(msg="权限部门解绑成功")


@SystemMappingRouter.post("/bind/org", response_model=ResponseSchema[None])
async def bind_org(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:org:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[OrgBindSchema, Body()],
) -> JSONResponse:
    await MappingService(auth, db).bind_org(data)
    return SuccessResponse(msg="组织绑定成功")


@SystemMappingRouter.post("/bind/dept", response_model=ResponseSchema[None])
async def bind_dept(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:dept:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[DeptBindSchema, Body()],
) -> JSONResponse:
    await MappingService(auth, db).bind_dept(data)
    return SuccessResponse(msg="部门绑定成功")


@SystemMappingRouter.post("/bind/person", response_model=ResponseSchema[None])
async def bind_person(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:person:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[PersonBindSchema, Body()],
) -> JSONResponse:
    await MappingService(auth, db).bind_person(data)
    return SuccessResponse(msg="人员绑定成功")


@SystemMappingRouter.post("/bind/person-org", response_model=ResponseSchema[None])
async def bind_person_org(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_mapping:person:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[PersonOrgBindSchema, Body()],
) -> JSONResponse:
    await MappingService(auth, db).bind_person_org(data)
    return SuccessResponse(msg="人员任岗绑定成功")
