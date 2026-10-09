"""手动同步 CRM 人员架构与人员到主数据来源表（不做定时任务）。

两个独立任务，可单独执行：

- ``org``：**同步 CRM 人员架构** —— ``GET /hs/base/getDepartment`` → ``source_org`` + ``source_dept``
- ``person``：**同步 CRM 人员** —— ``GET /hs/base/getPersonnel`` → ``source_person``
  （组织树只用于解析每人的所属组织/部门，落在 ``raw_json.departments``）

用法：
    python scripts/sync_crm_personnel.py                 # 两个任务都跑（--target all）
    python scripts/sync_crm_personnel.py --target org    # 只同步人员架构
    python scripts/sync_crm_personnel.py --target person # 只同步人员
    python scripts/sync_crm_personnel.py --dry-run       # 只打印统计与样例，不写库
    python scripts/sync_crm_personnel.py --base-url http://crmapi.yonggubox.com

同口径的手动入口还有：「系统映射管理 → 人工绑定」页面的两个同步按钮，
接口 ``POST /system-mapping/sync/crm-org``、``POST /system-mapping/sync/crm-person``；
三者共用 ``app/modules/crm/personnel_sync.py``，均**不注册** Cron。

落库口径：

- 来源类型固定写 ``crm``，与金蝶（``kingdee``）数据并存互不影响；按来源编码幂等新增/更新。
- 顶层节点写 ``source_org``（实测 4 棵：永锢、审批分组、其它分组、消息抄送），其下级写 ``source_dept``
  （``source_parent_code`` 指向上级部门；部门编码为空时用 ``CRM<节点ID>``，如「财务部」= ``CRM30``）。
- 人员来源编码取 ``username``（CRM 工号有重复，如 ``YG20013`` 对应两人），
  工号与所属部门保留在 ``raw_json``；在职（``state=1``）写 ``status=0``、离职写 ``status=1``，
  因此「人工绑定」页默认只出现在职人员。
- 只写来源表，**不创建**标准组织/部门/人员：CRM 编码与金蝶编码不同，请在「系统映射」页人工绑定。
"""

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.core.logger import logger  # noqa: E402
from app.modules.crm.client import CrmClientConfig  # noqa: E402
from app.modules.crm.personnel_sync import (  # noqa: E402
    fetch_crm_org_rows,
    fetch_crm_person_rows,
    sync_crm_org_structure,
    sync_crm_personnel,
)
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

TARGETS = ("org", "person", "all")


async def run_org(config: CrmClientConfig, dry_run: bool) -> dict[str, int]:
    """任务一：同步 CRM 人员架构。"""
    if dry_run:
        orgs, depts = await fetch_crm_org_rows(config)
        print(f"[架构] 来源组织 {len(orgs)} 条：{', '.join(o.source_name for o in orgs)}")
        print(f"[架构] 来源部门 {len(depts)} 条")
        print(json.dumps([asdict(o) for o in orgs], ensure_ascii=False, indent=2))
        print(json.dumps([asdict(d) for d in depts[:5]], ensure_ascii=False, indent=2))
        return {"orgs": len(orgs), "depts": len(depts)}
    async with async_db_session() as db, db.begin():
        result = await sync_crm_org_structure(db, config)
    print(f"[架构] 来源组织 +{result.orgs_created}/~{result.orgs_updated}；"
          f"来源部门 +{result.depts_created}/~{result.depts_updated}（共 {result.dept_total}）")
    return result.as_dict()


async def run_person(config: CrmClientConfig, dry_run: bool) -> dict[str, int]:
    """任务二：同步 CRM 人员。"""
    if dry_run:
        persons = await fetch_crm_person_rows(config)
        active = [p for p in persons if p.status == 0]
        no_dept = [p for p in active if not p.departments]
        print(f"[人员] 共 {len(persons)} 人（在职 {len(active)}，有部门 {len(active) - len(no_dept)}，无部门 {len(no_dept)}）")
        print(json.dumps([asdict(p) for p in active[:3]], ensure_ascii=False, indent=2))
        return {"persons": len(persons), "active": len(active)}

    async with async_db_session() as db, db.begin():
        result = (await sync_crm_personnel(db, config)).as_dict()
    print(f"[人员] 来源人员 +{result['persons_created']}/~{result['persons_updated']}"
          f"（共 {result['person_total']}，在职 {result['person_active']}）")
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description="手动同步 CRM 人员架构 / 人员到主数据来源表")
    parser.add_argument("--target", choices=TARGETS, default="all", help="org=人员架构，person=人员，all=两者（默认）")
    parser.add_argument("--base-url", default="http://crmapi.yonggubox.com", help="接口域名")
    parser.add_argument("--timeout", type=int, default=30, help="读取超时(秒)")
    parser.add_argument("--dry-run", action="store_true", help="只打印统计与样例，不写库")
    args = parser.parse_args()

    config = CrmClientConfig(base_url=args.base_url, timeout=args.timeout)
    summary: dict[str, dict[str, int]] = {}
    if args.target in ("org", "all"):
        summary["架构"] = await run_org(config, args.dry_run)
    if args.target in ("person", "all"):
        summary["人员"] = await run_person(config, args.dry_run)

    if args.dry_run:
        print("\n--dry-run：未写库")
        return

    await async_engine.dispose()
    logger.info(f"CRM 手动同步完成（target={args.target}）：{summary}")


if __name__ == "__main__":
    asyncio.run(main())
