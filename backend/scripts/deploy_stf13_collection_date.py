"""STF-13 业务员接单未税：收款日期口径部署脚本。

在服务器 ``backend/`` 目录、已激活 conda 环境后执行：

    python scripts/deploy_stf13_collection_date.py --dry-run
    python scripts/deploy_stf13_collection_date.py --apply
    python scripts/deploy_stf13_collection_date.py --check
    python scripts/deploy_stf13_collection_date.py --rollback

脚本行为：

1. 从 ``seed_crm_person_metrics.py`` 读取 STF-13 目标定义；
2. 更新前把当前 ``metric_def`` 备份到 ``backend/artifacts/stf13_collection_date_<时间>/``；
3. 更新 STF-13 的 formula / measures / description（period_field=collectiontime）；
4. 重算库中已有期间（默认 2026-07 ~ 2026-10），支持 ``--period`` 精确指定；
5. 校验公司合计 = 业务员行合计，并确认 period_field 已生效。
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

CODE = "marketing_person_order_intake_untaxed"
EXCEL_CODE = "STF-13"
EXPECTED_PERIOD_FIELD = "collectiontime"


def _load_seed_module():
    path = BACKEND / "scripts" / "seed_crm_person_metrics.py"
    spec = importlib.util.spec_from_file_location("seed_crm_person_metrics_deploy_stf13", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法加载指标定义脚本: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _target_spec() -> dict[str, Any]:
    module = _load_seed_module()
    for item in module.METRICS:
        if item["code"] == CODE:
            return item
    raise SystemExit(f"seed 脚本缺少指标定义: {CODE}")


def _description(module, item: dict[str, Any]) -> str:
    return (
        f"{item['rule']} "
        "数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》"
        f"（{module.ORDER_PATH} / {module.SHIPMENT_PATH}，GET、无需鉴权，month 为整月）；"
        "业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。"
        "月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。"
    )


def _snapshot(row: MetricDefModel) -> dict[str, Any]:
    return {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "formula": row.formula,
        "measures": row.measures,
        "description": row.description,
    }


def _artifact_dir(tag: str) -> Path:
    path = BACKEND / "artifacts" / f"stf13_collection_date_{tag}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _latest_backup() -> Path | None:
    root = BACKEND / "artifacts"
    if not root.exists():
        return None
    candidates = sorted(
        root.glob("stf13_collection_date_*/metric_def_before.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


async def _get_row(db) -> MetricDefModel:
    row = (await db.execute(select(MetricDefModel).where(MetricDefModel.code == CODE))).scalars().first()
    if row is None:
        raise SystemExit(f"metric_def 缺少指标: {CODE}")
    return row


async def _apply(dry_run: bool) -> tuple[Path, bool]:
    module = _load_seed_module()
    item = _target_spec()
    target_desc = _description(module, item)
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    async with async_db_session() as db, db.begin():
        row = await _get_row(db)
        out = _artifact_dir(tag)
        backup = out / "metric_def_before.json"
        changed = (
            row.name != item["name"]
            or row.formula != item["rule"]
            or row.measures != item["measures"]
            or row.description != target_desc
        )
        before_field = (row.measures or {}).get("period_field") if isinstance(row.measures, dict) else None
        after_field = item["measures"].get("period_field")
        print(f"{CODE} ({EXCEL_CODE}): period_field {before_field} -> {after_field}")
        if changed:
            print("  formula/measures/description 有变化")
        else:
            print("  已是最新定义，跳过写入")
        if changed and not dry_run:
            backup.write_text(json.dumps(_snapshot(row), ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  备份: {backup}")
            row.name = item["name"]
            row.formula = item["rule"]
            row.measures = item["measures"]
            row.description = target_desc
    return backup, changed


async def _rollback(backup: Path | None, dry_run: bool) -> Path:
    path = backup or _latest_backup()
    if path is None or not path.exists():
        raise SystemExit("未找到可回滚的 metric_def_before.json")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    async with async_db_session() as db, db.begin():
        row = await _get_row(db)
        print(f"restore {CODE} ({EXCEL_CODE}): period_field={((snapshot.get('measures') or {}).get('period_field'))}")
        if not dry_run:
            row.name = snapshot["name"]
            row.formula = snapshot["formula"]
            row.measures = snapshot["measures"]
            row.description = snapshot["description"]
    return path


async def _periods(args) -> list[str]:
    async with async_db_session() as db:
        row = await _get_row(db)
        rows = (
            await db.execute(
                select(MetricValueModel.period_value)
                .where(
                    MetricValueModel.metric_id == row.id,
                    MetricValueModel.period_type == "month",
                )
                .group_by(MetricValueModel.period_value)
                .order_by(MetricValueModel.period_value)
            )
        ).scalars().all()
    periods = [str(item) for item in rows]
    if args.period:
        periods = list(args.period)
    else:
        if args.period_from:
            periods = [item for item in periods if item >= args.period_from]
        if args.period_to:
            periods = [item for item in periods if item <= args.period_to]
    if not periods:
        raise SystemExit("没有匹配的期间；请先确认 metric_value 已有 STF-13 结果")
    return periods


def _run_recalc(periods: list[str], log_path: Path) -> None:
    cmd = [sys.executable, str(BACKEND / "scripts" / "recalc_metrics_batch.py"), "--code", CODE]
    if len(periods) == 1:
        cmd.extend(["--period", periods[0]])
    else:
        cmd.extend(["--period-from", periods[0], "--period-to", periods[-1]])
    cmd.extend(["--log", str(log_path)])
    print("执行:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(BACKEND), check=True)


async def _verify(periods: list[str]) -> dict[str, Any]:
    max_residual = 0.0
    totals: dict[str, float] = {}
    async with async_db_session() as db:
        row = await _get_row(db)
        measures = row.measures if isinstance(row.measures, dict) else json.loads(row.measures or "{}")
        errors: list[str] = []
        if measures.get("period_field") != EXPECTED_PERIOD_FIELD:
            errors.append(f"period_field={measures.get('period_field')}，期望 {EXPECTED_PERIOD_FIELD}")
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
            company = sum(float(v or 0) for dept_code, _person, v in values if dept_code is None)
            person_sum = sum(float(v or 0) for _dept, person, v in values if person is not None)
            totals[period] = round(company, 4)
            max_residual = max(max_residual, abs(company - person_sum))
        result = {
            "periods": periods,
            "totals": totals,
            "max_company_person_residual": round(max_residual, 4),
            "period_field": measures.get("period_field"),
            "errors": errors,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if errors or max_residual > 0.01:
            raise SystemExit("校验失败")
        return result


async def _run(args) -> None:
    try:
        if args.check:
            periods = await _periods(args)
            await _verify(periods)
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
        print(f"完成。验证结果: {artifact / 'verify_result.json'}")
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="STF-13 接单未税改为收款日期口径")
    parser.add_argument("--apply", action="store_true", help="更新指标定义并重算（默认动作）")
    parser.add_argument("--rollback", action="store_true", help="恢复最近一次备份并重算")
    parser.add_argument("--check", action="store_true", help="只校验当前结果，不改定义、不重算")
    parser.add_argument("--backup", default=None, help="回滚时指定 metric_def_before.json")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写库、不重算")
    parser.add_argument("--skip-recalc", action="store_true", help="只更新/回滚定义，不重算")
    parser.add_argument("--period", action="append", default=None, help="期间，可重复，如 2026-10")
    parser.add_argument("--period-from", default=None, help="起始期间（含）")
    parser.add_argument("--period-to", default=None, help="结束期间（含）")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
