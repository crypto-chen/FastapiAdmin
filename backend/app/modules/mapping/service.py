from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import AuthSchema, PageResultSchema
from app.core.exceptions import CustomException
from app.modules.crm.personnel_sync import sync_crm_org_structure, sync_crm_personnel
from app.modules.masterdata.model import (
    MasterDeptMappingModel,
    MasterDeptModel,
    MasterOrgModel,
    MasterPersonModel,
    MasterPersonOrgModel,
    OrgMappingModel,
    PersonMappingModel,
    SourceDeptModel,
    SourceOrgModel,
    SourcePersonModel,
    SysDeptBusinessMappingModel,
)
from app.modules.masterdata.schema import MappingQueryParam, OrgMappingOutSchema, PersonMappingOutSchema, SourceOrgOutSchema, SourcePersonOutSchema
from app.modules.masterdata.service import MasterMappingService
from app.modules.metadata.model import FieldMappingModel, SourceFieldModel, StandardFieldModel
from app.modules.metadata.schema import FieldMappingOutSchema, FieldMappingQueryParam
from app.modules.metadata.service import MetadataService
from app.modules.system.dept.model import DeptModel

from .schema import (
    AutoMatchSchema,
    DeptBindSchema,
    DeptMappingCreateSchema,
    DeptMappingOutSchema,
    DeptMappingQueryParam,
    DeptMappingUpdateSchema,
    MasterDeptBusinessOptionSchema,
    MasterDeptOptionSchema,
    OrgBindSchema,
    PersonBindSchema,
    PersonOrgBindSchema,
    SysDeptBindSchema,
    SysDeptBusinessMappingOutSchema,
    SysDeptUnbindSchema,
)


