"""STF-18 / STF-30 折算比例部署脚本（10% -> 18%）。

适用场景：服务器已部署本仓库代码后，一条命令完成「指标定义更新 + 历史指标重算 + 校验」。

常用命令（在仓库根目录执行）：

    python backend/scripts/deploy_stf30_rate.py --apply
    python backend/scripts/deploy_stf30_rate.py --check
    python backend/scripts/deploy_stf30_rate.py --rollback
    python backend/scripts/deploy_stf30_rate.py --apply --dry-run

脚本行为：

1. 从 ``seed_crm_person_metrics.py`` 读取 STF-18/26/27/28/30 的目标定义；
2. 更新前把当前 ``metric_def`` 行备份到 ``backend/artifacts/stf30_rate_<时间>/``；
3. 将 STF-18 的 ``measures.scale`` 改为 0.18，并同步相关口径说明；
4. 重算 STF-18/STF-26/STF-28 及其下游 STF-27/STF-30/STF-37（默认覆盖库中已有期间）；
5. 逐业务员校验 STF-30 = STF-27 - STF-28 - STF-29、STF-18 = STF-17 × 18%、STF-37 = STF-30。

``--rollback`` 会读取最近一次备份并恢复定义，然后重算同样的期间。
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
REPO = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import func, select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

TARGET_SCALE = 0.18
DEF_CODES = [
    "marketing_person_settlement_income",  # STF-18
    "marketing_person_variable_expense_allocation",  # STF-26
    "marketing_person_contribution_margin",  # STF-27
    "marketing_person_fixed_expense_allocation",  # STF-28
    "marketing_person_settlement_profit",  # STF-30
]
RECALC_CODES = [
    "marketing_person_settlement_income",
    "marketing_person_variable_expense_allocation",
    "marketing_person_fixed_expense_allocation",
]
VERIFY_CODES = [
    "marketing_person_external_shipment_net_untaxed",  # STF-17
    "marketing_person_settlement_income",  # STF-18
    "marketing_person_variable_expense_allocation",  # STF-26
    "marketing_person_contribution_margin",  # STF-27
    "marketing_person_fixed_expense_allocation",  # STF-28
    "marketing_person_hq_allocation",  # STF-29
    "marketing_person_settlement_profit",  # STF-30
    "marketing_person_profit_per_capita",  # STF-37
]


def _load_seed_module():
    path = BACKEND / "scripts" / "seed_crm_person_metrics.py"
    spec = importlib.util.spec_from_file_location("seed_crm_person_metrics_deploy", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"无法加载指标定义脚本: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _target_specs() -> dict[str, dict[str, Any]]:
    module = _load_seed_module()
    specs = {item["code"]: item for item in module.METRICS}
    missing = [code for code in DEF_CODES if code not in specs]
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


def _def_snapshot(rows: list[MetricDefModel]) -> list[dict[str, Any]]:
    return [
        {
            "id": row.id,
            "code": row.code,
            "name": row.name,
            "formula": row.formula,
            "measures": row.measures,
            "description": row.description,
        }
        for row in rows
    ]


def _artifact_dir(tag: str) -> Path:
    path = BACKEND / "artifacts" / f"stf30_rate_{tag}"
    path.mkdir(parents=True, exist_ok=True)
    return path


async def _load_defs(db) -> dict[str, MetricDefModel]:
    rows = (await db.execute(select(MetricDefModel).where(MetricDefModel.code.in_(DEF_CODES)))).scalars().all()
    by_code = {row.code: row for row in rows}
    missing = [code for code in DEF_CODES if code not in by_code]
    if missing:
        raise SystemExit(f"metric_def 缺少指标: {missing}")
    return by_code


async def _backup_defs(rows: list[MetricDefModel], tag: str) -> Path:
    out = _artifact_dir(tag)
    path = out / "metric_def_before.json"
    path.write_text(json.dumps(_def_snapshot(rows), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def _apply_defs(dry_run: bool) -> tuple[Path, list[str]]:
    module = _load_seed_module()
    specs = _target_specs()
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    changed: list[str] = []
    async with async_db_session() as db, db.begin():
        by_code = await _load_defs(db)
        backup = await _backup_defs(list(by_code.values()), tag)
        for code in DEF_CODES:
            row = by_code[code]
            item = specs[code]
            target_desc = _description(module, item)
            before_scale = (row.measures or {}).get("scale") if isinstance(row.measures, dict) else None
            after_scale = (item["measures"] or {}).get("scale") if isinstance(item["measures"], dict) else None
            delta = (
                row.name != item["name"]
                or row.formula != item["rule"]
                or row.measures != item["measures"]
                or row.description != target_desc
            )
            print(f"{code} ({row.excel_code}): scale {before_scale} -> {after_scale}")
            if not delta:
                print("  已是最新定义，跳过写入")
                continue
            changed.append(code)
            if dry_run:
                print("  dry-run: 不写入")
                continue
            row.name = item["name"]
            row.formula = item["rule"]
            row.measures = item["measures"]
            row.description = target_desc
    return backup, changed


async def _rollback_defs(backup: Path | None, dry_run: bool) -> Path:
    path = backup or _latest_backup()
    if path is None or not path.exists():
        raise SystemExit("未找到可回滚的 metric_def_before.json")
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    async with async_db_session() as db, db.begin():
        for item in snapshot:
            row = (await db.execute(select(MetricDefModel).where(MetricDefModel.code == item["code"]))).scalars().first()
            if row is None:
                raise SystemExit(f"metric_def 缺少指标: {item['code']}")
            print(f"restore {row.code} ({row.excel_code}): scale={(item['measures'] or {}).get('scale')}")
            if dry_run:
                continue
            row.name = item["name"]
            row.formula = item["formula"]
            row.measures = item["measures"]
            row.description = item["description"]
    return path


def _latest_backup() -> Path | None:
    root = BACKEND / "artifacts"
    if not root.exists():
        return None
    candidates = sorted(root.glob("stf30_rate_*/metric_def_before.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


async def _periods() -> list[str]:
    async with async_db_session() as db:
        row = (await db.execute(select(MetricDefModel).where(MetricDefModel.code == "marketing_person_settlement_profit"))).scalars().first()
        if row is None:
            raise SystemExit("metric_def 缺少 STF-30")
        periods = (
            await db.execute(
                select(MetricValueModel.period_value)
                .where(MetricValueModel.metric_id == row.id, MetricValueModel.period_type == "month")
                .group_by(MetricValueModel.period_value)
                .order_by(MetricValueModel.period_value)
            )
        ).scalars().all()
    return [str(item) for item in periods]


def _run_recalc(periods: list[str], log_path: Path) -> None:
    if not periods:
        raise SystemExit("没有可重算的期间")
    cmd = [
        sys.executable,
        str(BACKEND / "scripts" / "recalc_metrics_batch.py"),
        "--with-dependents",
        "--period-from",
        periods[0],
        "--period-to",
        periods[-1],
        "--log",
        str(log_path),
    ]
    for code in RECALC_CODES:
        cmd.extend(["--code", code])
    print("执行:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(BACKEND), check=True)


async def _load_values(db, metric_id: int, period: str) -> dict[str | None, float]:
    version = (
        await db.execute(
            select(func.max(MetricValueModel.calc_version)).where(
                MetricValueModel.metric_id == metric_id,
                MetricValueModel.period_type == "month",
                MetricValueModel.period_value == period,
            )
        )
    ).scalar()
    rows = (
        await db.execute(
            select(MetricValueModel).where(
                MetricValueModel.metric_id == metric_id,
                MetricValueModel.period_type == "month",
                MetricValueModel.period_value == period,
                MetricValueModel.calc_version == version,
            )
        )
    ).scalars().all()
    return {row.person_code: float(row.value) for row in rows}


async def _verify(periods: list[str]) -> dict[str, Any]:
    max_profit_residual = 0.0
    max_rate_error = 0.0
    max_ratio_error = 0.0
    async with async_db_session() as db:
        defs = (await db.execute(select(MetricDefModel).where(MetricDefModel.code.in_(VERIFY_CODES)))).scalars().all()
        ids = {item.code: item.id for item in defs}
        for period in periods:
            vals = {code: await _load_values(db, ids[code], period) for code in VERIFY_CODES}
            persons = set(vals["marketing_person_settlement_profit"]) - {None}
            for person in persons:
                s17 = vals["marketing_person_external_shipment_net_untaxed"].get(person, 0.0)
                s18 = vals["marketing_person_settlement_income"].get(person, 0.0)
                s26 = vals["marketing_person_variable_expense_allocation"].get(person, 0.0)
                s27 = vals["marketing_person_contribution_margin"].get(person, 0.0)
                s28 = vals["marketing_person_fixed_expense_allocation"].get(person, 0.0)
                s29 = vals["marketing_person_hq_allocation"].get(person, 0.0)
                s30 = vals["marketing_person_settlement_profit"].get(person, 0.0)
                s37 = vals["marketing_person_profit_per_capita"].get(person, 0.0)
                max_profit_residual = max(max_profit_residual, abs(s30 - (s27 - s28 - s29)))
                max_ratio_error = max(max_ratio_error, abs(s37 - s30))
                if abs(s17) > 0.01:
                    max_rate_error = max(max_rate_error, abs(s18 / s17 - TARGET_SCALE))
    result = {
        "periods": len(periods),
        "max_profit_residual": max_profit_residual,
        "max_rate_error": max_rate_error,
        "max_ratio_error": max_ratio_error,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if max_profit_residual > 1e-6 or max_rate_error > 1e-7 or max_ratio_error > 1e-6:
        raise SystemExit("校验失败：结果与公式不一致")
    return result


async def _run(args) -> None:
    try:
        if args.check:
            periods = await _periods()
            await _verify(periods)
            return

        if args.rollback:
            backup = await _rollback_defs(Path(args.backup) if args.backup else None, args.dry_run)
            print(f"已使用备份: {backup}")
        else:
            backup, changed = await _apply_defs(args.dry_run)
            print(f"备份: {backup}")
            print(f"定义变更: {changed or '无（已是 18% 口径）'}")

        if args.dry_run:
            print("dry-run 完成，未重算")
            return
        if args.skip_recalc:
            print("已跳过重算")
            return

        periods = await _periods()
        artifact = backup.parent
        _run_recalc(periods, artifact / "recalc.log")
        result = await _verify(periods)
        (artifact / "verify_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"完成。验证结果: {artifact / 'verify_result.json'}")
    finally:
        await async_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="STF-18/STF-30 10% -> 18% 部署脚本")
    parser.add_argument("--apply", action="store_true", help="更新指标定义并重算（默认动作）")
    parser.add_argument("--rollback", action="store_true", help="恢复最近一次备份并重算")
    parser.add_argument("--check", action="store_true", help="只校验当前结果，不改定义、不重算")
    parser.add_argument("--backup", default=None, help="回滚时指定 metric_def_before.json")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写库、不重算")
    parser.add_argument("--skip-recalc", action="store_true", help="只更新/回滚定义，不重算")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
