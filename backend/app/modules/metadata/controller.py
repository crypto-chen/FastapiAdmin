from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    FieldMappingCreateSchema,
    FieldMappingOutSchema,
    FieldMappingQueryParam,
    FieldMappingUpdateSchema,
    MetaSyncJobCreateSchema,
    MetaSyncJobOutSchema,
    MetaSyncJobQueryParam,
    MetaSyncJobUpdateSchema,
    MetaSyncRunDetailSchema,
    MetaSyncRunOutSchema,
    SourceFieldCreateSchema,
    SourceFieldOutSchema,
    SourceFieldQueryParam,
    SourceFieldUpdateSchema,
    SourceObjectCreateSchema,
    SourceObjectOutSchema,
    SourceObjectQueryParam,
    SourceObjectUpdateSchema,
    SourceSystemCreateSchema,
    SourceSystemOutSchema,
    SourceSystemQueryParam,
    SourceSystemUpdateSchema,
    StandardEntityCreateSchema,
    StandardEntityOutSchema,
    StandardEntityQueryParam,
    StandardEntityUpdateSchema,
    StandardFieldCreateSchema,
    StandardFieldOutSchema,
    StandardFieldQueryParam,
    StandardFieldUpdateSchema,
)
from .service import MetadataService

SourceSystemRouter = APIRouter(route_class=OperationLogRoute, prefix="/source-system", tags=["来源系统"])
SourceObjectRouter = APIRouter(route_class=OperationLogRoute, prefix="/source-object", tags=["来源对象"])
SourceFieldRouter = APIRouter(route_class=OperationLogRoute, prefix="/source-field", tags=["来源字段"])
FieldMappingRouter = APIRouter(route_class=OperationLogRoute, prefix="/field-mapping", tags=["字段映射"])
StandardEntityRouter = APIRouter(route_class=OperationLogRoute, prefix="/standard-entity", tags=["标准实体"])
StandardFieldRouter = APIRouter(route_class=OperationLogRoute, prefix="/standard-field", tags=["标准字段"])
SyncJobRouter = APIRouter(route_class=OperationLogRoute, prefix="/sync-job", tags=["元数据同步任务"])


