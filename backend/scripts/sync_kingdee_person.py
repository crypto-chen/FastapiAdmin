"""同步金蝶员工主数据到来源人员表，并可初始化标准人员与映射。

用法：
    python scripts/sync_kingdee_person.py
    python scripts/sync_kingdee_person.py --bootstrap-master
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
from app.modules.masterdata.model import (  # noqa: E402
    MasterPersonModel,
    PersonMappingModel,
    SourceOrgModel,
    SourcePersonModel,
)
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

PERSON_FIELDS = "FID,FNumber,FName,FStaffNumber,FMobile,FEmail,FDocumentStatus,FForbidStatus,FUseOrgId"


def _as_text(value: Any) -> str:
    return str(value or "").strip()


def _org_id_map(orgs: list[SourceOrgModel]) -> dict[str, str]:
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
            form_id="BD_Empinfo",
            field_keys=PERSON_FIELDS,
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
    parser = argparse.ArgumentParser(description="同步金蝶员工主数据")
    parser.add_argument("--ini", default=str(DEFAULT_INI), help="金蝶 conf.ini 路径")
    parser.add_argument("--limit", type=int, default=2000, help="单页行数")
    parser.add_argument("--bootstrap-master", action="store_true", help="同时初始化标准人员与映射")
    args = parser.parse_args()

    client = KingdeeClient.from_ini(args.ini)
    items = await fetch_all(client, args.limit)
    if not items:
        raise SystemExit("未读取到员工数据")

    async with async_db_session() as db:
        orgs = (
            await db.execute(select(SourceOrgModel).where(SourceOrgModel.source_type == "kingdee"))
        ).scalars().all()
    org_id_map = _org_id_map(list(orgs))

    saved = 0
    async with async_db_session() as db, db.begin():
        for item in items:
            code = _as_text(item.get("FNumber"))
            org_code = org_id_map.get(_as_text(item.get("FUseOrgId")), "")
            stmt = select(SourcePersonModel).where(
                SourcePersonModel.source_type == "kingdee",
                SourcePersonModel.source_code == code,
            )
            obj = (await db.execute(stmt)).scalar_one_or_none()
            payload = {
                "source_name": _as_text(item.get("FName")),
                "source_org_code": org_code or None,
                "mobile": _as_text(item.get("FMobile")),
                "email": _as_text(item.get("FEmail")),
                "raw_json": item,
                "status": 0 if _as_text(item.get("FForbidStatus")) == "A" else 1,
            }
            if obj is None:
                obj = SourcePersonModel(source_type="kingdee", source_code=code, **payload)
                db.add(obj)
            else:
                for key, value in payload.items():
                    setattr(obj, key, value)
            await db.flush()

            if args.bootstrap_master:
                stmt = select(MasterPersonModel).where(MasterPersonModel.code == code)
                master = (await db.execute(stmt)).scalar_one_or_none()
                if master is None:
                    master = MasterPersonModel(
                        code=code,
                        name=payload["source_name"],
                        mobile=payload["mobile"],
                        email=payload["email"],
                        status=payload["status"],
                    )
                    db.add(master)
                else:
                    master.name = payload["source_name"]
                    master.mobile = payload["mobile"]
                    master.email = payload["email"]
                    master.status = payload["status"]
                await db.flush()

                stmt = select(PersonMappingModel).where(
                    PersonMappingModel.source_person_id == obj.id,
                    PersonMappingModel.master_person_id == master.id,
                )
                mapping = (await db.execute(stmt)).scalar_one_or_none()
                if mapping is None:
                    db.add(
                        PersonMappingModel(
                            source_person_id=obj.id,
                            master_person_id=master.id,
                            match_mode="exact",
                            confidence=100,
                            status=0,
                        )
                    )
            saved += 1
    await async_engine.dispose()
    logger.info(f"同步完成，读取 {len(items)} 个员工，保存 {saved} 个")


if __name__ == "__main__":
    asyncio.run(main())
