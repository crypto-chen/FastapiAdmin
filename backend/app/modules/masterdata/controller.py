from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    AutoMatchSchema,
    MappingQueryParam,
    MasterOrgCreateSchema,
    MasterOrgOutSchema,
    MasterOrgQueryParam,
    MasterOrgUpdateSchema,
    MasterPersonCreateSchema,
    MasterPersonOutSchema,
    MasterPersonQueryParam,
    MasterPersonUpdateSchema,
    OrgMappingCreateSchema,
    OrgMappingOutSchema,
    OrgMappingUpdateSchema,
    PersonMappingCreateSchema,
    PersonMappingOutSchema,
    PersonMappingUpdateSchema,
    SourceOrgOutSchema,
    SourcePersonOutSchema,
    SourceQueryParam,
)
from .service import MasterMappingService, MasterOrgService, MasterPersonService, MasterSourceService

MasterOrgRouter = APIRouter(route_class=OperationLogRoute, prefix="/org", tags=["标准组织"])
MasterPersonRouter = APIRouter(route_class=OperationLogRoute, prefix="/person", tags=["标准人员"])
MasterSourceRouter = APIRouter(route_class=OperationLogRoute, prefix="/source", tags=["来源数据"])
MasterMappingRouter = APIRouter(route_class=OperationLogRoute, prefix="/mapping", tags=["主数据映射"])


@MasterOrgRouter.get("/tree", summary="查询标准组织树", response_model=ResponseSchema[list[dict[str, Any]]])
async def get_master_org_tree_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:org:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    search: Annotated[MasterOrgQueryParam, Query()],
) -> JSONResponse:
    result = await MasterOrgService(auth, db).tree(search=search)
    return SuccessResponse(data=result, msg="查询标准组织树成功")


@MasterOrgRouter.get("/page", summary="分页查询标准组织", response_model=ResponseSchema[PageResultSchema[MasterOrgOutSchema]])
async def get_master_org_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:org:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MasterOrgQueryParam, Query()],
) -> JSONResponse:
    result: PageResultSchema[MasterOrgOutSchema] = await MasterOrgService(auth, db).page(
        search=search,
        page_no=page.page_no,
        page_size=page.page_size,
        order_by=page.order_by,
    )
    return SuccessResponse(data=result, msg="查询标准组织成功")


@MasterOrgRouter.get("/detail/{id}", summary="查询标准组织详情", response_model=ResponseSchema[MasterOrgOutSchema])
async def get_master_org_detail_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:org:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="组织ID", ge=1)],
) -> JSONResponse:
    result: MasterOrgOutSchema = await MasterOrgService(auth, db).detail(id=id)
    return SuccessResponse(data=result, msg="查询标准组织详情成功")


@MasterOrgRouter.post("/create", status_code=status.HTTP_201_CREATED, summary="创建标准组织", response_model=ResponseSchema[MasterOrgOutSchema])
async def create_master_org_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:org:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[MasterOrgCreateSchema, Body(description="标准组织创建参数")],
) -> JSONResponse:
    result: MasterOrgOutSchema = await MasterOrgService(auth, db).create(data=data)
    return SuccessResponse(data=result, msg="创建标准组织成功")


@MasterOrgRouter.put("/update/{id}", summary="修改标准组织", response_model=ResponseSchema[MasterOrgOutSchema])
async def update_master_org_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:org:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="组织ID", ge=1)],
    data: Annotated[MasterOrgUpdateSchema, Body(description="标准组织修改参数")],
) -> JSONResponse:
    result: MasterOrgOutSchema = await MasterOrgService(auth, db).update(id=id, data=data)
    return SuccessResponse(data=result, msg="修改标准组织成功")


@MasterOrgRouter.delete("/delete", summary="删除标准组织", response_model=ResponseSchema[None])
async def delete_master_org_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:org:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body(description="组织ID列表")],
) -> JSONResponse:
    await MasterOrgService(auth, db).delete(ids=ids)
    return SuccessResponse(msg="删除标准组织成功")


@MasterPersonRouter.get("/page", summary="分页查询标准人员", response_model=ResponseSchema[PageResultSchema[MasterPersonOutSchema]])
async def get_master_person_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:person:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MasterPersonQueryParam, Query()],
) -> JSONResponse:
    result: PageResultSchema[MasterPersonOutSchema] = await MasterPersonService(auth, db).page(
        search=search,
        page_no=page.page_no,
        page_size=page.page_size,
        order_by=page.order_by,
    )
    return SuccessResponse(data=result, msg="查询标准人员成功")


@MasterPersonRouter.get("/detail/{id}", summary="查询标准人员详情", response_model=ResponseSchema[MasterPersonOutSchema])
async def get_master_person_detail_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:person:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="人员ID", ge=1)],
) -> JSONResponse:
    result: MasterPersonOutSchema = await MasterPersonService(auth, db).detail(id=id)
    return SuccessResponse(data=result, msg="查询标准人员详情成功")


@MasterPersonRouter.post("/create", status_code=status.HTTP_201_CREATED, summary="创建标准人员", response_model=ResponseSchema[MasterPersonOutSchema])
async def create_master_person_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:person:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[MasterPersonCreateSchema, Body(description="标准人员创建参数")],
) -> JSONResponse:
    result: MasterPersonOutSchema = await MasterPersonService(auth, db).create(data=data)
    return SuccessResponse(data=result, msg="创建标准人员成功")


