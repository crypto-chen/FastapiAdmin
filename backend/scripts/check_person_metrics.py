"""业务员指标上线自检：一次性打印数据库版本、表结构、指标数、同步任务与结果概况。

用法（backend 目录，dev 环境先设置 ENVIRONMENT=dev）：

    python scripts/check_person_metrics.py

输出示例（每项都有「✅ / ⚠️」结论）：

    [1] 数据库迁移版本：cd6a5655eba2 ✅
    [2] metric_value 业务员列：person_code / person_name ✅
    [3] open_client.业务员明细权限列：allow_person_detail ✅
    [4] 业务员指标：16 个 ✅
    [5] 业务员指标同步任务：6 个 ✅
    [6] 各期间结果概况：...
    [7] 接入应用业务员明细权限：...
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import case, func, select, text

# Windows 控制台默认 GBK，输出 ✅/⚠️ 会抛 UnicodeEncodeError；统一改成 UTF-8
for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):  # pragma: no cover - 非标准输出流
        pass

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.modules.openapi.model import OpenClientModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

PERSON_CATEGORY = "营销中心-业务员"
TARGET_HEAD = "cd6a5655eba2"


async def main() -> None:
    problems: list[str] = []
    async with async_db_session() as db:
        print("=" * 78)
        print("业务员指标上线自检")
        print("=" * 78)

        # [1] 迁移版本
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalars().first()
        ok = bool(version)
        print(f"[1] 数据库迁移版本：{version} {'✅' if ok else '⚠️ 读不到 alembic_version'}")
        if version != TARGET_HEAD:
            print(f"    提示：本地开发环境为 {TARGET_HEAD}；版本不同不一定有问题，但请确认表结构已包含业务员列（见 [2]）")

        # [2] metric_value 业务员列
        cols = {
            row[0]
            for row in (
                await db.execute(
                    text(
                        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'metric_value'"
                    )
                )
            ).all()
        }
        person_cols = [name for name in ("person_id", "person_code", "person_name") if name in cols]
        has_person = {"person_code", "person_name"} <= cols
        print(f"[2] metric_value 业务员列：{' / '.join(person_cols) or '无'} {'✅' if has_person else '⚠️ 缺少 person_code/person_name'}")
        if not has_person:
            problems.append("metric_value 缺 person_code/person_name：执行 main.py upgrade --env=dev")

        # [3] open_client 权限列
        client_cols = {
            row[0]
            for row in (
                await db.execute(
                    text(
                        "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'open_client'"
                    )
                )
            ).all()
        }
        has_person_detail = "allow_person_detail" in client_cols
        print(f"[3] open_client.业务员明细权限列：{'allow_person_detail' if has_person_detail else '无'} {'✅' if has_person_detail else '⚠️'}")
        if not has_person_detail:
            problems.append("open_client 缺 allow_person_detail：执行 main.py upgrade --env=dev")

        # [4] 指标定义
        metrics = (
            await db.execute(
                select(MetricDefModel).where(MetricDefModel.category == PERSON_CATEGORY).order_by(MetricDefModel.excel_code)
            )
        ).scalars().all()
        print(f"[4] 业务员指标：{len(metrics)} 个 {'✅' if metrics else '⚠️ 未建指标，先跑 seed_crm_person_metrics.py'}")
        if not metrics:
            problems.append("没有业务员指标定义：执行 scripts/seed_crm_person_metrics.py")
        else:
            print("    " + "、".join(f"{m.excel_code or '-'}:{m.code}" for m in metrics))

        # [5] 同步任务
        jobs = (
            await db.execute(
                select(MetaSyncJobModel)
                .where(MetaSyncJobModel.name.like("CRM业务员指标%"))
                .order_by(MetaSyncJobModel.id)
            )
        ).scalars().all()
        print(f"[5] 业务员指标同步任务：{len(jobs)} 个 {'✅' if len(jobs) >= 6 else '⚠️ 少于 6 个'}")
        for job in jobs:
            state = "启用" if int(job.status or 0) == 0 else "停用"
            print(f"    - {job.id} {job.name}（{job.cron_expr}，{state}）")
        if len(jobs) < 6:
            problems.append("同步任务不足 6 个：执行 scripts/seed_crm_person_metrics.py")

        # [6] 结果概况
        metric_ids = [int(item.id) for item in metrics]
        print("[6] 各期间结果概况（期间 / 有结果的指标数 / 涉及业务员数，业务员为各指标并集）")
        if metric_ids:
            rows = (
                await db.execute(
                    select(
                        MetricValueModel.period_value,
                        func.count(func.distinct(MetricValueModel.metric_id)),
                        func.count(func.distinct(MetricValueModel.person_code)),
                    )
                    .where(MetricValueModel.metric_id.in_(metric_ids))
                    .group_by(MetricValueModel.period_value)
                    .order_by(MetricValueModel.period_value.desc())
                    .limit(6)
                )
            ).all()
            if not rows:
                print("    ⚠️ 还没有任何计算结果：执行 scripts/backfill_person_metrics.py --start ... --end ...")
                problems.append("没有任何业务员指标结果：执行 backfill_person_metrics.py")
            for period_value, metric_count, person_count in rows:
                print(f"    - {period_value}：{metric_count} 个指标，{int(person_count or 0)} 个业务员")

        # [7] 接入应用权限
        clients = (
            await db.execute(select(OpenClientModel).where(OpenClientModel.is_deleted == False))  # noqa: E712
        ).scalars().all()
        print("[7] 接入应用的业务员明细权限")
        if has_person_detail:
            for item in clients:
                flag = "已开放" if getattr(item, "allow_person_detail", False) else "未开放"
                print(f"    - {item.app_id}（{item.name}）：{flag}")
            if clients and not any(getattr(item, "allow_person_detail", False) for item in clients):
                print("    ⚠️ 没有任何应用开放：调用方 level=person 会收到 403 / 40102")
                problems.append("没有应用开放业务员明细：跑 set_open_client_person_permission.py --app-id xxx --enable")
        else:
            print("    （跳过：缺 allow_person_detail 列）")

    await async_engine.dispose()
    print("=" * 78)
    if problems:
        print("需要处理：")
        for index, item in enumerate(problems, start=1):
            print(f"  {index}. {item}")
        raise SystemExit(1)
    print("全部检查通过 ✅ 业务员指标可以对外提供（level=person）")


if __name__ == "__main__":
    asyncio.run(main())
