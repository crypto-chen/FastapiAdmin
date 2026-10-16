"""产品线分析：一键部署脚本（**dev 环境直跑，非 Docker**）。

把「迁移 → 建来源对象/同步任务 → 建实体/字段/菜单 → 回补取数 → 订单全链路 → 产品线宽表 →
出对接文档 → 自检」串成一次运行，每步都打印将执行的命令与实际输出。

用法（在 ``backend`` 目录下执行）：
    python scripts/deploy_product_line.py --dry-run                    # 只看会做什么
    python scripts/deploy_product_line.py                              # 默认期间 2026-07~09，dev 环境
    python scripts/deploy_product_line.py --env prod --periods 2025-01,2025-02
    python scripts/deploy_product_line.py --skip-backup --skip-doc     # 跳过备份与文档生成
    python scripts/deploy_product_line.py --base-url https://<对外域名>

说明：
1. 删除/覆盖类操作只有「备份文件」与「宽表新增版本」——**宽表按 calc_version 追加，不覆盖历史**。
2. 备份用 ``mysqldump``（PATH 里没有就跳过并提醒，不阻断流程）。
3. 前 6 步都是幂等的，可以反复跑；重复跑只会生成新的 calc_version。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_PERIODS = "2026-07,2026-08,2026-09"
EXPECTED_HEAD = "27578c7b66b6"


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
class Step:
    """一个部署步骤：名称 + 命令行（dry-run 只打印）。"""

    def __init__(self, index: str, title: str, argv: list[str]) -> None:
        self.index = index
        self.title = title
        self.argv = argv


def banner(text: str, char: str = "=") -> None:
    print(f"\n{char * 78}\n{text}\n{char * 78}")


def run_step(step: Step, apply: bool) -> None:
    banner(f"[{step.index}] {step.title}", "-")
    printable = " ".join(f'"{item}"' if " " in item else item for item in step.argv)
    print(f"$ {printable}")
    if not apply:
        print("  （dry-run，未执行）")
        return
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run(step.argv, cwd=str(PROJECT_ROOT), env=env, check=False)
    if result.returncode != 0:
        print(f"\n步骤 [{step.index}] 失败（退出码 {result.returncode}），已中止。")
        raise SystemExit(result.returncode)


def backup_database(apply: bool, skip: bool) -> None:
    banner("[0] 备份数据库", "-")
    if skip:
        print("  已按 --skip-backup 跳过（请自行确认已有可用备份）")
        return
    if shutil.which("mysqldump") is None:
        print("  跳过：PATH 里没有 mysqldump（非 MySQL 部署或未装客户端）——请自行确认已有备份")
        return
    from app.config.setting import settings

    if not settings.DATABASE_PASSWORD:
        print("  跳过：DATABASE_PASSWORD 为空（.env 里没配），请自行确认已有备份")
        return
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    target = Path.home() / f"fastapiadmin_backup_{stamp}.sql"
    argv = [
        "mysqldump",
        f"-h{settings.DATABASE_HOST}",
        f"-P{settings.DATABASE_PORT}",
        f"-u{settings.DATABASE_USER}",
        f"-p{settings.DATABASE_PASSWORD}",
        "--single-transaction",
        "--databases",
        settings.DATABASE_NAME,
    ]
    print(f"$ mysqldump -h{settings.DATABASE_HOST} -P{settings.DATABASE_PORT} "
          f"-u{settings.DATABASE_USER} -p*** --single-transaction --databases {settings.DATABASE_NAME} > {target}")
    if not apply:
        print("  （dry-run，未执行）")
        return
    with target.open("wb") as fh:
        result = subprocess.run(argv, stdout=fh, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        print(f"  备份失败：{result.stderr.decode('utf-8', 'ignore')[:300]}")
        print("  已中止（如确认不需要备份，可加 --skip-backup 重跑）")
        raise SystemExit(result.returncode)
    print(f"  已备份：{target}（{target.stat().st_size / 1024:.1f} KB）")


def build_steps(args: argparse.Namespace) -> list[Step]:
    py = sys.executable
    periods = args.periods
    steps = [
        Step("1", f"数据库迁移（alembic upgrade head，期望 {EXPECTED_HEAD}）",
             [py, "main.py", "upgrade", f"--env={args.env}"]),
        Step("2", "建 CRM 发货明细来源对象与同步任务",
             [py, "scripts/seed_crm_shipment_detail.py"]),
        Step("3", "建标准实体 / 65 个字段 / 菜单 / 角色授权",
             [py, "scripts/seed_product_module.py"]),
        Step("4", f"回补 CRM 发货明细取数（期间 {periods}）",
             [py, "scripts/run_meta_sync.py", "--name", "CRM发货明细-getShipmentsDetail",
              "--period", periods, "--show-latest"]),
        Step("5", f"重建订单全链路（期间 {periods}，会带上 order_id / ship_qty）",
             [py, "scripts/run_order_build.py", "--period", periods]),
        Step("6", f"构建产品线宽表（期间 {periods}）",
             [py, "scripts/run_product_build.py", "--period", periods]),
    ]
    if not args.skip_doc:
        first = periods.split(",")[0].strip()
        steps.append(
            Step("7", "生成外部对接文档",
                 [py, "scripts/gen_product_line_api_doc.py", "--base-url", args.base_url,
                  "--period", first])
        )
    return steps


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #
async def verify(periods: list[str]) -> None:
    from sqlalchemy import text

    from app.core.base_model import MappedBase
    from app.core.database import async_db_session, async_engine
    from app.utils.import_util import ImportUtil

    ImportUtil.find_models(MappedBase)
    banner("[8] 自检", "-")
    async with async_db_session() as db:
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar()
        print(f"  alembic head：{version}（期望 {EXPECTED_HEAD}）"
              f"{'  ✅' if version == EXPECTED_HEAD else '  ⚠️ 不一致'}")
        tables = (await db.execute(text("SHOW TABLES LIKE 'dwd_product_line%'"))).scalars().all()
        print(f"  产品线表：{list(tables)}")
        cols = (await db.execute(text("SHOW COLUMNS FROM dwd_order_full_chain LIKE 'ship_qty'"))).all()
        print(f"  dwd_order_full_chain.ship_qty：{'存在 ✅' if cols else '缺失 ⚠️'}")
        flag = (
            await db.execute(
                text("SHOW COLUMNS FROM open_client LIKE 'allow_product_line_detail'")
            )
        ).all()
        print(f"  open_client.allow_product_line_detail：{'存在 ✅' if flag else '缺失 ⚠️'}")

        print("  宽表分层行数（只列各期间最新版本；0=产品线×SKU 明细 / 1=产品线小计 / 2=全表合计）：")
        rows = (
            await db.execute(
                text(
                    "SELECT a.period_value, a.calc_version, a.is_aggregate, COUNT(*) AS n "
                    "FROM dwd_product_line_analysis a "
                    "JOIN (SELECT period_value, MAX(calc_version) AS v FROM dwd_product_line_analysis "
                    "      GROUP BY period_value) m "
                    "  ON m.period_value = a.period_value AND m.v = a.calc_version "
                    "GROUP BY 1,2,3 ORDER BY 1,3"
                )
            )
        ).all()
        if not rows:
            print("    （空）—— 第 6 步可能没跑成功")
        for period, calc_version, level, count in rows:
            mark = " ✅" if str(period) in periods else ""
            print(f"    {period}  v{calc_version}  level={level}  {count} 行{mark}")

        print("  构建批次（最近 5 条）：")
        runs = (
            await db.execute(
                text(
                    "SELECT period_value, calc_version, status, line_count, sku_count, order_count, "
                    "matched_rows, unmatched_rows FROM dwd_product_line_build_run ORDER BY id DESC LIMIT 5"
                )
            )
        ).all()
        for period, ver, status, line_count, sku_count, order_count, matched, unmatched in runs:
            print(
                f"    {period} v{ver} {status}｜产品线 {line_count}｜SKU {sku_count}｜"
                f"订单 {order_count}｜命中型号字典 {matched}／未命中 {unmatched}"
            )

        print("  开放接口权限（需对接的应用要 allow_product_line_detail=1）：")
        clients = (
            await db.execute(
                text(
                    "SELECT app_id, name, allow_product_line_detail, allow_cost_fields, status "
                    "FROM open_client ORDER BY id"
                )
            )
        ).all()
        if not clients:
            print("    （还没建接入应用，可在管理端「开放接口 → 接入应用」新建）")
        for app_id, name, product_line, cost, status in clients:
            state = "启用" if int(status or 0) == 0 else "停用"
            print(
                f"    {app_id}（{name}，{state}）产品线分析="
                f"{'开' if product_line else '关'}｜成本字段={'开' if cost else '关'}"
            )
    await async_engine.dispose()


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description="产品线分析一键部署（dev 环境直跑）")
    parser.add_argument("--env", default="dev", help="环境名，默认 dev（读取 backend/env/.env.$ENV）")
    parser.add_argument("--periods", default=DEFAULT_PERIODS, help=f"回补期间，逗号分隔（默认 {DEFAULT_PERIODS}）")
    parser.add_argument("--base-url", default="https://<对外域名>", help="生成对接文档时写入的对外服务地址")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不做任何改动")
    parser.add_argument("--skip-backup", action="store_true", help="跳过 mysqldump 备份")
    parser.add_argument("--skip-doc", action="store_true", help="跳过生成外部对接文档")
    args = parser.parse_args()

    os.environ["ENVIRONMENT"] = args.env
    periods = [item.strip() for item in args.periods.split(",") if item.strip()]
    env_file = PROJECT_ROOT / "env" / f".env.{args.env}"

    banner("产品线分析一键部署")
    print(f"  代码目录   ：{PROJECT_ROOT}")
    print(f"  环境       ：{args.env}（{env_file}）")
    print(f"  期间       ：{', '.join(periods)}")
    print(f"  解释器     ：{sys.executable}")
    print(f"  模式       ：{'dry-run（只看不做）' if args.dry_run else '执行'}")
    if not env_file.exists():
        print(f"\n⚠️  环境文件不存在：{env_file}")
        print("    请参照 env/.env.example 创建，至少填写 ENVIRONMENT / SECRET_KEY / DATABASE_* / REDIS_*")
        raise SystemExit(2)

    apply = not args.dry_run
    backup_database(apply, args.skip_backup)
    for step in build_steps(args):
        run_step(step, apply)

    if args.dry_run:
        print("\n（dry-run 结束，未执行任何命令；确认后去掉 --dry-run 重跑）")
        return

    asyncio.run(verify(periods))

    banner("完成")
    print("  别忘了两件事：")
    print("    1) 重启一次后端进程 —— 新增同步任务要重启才会进调度器；")
    print("    2) 给对接方开权限 —— UPDATE open_client SET allow_product_line_detail=1 WHERE app_id='...';")


if __name__ == "__main__":
    main()