class MappingService:
    """系统映射聚合服务。"""

    def __init__(self, auth: AuthSchema, db: AsyncSession) -> None:
        self.auth = auth
        self.db = db

    async def page_org(self, search: MappingQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[OrgMappingOutSchema]:
        return await MasterMappingService(self.auth, self.db).page_org_mappings(search, page_no, page_size)

    async def page_person(self, search: MappingQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[PersonMappingOutSchema]:
        return await MasterMappingService(self.auth, self.db).page_person_mappings(search, page_no, page_size)

    async def page_field(self, search: FieldMappingQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[FieldMappingOutSchema]:
        return await MetadataService(self.auth, self.db).page_field_mapping(search, page_no, page_size)

    async def _dept_out(self, obj: MasterDeptMappingModel) -> DeptMappingOutSchema:
        out = DeptMappingOutSchema.model_validate(obj)
        source = await self.db.get(SourceDeptModel, obj.source_dept_id)
        master = await self.db.get(MasterDeptModel, obj.master_dept_id)
        if source:
            out.source_type = source.source_type
            out.source_org_code = source.source_org_code
            out.source_dept_code = source.source_code
            out.source_dept_name = source.source_name
        if master:
            out.master_dept_code = master.code
            out.master_dept_name = master.name
            org = await self.db.get(MasterOrgModel, master.org_id)
            out.master_org_code = org.code if org else None
        return out

    async def page_dept(self, search: DeptMappingQueryParam | None, page_no: int, page_size: int) -> PageResultSchema[DeptMappingOutSchema]:
        from app.utils.common_util import search_to_dict

        stmt = select(MasterDeptMappingModel)
        conditions = []
        if search:
            for key, value in search_to_dict(search).items():
                if value is not None and value != "":
                    conditions.append(getattr(MasterDeptMappingModel, key) == value)
        if conditions:
            stmt = stmt.where(*conditions)
        total = len((await self.db.execute(stmt)).scalars().all())
        rows = (
            await self.db.execute(stmt.order_by(MasterDeptMappingModel.id.desc()).offset((page_no - 1) * page_size).limit(page_size))
        ).scalars().all()
        return PageResultSchema[DeptMappingOutSchema](
            page_no=page_no,
            page_size=page_size,
            total=total,
            has_next=page_no * page_size < total,
            items=[await self._dept_out(row) for row in rows],
        )

    async def create_dept(self, data: DeptMappingCreateSchema) -> DeptMappingOutSchema:
        await self._validate_dept_pair(data.source_dept_id, data.master_dept_id)
        exists = (
            await self.db.execute(
                select(MasterDeptMappingModel).where(
                    MasterDeptMappingModel.source_dept_id == data.source_dept_id,
                    MasterDeptMappingModel.master_dept_id == data.master_dept_id,
                )
            )
        ).scalars().first()
        if exists:
            raise CustomException(msg="该部门映射已存在")
        obj = MasterDeptMappingModel(**data.model_dump())
        self.db.add(obj)
        await self.db.flush()
        return await self._dept_out(obj)

    async def update_dept(self, id: int, data: DeptMappingUpdateSchema) -> DeptMappingOutSchema:
        obj = await self.db.get(MasterDeptMappingModel, id)
        if obj is None:
            raise CustomException(msg="该部门映射不存在")
        await self._validate_dept_pair(data.source_dept_id, data.master_dept_id)
        for key, value in data.model_dump().items():
            setattr(obj, key, value)
        await self.db.flush()
        return await self._dept_out(obj)

    async def delete_dept(self, ids: list[int]) -> None:
        for obj in (await self.db.execute(select(MasterDeptMappingModel).where(MasterDeptMappingModel.id.in_(ids)))).scalars().all():
            await self.db.delete(obj)
        await self.db.flush()

    async def _validate_dept_pair(self, source_dept_id: int, master_dept_id: int) -> None:
        if await self.db.get(SourceDeptModel, source_dept_id) is None:
            raise CustomException(msg="来源部门不存在")
        if await self.db.get(MasterDeptModel, master_dept_id) is None:
            raise CustomException(msg="内部标准部门不存在")

    # ── 人工绑定 ─────────────────────────────────────────────────

    async def unmapped_orgs(self, source_type: str | None = None) -> list[SourceOrgOutSchema]:
        stmt = select(SourceOrgModel).where(SourceOrgModel.status == 0)
        if source_type:
            stmt = stmt.where(SourceOrgModel.source_type == source_type)
        sources = (await self.db.execute(stmt)).scalars().all()
        mapped_ids = set(
            (await self.db.execute(select(OrgMappingModel.source_org_id).where(OrgMappingModel.status == 0))).scalars().all()
        )
        return [SourceOrgOutSchema.model_validate(item) for item in sources if item.id not in mapped_ids]

    async def unmapped_depts(self, source_type: str | None = None) -> list[dict]:
        stmt = select(SourceDeptModel).where(SourceDeptModel.status == 0)
        if source_type:
            stmt = stmt.where(SourceDeptModel.source_type == source_type)
        sources = (await self.db.execute(stmt)).scalars().all()
        mapped_ids = set(
            (await self.db.execute(select(MasterDeptMappingModel.source_dept_id).where(MasterDeptMappingModel.status == 0))).scalars().all()
        )
        orgs = {o.code: o for o in (await self.db.execute(select(MasterOrgModel))).scalars().all()}
        return [
            {
                "id": item.id,
                "source_type": item.source_type,
                "source_org_code": item.source_org_code,
                "source_code": item.source_code,
                "source_name": item.source_name,
                "source_parent_code": item.source_parent_code,
                "master_org_id": orgs[item.source_org_code].id if item.source_org_code in orgs else None,
            }
            for item in sources
            if item.id not in mapped_ids
        ]

    async def unmapped_persons(self, source_type: str | None = None) -> list[SourcePersonOutSchema]:
        stmt = select(SourcePersonModel).where(SourcePersonModel.status == 0)
        if source_type:
            stmt = stmt.where(SourcePersonModel.source_type == source_type)
        sources = (await self.db.execute(stmt)).scalars().all()
        mapped_ids = set(
            (await self.db.execute(select(PersonMappingModel.source_person_id).where(PersonMappingModel.status == 0))).scalars().all()
        )
        return [SourcePersonOutSchema.model_validate(item) for item in sources if item.id not in mapped_ids]

    async def org_options(self) -> list[dict]:
        orgs = (await self.db.execute(select(MasterOrgModel).where(MasterOrgModel.status == 0).order_by(MasterOrgModel.code))).scalars().all()
        return [{"value": org.id, "label": f"{org.code} - {org.name}"} for org in orgs]

    async def dept_options(self, org_id: int | None = None) -> list[MasterDeptOptionSchema]:
        stmt = select(MasterDeptModel).where(MasterDeptModel.status == 0)
        if org_id:
            stmt = stmt.where(MasterDeptModel.org_id == org_id)
        depts = (await self.db.execute(stmt.order_by(MasterDeptModel.code))).scalars().all()
        orgs = {o.id: o for o in (await self.db.execute(select(MasterOrgModel))).scalars().all()}
        return [
            MasterDeptOptionSchema(id=d.id, code=d.code, name=d.name, org_id=d.org_id, org_name=orgs[d.org_id].name if d.org_id in orgs else None)
            for d in depts
        ]

    async def person_options(self) -> list[dict]:
        persons = (await self.db.execute(select(MasterPersonModel).where(MasterPersonModel.status == 0).order_by(MasterPersonModel.code))).scalars().all()
        return [{"value": p.id, "label": f"{p.code} - {p.name}"} for p in persons]

    async def source_types(self) -> list[dict]:
        """返回当前来源数据中出现过的来源类型。"""
        types: set[str] = set()
        for model in (SourceOrgModel, SourceDeptModel, SourcePersonModel):
            rows = (await self.db.execute(select(model.source_type).distinct())).scalars().all()
            types.update(str(row) for row in rows if row)
        return [{"value": item, "label": item} for item in sorted(types)]

    # ── 手动同步任务（无 Cron） ──────────────────────────────────

    async def sync_crm_org(self) -> dict[str, int]:
        """手动任务：同步 CRM 人员架构（来源组织 + 来源部门）。"""
        result = await sync_crm_org_structure(self.db)
        return result.as_dict()

    async def sync_crm_person(self) -> dict[str, int]:
        """手动任务：同步 CRM 人员（来源人员）。"""
        result = await sync_crm_personnel(self.db)
        return result.as_dict()

    # ── 权限部门(sys_dept) ↔ 业务标准部门(master_dept) ──────────────

    async def sys_dept_bindings(self, sys_dept_id: int) -> list[SysDeptBusinessMappingOutSchema]:
        rows = (
            await self.db.execute(
                select(SysDeptBusinessMappingModel)
                .where(
                    SysDeptBusinessMappingModel.sys_dept_id == sys_dept_id,
                    SysDeptBusinessMappingModel.status == 0,
                )
                .order_by(SysDeptBusinessMappingModel.id)
            )
        ).scalars().all()
        return [await self._sys_dept_binding_out(row) for row in rows]

    async def _sys_dept_binding_out(self, row: SysDeptBusinessMappingModel) -> SysDeptBusinessMappingOutSchema:
        sys_dept = await self.db.get(DeptModel, row.sys_dept_id)
        master_dept = await self.db.get(MasterDeptModel, row.master_dept_id)
        source = (
            await self.db.execute(
                select(SourceDeptModel)
                .join(MasterDeptMappingModel, MasterDeptMappingModel.source_dept_id == SourceDeptModel.id)
                .where(
                    MasterDeptMappingModel.master_dept_id == row.master_dept_id,
                    MasterDeptMappingModel.status == 0,
                )
                .limit(1)
            )
        ).scalars().first()
        return SysDeptBusinessMappingOutSchema(
            id=row.id,
            sys_dept_id=row.sys_dept_id,
            sys_dept_code=sys_dept.code if sys_dept else None,
            sys_dept_name=sys_dept.name if sys_dept else None,
            master_dept_id=row.master_dept_id,
            master_dept_code=master_dept.code if master_dept else None,
            master_dept_name=master_dept.name if master_dept else None,
            source_type=source.source_type if source else None,
            source_org_code=source.source_org_code if source else None,
            source_dept_code=source.source_code if source else None,
            status=row.status,
        )

    async def master_dept_business_options(
        self,
        source_type: str | None = None,
        org_id: int | None = None,
        keyword: str | None = None,
    ) -> list[MasterDeptBusinessOptionSchema]:
        stmt = select(MasterDeptModel).where(MasterDeptModel.status == 0)
        if org_id:
            stmt = stmt.where(MasterDeptModel.org_id == org_id)
        if keyword:
            stmt = stmt.where(MasterDeptModel.name.like(f"%{keyword}%"))
        depts = (await self.db.execute(stmt.order_by(MasterDeptModel.org_id, MasterDeptModel.code))).scalars().all()
        orgs = {o.id: o for o in (await self.db.execute(select(MasterOrgModel))).scalars().all()}
        sources_by_master: dict[int, SourceDeptModel] = {}
        rows = (
            await self.db.execute(
                select(MasterDeptMappingModel.master_dept_id, SourceDeptModel)
                .join(SourceDeptModel, SourceDeptModel.id == MasterDeptMappingModel.source_dept_id)
                .where(MasterDeptMappingModel.status == 0)
            )
        ).all()
        for master_dept_id, source in rows:
            if source_type and source.source_type != source_type:
                continue
            sources_by_master.setdefault(master_dept_id, source)
        return [
            MasterDeptBusinessOptionSchema(
                id=d.id,
                code=d.code,
                name=d.name,
                org_id=d.org_id,
                org_code=orgs[d.org_id].code if d.org_id in orgs else None,
                org_name=orgs[d.org_id].name if d.org_id in orgs else None,
                source_type=sources_by_master[d.id].source_type if d.id in sources_by_master else None,
                source_org_code=sources_by_master[d.id].source_org_code if d.id in sources_by_master else None,
                source_dept_code=sources_by_master[d.id].source_code if d.id in sources_by_master else None,
            )
            for d in depts
            if not source_type or d.id in sources_by_master
        ]

    async def bind_sys_dept(self, data: SysDeptBindSchema) -> None:
        if await self.db.get(DeptModel, data.sys_dept_id) is None:
            raise CustomException(msg="系统权限部门不存在")
        for master_dept_id in data.master_dept_ids:
            if await self.db.get(MasterDeptModel, master_dept_id) is None:
                raise CustomException(msg=f"业务标准部门不存在: {master_dept_id}")
        for master_dept_id in data.master_dept_ids:
            exists = (
                await self.db.execute(
                    select(SysDeptBusinessMappingModel).where(
                        SysDeptBusinessMappingModel.sys_dept_id == data.sys_dept_id,
                        SysDeptBusinessMappingModel.master_dept_id == master_dept_id,
                    )
                )
            ).scalars().first()
            if exists is None:
                self.db.add(
                    SysDeptBusinessMappingModel(
                        sys_dept_id=data.sys_dept_id,
                        master_dept_id=master_dept_id,
                        match_mode="manual",
                        confidence=100,
                        status=0,
                    )
                )
            else:
                exists.status = 0
        await self.db.flush()

    async def unbind_sys_dept(self, data: SysDeptUnbindSchema) -> None:
        rows = (
            await self.db.execute(
                select(SysDeptBusinessMappingModel).where(
                    SysDeptBusinessMappingModel.sys_dept_id == data.sys_dept_id,
                    SysDeptBusinessMappingModel.master_dept_id.in_(data.master_dept_ids),
                )
            )
        ).scalars().all()
        for row in rows:
            await self.db.delete(row)
        await self.db.flush()

    async def master_dept_ids_for_sys_depts(self, sys_dept_ids: list[int]) -> list[int]:
        """数据权限用：系统权限部门 → 可访问的业务标准部门ID。"""
        if not sys_dept_ids:
            return []
        rows = (
            await self.db.execute(
                select(SysDeptBusinessMappingModel.master_dept_id).where(
                    SysDeptBusinessMappingModel.sys_dept_id.in_(sys_dept_ids),
                    SysDeptBusinessMappingModel.status == 0,
                )
            )
        ).scalars().all()
        return sorted({int(row) for row in rows})

    async def bind_org(self, data: OrgBindSchema) -> None:
        if await self.db.get(SourceOrgModel, data.source_org_id) is None:
            raise CustomException(msg="来源组织不存在")
        if await self.db.get(MasterOrgModel, data.master_org_id) is None:
            raise CustomException(msg="内部标准组织不存在")
        await self._upsert_org_mapping(data.source_org_id, data.master_org_id)

    async def bind_dept(self, data: DeptBindSchema) -> None:
        if await self.db.get(SourceDeptModel, data.source_dept_id) is None:
            raise CustomException(msg="来源部门不存在")
        if await self.db.get(MasterDeptModel, data.master_dept_id) is None:
            raise CustomException(msg="内部标准部门不存在")
        await self._upsert_dept_mapping(data.source_dept_id, data.master_dept_id)

    async def bind_person(self, data: PersonBindSchema) -> None:
        if await self.db.get(SourcePersonModel, data.source_person_id) is None:
            raise CustomException(msg="来源人员不存在")
        if await self.db.get(MasterPersonModel, data.master_person_id) is None:
            raise CustomException(msg="内部标准人员不存在")
        await self._upsert_person_mapping(data.source_person_id, data.master_person_id)

    async def bind_person_org(self, data: PersonOrgBindSchema) -> None:
        if await self.db.get(SourcePersonModel, data.source_person_id) is None:
            raise CustomException(msg="来源人员不存在")
        if await self.db.get(MasterPersonModel, data.master_person_id) is None:
            raise CustomException(msg="内部标准人员不存在")
        if await self.db.get(MasterOrgModel, data.master_org_id) is None:
            raise CustomException(msg="内部标准组织不存在")
        if data.master_dept_id and await self.db.get(MasterDeptModel, data.master_dept_id) is None:
            raise CustomException(msg="内部标准部门不存在")
        exists = (
            await self.db.execute(
                select(MasterPersonOrgModel).where(
                    MasterPersonOrgModel.person_id == data.master_person_id,
                    MasterPersonOrgModel.org_id == data.master_org_id,
                    MasterPersonOrgModel.dept_id == data.master_dept_id,
                )
            )
        ).scalars().first()
        if exists is None:
            self.db.add(
                MasterPersonOrgModel(
                    person_id=data.master_person_id,
                    org_id=data.master_org_id,
                    dept_id=data.master_dept_id,
                    is_primary=data.is_primary,
                    status=data.status,
                )
            )
        else:
            exists.is_primary = data.is_primary
            exists.status = data.status
        await self.db.flush()

    async def _upsert_org_mapping(self, source_org_id: int, master_org_id: int) -> None:
        exists = (
            await self.db.execute(
                select(OrgMappingModel).where(
                    OrgMappingModel.source_org_id == source_org_id,
                    OrgMappingModel.master_org_id == master_org_id,
                )
            )
        ).scalars().first()
        if exists is None:
            self.db.add(
                OrgMappingModel(
                    source_org_id=source_org_id,
                    master_org_id=master_org_id,
                    match_mode="manual",
                    confidence=100,
                    status=0,
                )
            )
        else:
            exists.match_mode = "manual"
            exists.confidence = 100
            exists.status = 0
        await self.db.flush()

    async def _upsert_dept_mapping(self, source_dept_id: int, master_dept_id: int) -> None:
        exists = (
            await self.db.execute(
                select(MasterDeptMappingModel).where(
                    MasterDeptMappingModel.source_dept_id == source_dept_id,
                    MasterDeptMappingModel.master_dept_id == master_dept_id,
                )
            )
        ).scalars().first()
        if exists is None:
            self.db.add(
                MasterDeptMappingModel(
                    source_dept_id=source_dept_id,
                    master_dept_id=master_dept_id,
                    match_mode="manual",
                    confidence=100,
                    status=0,
                )
            )
        else:
            exists.match_mode = "manual"
            exists.confidence = 100
            exists.status = 0
        await self.db.flush()

    async def _upsert_person_mapping(self, source_person_id: int, master_person_id: int) -> None:
        exists = (
            await self.db.execute(
                select(PersonMappingModel).where(
                    PersonMappingModel.source_person_id == source_person_id,
                    PersonMappingModel.master_person_id == master_person_id,
                )
            )
        ).scalars().first()
        if exists is None:
            self.db.add(
                PersonMappingModel(
                    source_person_id=source_person_id,
                    master_person_id=master_person_id,
                    match_mode="manual",
                    confidence=100,
                    status=0,
                )
            )
        else:
            exists.match_mode = "manual"
            exists.confidence = 100
            exists.status = 0
        await self.db.flush()

    async def auto_match_dept(self, data: AutoMatchSchema) -> dict[str, int]:
        stmt = select(SourceDeptModel).where(SourceDeptModel.status == 0)
        if data.source_type:
            stmt = stmt.where(SourceDeptModel.source_type == data.source_type)
        sources = (await self.db.execute(stmt)).scalars().all()
        masters = (await self.db.execute(select(MasterDeptModel).where(MasterDeptModel.status == 0))).scalars().all()
        master_by_key = {(m.org_id, m.code): m for m in masters}
        org_by_code = {o.code: o for o in (await self.db.execute(select(MasterOrgModel))).scalars().all()}

        created = 0
        skipped = 0
        for source in sources:
            org = org_by_code.get(source.source_org_code)
            if org is None:
                continue
            master = master_by_key.get((org.id, source.source_code))
            if master is None:
                continue
            exists = (
                await self.db.execute(
                    select(MasterDeptMappingModel).where(
                        MasterDeptMappingModel.source_dept_id == source.id,
                        MasterDeptMappingModel.master_dept_id == master.id,
                    )
                )
            ).scalars().first()
            if exists:
                skipped += 1
                continue
            self.db.add(
                MasterDeptMappingModel(
                    source_dept_id=source.id,
                    master_dept_id=master.id,
                    match_mode="exact",
                    confidence=100,
                    status=0,
                )
            )
            created += 1
        await self.db.flush()
        return {"created": created, "skipped": skipped}

    async def auto_match_field(self, data: AutoMatchSchema) -> dict[str, int]:
        sources = (await self.db.execute(select(SourceFieldModel).where(SourceFieldModel.status == 0))).scalars().all()
        standards = (await self.db.execute(select(StandardFieldModel).where(StandardFieldModel.status == 0))).scalars().all()
        standard_by_code = {s.field_code: s for s in standards}
        standard_by_name = {s.field_name: s for s in standards}

        created = 0
        skipped = 0
        for source in sources:
            standard = standard_by_code.get(source.field_key) or standard_by_name.get(source.field_name)
            if standard is None:
                continue
            exists = (
                await self.db.execute(
                    select(FieldMappingModel).where(
                        FieldMappingModel.source_field_id == source.id,
                        FieldMappingModel.standard_field_id == standard.id,
                    )
                )
            ).scalars().first()
            if exists:
                skipped += 1
                continue
            self.db.add(
                FieldMappingModel(
                    source_object_id=source.object_id,
                    source_field_id=source.id,
                    standard_field_id=standard.id,
                    transform_type="direct",
                    transform_config=None,
                    order=0,
                    status=0,
                )
            )
            created += 1
        await self.db.flush()
        return {"created": created, "skipped": skipped}
