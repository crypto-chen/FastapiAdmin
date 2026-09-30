
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.utils.common_util import search_to_dict

from .crud import (
    FieldMappingCRUD,
    MetaSyncJobCRUD,
    MetaSyncRunCRUD,
    SourceFieldCRUD,
    SourceObjectCRUD,
    SourceSystemCRUD,
    StandardEntityCRUD,
    StandardFieldCRUD,
)
from .model import FieldMappingModel, MetaSyncJobModel, SourceFieldModel, SourceObjectModel, SourceSystemModel, StandardEntityModel, StandardFieldModel
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
from .sync import register_meta_sync_job, unregister_meta_sync_job


class MetadataService:
    """元数据配置服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    # 来源系统
    async def page_source_system(self, search: SourceSystemQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[SourceSystemOutSchema]:
        result = await SourceSystemCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "asc"}], search=search_to_dict(search)
        )
        return PageResultSchema[SourceSystemOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[SourceSystemOutSchema.model_validate(obj) for obj in result.items],
        )

    async def detail_source_system(self, id: int) -> SourceSystemOutSchema:
        return SourceSystemOutSchema.model_validate(await SourceSystemCRUD(self.auth, self.db).get_or_404(id=id, msg="该来源系统不存在"))

    async def create_source_system(self, data: SourceSystemCreateSchema) -> SourceSystemOutSchema:
        if await SourceSystemCRUD(self.auth, self.db).get(code=data.code):
            raise CustomException(msg="创建失败，系统编码已存在")
        return SourceSystemOutSchema.model_validate(await SourceSystemCRUD(self.auth, self.db).create(data=data))

    async def update_source_system(self, id: int, data: SourceSystemUpdateSchema) -> SourceSystemOutSchema:
        await SourceSystemCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该来源系统不存在")
        exist = await SourceSystemCRUD(self.auth, self.db).get(code=data.code)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，系统编码已存在")
        await SourceSystemCRUD(self.auth, self.db).update(id=id, data=data)
        return await self.detail_source_system(id)

    async def delete_source_system(self, ids: list[int]) -> None:
        await SourceSystemCRUD(self.auth, self.db).delete(ids=ids)

    # 来源对象
    async def _source_object_out(self, obj: SourceObjectModel) -> SourceObjectOutSchema:
        out = SourceObjectOutSchema.model_validate(obj)
        system = await self.db.get(SourceSystemModel, obj.system_id)
        out.system_code = system.code if system else None
        out.system_name = system.name if system else None
        return out

    async def page_source_object(self, search: SourceObjectQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[SourceObjectOutSchema]:
        result = await SourceObjectCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "asc"}], search=search_to_dict(search)
        )
        return PageResultSchema[SourceObjectOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[await self._source_object_out(obj) for obj in result.items],
        )

    async def detail_source_object(self, id: int) -> SourceObjectOutSchema:
        obj = await SourceObjectCRUD(self.auth, self.db).get_or_404(id=id, msg="该来源对象不存在")
        return await self._source_object_out(obj)

    async def create_source_object(self, data: SourceObjectCreateSchema) -> SourceObjectOutSchema:
        await SourceSystemCRUD(self.auth, self.db).get_or_404(id=data.system_id, msg="来源系统不存在")
        if await SourceObjectCRUD(self.auth, self.db).get(system_id=data.system_id, code=data.code):
            raise CustomException(msg="创建失败，该对象编码已存在")
        obj = await SourceObjectCRUD(self.auth, self.db).create(data=data)
        return await self.detail_source_object(obj.id)

    async def update_source_object(self, id: int, data: SourceObjectUpdateSchema) -> SourceObjectOutSchema:
        await SourceObjectCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该来源对象不存在")
        await SourceSystemCRUD(self.auth, self.db).get_or_404(id=data.system_id, msg="来源系统不存在")
        exist = await SourceObjectCRUD(self.auth, self.db).get(system_id=data.system_id, code=data.code)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，该对象编码已存在")
        await SourceObjectCRUD(self.auth, self.db).update(id=id, data=data)
        return await self.detail_source_object(id)

    async def delete_source_object(self, ids: list[int]) -> None:
        await SourceObjectCRUD(self.auth, self.db).delete(ids=ids)

    # 来源字段
    async def _source_field_out(self, obj: SourceFieldModel) -> SourceFieldOutSchema:
        out = SourceFieldOutSchema.model_validate(obj)
        source_obj = await self.db.get(SourceObjectModel, obj.object_id)
        out.object_code = source_obj.code if source_obj else None
        out.object_name = source_obj.name if source_obj else None
        return out

    async def page_source_field(self, search: SourceFieldQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[SourceFieldOutSchema]:
        result = await SourceFieldCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "asc"}], search=search_to_dict(search)
        )
        return PageResultSchema[SourceFieldOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[await self._source_field_out(obj) for obj in result.items],
        )

    async def detail_source_field(self, id: int) -> SourceFieldOutSchema:
        obj = await SourceFieldCRUD(self.auth, self.db).get_or_404(id=id, msg="该来源字段不存在")
        return await self._source_field_out(obj)

    async def create_source_field(self, data: SourceFieldCreateSchema) -> SourceFieldOutSchema:
        await SourceObjectCRUD(self.auth, self.db).get_or_404(id=data.object_id, msg="来源对象不存在")
        if await SourceFieldCRUD(self.auth, self.db).get(object_id=data.object_id, field_key=data.field_key):
            raise CustomException(msg="创建失败，该字段Key已存在")
        obj = await SourceFieldCRUD(self.auth, self.db).create(data=data)
        return await self.detail_source_field(obj.id)

    async def update_source_field(self, id: int, data: SourceFieldUpdateSchema) -> SourceFieldOutSchema:
        await SourceFieldCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该来源字段不存在")
        await SourceObjectCRUD(self.auth, self.db).get_or_404(id=data.object_id, msg="来源对象不存在")
        exist = await SourceFieldCRUD(self.auth, self.db).get(object_id=data.object_id, field_key=data.field_key)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，该字段Key已存在")
        await SourceFieldCRUD(self.auth, self.db).update(id=id, data=data)
        return await self.detail_source_field(id)

    async def delete_source_field(self, ids: list[int]) -> None:
        await SourceFieldCRUD(self.auth, self.db).delete(ids=ids)

    # 字段映射
    async def _field_mapping_out(self, obj: FieldMappingModel) -> FieldMappingOutSchema:
        out = FieldMappingOutSchema.model_validate(obj)
        source_field = await self.db.get(SourceFieldModel, obj.source_field_id)
        standard_field = await self.db.get(StandardFieldModel, obj.standard_field_id)
        out.source_field_key = source_field.field_key if source_field else None
        out.source_field_name = source_field.field_name if source_field else None
        out.standard_field_code = standard_field.field_code if standard_field else None
        out.standard_field_name = standard_field.field_name if standard_field else None
        return out

    async def page_field_mapping(self, search: FieldMappingQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[FieldMappingOutSchema]:
        result = await FieldMappingCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"order": "asc"}, {"id": "asc"}], search=search_to_dict(search)
        )
        return PageResultSchema[FieldMappingOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[await self._field_mapping_out(obj) for obj in result.items],
        )

    async def detail_field_mapping(self, id: int) -> FieldMappingOutSchema:
        obj = await FieldMappingCRUD(self.auth, self.db).get_or_404(id=id, msg="该字段映射不存在")
        return await self._field_mapping_out(obj)

    async def create_field_mapping(self, data: FieldMappingCreateSchema) -> FieldMappingOutSchema:
        await SourceFieldCRUD(self.auth, self.db).get_or_404(id=data.source_field_id, msg="来源字段不存在")
        from app.modules.metadata.crud import StandardFieldCRUD  # type: ignore[attr-defined]

        await StandardFieldCRUD(self.auth, self.db).get_or_404(id=data.standard_field_id, msg="标准字段不存在")
        if await FieldMappingCRUD(self.auth, self.db).get(source_field_id=data.source_field_id, standard_field_id=data.standard_field_id):
            raise CustomException(msg="创建失败，该字段映射已存在")
        obj = await FieldMappingCRUD(self.auth, self.db).create(data=data)
        return await self.detail_field_mapping(obj.id)

    async def update_field_mapping(self, id: int, data: FieldMappingUpdateSchema) -> FieldMappingOutSchema:
        await FieldMappingCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该字段映射不存在")
        await SourceFieldCRUD(self.auth, self.db).get_or_404(id=data.source_field_id, msg="来源字段不存在")
        from app.modules.metadata.crud import StandardFieldCRUD  # type: ignore[attr-defined]

        await StandardFieldCRUD(self.auth, self.db).get_or_404(id=data.standard_field_id, msg="标准字段不存在")
        await FieldMappingCRUD(self.auth, self.db).update(id=id, data=data)
        return await self.detail_field_mapping(id)

    async def delete_field_mapping(self, ids: list[int]) -> None:
        await FieldMappingCRUD(self.auth, self.db).delete(ids=ids)

    # 标准实体
    async def page_standard_entity(self, search: StandardEntityQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[StandardEntityOutSchema]:
        result = await StandardEntityCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "asc"}], search=search_to_dict(search)
        )
        return PageResultSchema[StandardEntityOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[StandardEntityOutSchema.model_validate(obj) for obj in result.items],
        )

    async def detail_standard_entity(self, id: int) -> StandardEntityOutSchema:
        return StandardEntityOutSchema.model_validate(await StandardEntityCRUD(self.auth, self.db).get_or_404(id=id, msg="该标准实体不存在"))

    async def create_standard_entity(self, data: StandardEntityCreateSchema) -> StandardEntityOutSchema:
        if await StandardEntityCRUD(self.auth, self.db).get(code=data.code):
            raise CustomException(msg="创建失败，标准实体编码已存在")
        return StandardEntityOutSchema.model_validate(await StandardEntityCRUD(self.auth, self.db).create(data=data))

    async def update_standard_entity(self, id: int, data: StandardEntityUpdateSchema) -> StandardEntityOutSchema:
        await StandardEntityCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该标准实体不存在")
        exist = await StandardEntityCRUD(self.auth, self.db).get(code=data.code)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，标准实体编码已存在")
        await StandardEntityCRUD(self.auth, self.db).update(id=id, data=data)
        return await self.detail_standard_entity(id)

    async def delete_standard_entity(self, ids: list[int]) -> None:
        await StandardEntityCRUD(self.auth, self.db).delete(ids=ids)

    # 标准字段
    async def _standard_field_out(self, obj: StandardFieldModel) -> StandardFieldOutSchema:
        out = StandardFieldOutSchema.model_validate(obj)
        entity = await self.db.get(StandardEntityModel, obj.entity_id)
        out.entity_code = entity.code if entity else None
        out.entity_name = entity.name if entity else None
        return out

    async def page_standard_field(self, search: StandardFieldQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[StandardFieldOutSchema]:
        result = await StandardFieldCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "asc"}], search=search_to_dict(search)
        )
        return PageResultSchema[StandardFieldOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[await self._standard_field_out(obj) for obj in result.items],
        )

    async def detail_standard_field(self, id: int) -> StandardFieldOutSchema:
        obj = await StandardFieldCRUD(self.auth, self.db).get_or_404(id=id, msg="该标准字段不存在")
        return await self._standard_field_out(obj)

    async def create_standard_field(self, data: StandardFieldCreateSchema) -> StandardFieldOutSchema:
        await StandardEntityCRUD(self.auth, self.db).get_or_404(id=data.entity_id, msg="标准实体不存在")
        if await StandardFieldCRUD(self.auth, self.db).get(entity_id=data.entity_id, field_code=data.field_code):
            raise CustomException(msg="创建失败，标准字段编码已存在")
        obj = await StandardFieldCRUD(self.auth, self.db).create(data=data)
        return await self.detail_standard_field(obj.id)

    async def update_standard_field(self, id: int, data: StandardFieldUpdateSchema) -> StandardFieldOutSchema:
        await StandardFieldCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该标准字段不存在")
        await StandardEntityCRUD(self.auth, self.db).get_or_404(id=data.entity_id, msg="标准实体不存在")
        exist = await StandardFieldCRUD(self.auth, self.db).get(entity_id=data.entity_id, field_code=data.field_code)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，标准字段编码已存在")
        await StandardFieldCRUD(self.auth, self.db).update(id=id, data=data)
        return await self.detail_standard_field(id)

    async def delete_standard_field(self, ids: list[int]) -> None:
        await StandardFieldCRUD(self.auth, self.db).delete(ids=ids)

    # 元数据同步任务
    async def _sync_job_out(self, obj: MetaSyncJobModel) -> MetaSyncJobOutSchema:
        out = MetaSyncJobOutSchema.model_validate(obj)
        system = await self.db.get(SourceSystemModel, obj.source_system_id)
        source_obj = await self.db.get(SourceObjectModel, obj.source_object_id)
        out.system_code = system.code if system else None
        out.object_code = source_obj.code if source_obj else None
        out.object_name = source_obj.name if source_obj else None
        return out

    async def page_sync_job(self, search: MetaSyncJobQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[MetaSyncJobOutSchema]:
        result = await MetaSyncJobCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "desc"}], search=search_to_dict(search)
        )
        return PageResultSchema[MetaSyncJobOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[await self._sync_job_out(obj) for obj in result.items],
        )

    async def detail_sync_job(self, id: int) -> MetaSyncJobOutSchema:
        obj = await MetaSyncJobCRUD(self.auth, self.db).get_or_404(id=id, msg="该同步任务不存在")
        return await self._sync_job_out(obj)

    async def create_sync_job(self, data: MetaSyncJobCreateSchema) -> MetaSyncJobOutSchema:
        await SourceSystemCRUD(self.auth, self.db).get_or_404(id=data.source_system_id, msg="来源系统不存在")
        await SourceObjectCRUD(self.auth, self.db).get_or_404(id=data.source_object_id, msg="来源对象不存在")
        obj = await MetaSyncJobCRUD(self.auth, self.db).create(data=data)
        register_meta_sync_job(obj)
        return await self.detail_sync_job(obj.id)

    async def update_sync_job(self, id: int, data: MetaSyncJobUpdateSchema) -> MetaSyncJobOutSchema:
        await MetaSyncJobCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该同步任务不存在")
        await MetaSyncJobCRUD(self.auth, self.db).update(id=id, data=data)
        obj = await MetaSyncJobCRUD(self.auth, self.db).get_or_404(id=id)
        register_meta_sync_job(obj)
        return await self._sync_job_out(obj)

    async def delete_sync_job(self, ids: list[int]) -> None:
        for id in ids:
            unregister_meta_sync_job(id)
        await MetaSyncJobCRUD(self.auth, self.db).delete(ids=ids)

    async def page_sync_run(self, job_id: int | None, page_no: int, page_size: int) -> PageResultSchema[MetaSyncRunOutSchema]:
        search = {"job_id": ("eq", job_id)} if job_id else {}
        result = await MetaSyncRunCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size, limit=page_size, order_by=[{"id": "desc"}], search=search
        )
        return PageResultSchema[MetaSyncRunOutSchema](
            page_no=result.page_no, page_size=result.page_size, total=result.total, has_next=result.has_next,
            items=[MetaSyncRunOutSchema.model_validate(obj) for obj in result.items],
        )

    async def run_sync_job_now(self, id: int) -> None:
        from .sync import execute_meta_sync_job

        await execute_meta_sync_job(id)

    async def detail_sync_run(self, id: int) -> MetaSyncRunDetailSchema:
        obj = await MetaSyncRunCRUD(self.auth, self.db).get_or_404(id=id, msg="该同步日志不存在")
        return MetaSyncRunDetailSchema.model_validate(obj)
