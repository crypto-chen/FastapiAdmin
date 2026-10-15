"""客户分析上线自检：表 / 迁移 / 开放接口开关（只读，不写库）。

在服务器上迁移完成后跑这个脚本，一次性确认：

1. 客户分析两张表是否建好；
2. ``alembic`` 是否只剩一个 head（多 head 会导致 ``alembic upgrade head`` 报错）；
3. 数据库当前迁移版本；
4. ``open_client.allow_customer_detail`` 列是否存在、哪些应用已开通。

用法：
    cd backend
    python scripts/check_customer_tables.py
"""

import asyncio
import io
import sys
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.core.database import async_engine  # noqa: E402

EXPECTED_TABLES = ("dwd_customer_analysis", "dwd_customer_build_run")


async def main() -> int:
    problems: list[str] = []
    async with async_engine.connect() as conn:
        for table in EXPECTED_TABLES:
            exists = bool((await conn.execute(text(f"show tables like '{table}'"))).scalars().all())
            print(f"{'OK ' if exists else 'MISS'} 表 {table}")
            if not exists:
                problems.append(f"缺少表 {table}（执行 python -m alembic upgrade 969cd6f128d1）")

        versions = (await conn.execute(text("select version_num from alembic_version"))).scalars().all()
        print(f"OK  数据库迁移版本：{versions}")

        cols = [row[0] for row in (await conn.execute(text("show columns from open_client"))).all()]
        has_flag = "allow_customer_detail" in cols
        print(f"{'OK ' if has_flag else 'MISS'} open_client.allow_customer_detail")
        if not has_flag:
            problems.append("open_client 缺 allow_customer_detail 列（迁移未跑完）")

        if has_flag:
            rows = (
                await conn.execute(
                    text(
                        "select app_id, name, allow_customer_detail, allow_cost_fields from open_client order by id"
                    )
                )
            ).all()
            print("     接入应用（app_id / 名称 / 客户明细 / 成本字段）：")
            for app_id, name, customer_detail, cost_fields in rows:
                flag = "已开通" if customer_detail else "未开通"
                print(f"       {app_id:<16}{str(name)[:14]:<16}{flag:<8}成本字段={'是' if cost_fields else '否'}")
            if not any(row[2] for row in rows):
                print("     提示：没有任何应用开通客户明细，外部调用会返回 403 —— 见文档 §开通")

    # 迁移 head 检查（读本地迁移文件，不连库）
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(file_=str(PROJECT_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "alembic"))
        heads = ScriptDirectory.from_config(cfg).get_heads()
        print(f"{'OK ' if len(heads) == 1 else 'WARN'} alembic heads：{heads}")
        if len(heads) > 1:
            print("     多 head 会让 `alembic upgrade head` 报错；"
                  "先 `python -m alembic upgrade 969cd6f128d1`，再 `python -m alembic merge heads`")
    except Exception as exc:  # noqa: BLE001
        print(f"SKIP alembic head 检查失败：{exc}")

    print()
    if problems:
        print("结论：未就绪")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("结论：客户分析表与开放接口开关均已就绪；接着执行")
    print("  python scripts/seed_customer_module.py")
    print("  python scripts/run_customer_build.py --period 2026-08,2026-09,2026-10")
    print("  python scripts/check_customer_open_api.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
