"""同步金蝶多组织（法人）到来源组织表，并可选初始化标准组织与映射。

用法：
    python scripts/sync_kingdee_org.py --start 100 --end 113
    python scripts/sync_kingdee_org.py --start 100 --end 113 --bootstrap-master
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = PROJECT_ROOT / "env" / "kindee_conf.ini"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.erp.kingdee.client import KingdeeClient  # noqa: E402
from app.modules.masterdata.model import MasterOrgModel, OrgMappingModel, SourceOrgModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


def localized_text(value: Any) -> str:
    """提取金蝶多语言字段里的简体中文文本，回退到第一个值。"""
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict) and str(item.get("Key")) == "2052":
                return str(item.get("Value") or "").strip()
        if value and isinstance(value[0], dict):
            return str(value[0].get("Value") or "").strip()
        return ""
    if isinstance(value, dict):
        return str(value.get("Value") or value.get("Name") or "").strip()
    return str(value or "").strip()


def parent_number(org: dict[str, Any], own_number: str) -> str | None:
    parent = org.get("ParentOrg") if isinstance(org.get("ParentOrg"), dict) else None
    number = parent.get("Number") if parent else None
    if not number or str(number) == str(own_number):
        return None
    return str(number)


async def fetch_org(client: KingdeeClient, number: str) -> dict[str, Any] | None:
    data = {"CreateOrgId": 0, "Number": number, "Id": "", "IsSortBySeq": "false"}
    result = await client.view("ORG_Organizations", data)
    inner = result.get("Result") or {}
    status = inner.get("ResponseStatus") or {}
    if not status.get("IsSuccess"):
        errors = status.get("Errors") or []
        logger.warning(f"组织 {number} 读取失败: {errors}")
        return None
    org = inner.get("Result")
    return org if isinstance(org, dict) else None


async def main() -> None:
    parser = argparse.ArgumentParser(description="同步金蝶组织到主数据")
    parser.add_argument("--ini", default=str(DEFAULT_INI), help="金蝶 conf.ini 路径")
    parser.add_argument("--start", type=int, default=100, help="组织编码起始值")
    parser.add_argument("--end", type=int, default=113, help="组织编码结束值")
    parser.add_argument("--bootstrap-master", action="store_true", help="同时创建内部标准组织与映射")
    args = parser.parse_args()

    client = KingdeeClient.from_ini(args.ini)
    orgs: dict[str, dict[str, Any]] = {}
    for number in range(args.start, args.end + 1):
        code = str(number)
        org = await fetch_org(client, code)
        if org is None:
            continue
        orgs[code] = org
        name = localized_text(org.get("Name"))
        parent = parent_number(org, code)
        logger.info(f"读取组织 {code}: {name} parent={parent}")

    async with async_db_session() as db, db.begin():
        source_by_code: dict[str, SourceOrgModel] = {}
        for code, org in orgs.items():
            name = localized_text(org.get("Name"))
            parent = parent_number(org, code)
            stmt = select(SourceOrgModel).where(
                SourceOrgModel.source_type == "kingdee",
                SourceOrgModel.source_code == code,
            )
            obj = (await db.execute(stmt)).scalar_one_or_none()
            if obj is None:
                obj = SourceOrgModel(
                    source_type="kingdee",
                    source_code=code,
                    source_name=name,
                    source_parent_code=parent,
                    raw_json=org,
                    status=0,
                )
                db.add(obj)
            else:
                obj.source_name = name
                obj.source_parent_code = parent
                obj.raw_json = org
                obj.status = 0
            await db.flush()
            source_by_code[code] = obj

        if not args.bootstrap_master:
            return

        master_by_code: dict[str, MasterOrgModel] = {}
        for code, org in orgs.items():
            name = localized_text(org.get("Name"))
            stmt = select(MasterOrgModel).where(MasterOrgModel.code == code)
            obj = (await db.execute(stmt)).scalar_one_or_none()
            if obj is None:
                obj = MasterOrgModel(code=code, name=name, status=0)
                db.add(obj)
            else:
                obj.name = name
                obj.status = 0
            await db.flush()
            master_by_code[code] = obj

        # 第二遍补 parent_id，避免父组织尚未创建
        for code, org in orgs.items():
            parent = parent_number(org, code)
            obj = master_by_code[code]
            obj.parent_id = master_by_code[parent].id if parent and parent in master_by_code else None

        for code, source in source_by_code.items():
            master = master_by_code[code]
            stmt = select(OrgMappingModel).where(
                OrgMappingModel.source_org_id == source.id,
                OrgMappingModel.master_org_id == master.id,
            )
            mapping = (await db.execute(stmt)).scalar_one_or_none()
            if mapping is None:
                db.add(
                    OrgMappingModel(
                        source_org_id=source.id,
                        master_org_id=master.id,
                        match_mode="exact",
                        confidence=100,
                        status=0,
                    )
                )

    await async_engine.dispose()
    logger.info(f"同步完成，共读取 {len(orgs)} 个组织")


if __name__ == "__main__":
    asyncio.run(main())
