from typing import Annotated

from fastapi import APIRouter, Body, Depends, Path, Query, Security, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.response import ResponseSchema, SuccessResponse
from app.core.base_schema import AuthSchema, PageResultSchema, PaginationQueryParam
from app.core.dependencies import AuthPermission, db_getter
from app.core.router_class import OperationLogRoute

from .schema import (
    KingdeeBillQueryResultSchema,
    KingdeeBillQuerySchema,
    KingdeeConnectionCreateSchema,
    KingdeeConnectionOutSchema,
    KingdeeConnectionQueryParam,
    KingdeeConnectionUpdateSchema,
    KingdeeViewSchema,
)
from .service import KingdeeService

KingdeeRouter = APIRouter(route_class=OperationLogRoute, prefix="/kingdee", tags=["金蝶数据源"])


@KingdeeRouter.get("/page", summary="分页查询金蝶连接", response_model=ResponseSchema[PageResultSchema[KingdeeConnectionOutSchema]])
async def get_kingdee_connection_page_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    page: Annotated[PaginationQueryParam, Depends()],
    search: Annotated[KingdeeConnectionQueryParam, Query()],
) -> JSONResponse:
    result: PageResultSchema[KingdeeConnectionOutSchema] = await KingdeeService(auth, db).page(
        search=search,
        page_no=page.page_no,
        page_size=page.page_size,
        order_by=page.order_by,
    )
    return SuccessResponse(data=result, msg="查询金蝶连接成功")


@KingdeeRouter.get("/list", summary="查询金蝶连接列表", response_model=ResponseSchema[list[KingdeeConnectionOutSchema]])
async def get_kingdee_connection_list_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    search: Annotated[KingdeeConnectionQueryParam, Query()],
) -> JSONResponse:
    result: list[KingdeeConnectionOutSchema] = await KingdeeService(auth, db).get_list(search=search)
    return SuccessResponse(data=result, msg="查询金蝶连接成功")


@KingdeeRouter.get("/detail/{id}", summary="查询金蝶连接详情", response_model=ResponseSchema[KingdeeConnectionOutSchema])
async def get_kingdee_connection_detail_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="金蝶连接ID", ge=1)],
) -> JSONResponse:
    result: KingdeeConnectionOutSchema = await KingdeeService(auth, db).detail(id=id)
    return SuccessResponse(data=result, msg="查询金蝶连接详情成功")


@KingdeeRouter.post("/create", status_code=status.HTTP_201_CREATED, summary="创建金蝶连接", response_model=ResponseSchema[KingdeeConnectionOutSchema])
async def create_kingdee_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:create"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[KingdeeConnectionCreateSchema, Body(description="金蝶连接创建参数")],
) -> JSONResponse:
    result: KingdeeConnectionOutSchema = await KingdeeService(auth, db).create(data=data)
    return SuccessResponse(data=result, msg="创建金蝶连接成功")


@KingdeeRouter.put("/update/{id}", summary="修改金蝶连接", response_model=ResponseSchema[KingdeeConnectionOutSchema])
async def update_kingdee_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:update"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="金蝶连接ID", ge=1)],
    data: Annotated[KingdeeConnectionUpdateSchema, Body(description="金蝶连接修改参数")],
) -> JSONResponse:
    result: KingdeeConnectionOutSchema = await KingdeeService(auth, db).update(id=id, data=data)
    return SuccessResponse(data=result, msg="修改金蝶连接成功")


@KingdeeRouter.delete("/delete", summary="删除金蝶连接", response_model=ResponseSchema[None])
async def delete_kingdee_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:delete"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    ids: Annotated[list[int], Body(description="金蝶连接ID列表")],
) -> JSONResponse:
    await KingdeeService(auth, db).delete(ids=ids)
    return SuccessResponse(msg="删除金蝶连接成功")


@KingdeeRouter.post("/test/{id}", summary="测试金蝶连接", response_model=ResponseSchema[bool])
async def test_kingdee_connection_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    id: Annotated[int, Path(description="金蝶连接ID", ge=1)],
) -> JSONResponse:
    result: bool = await KingdeeService(auth, db).test_connection(id=id)
    return SuccessResponse(data=result, msg="连接成功")


@KingdeeRouter.post("/query", summary="查询金蝶单据数据", response_model=ResponseSchema[KingdeeBillQueryResultSchema])
async def query_kingdee_bill_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[KingdeeBillQuerySchema, Body(description="金蝶单据查询参数")],
) -> JSONResponse:
    result: KingdeeBillQueryResultSchema = await KingdeeService(auth, db).bill_query(data=data)
    return SuccessResponse(data=result, msg="查询金蝶单据成功")


@KingdeeRouter.post("/view", summary="查看金蝶业务对象", response_model=ResponseSchema[dict])
async def view_kingdee_object_controller(
    auth: Annotated[AuthSchema, Security(AuthPermission(["module_erp:kingdee:query"]))],
    db: Annotated[AsyncSession, Depends(db_getter)],
    data: Annotated[KingdeeViewSchema, Body(description="金蝶业务对象查看参数")],
) -> JSONResponse:
    result: dict = await KingdeeService(auth, db).view(data=data)
    return SuccessResponse(data=result, msg="查看金蝶业务对象成功")
