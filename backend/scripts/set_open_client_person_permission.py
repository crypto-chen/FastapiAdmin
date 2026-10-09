"""查看 / 设置开放接口接入应用的「业务员明细」权限（`open_client.allow_person_detail`）。

没有权限时调用方用 ``level=person`` 取数会被拒（403，错误码 40102：
「该应用未开放业务员明细，level 不能为 person」）。管理端也有开关
（开放接口 → 接入应用 → 业务员明细），不方便开页面时用本脚本。

用法（在 backend 目录下执行，dev 环境先设置 ENVIRONMENT=dev）：

    python scripts/set_open_client_person_permission.py --list
    python scripts/set_open_client_person_permission.py --app-id hs_report --enable
    python scripts/set_open_client_person_permission.py --app-id hs_report --disable
    python scripts/set_open_client_person_permission.py --all --enable   # 给全部启用中的应用开放
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.openapi.model import OpenClientModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)


async def _list_clients(db) -> list[OpenClientModel]:
    return list(
        (
            await db.execute(
                select(OpenClientModel)
                .where(OpenClientModel.is_deleted == False)  # noqa: E712
                .order_by(OpenClientModel.id.asc())
            )
        ).scalars().all()
    )


def _print_clients(clients: list[OpenClientModel]) -> None:
    print(f"{'id':<5} {'app_id':<20} {'应用名称':<20} {'状态':<6} {'组织明细':<9} {'业务员明细'}")
    print("-" * 90)
    for item in clients:
        status = "启用" if int(item.status or 0) == 0 else "停用"
        dept = "含明细" if item.allow_dept_detail else "仅合计"
        person = "已开放" if getattr(item, "allow_person_detail", False) else "未开放"
        print(f"{item.id:<5} {item.app_id:<20} {str(item.name or ''):<20} {status:<6} {dept:<9} {person}")


async def main() -> None:
    parser = argparse.ArgumentParser(description="查看/设置接入应用的业务员明细权限")
    parser.add_argument("--list", action="store_true", help="只列出全部接入应用及当前权限")
    parser.add_argument("--app-id", default=None, help="目标应用标识（app_id）")
    parser.add_argument("--all", action="store_true", help="对全部启用的应用生效")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true", help="开放业务员明细")
    group.add_argument("--disable", action="store_true", help="关闭业务员明细")
    args = parser.parse_args()

    async with async_db_session() as db:
        clients = await _list_clients(db)
        if not clients:
            raise SystemExit("没有找到接入应用（open_client 表为空）")
        _print_clients(clients)
        if args.list or not (args.enable or args.disable):
            if not args.list:
                print()
                print("未指定 --enable / --disable，仅展示当前权限。示例：")
                print("  python scripts/set_open_client_person_permission.py --app-id hs_report --enable")
            return

        wanted = bool(args.enable)
        targets = [item for item in clients if args.all and int(item.status or 0) == 0]
        if args.app_id:
            targets = [item for item in clients if str(item.app_id) == args.app_id]
            if not targets:
                raise SystemExit(f"没有找到 app_id = {args.app_id} 的接入应用（见上方列表）")
        if not targets:
            raise SystemExit("没有匹配的接入应用：请用 --app-id 指定，或用 --all 对全部启用应用生效")

        for item in targets:
            item.allow_person_detail = wanted
        await db.commit()
        print()
        print(f"已{'开放' if wanted else '关闭'}业务员明细：{', '.join(str(item.app_id) for item in targets)}")
        print("（权限在每次请求时读库判断，无需重启服务）")

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
