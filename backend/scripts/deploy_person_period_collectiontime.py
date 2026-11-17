"""业务员业绩指标改为收款日期口径（收款日期为空时回退建单月）。

在服务器 ``backend/`` 目录、已激活 conda 环境后执行：

    python scripts/deploy_person_period_collectiontime.py --dry-run
    python scripts/deploy_person_period_collectiontime.py --apply
    python scripts/deploy_person_period_collectiontime.py --check
    python scripts/deploy_person_period_collectiontime.py --rollback

脚本行为：

1. 从 ``seed_crm_person_metrics.py`` 读取 7 个目标指标定义；
2. 更新前把当前 ``metric_def`` 备份到
   ``backend/artifacts/person_period_collectiontime_<时间>/metric_def_before.json``；
3. 写入 ``period_field=collectiontime``、``period_field_fallback=createtime``、
   回看 12 期 / 前看 1 期；
4. 用 ``recalc_metrics_batch.py --with-dependents`` 重算这些指标及其下游；
5. 校验定义、公司合计与业务员合计（客户数类按并集口径单独校验）。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import func, select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

# 上一轮排查中仍按建单月 createtime 归期的业务员业绩指标。
# STF-16（退货退款）明细只有 number/account/create_id，没有日期字段，保持接口按建单月取数。
CODES = [
    "marketing_person_design_service_income",  # STF-15
    "marketing_person_sample_order_intake_untaxed",  # STF-38
    "marketing_person_batch_order_intake_untaxed",  # STF-39
    "marketing_person_new_customer_intake_untaxed",  # STF-40
    "marketing_person_old_customer_intake_untaxed",  # STF-41
    "marketing_person_old_customer_order_count",  # STF-48
    "marketing_person_order_count",  # 接单量（客单价分母）
]

EXPECTED_PERIOD_FIELD = "collectiontime"
EXPECTED_FALLBACK = "createtime"


def _load_seed_module():
    path = BACKEND / "scripts" / "seed_crm_person_metrics.py"
    spec = importlib.util.spec_from_file_location("seed_crm_person_metrics_deploy_period", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法加载指标定义脚本: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _target_specs() -> dict[str, dict[str, Any]]:
    module = _load_seed_module()
    specs = {item["code"]: item for item in module.METRICS if item["code"] in CODES}
    missing = [code for code in CODES if code not in specs]
    if missing:
        raise SystemExit(f"seed 脚本缺少指标定义: {missing}")
    return specs


def _description(module, item: dict[str, Any]) -> str:
    return (
        f"{item['rule']} "
        "数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》"
        f"（{module.ORDER_PATH} / {module.SHIPMENT_PATH}，GET、无需鉴权，month 为整月）；"
        "业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。"
        "月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。"
    )


def _measures(row: MetricDefModel) -> dict[str, Any]:
    value = row.measures
    if isinstance(value, str):
        return json.loads(value or "{}")
    return dict(value or {})


def _snapshot(row: MetricDefModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "formula": row.formula,
        "measures": _measures(row),
        "description": row.description,
    }


def _artifact_dir(tag: str) -> Path:
    path = BACKEND / "artifacts" / f"person_period_collectiontime_{tag}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_backup() -> Path | None:
    root = BACKEND / "artifacts"
    if not root.exists():
        return None
    candidates = sorted(
        root.glob("person_period_collectiontime_*/metric_def_before.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


async def _get_rows(db) -> dict[str, MetricDefModel]:
    rows = (
        await db.execute(select(MetricDefModel).where(MetricDefModel.code.in_(CODES)))
    ).scalars().all()
    found = {row.code: row for row in rows}
    missing = [code for code in CODES if code not in found]
    if missing:
        raise SystemExit(f"metric_def 缺少指标: {missing}")
    return found


async def _apply(dry_run: bool) -> tuple[Path, bool]:
    module = _load_seed_module()
    specs = _target_specs()
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _artifact_dir(tag)
    backup = out / "metric_def_before.json"
    any_changed = False
    async with async_db_session() as db, db.begin():
        rows = await _get_rows(db)
        snapshots = []
        for code in CODES:
            row = rows[code]
            item = specs[code]
            target_desc = _description(module, item)
            before_field = _measures(row).get("period_field")
            after_field = item["measures"].get("period_field")
            changed = (
                row.name != item["name"]
                or row.formula != item["rule"]
                or _measures(row) != item["measures"]
                or row.description != target_desc
            )
            print(f"{code}: period_field {before_field} -> {after_field}; changed={changed}")
            any_changed = any_changed or changed
            snapshots.append(_snapshot(row))
            if changed and not dry_run:
                row.name = item["name"]
                row.formula = item["rule"]
                row.measures = item["measures"]
                row.description = target_desc
        if any_changed and not dry_run:
            backup.write_text(
                json.dumps(snapshots, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"备份: {backup}")
    return backup, any_changed


async def _rollback(backup: Path | None, dry_run: bool) -> Path:
    path = backup or _latest_backup()
    if path is None or not path.exists():
        raise SystemExit("未找到可回滚的 metric_def_before.json")
    snapshots = json.loads(path.read_text(encoding="utf-8"))
    async with async_db_session() as db, db.begin():
        rows = await _get_rows(db)
        for snap in snapshots:
            row = rows[snap["code"]]
            print(
                f"restore {snap['code']}: period_field="
                f"{(snap.get('measures') or {}).get('period_field')}"
            )
            if not dry_run:
                row.name = snap["name"]
                row.formula = snap["formula"]
                row.measures = snap["measures"]
                row.description = snap["description"]
    return path


async def _periods(args) -> list[str]:
    async with async_db_session() as db:
        rows = await _get_rows(db)
        ids = [row.id for row in rows.values()]
        periods = (
            await db.execute(
                select(MetricValueModel.period_value)
                .where(
                    MetricValueModel.metric_id.in_(ids),
                    MetricValueModel.period_type == "month",
                )
                .group_by(MetricValueModel.period_value)
                .order_by(MetricValueModel.period_value)
            )
        ).scalars().all()
    values = [str(item) for item in periods]
    if args.period:
        values = list(args.period)
    else:
        if args.period_from:
            values = [item for item in values if item >= args.period_from]
        if args.period_to:
            values = [item for item in values if item <= args.period_to]
    if not values:
        raise SystemExit("没有匹配的期间；请先确认 metric_value 已有结果")
    return values


def _run_recalc(periods: list[str], log_path: Path, codes: list[str] | None = None) -> None:
    cmd = [sys.executable, str(BACKEND / "scripts" / "recalc_metrics_batch.py")]
    for code in codes or CODES:
        cmd.extend(["--code", code])
    cmd.append("--with-dependents")
    if len(periods) == 1:
        cmd.extend(["--period", periods[0]])
    else:
        cmd.extend(["--period-from", periods[0], "--period-to", periods[-1]])
    cmd.extend(["--log", str(log_path)])
    print("执行:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(BACKEND), check=True)


async def _verify(periods: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"periods": periods, "metrics": {}, "errors": []}
    errors: list[str] = result["errors"]
    async with async_db_session() as db:
        rows = await _get_rows(db)
        for code in CODES:
            row = rows[code]
            config = _measures(row)
            if config.get("period_field") != EXPECTED_PERIOD_FIELD:
                errors.append(
                    f"{code}: period_field={config.get('period_field')}，"
                    f"期望 {EXPECTED_PERIOD_FIELD}"
                )
            if config.get("period_field_fallback") != EXPECTED_FALLBACK:
                errors.append(
                    f"{code}: period_field_fallback={config.get('period_field_fallback')}，"
                    f"期望 {EXPECTED_FALLBACK}"
                )
            is_customer_count = config.get("value_mode") == "count_customers"
            per_period: dict[str, Any] = {}
            for period in periods:
                version = (
                    await db.execute(
                        select(func.max(MetricValueModel.calc_version)).where(
                            MetricValueModel.metric_id == row.id,
                            MetricValueModel.period_type == "month",
                            MetricValueModel.period_value == period,
                        )
                    )
                ).scalar()
                values = (
                    await db.execute(
                        select(
                            MetricValueModel.dept_code,
                            MetricValueModel.person_code,
                            MetricValueModel.value,
                        ).where(
                            MetricValueModel.metric_id == row.id,
                            MetricValueModel.period_type == "month",
                            MetricValueModel.period_value == period,
                            MetricValueModel.calc_version == version,
                        )
                    )
                ).all()
                company = sum(
                    float(value or 0)
                    for dept_code, person_code, value in values
                    if dept_code is None and person_code is None
                )
                person_sum = sum(
                    float(value or 0)
                    for _dept, person_code, value in values
                    if person_code is not None
                )
                residual = round(company - person_sum, 4)
                per_period[period] = {
                    "version": version,
                    "company": round(company, 4),
                    "person_sum": round(person_sum, 4),
                    "residual": residual,
                }
                if is_customer_count:
                    # 客户数公司合计是业务员客户并集，允许小于业务员行相加
                    if company > person_sum + 0.01:
                        errors.append(f"{code} {period}: 公司合计 > 业务员合计")
                elif abs(residual) > 0.01:
                    errors.append(f"{code} {period}: 公司合计与业务员合计差 {residual}")
            result["metrics"][code] = per_period
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


async def _run(args) -> None:
    try:
        if args.check:
            periods = await _periods(args)
            result = await _verify(periods)
            if result["errors"]:
                raise SystemExit("校验失败")
            return

        if args.rollback:
            backup = await _rollback(Path(args.backup) if args.backup else None, args.dry_run)
            print(f"已使用备份: {backup}")
        else:
            backup, changed = await _apply(args.dry_run)
            print(f"定义变更: {'有' if changed else '无'}")

        if args.dry_run:
            print("dry-run 完成，未重算")
            return
        if args.skip_recalc:
            print("已跳过重算")
            return

        periods = await _periods(args)
        artifact = backup.parent
        log_path = artifact / "recalc.log"
        _run_recalc(periods, log_path)
        result = await _verify(periods)
        (artifact / "verify_result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if result["errors"]:
            raise SystemExit("校验失败")
        print(f"完成。验证结果: {artifact / 'verify_result.json'}")
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="业务员业绩指标改为收款日期口径")
    parser.add_argument("--apply", action="store_true", help="更新指标定义并重算（默认动作）")
    parser.add_argument("--rollback", action="store_true", help="恢复最近一次备份并重算")
    parser.add_argument("--check", action="store_true", help="只校验当前结果")
    parser.add_argument("--backup", default=None, help="回滚时指定 metric_def_before.json")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写库、不重算")
    parser.add_argument("--skip-recalc", action="store_true", help="只更新/回滚定义，不重算")
    parser.add_argument("--period", action="append", default=None, help="期间，可重复")
    parser.add_argument("--period-from", default=None, help="起始期间（含）")
    parser.add_argument("--period-to", default=None, help="结束期间（含）")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