@MasterPersonRouter.put("/update/{id}", summary="修改标准人员", response_model=ResponseSchema[MasterPersonOutSchema])
async def update_master_person_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:person:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="人员ID", ge=1)],
    data: Annotated[MasterPersonUpdateSchema, Body(description="标准人员修改参数")],
) -> JSONResponse:
    result: MasterPersonOutSchema = await MasterPersonService(auth, db).update(id=id, data=data)
    return SuccessResponse(data=result, msg="修改标准人员成功")


@MasterPersonRouter.delete("/delete", summary="删除标准人员", response_model=ResponseSchema[None])
async def delete_master_person_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:person:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body(description="人员ID列表")],
) -> JSONResponse:
    await MasterPersonService(auth, db).delete(ids=ids)
    return SuccessResponse(msg="删除标准人员成功")


@MasterSourceRouter.get("/org/page", summary="分页查询来源组织", response_model=ResponseSchema[PageResultSchema[SourceOrgOutSchema]])
async def get_source_org_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[SourceQueryParam, Query()],
) -> JSONResponse:
    result = await MasterSourceService(auth, db).page_orgs(search=search, page_no=page.page_no, page_size=page.page_size)
    return SuccessResponse(data=result, msg="查询来源组织成功")


@MasterSourceRouter.get("/person/page", summary="分页查询来源人员", response_model=ResponseSchema[PageResultSchema[SourcePersonOutSchema]])
async def get_source_person_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[SourceQueryParam, Query()],
) -> JSONResponse:
    result = await MasterSourceService(auth, db).page_persons(search=search, page_no=page.page_no, page_size=page.page_size)
    return SuccessResponse(data=result, msg="查询来源人员成功")


@MasterMappingRouter.get("/org/page", summary="分页查询组织映射", response_model=ResponseSchema[PageResultSchema[OrgMappingOutSchema]])
async def get_org_mapping_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MappingQueryParam, Query()],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).page_org_mappings(search=search, page_no=page.page_no, page_size=page.page_size)
    return SuccessResponse(data=result, msg="查询组织映射成功")


@MasterMappingRouter.get("/person/page", summary="分页查询人员映射", response_model=ResponseSchema[PageResultSchema[PersonMappingOutSchema]])
async def get_person_mapping_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MappingQueryParam, Query()],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).page_person_mappings(search=search, page_no=page.page_no, page_size=page.page_size)
    return SuccessResponse(data=result, msg="查询人员映射成功")


@MasterMappingRouter.post("/org/create", status_code=status.HTTP_201_CREATED, summary="创建组织映射", response_model=ResponseSchema[OrgMappingOutSchema])
async def create_org_mapping_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[OrgMappingCreateSchema, Body(description="组织映射参数")],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).create_org_mapping(data=data)
    return SuccessResponse(data=result, msg="创建组织映射成功")


@MasterMappingRouter.put("/org/update/{id}", summary="修改组织映射", response_model=ResponseSchema[OrgMappingOutSchema])
async def update_org_mapping_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="组织映射ID", ge=1)],
    data: Annotated[OrgMappingUpdateSchema, Body(description="组织映射参数")],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).update_org_mapping(id=id, data=data)
    return SuccessResponse(data=result, msg="修改组织映射成功")


@MasterMappingRouter.delete("/org/delete", summary="删除组织映射", response_model=ResponseSchema[None])
async def delete_org_mapping_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body(description="组织映射ID列表")],
) -> JSONResponse:
    await MasterMappingService(auth, db).delete_org_mappings(ids=ids)
    return SuccessResponse(msg="删除组织映射成功")


@MasterMappingRouter.post("/person/create", status_code=status.HTTP_201_CREATED, summary="创建人员映射", response_model=ResponseSchema[PersonMappingOutSchema])
async def create_person_mapping_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[PersonMappingCreateSchema, Body(description="人员映射参数")],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).create_person_mapping(data=data)
    return SuccessResponse(data=result, msg="创建人员映射成功")


@MasterMappingRouter.put("/person/update/{id}", summary="修改人员映射", response_model=ResponseSchema[PersonMappingOutSchema])
async def update_person_mapping_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="人员映射ID", ge=1)],
    data: Annotated[PersonMappingUpdateSchema, Body(description="人员映射参数")],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).update_person_mapping(id=id, data=data)
    return SuccessResponse(data=result, msg="修改人员映射成功")


@MasterMappingRouter.delete("/person/delete", summary="删除人员映射", response_model=ResponseSchema[None])
async def delete_person_mapping_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body(description="人员映射ID列表")],
) -> JSONResponse:
    await MasterMappingService(auth, db).delete_person_mappings(ids=ids)
    return SuccessResponse(msg="删除人员映射成功")


@MasterMappingRouter.post("/org/auto-match", summary="按编码自动匹配组织", response_model=ResponseSchema[dict[str, int]])
async def auto_match_org_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[AutoMatchSchema, Body(description="自动匹配参数")],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).auto_match_org(data=data)
    return SuccessResponse(data=result, msg="组织自动匹配完成")


@MasterMappingRouter.post("/person/auto-match", summary="按编码自动匹配人员", response_model=ResponseSchema[dict[str, int]])
async def auto_match_person_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_masterdata:mapping:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[AutoMatchSchema, Body(description="自动匹配参数")],
) -> JSONResponse:
    result = await MasterMappingService(auth, db).auto_match_person(data=data)
    return SuccessResponse(data=result, msg="人员自动匹配完成")
