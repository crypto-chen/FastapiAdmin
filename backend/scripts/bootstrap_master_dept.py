"""根据来源部门初始化内部标准部门与映射。

用法：
    python scripts/bootstrap_master_dept.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.masterdata.model import (  # noqa: E402
    MasterDeptMappingModel,
    MasterDeptModel,
    MasterOrgModel,
    SourceDeptModel,
    SourceOrgModel,
)
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def main() -> None:
    async with async_db_session() as db, db.begin():
        source_orgs = (
            await db.execute(select(SourceOrgModel).where(SourceOrgModel.source_type == "kingdee"))
        ).scalars().all()
        org_name_by_code = {org.source_code: org.source_name for org in source_orgs}

        masters = (await db.execute(select(MasterOrgModel))).scalars().all()
        master_by_code = {m.code: m for m in masters}
        for code, name in org_name_by_code.items():
            if code not in master_by_code:
                master = MasterOrgModel(code=code, name=name, status=0)
                db.add(master)
                master_by_code[code] = master
        await db.flush()

        source_depts = (
            await db.execute(select(SourceDeptModel).where(SourceDeptModel.source_type == "kingdee"))
        ).scalars().all()

        dept_by_key: dict[tuple[str, str], MasterDeptModel] = {}
        for source in source_depts:
            org = master_by_code.get(source.source_org_code)
            if org is None:
                logger.warning(f"部门 {source.source_code} 找不到标准组织 {source.source_org_code}，跳过")
                continue
            stmt = select(MasterDeptModel).where(
                MasterDeptModel.org_id == org.id,
                MasterDeptModel.code == source.source_code,
            )
            dept = (await db.execute(stmt)).scalar_one_or_none()
            if dept is None:
                dept = MasterDeptModel(
                    org_id=org.id,
                    code=source.source_code,
                    name=source.source_name,
                    status=source.status,
                )
                db.add(dept)
            else:
                dept.name = source.source_name
                dept.status = source.status
            await db.flush()
            dept_by_key[(source.source_org_code, source.source_code)] = dept

        # 补上级部门
        for source in source_depts:
            if not source.source_parent_code:
                continue
            dept = dept_by_key.get((source.source_org_code, source.source_code))
            parent = dept_by_key.get((source.source_org_code, source.source_parent_code))
            if dept is not None and parent is not None:
                dept.parent_id = parent.id

        # 建来源映射
        for source in source_depts:
            dept = dept_by_key.get((source.source_org_code, source.source_code))
            if dept is None:
                continue
            stmt = select(MasterDeptMappingModel).where(
                MasterDeptMappingModel.source_dept_id == source.id,
                MasterDeptMappingModel.master_dept_id == dept.id,
            )
            mapping = (await db.execute(stmt)).scalar_one_or_none()
            if mapping is None:
                db.add(
                    MasterDeptMappingModel(
                        source_dept_id=source.id,
                        master_dept_id=dept.id,
                        match_mode="exact",
                        confidence=100,
                        status=0,
                    )
                )

    await async_engine.dispose()
    logger.info(f"标准部门初始化完成，共处理 {len(source_depts)} 个来源部门")


if __name__ == "__main__":
    asyncio.run(main())
