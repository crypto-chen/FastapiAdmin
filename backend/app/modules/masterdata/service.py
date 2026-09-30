from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.utils.common_util import get_child_id_map, get_child_recursion, search_to_dict, traversal_to_tree

from .crud import (
    MasterOrgCRUD,
    MasterPersonCRUD,
    OrgMappingCRUD,
    PersonMappingCRUD,
    SourceOrgCRUD,
    SourcePersonCRUD,
)
from .model import (
    MasterOrgModel,
    MasterPersonModel,
    OrgMappingModel,
    PersonMappingModel,
    SourceOrgModel,
    SourcePersonModel,
)
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


class MasterOrgService:
    """内部标准组织服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _crud(self) -> MasterOrgCRUD:
        return MasterOrgCRUD(self.auth, self.db)

    async def detail(self, id: int) -> MasterOrgOutSchema:
        obj = await self._crud().get_or_404(id=id, msg="该组织不存在")
        out = MasterOrgOutSchema.model_validate(obj)
        if obj.parent_id:
            parent = await self._crud().get(id=obj.parent_id)
            out.parent_name = parent.name if parent else None
        return out

    async def tree(self, search: MasterOrgQueryParam | None = None) -> list[dict[str, Any]]:
        objs = await self._crud().get_list(search=search_to_dict(search), order_by=[{"order": "asc"}, {"id": "asc"}])
        nodes = [MasterOrgOutSchema.model_validate(obj).model_dump(mode="json") for obj in objs]
        return traversal_to_tree(nodes)

    async def page(
        self,
        search: MasterOrgQueryParam | None,
        page_no: int,
        page_size: int,
        order_by: list[dict] | None = None,
    ) -> PageResultSchema[MasterOrgOutSchema]:
        result = await self._crud().page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=order_by or [{"order": "asc"}, {"id": "asc"}],
            search=search_to_dict(search),
        )
        items = [MasterOrgOutSchema.model_validate(obj) for obj in result.items]
        return PageResultSchema[MasterOrgOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=items,
        )

    async def create(self, data: MasterOrgCreateSchema) -> MasterOrgOutSchema:
        if await self._crud().get(code=data.code):
            raise CustomException(msg="创建失败，组织编码已存在")
        if data.parent_id:
            await self._crud().get_or_404(id=data.parent_id, msg="上级组织不存在")
        obj = await self._crud().create(data=data)
        return await self.detail(id=obj.id)

    async def update(self, id: int, data: MasterOrgUpdateSchema) -> MasterOrgOutSchema:
        await self._crud().get_or_404(id=id, msg="更新失败，该组织不存在")
        exist = await self._crud().get(code=data.code)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，组织编码已存在")
        if data.parent_id == id:
            raise CustomException(msg="上级组织不能是自身")
        if data.parent_id:
            all_orgs = await self._crud().get_list()
            child_map = get_child_id_map(list(all_orgs))
            if data.parent_id in get_child_recursion(id, child_map):
                raise CustomException(msg="上级组织不能是自己的下级组织")
            await self._crud().get_or_404(id=data.parent_id, msg="上级组织不存在")
        await self._crud().update(id=id, data=data)
        return await self.detail(id=id)

    async def delete(self, ids: list[int]) -> None:
        if not ids:
            raise CustomException(msg="删除失败，删除对象不能为空")
        all_orgs = await self._crud().get_list()
        child_map = get_child_id_map(list(all_orgs))
        for org_id in ids:
            if child_map.get(org_id):
                raise CustomException(msg="存在下级组织，不允许删除")
        person_crud = MasterPersonCRUD(self.auth, self.db)
        if await person_crud.count(org_id=("in", ids)):
            raise CustomException(msg="组织下存在人员，不允许删除")
        await self._crud().delete(ids=ids)


class MasterPersonService:
    """内部标准人员服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    def _crud(self) -> MasterPersonCRUD:
        return MasterPersonCRUD(self.auth, self.db)

    async def detail(self, id: int) -> MasterPersonOutSchema:
        obj = await self._crud().get_or_404(id=id, msg="该人员不存在")
        return await self._to_out(obj)

    async def _to_out(self, obj: MasterPersonModel) -> MasterPersonOutSchema:
        out = MasterPersonOutSchema.model_validate(obj)
        if obj.org_id:
            org = await self.db.get(MasterOrgModel, obj.org_id)
            out.org_name = org.name if org else None
        return out

    async def page(
        self,
        search: MasterPersonQueryParam | None,
        page_no: int,
        page_size: int,
        order_by: list[dict] | None = None,
    ) -> PageResultSchema[MasterPersonOutSchema]:
        result = await self._crud().page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=order_by or [{"id": "asc"}],
            search=search_to_dict(search),
        )
        items = [await self._to_out(obj) for obj in result.items]
        return PageResultSchema[MasterPersonOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=items,
        )

    async def create(self, data: MasterPersonCreateSchema) -> MasterPersonOutSchema:
        if await self._crud().get(code=data.code):
            raise CustomException(msg="创建失败，人员编码已存在")
        if data.org_id:
            await MasterOrgCRUD(self.auth, self.db).get_or_404(id=data.org_id, msg="所属组织不存在")
        obj = await self._crud().create(data=data)
        return await self.detail(id=obj.id)

    async def update(self, id: int, data: MasterPersonUpdateSchema) -> MasterPersonOutSchema:
        await self._crud().get_or_404(id=id, msg="更新失败，该人员不存在")
        exist = await self._crud().get(code=data.code)
        if exist and exist.id != id:
            raise CustomException(msg="更新失败，人员编码已存在")
        if data.org_id:
            await MasterOrgCRUD(self.auth, self.db).get_or_404(id=data.org_id, msg="所属组织不存在")
        await self._crud().update(id=id, data=data)
        return await self.detail(id=id)

    async def delete(self, ids: list[int]) -> None:
        if not ids:
            raise CustomException(msg="删除失败，删除对象不能为空")
        await self._crud().delete(ids=ids)


