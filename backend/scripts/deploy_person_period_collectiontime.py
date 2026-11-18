"""业务员业绩指标改为收款日期口径（收款日期为空时回退建单月）。

在服务器 ``backend/`` 目录、已激活 conda 环境后执行：

    python scripts/deploy_person_period_collectiontime.py --dry-run
    python scripts/deploy_person_period_collectiontime.py --apply --period 2026-11
    python scripts/deploy_person_period_collectiontime.py --check --period 2026-11
    python scripts/deploy_person_period_collectiontime.py --rollback

脚本行为：

1. 从 ``seed_crm_person_metrics.py`` 读取 7 个目标指标定义；
2. 发布新的 ``metric_def_version`` 快照并递增 ``metric_def.version``：
   只改 ``metric_def`` 不会生效，引擎会优先读取该版本号对应的旧快照；
3. 把本次重算期间的 ``metric_period_version`` 钉到新版本（``--no-repin`` 可跳过）；
4. 用 ``recalc_metrics_batch.py --rule-mode current --with-dependents`` 重算；
5. 校验定义、版本快照、期间指针、公司合计与业务员合计。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from sqlalchemy import delete, func, select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import (  # noqa: E402
    MetricDefModel,
    MetricDefVersionModel,
    MetricPeriodVersionModel,
    MetricValueModel,
)
from app.modules.metric.versions import snapshot_from_metric  # noqa: E402
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
        "version_before": int(row.version or 1),
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


async def _versions(db, metric_id: int) -> list[MetricDefVersionModel]:
    return list(
        (
            await db.execute(
                select(MetricDefVersionModel)
                .where(MetricDefVersionModel.metric_id == metric_id)
                .order_by(MetricDefVersionModel.version)
            )
        ).scalars().all()
    )


async def _apply(dry_run: bool, effective_from: date) -> tuple[Path, bool, dict[str, int]]:
    module = _load_seed_module()
    specs = _target_specs()
    tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = _artifact_dir(tag)
    backup = out / "metric_def_before.json"
    any_changed = False
    current_versions: dict[str, int] = {}
    async with async_db_session() as db, db.begin():
        rows = await _get_rows(db)
        snapshots = []
        for code in CODES:
            row = rows[code]
            item = specs[code]
            target_desc = _description(module, item)
            versions = await _versions(db, row.id)
            max_version = max((int(v.version) for v in versions), default=0)
            latest = versions[-1] if versions else None
            def_matches = (
                row.name == item["name"]
                and row.formula == item["rule"]
                and _measures(row) == item["measures"]
                and row.description == target_desc
            )
            snapshot_matches = (
                latest is not None
                and int(latest.version) == int(row.version or 1)
                and latest.formula == item["rule"]
                and dict(latest.measures or {}) == item["measures"]
            )
            need_publish = not (def_matches and snapshot_matches)
            any_changed = any_changed or need_publish
            snap = _snapshot(row)
            snap["max_def_version_before"] = max_version
            print(
                f"{code}: def_version={row.version} latest_snapshot={max_version} "
                f"need_publish={need_publish}"
            )
            if need_publish and not dry_run:
                if max_version == 0:
                    # 兼容没有版本快照的库：先把当前行钉成基线版本
                    base_version = int(row.version or 1)
                    base = snapshot_from_metric(row)
                    base.pop("metric_id", None)
                    base.pop("version", None)
                    db.add(
                        MetricDefVersionModel(
                            metric_id=row.id,
                            version=base_version,
                            effective_from=date(1970, 1, 1),
                            **base,
                        )
                    )
                    max_version = base_version
                    latest = None
                    await db.flush()
                new_version = max(max_version, int(row.version or 1)) + 1
                previous = latest
                if previous is None:
                    previous = (
                        await db.execute(
                            select(MetricDefVersionModel).where(
                                MetricDefVersionModel.metric_id == row.id,
                                MetricDefVersionModel.version == max_version,
                            )
                        )
                    ).scalars().first()
                if previous is not None:
                    previous.effective_to = effective_from - timedelta(days=1)
                merged = snapshot_from_metric(row)
                merged.pop("metric_id", None)
                merged.pop("version", None)
                merged.update(
                    {
                        "name": item["name"],
                        "formula": item["rule"],
                        "measures": item["measures"],
                        "description": target_desc,
                    }
                )
                db.add(
                    MetricDefVersionModel(
                        metric_id=row.id,
                        version=new_version,
                        effective_from=effective_from,
                        **merged,
                    )
                )
                row.name = item["name"]
                row.formula = item["rule"]
                row.measures = item["measures"]
                row.description = target_desc
                row.version = new_version
                snap["new_version"] = new_version
            current_versions[code] = int(snap.get("new_version") or row.version or 1)
            snapshots.append(snap)
        if any_changed and not dry_run:
            backup.write_text(
                json.dumps(
                    {
                        "generated_at": datetime.now().isoformat(timespec="seconds"),
                        "effective_from": effective_from.isoformat(),
                        "metrics": snapshots,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            print(f"备份: {backup}")
    return backup, any_changed, current_versions


async def _repin(periods: list[str], versions: dict[str, int], dry_run: bool) -> None:
    if dry_run:
        return
    async with async_db_session() as db, db.begin():
        rows = await _get_rows(db)
        for code, version in versions.items():
            row = rows[code]
            for period in periods:
                pointer = (
                    await db.execute(
                        select(MetricPeriodVersionModel).where(
                            MetricPeriodVersionModel.metric_id == row.id,
                            MetricPeriodVersionModel.period_type == "month",
                            MetricPeriodVersionModel.period_value == period,
                        )
                    )
                ).scalars().first()
                if pointer is None:
                    db.add(
                        MetricPeriodVersionModel(
                            metric_id=row.id,
                            period_type="month",
                            period_value=period,
                            pinned_def_version=int(version),
                            active_def_version=int(version),
                            last_calc_version=1,
                            last_rule_mode="historical",
                        )
                    )
                else:
                    pointer.pinned_def_version = int(version)
                    pointer.active_def_version = int(version)
    print(f"期间口径已钉到新版本: {len(periods)} 个期间 x {len(versions)} 个指标")


async def _rollback(backup: Path | None, dry_run: bool) -> tuple[Path, dict[str, int]]:
    path = backup or _latest_backup()
    if path is None or not path.exists():
        raise SystemExit("未找到可回滚的 metric_def_before.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    snapshots = raw.get("metrics") if isinstance(raw, dict) else raw
    versions_before: dict[str, int] = {}
    async with async_db_session() as db, db.begin():
        rows = await _get_rows(db)
        for snap in snapshots:
            row = rows[snap["code"]]
            version_before = int(snap.get("version_before") or row.version or 1)
            max_before = int(snap.get("max_def_version_before") or 0)
            print(
                f"restore {snap['code']}: period_field="
                f"{(snap.get('measures') or {}).get('period_field')} "
                f"version={row.version}->{version_before}"
            )
            versions_before[snap["code"]] = version_before
            if not dry_run:
                row.name = snap["name"]
                row.formula = snap["formula"]
                row.measures = snap["measures"]
                row.description = snap["description"]
                row.version = version_before
                if max_before:
                    await db.execute(
                        delete(MetricDefVersionModel).where(
                            MetricDefVersionModel.metric_id == row.id,
                            MetricDefVersionModel.version > max_before,
                        )
                    )
    return path, versions_before


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


def _run_recalc(periods: list[str], log_path: Path, rule_mode: str) -> None:
    cmd = [sys.executable, str(BACKEND / "scripts" / "recalc_metrics_batch.py")]
    for code in CODES:
        cmd.extend(["--code", code])
    cmd.extend(["--with-dependents", "--rule-mode", rule_mode])
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
            versions = await _versions(db, row.id)
            latest = versions[-1] if versions else None
            if latest is None:
                errors.append(f"{code}: 没有 metric_def_version 快照")
            else:
                if int(latest.version) != int(row.version or 1):
                    errors.append(
                        f"{code}: metric_def.version={row.version}，"
                        f"最新快照={latest.version}"
                    )
                if dict(latest.measures or {}) != config:
                    errors.append(f"{code}: 最新快照 measures 与 metric_def 不一致")
            is_customer_count = config.get("value_mode") == "count_customers"
            per_period: dict[str, Any] = {}
            for period in periods:
                pointer = (
                    await db.execute(
                        select(
                            MetricPeriodVersionModel.pinned_def_version,
                            MetricPeriodVersionModel.active_def_version,
                        ).where(
                            MetricPeriodVersionModel.metric_id == row.id,
                            MetricPeriodVersionModel.period_type == "month",
                            MetricPeriodVersionModel.period_value == period,
                        )
                    )
                ).first()
                if pointer is None:
                    errors.append(f"{code} {period}: 缺少 metric_period_version")
                else:
                    pinned, active = int(pointer[0]), int(pointer[1])
                    if pinned != int(row.version or 1) or active != int(row.version or 1):
                        errors.append(
                            f"{code} {period}: pinned/active={pinned}/{active}，"
                            f"期望 {row.version}"
                        )
                version = (
                    await db.execute(
                        select(func.max(MetricValueModel.calc_version)).where(
                            MetricValueModel.metric_id == row.id,
                            MetricValueModel.period_type == "month",
                            MetricValueModel.period_value == period,
                            MetricValueModel.version == int(row.version or 1),
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
                            MetricValueModel.version == int(row.version or 1),
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
                    "def_version": int(row.version or 1),
                    "company": round(company, 4),
                    "person_sum": round(person_sum, 4),
                    "residual": residual,
                }
                if is_customer_count:
                    if company > person_sum + 0.01:
                        errors.append(f"{code} {period}: 公司合计 > 业务员合计")
                elif abs(residual) > 0.01:
                    errors.append(f"{code} {period}: 公司合计与业务员合计差 {residual}")
            result["metrics"][code] = per_period
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


async def _run(args) -> None:
    try:
        effective_from = date.fromisoformat(args.effective_from)
        if args.check:
            periods = await _periods(args)
            result = await _verify(periods)
            if result["errors"]:
                raise SystemExit("校验失败")
            return

        if args.rollback:
            backup, versions = await _rollback(
                Path(args.backup) if args.backup else None, args.dry_run
            )
            print(f"已使用备份: {backup}")
            rule_mode = "historical"
        else:
            backup, changed, versions = await _apply(args.dry_run, effective_from)
            print(f"定义变更: {'有' if changed else '无'}")
            rule_mode = "current"

        if args.dry_run:
            print("dry-run 完成，未写库、未重算")
            return
        if args.skip_recalc:
            print("已跳过重算")
            return

        periods = await _periods(args)
        if not args.no_repin:
            await _repin(periods, versions, args.dry_run)
        artifact = backup.parent
        log_path = artifact / "recalc.log"
        _run_recalc(periods, log_path, rule_mode)
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
    parser.add_argument("--apply", action="store_true", help="发布新版本并重算（默认动作）")
    parser.add_argument("--rollback", action="store_true", help="恢复最近一次备份并重算")
    parser.add_argument("--check", action="store_true", help="只校验当前定义与结果")
    parser.add_argument("--backup", default=None, help="回滚时指定 metric_def_before.json")
    parser.add_argument("--dry-run", action="store_true", help="只打印变更，不写库、不重算")
    parser.add_argument("--skip-recalc", action="store_true", help="只发布/回滚定义，不重算")
    parser.add_argument(
        "--no-repin",
        action="store_true",
        help="不把重算期间的 pinned/active 口径切到新版本（保留历史钉版）",
    )
    parser.add_argument("--effective-from", default="2026-11-01", help="新口径生效日")
    parser.add_argument("--period", action="append", default=None, help="期间，可重复")
    parser.add_argument("--period-from", default=None, help="起始期间（含）")
    parser.add_argument("--period-to", default=None, help="结束期间（含）")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