@SourceSystemRouter.get("/page", response_model=ResponseSchema[PageResultSchema[SourceSystemOutSchema]])
async def page_source_system(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[SourceSystemQueryParam, Query()],
) -> JSONResponse:
    result = await MetadataService(auth, db).page_source_system(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询来源系统成功")


@SourceSystemRouter.get("/detail/{id}", response_model=ResponseSchema[SourceSystemOutSchema])
async def detail_source_system(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_source_system(id)
    return SuccessResponse(data=result, msg="查询来源系统详情成功")


@SourceSystemRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[SourceSystemOutSchema])
async def create_source_system(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[SourceSystemCreateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).create_source_system(data)
    return SuccessResponse(data=result, msg="创建来源系统成功")


@SourceSystemRouter.put("/update/{id}", response_model=ResponseSchema[SourceSystemOutSchema])
async def update_source_system(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[SourceSystemUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).update_source_system(id, data)
    return SuccessResponse(data=result, msg="修改来源系统成功")


@SourceSystemRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_source_system(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetadataService(auth, db).delete_source_system(ids)
    return SuccessResponse(msg="删除来源系统成功")


@SourceObjectRouter.get("/page", response_model=ResponseSchema[PageResultSchema[SourceObjectOutSchema]])
async def page_source_object(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[SourceObjectQueryParam, Query()],
) -> JSONResponse:
    result = await MetadataService(auth, db).page_source_object(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询来源对象成功")


@SourceObjectRouter.get("/detail/{id}", response_model=ResponseSchema[SourceObjectOutSchema])
async def detail_source_object(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_source_object(id)
    return SuccessResponse(data=result, msg="查询来源对象详情成功")


@SourceObjectRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[SourceObjectOutSchema])
async def create_source_object(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[SourceObjectCreateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).create_source_object(data)
    return SuccessResponse(data=result, msg="创建来源对象成功")


@SourceObjectRouter.put("/update/{id}", response_model=ResponseSchema[SourceObjectOutSchema])
async def update_source_object(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[SourceObjectUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).update_source_object(id, data)
    return SuccessResponse(data=result, msg="修改来源对象成功")


@SourceObjectRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_source_object(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetadataService(auth, db).delete_source_object(ids)
    return SuccessResponse(msg="删除来源对象成功")


@SourceFieldRouter.get("/page", response_model=ResponseSchema[PageResultSchema[SourceFieldOutSchema]])
async def page_source_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[SourceFieldQueryParam, Query()],
) -> JSONResponse:
    result = await MetadataService(auth, db).page_source_field(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询来源字段成功")


@SourceFieldRouter.get("/detail/{id}", response_model=ResponseSchema[SourceFieldOutSchema])
async def detail_source_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_source_field(id)
    return SuccessResponse(data=result, msg="查询来源字段详情成功")


@SourceFieldRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[SourceFieldOutSchema])
async def create_source_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[SourceFieldCreateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).create_source_field(data)
    return SuccessResponse(data=result, msg="创建来源字段成功")


@SourceFieldRouter.put("/update/{id}", response_model=ResponseSchema[SourceFieldOutSchema])
async def update_source_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[SourceFieldUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).update_source_field(id, data)
    return SuccessResponse(data=result, msg="修改来源字段成功")


@SourceFieldRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_source_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:source:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetadataService(auth, db).delete_source_field(ids)
    return SuccessResponse(msg="删除来源字段成功")


@FieldMappingRouter.get("/page", response_model=ResponseSchema[PageResultSchema[FieldMappingOutSchema]])
async def page_field_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:mapping:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[FieldMappingQueryParam, Query()],
) -> JSONResponse:
    result = await MetadataService(auth, db).page_field_mapping(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询字段映射成功")


@FieldMappingRouter.get("/detail/{id}", response_model=ResponseSchema[FieldMappingOutSchema])
async def detail_field_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:mapping:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_field_mapping(id)
    return SuccessResponse(data=result, msg="查询字段映射详情成功")


@FieldMappingRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[FieldMappingOutSchema])
async def create_field_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:mapping:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[FieldMappingCreateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).create_field_mapping(data)
    return SuccessResponse(data=result, msg="创建字段映射成功")


@FieldMappingRouter.put("/update/{id}", response_model=ResponseSchema[FieldMappingOutSchema])
async def update_field_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:mapping:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[FieldMappingUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).update_field_mapping(id, data)
    return SuccessResponse(data=result, msg="修改字段映射成功")


@FieldMappingRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_field_mapping(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:mapping:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetadataService(auth, db).delete_field_mapping(ids)
    return SuccessResponse(msg="删除字段映射成功")


@StandardEntityRouter.get("/page", response_model=ResponseSchema[PageResultSchema[StandardEntityOutSchema]])
async def page_standard_entity(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[StandardEntityQueryParam, Query()],
) -> JSONResponse:
    result = await MetadataService(auth, db).page_standard_entity(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询标准实体成功")


@StandardEntityRouter.get("/detail/{id}", response_model=ResponseSchema[StandardEntityOutSchema])
async def detail_standard_entity(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_standard_entity(id)
    return SuccessResponse(data=result, msg="查询标准实体详情成功")


@StandardEntityRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[StandardEntityOutSchema])
async def create_standard_entity(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[StandardEntityCreateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).create_standard_entity(data)
    return SuccessResponse(data=result, msg="创建标准实体成功")


@StandardEntityRouter.put("/update/{id}", response_model=ResponseSchema[StandardEntityOutSchema])
async def update_standard_entity(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[StandardEntityUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).update_standard_entity(id, data)
    return SuccessResponse(data=result, msg="修改标准实体成功")


@StandardEntityRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_standard_entity(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetadataService(auth, db).delete_standard_entity(ids)
    return SuccessResponse(msg="删除标准实体成功")


@StandardFieldRouter.get("/page", response_model=ResponseSchema[PageResultSchema[StandardFieldOutSchema]])
async def page_standard_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[StandardFieldQueryParam, Query()],
) -> JSONResponse:
    result = await MetadataService(auth, db).page_standard_field(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询标准字段成功")


@StandardFieldRouter.get("/detail/{id}", response_model=ResponseSchema[StandardFieldOutSchema])
async def detail_standard_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_standard_field(id)
    return SuccessResponse(data=result, msg="查询标准字段详情成功")


@StandardFieldRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[StandardFieldOutSchema])
async def create_standard_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[StandardFieldCreateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).create_standard_field(data)
    return SuccessResponse(data=result, msg="创建标准字段成功")


@StandardFieldRouter.put("/update/{id}", response_model=ResponseSchema[StandardFieldOutSchema])
async def update_standard_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[StandardFieldUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).update_standard_field(id, data)
    return SuccessResponse(data=result, msg="修改标准字段成功")


@StandardFieldRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_standard_field(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:standard:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetadataService(auth, db).delete_standard_field(ids)
    return SuccessResponse(msg="删除标准字段成功")


@SyncJobRouter.get("/page", response_model=ResponseSchema[PageResultSchema[MetaSyncJobOutSchema]])
async def page_sync_job(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[MetaSyncJobQueryParam, Query()],
) -> JSONResponse:
    result = await MetadataService(auth, db).page_sync_job(search, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询同步任务成功")


@SyncJobRouter.get("/detail/{id}", response_model=ResponseSchema[MetaSyncJobOutSchema])
async def detail_sync_job(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_sync_job(id)
    return SuccessResponse(data=result, msg="查询同步任务详情成功")


@SyncJobRouter.post("/create", status_code=status.HTTP_201_CREATED, response_model=ResponseSchema[MetaSyncJobOutSchema])
async def create_sync_job(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[MetaSyncJobCreateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).create_sync_job(data)
    return SuccessResponse(data=result, msg="创建同步任务成功")


@SyncJobRouter.put("/update/{id}", response_model=ResponseSchema[MetaSyncJobOutSchema])
async def update_sync_job(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
    data: Annotated[MetaSyncJobUpdateSchema, Body()],
) -> JSONResponse:
    result = await MetadataService(auth, db).update_sync_job(id, data)
    return SuccessResponse(data=result, msg="修改同步任务成功")


@SyncJobRouter.delete("/delete", response_model=ResponseSchema[None])
async def delete_sync_job(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body()],
) -> JSONResponse:
    await MetadataService(auth, db).delete_sync_job(ids)
    return SuccessResponse(msg="删除同步任务成功")


@SyncJobRouter.post("/run/{id}", response_model=ResponseSchema[None])
async def run_sync_job_now(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    await MetadataService(auth, db).run_sync_job_now(id)
    return SuccessResponse(msg="同步任务已执行")


@SyncJobRouter.get("/run/page", response_model=ResponseSchema[PageResultSchema[MetaSyncRunOutSchema]])
async def page_sync_run(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    job_id: Annotated[int | None, Query(ge=1)] = None,
) -> JSONResponse:
    result = await MetadataService(auth, db).page_sync_run(job_id, page.page_no, page.page_size)
    return SuccessResponse(data=result, msg="查询同步日志成功")


@SyncJobRouter.get("/run/detail/{id}", response_model=ResponseSchema[MetaSyncRunDetailSchema])
async def detail_sync_run(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_metadata:sync:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(ge=1)],
) -> JSONResponse:
    result = await MetadataService(auth, db).detail_sync_run(id)
    return SuccessResponse(data=result, msg="查询同步日志详情成功")
