"""本地调试：查看金蝶某组织下的部门。

用法：
    python scripts/kingdee_dept_view.py --number 部门编码
    python scripts/kingdee_dept_view.py --id 部门内码
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INI = PROJECT_ROOT / "env" / "kindee_conf.ini"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.erp.kingdee.client import KingdeeClient  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description="查看金蝶部门")
    parser.add_argument("--ini", default=str(DEFAULT_INI), help="金蝶 conf.ini 路径")
    parser.add_argument("--number", default="", help="部门编码")
    parser.add_argument("--id", default="", help="部门内码")
    parser.add_argument("--create-org-id", type=int, default=0, help="创建者组织内码")
    args = parser.parse_args()

    client = KingdeeClient.from_ini(args.ini)
    data = {
        "CreateOrgId": args.create_org_id,
        "Number": args.number,
        "Id": args.id,
        "IsSortBySeq": "false",
    }
    result = await client.view("BD_Department", data)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
