"""按 ExecuteBillQuery 列表接口同步金蝶部门到来源部门表。

用法：
    python scripts/sync_kingdee_dept.py
    python scripts/sync_kingdee_dept.py --org 100
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
from app.modules.erp.kingdee.client import KingdeeBillQueryRequest, KingdeeClient  # noqa: E402
from app.modules.masterdata.model import SourceDeptModel, SourceOrgModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

DEPT_FIELDS = "FDEPTID,FNumber,FName,FFullName,FDocumentStatus,FForbidStatus,FUseOrgId,FParentID,FDepth"


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _org_id_map(orgs: list[SourceOrgModel]) -> dict[str, str]:
    """金蝶组织内码 -> 组织编码。"""
    mapping: dict[str, str] = {}
    for org in orgs:
        raw = org.raw_json or {}
        internal_id = raw.get("Id")
        if internal_id is not None:
            mapping[str(internal_id)] = org.source_code
    return mapping


async def fetch_all(client: KingdeeClient, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start_row = 0
    while True:
        request = KingdeeBillQueryRequest(
            form_id="BD_Department",
            field_keys=DEPT_FIELDS,
            filter_string="",
            order_string="",
            top_row_count=0,
            start_row=start_row,
            limit=limit,
        )
        _, items = await client.bill_query(request)
        rows.extend(items)
        if len(items) < limit:
            break
        start_row += len(items)
    return rows


async def main() -> None:
    parser = argparse.ArgumentParser(description="同步金蝶部门到主数据")
    parser.add_argument("--ini", default=str(DEFAULT_INI), help="金蝶 conf.ini 路径")
    parser.add_argument("--org", default="", help="只同步指定组织编码，如 100；空为全部组织")
    parser.add_argument("--limit", type=int, default=2000, help="单页行数")
    args = parser.parse_args()

    client = KingdeeClient.from_ini(args.ini)
    items = await fetch_all(client, args.limit)
    if not items:
        raise SystemExit("未读取到部门数据")

    async with async_db_session() as db:
        orgs = (
            await db.execute(select(SourceOrgModel).where(SourceOrgModel.source_type == "kingdee"))
        ).scalars().all()
    org_id_map = _org_id_map(list(orgs))
    dept_id_to_code = {_as_text(item.get("FDEPTID")): _as_text(item.get("FNumber")) for item in items}

    saved = 0
    async with async_db_session() as db, db.begin():
        for item in items:
            dept_code = _as_text(item.get("FNumber"))
            org_code = org_id_map.get(_as_text(item.get("FUseOrgId")), "")
            if args.org and org_code != args.org:
                continue
            if not org_code:
                logger.warning(f"部门 {dept_code} 无法识别所属组织: FUseOrgId={item.get('FUseOrgId')}")
                continue

            parent_code = None
            parent_id = _as_text(item.get("FParentID"))
            if parent_id and parent_id != "0":
                parent_code = dept_id_to_code.get(parent_id)

            stmt = select(SourceDeptModel).where(
                SourceDeptModel.source_type == "kingdee",
                SourceDeptModel.source_org_code == org_code,
                SourceDeptModel.source_code == dept_code,
            )
            obj = (await db.execute(stmt)).scalar_one_or_none()
            if obj is None:
                obj = SourceDeptModel(
                    source_type="kingdee",
                    source_org_code=org_code,
                    source_code=dept_code,
                    source_name=_as_text(item.get("FName")),
                    source_parent_code=parent_code,
                    raw_json=item,
                    status=0 if _as_text(item.get("FForbidStatus")) == "A" else 1,
                )
                db.add(obj)
            else:
                obj.source_name = _as_text(item.get("FName"))
                obj.source_parent_code = parent_code
                obj.raw_json = item
                obj.status = 0 if _as_text(item.get("FForbidStatus")) == "A" else 1
            saved += 1
    await async_engine.dispose()
    logger.info(f"同步完成，读取 {len(items)} 个部门，保存 {saved} 个")


if __name__ == "__main__":
    asyncio.run(main())
