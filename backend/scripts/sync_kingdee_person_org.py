"""从员工 View 接口同步人员-组织-部门关系到 master_person_org。

用法：
    python scripts/sync_kingdee_person_org.py
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = PROJECT_ROOT / "env" / "kindee_conf.ini"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.getLogger("urllib3").setLevel(logging.WARNING)

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.erp.kingdee.client import KingdeeClient  # noqa: E402
from app.modules.masterdata.model import (  # noqa: E402
    MasterDeptModel,
    MasterOrgModel,
    MasterPersonModel,
    MasterPersonOrgModel,
    SourcePersonModel,
)
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


def _number(obj: Any) -> str:
    if isinstance(obj, dict):
        return str(obj.get("Number") or obj.get("Id") or "").strip()
    return str(obj or "").strip()


async def fetch_person_org(client: KingdeeClient, person_code: str) -> list[dict[str, str]]:
    result = await client.view(
        "BD_Empinfo",
        {"CreateOrgId": 0, "Number": person_code, "Id": "", "IsSortBySeq": "false"},
    )
    inner = result.get("Result") or {}
    status = inner.get("ResponseStatus") or {}
    if not status.get("IsSuccess"):
        logger.warning(f"员工 {person_code} View 失败: {status.get('Errors') or status}")
        return []
    emp = inner.get("Result")
    if not isinstance(emp, dict):
        return []

    relations: list[dict[str, str]] = []
    post_entries = emp.get("PostEntity") or []
    if not isinstance(post_entries, list):
        post_entries = []
    for entry in post_entries:
        if not isinstance(entry, dict):
            continue
        dept_obj = entry.get("PostDept") if isinstance(entry.get("PostDept"), dict) else entry.get("FDept")
        dept_code = _number(dept_obj)
        org_obj = None
        if isinstance(dept_obj, dict) and isinstance(dept_obj.get("UseOrgId"), dict):
            org_obj = dept_obj["UseOrgId"]
        if org_obj is None and isinstance(entry.get("WorkOrgId"), dict):
            org_obj = entry["WorkOrgId"]
        org_code = _number(org_obj)
        if dept_code and org_code:
            relations.append(
                {
                    "org_code": org_code,
                    "dept_code": dept_code,
                    "status": "0" if entry.get("StaffForbidStatus") == "A" else "1",
                }
            )
    deduped: dict[tuple[str, str], str] = {}
    for rel in relations:
        key = (rel["org_code"], rel["dept_code"])
        deduped.setdefault(key, rel["status"])
    return [{"org_code": key[0], "dept_code": key[1], "status": status} for key, status in deduped.items()]


async def main() -> None:
    client = KingdeeClient.from_ini(DEFAULT_INI)

    async with async_db_session() as db:
        persons = (await db.execute(select(SourcePersonModel).where(SourcePersonModel.source_type == "kingdee"))).scalars().all()
        master_persons = (await db.execute(select(MasterPersonModel))).scalars().all()
        orgs = (await db.execute(select(MasterOrgModel))).scalars().all()
        depts = (await db.execute(select(MasterDeptModel))).scalars().all()

    master_person_by_code = {p.code: p for p in master_persons}
    org_by_code = {o.code: o for o in orgs}
    dept_by_key = {(d.org_id, d.code): d for d in depts}

    saved = 0
    missing_org = 0
    missing_dept = 0
    async with async_db_session() as db, db.begin():
        for source in persons:
            master_person = master_person_by_code.get(source.source_code)
            if master_person is None:
                continue
            relations = await fetch_person_org(client, source.source_code)
            for rel in relations:
                org = org_by_code.get(rel["org_code"])
                if org is None:
                    missing_org += 1
                    continue
                dept = dept_by_key.get((org.id, rel["dept_code"]))
                if dept is None:
                    missing_dept += 1
                    continue
                stmt = select(MasterPersonOrgModel).where(
                    MasterPersonOrgModel.person_id == master_person.id,
                    MasterPersonOrgModel.org_id == org.id,
                    MasterPersonOrgModel.dept_id == dept.id,
                )
                obj = (await db.execute(stmt)).scalar_one_or_none()
                if obj is None:
                    db.add(
                        MasterPersonOrgModel(
                            person_id=master_person.id,
                            org_id=org.id,
                            dept_id=dept.id,
                            status=int(rel["status"]),
                        )
                    )
                else:
                    obj.status = int(rel["status"])
                saved += 1
    await async_engine.dispose()
    logger.info(
        f"人员组织部门关系同步完成，保存 {saved} 条；缺失组织 {missing_org} 条，缺失部门 {missing_dept} 条"
    )


if __name__ == "__main__":
    asyncio.run(main())