class MasterSourceService:
    """来源组织/人员查询服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def page_orgs(
        self,
        search: SourceQueryParam | None,
        page_no: int,
        page_size: int,
    ) -> PageResultSchema[SourceOrgOutSchema]:
        result = await SourceOrgCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"id": "asc"}],
            search=search_to_dict(search),
        )
        return PageResultSchema[SourceOrgOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=[SourceOrgOutSchema.model_validate(obj) for obj in result.items],
        )

    async def page_persons(
        self,
        search: SourceQueryParam | None,
        page_no: int,
        page_size: int,
    ) -> PageResultSchema[SourcePersonOutSchema]:
        result = await SourcePersonCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"id": "asc"}],
            search=search_to_dict(search),
        )
        return PageResultSchema[SourcePersonOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=[SourcePersonOutSchema.model_validate(obj) for obj in result.items],
        )


class MasterMappingService:
    """来源数据到内部标准数据的映射服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def page_org_mappings(
        self,
        search: MappingQueryParam | None,
        page_no: int,
        page_size: int,
    ) -> PageResultSchema[OrgMappingOutSchema]:
        result = await OrgMappingCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"id": "desc"}],
            search=search_to_dict(search),
        )
        items = [await self._to_org_out(obj) for obj in result.items]
        return PageResultSchema[OrgMappingOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=items,
        )

    async def page_person_mappings(
        self,
        search: MappingQueryParam | None,
        page_no: int,
        page_size: int,
    ) -> PageResultSchema[PersonMappingOutSchema]:
        result = await PersonMappingCRUD(self.auth, self.db).page(
            offset=(page_no - 1) * page_size,
            limit=page_size,
            order_by=[{"id": "desc"}],
            search=search_to_dict(search),
        )
        items = [await self._to_person_out(obj) for obj in result.items]
        return PageResultSchema[PersonMappingOutSchema](
            page_no=result.page_no,
            page_size=result.page_size,
            total=result.total,
            has_next=result.has_next,
            items=items,
        )

    async def _to_org_out(self, obj: OrgMappingModel) -> OrgMappingOutSchema:
        out = OrgMappingOutSchema.model_validate(obj)
        source = await self.db.get(SourceOrgModel, obj.source_org_id)
        master = await self.db.get(MasterOrgModel, obj.master_org_id)
        out.source_type = source.source_type if source else None
        out.source_org_code = source.source_code if source else None
        out.source_org_name = source.source_name if source else None
        out.master_org_code = master.code if master else None
        out.master_org_name = master.name if master else None
        return out

    async def _to_person_out(self, obj: PersonMappingModel) -> PersonMappingOutSchema:
        out = PersonMappingOutSchema.model_validate(obj)
        source = await self.db.get(SourcePersonModel, obj.source_person_id)
        master = await self.db.get(MasterPersonModel, obj.master_person_id)
        out.source_type = source.source_type if source else None
        out.source_person_code = source.source_code if source else None
        out.source_person_name = source.source_name if source else None
        out.master_person_code = master.code if master else None
        out.master_person_name = master.name if master else None
        return out

    async def create_org_mapping(self, data: OrgMappingCreateSchema) -> OrgMappingOutSchema:
        await self._validate_org_pair(data.source_org_id, data.master_org_id)
        if await OrgMappingCRUD(self.auth, self.db).get(source_org_id=data.source_org_id, master_org_id=data.master_org_id):
            raise CustomException(msg="创建失败，该组织映射已存在")
        obj = await OrgMappingCRUD(self.auth, self.db).create(data=data)
        return await self._to_org_out(obj)

    async def update_org_mapping(self, id: int, data: OrgMappingUpdateSchema) -> OrgMappingOutSchema:
        await OrgMappingCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该组织映射不存在")
        await self._validate_org_pair(data.source_org_id, data.master_org_id)
        await OrgMappingCRUD(self.auth, self.db).update(id=id, data=data)
        obj = await OrgMappingCRUD(self.auth, self.db).get_or_404(id=id)
        return await self._to_org_out(obj)

    async def create_person_mapping(self, data: PersonMappingCreateSchema) -> PersonMappingOutSchema:
        await self._validate_person_pair(data.source_person_id, data.master_person_id)
        if await PersonMappingCRUD(self.auth, self.db).get(source_person_id=data.source_person_id, master_person_id=data.master_person_id):
            raise CustomException(msg="创建失败，该人员映射已存在")
        obj = await PersonMappingCRUD(self.auth, self.db).create(data=data)
        return await self._to_person_out(obj)

    async def update_person_mapping(self, id: int, data: PersonMappingUpdateSchema) -> PersonMappingOutSchema:
        await PersonMappingCRUD(self.auth, self.db).get_or_404(id=id, msg="更新失败，该人员映射不存在")
        await self._validate_person_pair(data.source_person_id, data.master_person_id)
        await PersonMappingCRUD(self.auth, self.db).update(id=id, data=data)
        obj = await PersonMappingCRUD(self.auth, self.db).get_or_404(id=id)
        return await self._to_person_out(obj)

    async def delete_org_mappings(self, ids: list[int]) -> None:
        await OrgMappingCRUD(self.auth, self.db).delete(ids=ids)

    async def delete_person_mappings(self, ids: list[int]) -> None:
        await PersonMappingCRUD(self.auth, self.db).delete(ids=ids)

    async def auto_match_org(self, data: AutoMatchSchema) -> dict[str, int]:
        search: dict[str, Any] = {"status": 0}
        if data.source_type:
            search["source_type"] = data.source_type
        sources = await SourceOrgCRUD(self.auth, self.db).get_list(search=search, order_by=[{"id": "asc"}])
        masters = await MasterOrgCRUD(self.auth, self.db).get_list(search={"status": 0}, order_by=[{"id": "asc"}])
        master_map = {m.code: m for m in masters}

        created = 0
        skipped = 0
        for source in sources:
            exists = await OrgMappingCRUD(self.auth, self.db).get(source_org_id=source.id, status=0)
            if exists:
                skipped += 1
                continue
            master = master_map.get(source.source_code)
            if master is None:
                continue
            await OrgMappingCRUD(self.auth, self.db).create(
                data=OrgMappingCreateSchema(source_org_id=source.id, master_org_id=master.id, match_mode="exact", confidence=100, status=0)
            )
            created += 1
        return {"created": created, "skipped": skipped}

    async def auto_match_person(self, data: AutoMatchSchema) -> dict[str, int]:
        search: dict[str, Any] = {"status": 0}
        if data.source_type:
            search["source_type"] = data.source_type
        sources = await SourcePersonCRUD(self.auth, self.db).get_list(search=search, order_by=[{"id": "asc"}])
        masters = await MasterPersonCRUD(self.auth, self.db).get_list(search={"status": 0}, order_by=[{"id": "asc"}])
        master_map = {m.code: m for m in masters}

        created = 0
        skipped = 0
        for source in sources:
            exists = await PersonMappingCRUD(self.auth, self.db).get(source_person_id=source.id, status=0)
            if exists:
                skipped += 1
                continue
            master = master_map.get(source.source_code)
            if master is None:
                continue
            await PersonMappingCRUD(self.auth, self.db).create(
                data=PersonMappingCreateSchema(source_person_id=source.id, master_person_id=master.id, match_mode="exact", confidence=100, status=0)
            )
            created += 1
        return {"created": created, "skipped": skipped}

    async def _validate_org_pair(self, source_org_id: int, master_org_id: int) -> None:
        await SourceOrgCRUD(self.auth, self.db).get_or_404(id=source_org_id, msg="来源组织不存在")
        await MasterOrgCRUD(self.auth, self.db).get_or_404(id=master_org_id, msg="内部标准组织不存在")

    async def _validate_person_pair(self, source_person_id: int, master_person_id: int) -> None:
        await SourcePersonCRUD(self.auth, self.db).get_or_404(id=source_person_id, msg="来源人员不存在")
        await MasterPersonCRUD(self.auth, self.db).get_or_404(id=master_person_id, msg="内部标准人员不存在")
