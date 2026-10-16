"""校验「存货收发存汇总表（全仓·全物料）」数据接入：金蝶实时取数（基线） vs 落库批次（接入后）。

两侧用**同一份请求参数与同一套汇总规则**：

- 汇总规则与指标引擎 ``extract_inventory_ledger`` 一致：跳过小计行（物料编码以 ``-总计`` 结尾）
  与仓库为空的行，明细行求和；
- 基线（BASELINE）= 实时直连金蝶 ``GetSysReportData`` 分页取全量后汇总；
- 接入后（MODIFIED）= 读 ``meta_sync_run.rows_json``（该数据源当日同步批次）汇总。

输出：

1. 行数（总行 / 明细行 / 小计行）与 12 个数量·单价·金额列的合计；
2. **库存结存成本** = 期末结存金额 ``FENDAmount`` 合计、期末结存数量 ``FENDQty`` 合计；
3. **物料成本** = 期末结存单价 ``FENDPrice``（按期末结存金额 Top N 明细，附 数量×单价≈金额 校验）；
4. 基线 vs 落库的逐项差异（差异为 0 才算通过，退出码 0/1）。

用法：
    python scripts/check_inventory_inout_summary.py --period 2026-09
    python scripts/check_inventory_inout_summary.py --period 2026-09 --check-period-column
    python scripts/check_inventory_inout_summary.py --period 2026-09 --skip-live   # 只看落库批次
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
INI_PATH = PROJECT_ROOT / "env" / "kindee_conf.ini"
ENV_PATH = PROJECT_ROOT / "env" / ".env.dev"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
# 声明式常量与本脚本同目录；直接运行脚本时目录已在 sys.path，用 importlib 加载时需要显式补上
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from seed_inventory_inout_summary_full import (  # noqa: E402
    ENV_PATH as _ENV_PATH,
)
from seed_inventory_inout_summary_full import (  # noqa: E402
    FORM_ID,
    REQUEST_PARAMS,
    SYNC_JOB_NAME,
    load_env_file,
)

from app.modules.erp.kingdee.client import KingdeeClient  # noqa: E402
from app.modules.metadata.sync import (  # noqa: E402
    fetch_report_data,
    render_request_params,
    resolve_period_datetime,
)

SUBTOTAL_SUFFIX = "-总计"
AMOUNT_COLUMNS = ["FINITAMOUNT", "FRECEIVEAmount", "FSENDAmount", "FENDAmount"]
QTY_COLUMNS = ["FINITQty", "FRECEIVEQty", "FSENDQty", "FENDQty"]
PRICE_COLUMNS = ["FINITPrice", "FRECEIVEPrice", "FSENDPrice", "FENDPrice"]
HIGHLIGHT_COLUMNS = QTY_COLUMNS + PRICE_COLUMNS + AMOUNT_COLUMNS


def to_number(value) -> float:
    text = str(value if value is not None else "").strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def aggregate(rows: list, fields: list[str]) -> dict:
    """按指标引擎同一规则汇总：跳过小计行与仓库为空的行。"""
    index = {field: position for position, field in enumerate(fields)}
    totals = dict.fromkeys(HIGHLIGHT_COLUMNS, 0.0)
    non_null = dict.fromkeys(HIGHLIGHT_COLUMNS, 0)
    detail_rows = 0
    subtotal_rows = 0
    rows_without_stock = 0
    details: list[dict] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        material = str(row[index["FMATERIALBASEID"]] or "") if "FMATERIALBASEID" in index else ""
        if material.endswith(SUBTOTAL_SUFFIX):
            subtotal_rows += 1
            continue
        stock = str(row[index["FSTOCKId"]] or "") if "FSTOCKId" in index else ""
        if not stock.strip():
            rows_without_stock += 1
            continue
        detail_rows += 1
        for field in HIGHLIGHT_COLUMNS:
            value = row[index[field]] if index.get(field) is not None and index[field] < len(row) else None
            if str(value if value is not None else "").strip():
                non_null[field] += 1
            totals[field] += to_number(value)
        details.append(
            {
                "material": material,
                "name": str(row[index["FMATERIALNAME"]] or ""),
                "group": str(row[index["FMATERIALGROUP"]] or ""),
                "model": str(row[index["FMODEL"]] or ""),
                "stock": stock,
                "end_qty": to_number(row[index["FENDQty"]]),
                "end_price": to_number(row[index["FENDPrice"]]),
                "end_amount": to_number(row[index["FENDAmount"]]),
            }
        )
    return {
        "rows": len(rows),
        "detail_rows": detail_rows,
        "subtotal_rows": subtotal_rows,
        "rows_without_stock": rows_without_stock,
        "totals": totals,
        "non_null": non_null,
        "details": details,
    }


def print_side(tag: str, stat: dict) -> None:
    print(f"\n--- {tag} ---")
    print(
        f"行数 总={stat['rows']} 明细={stat['detail_rows']} "
        f"小计={stat['subtotal_rows']} 无仓库={stat['rows_without_stock']}"
    )
    for field in HIGHLIGHT_COLUMNS:
        print(f"  {field:<16} 合计={stat['totals'][field]:>18,.4f}  非空行={stat['non_null'][field]}")


def diff_side(baseline: dict, modified: dict) -> list[str]:
    problems: list[str] = []
    for key in ("rows", "detail_rows", "subtotal_rows"):
        if baseline[key] != modified[key]:
            problems.append(f"{key}: 基线 {baseline[key]} ≠ 落库 {modified[key]}")
    for field in HIGHLIGHT_COLUMNS:
        delta = round(baseline["totals"][field] - modified["totals"][field], 4)
        if abs(delta) > 1e-6:
            problems.append(f"{field} 合计差异 {delta}")
    return problems


def top_material_cost(stat: dict, limit: int) -> None:
    """物料成本（期末结存单价）按期末结存金额 Top N 展示，并校验 数量×单价≈金额。"""
    picks = sorted(stat["details"], key=lambda item: item["end_amount"], reverse=True)[:limit]
    print(f"\n--- 物料成本（期末结存单价 FENDPrice）Top {limit}，按期末结存金额排序 ---")
    print(f"{'物料编码':<16}{'名称':<14}{'分组':<10}{'规格':<12}{'仓库':<12}{'期末数量':>12}{'期末单价':>14}{'期末金额':>16}  数量×单价")
    for item in picks:
        check = item["end_qty"] * item["end_price"]
        flag = "" if abs(check - item["end_amount"]) < 0.02 else f"  ← 与金额差 {check - item['end_amount']:.4f}"
        print(
            f"{item['material']:<16}{item['name'][:12]:<14}{item['group'][:8]:<10}{item['model'][:10]:<12}"
            f"{item['stock'][:10]:<12}{item['end_qty']:>12,.4f}{item['end_price']:>14,.4f}{item['end_amount']:>16,.2f}{flag}"
        )


def load_batch(job_name: str, period: str) -> dict:
    """读落库批次：任务参数（字段顺序）与该期间最新一次成功批次。"""
    import pymysql

    env = load_env_file(_ENV_PATH)
    connection = pymysql.connect(
        host=env.get("DATABASE_HOST", "localhost"),
        port=int(env.get("DATABASE_PORT", "3306")),
        user=env.get("DATABASE_USER", "root"),
        password=env.get("DATABASE_PASSWORD", ""),
        database=env.get("DATABASE_NAME", "fastapiadmin"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "select j.id job_id, j.request_params, j.variables, o.variables object_variables "
                "from meta_sync_job j join meta_source_object o on o.id = j.source_object_id "
                "where j.name = %s",
                (job_name,),
            )
            job = cursor.fetchone()
            if job is None:
                raise SystemExit(f"同步任务不存在：{job_name}（先跑 seed_inventory_inout_summary_full.py）")
            cursor.execute(
                "select id, batch_id, status, row_count, period_value, started_at, finished_at "
                "from meta_sync_run where job_id = %s and period_value = %s and status = 'success' "
                "order by id desc limit 1",
                (job["job_id"], period),
            )
            run = cursor.fetchone()
            if run is not None:
                # rows_json 单批可达 10MB：按主键单独取，避免小 sort buffer 下 filesort 报
                # 「Out of sort memory」（同一查询里带大 JSON 列排序会踩这个坑）
                cursor.execute("select rows_json from meta_sync_run where id = %s", (run["id"],))
                payload_row = cursor.fetchone()
                run["rows_json"] = payload_row["rows_json"] if payload_row else None
    finally:
        connection.close()
    if run is None:
        raise SystemExit(f"没有 {period} 的成功批次：{job_name}（先执行 run_meta_sync.py --job-id … --period {period}）")
    request_params = job["request_params"]
    if isinstance(request_params, str):
        request_params = json.loads(request_params)
    payload = run["rows_json"]
    if isinstance(payload, (str, bytes)):
        payload = json.loads(payload)
    meta = {
        "job_id": job["job_id"],
        "run_id": run["id"],
        "batch_id": run["batch_id"],
        "row_count": run["row_count"],
        "started_at": run["started_at"],
        "finished_at": run["finished_at"],
        "period_value": run["period_value"],
    }
    return {"request_params": request_params, "rows": payload.get("Rows") or [], "meta": meta}


def render_params(period: str) -> dict:
    now = resolve_period_datetime(period)
    variables = [
        {"name": "year", "value_type": "expression", "value": "now.strftime('%Y')"},
        {"name": "period", "value_type": "expression", "value": "now.strftime('%m')"},
    ]
    return render_request_params(REQUEST_PARAMS, "100", variables, now=now)


async def live_rows(period: str, params: dict | None = None) -> tuple[list, dict]:
    client = KingdeeClient.from_ini(INI_PATH)
    payload = params or render_params(period)
    report = await fetch_report_data(client, FORM_ID, payload)
    return report.get("Rows") or [], payload


async def main() -> int:
    parser = argparse.ArgumentParser(description="校验存货收发存汇总表（全仓·全物料）数据接入")
    parser.add_argument("--period", default=datetime.now().strftime("%Y-%m"), help="取数期间 YYYY-MM")
    parser.add_argument("--job-name", default=SYNC_JOB_NAME, help="同步任务名称")
    parser.add_argument("--top", type=int, default=8, help="物料成本展示条数")
    parser.add_argument("--skip-live", action="store_true", help="跳过金蝶实时基线（只看落库批次）")
    parser.add_argument(
        "--check-period-column",
        action="store_true",
        help="额外比一次「不显示各期间明细」（20 列）与「显示各期间明细」（21 列）的汇总是否一致",
    )
    args = parser.parse_args()

    batch = load_batch(args.job_name, args.period)
    fields = [item.strip() for item in str(batch["request_params"].get("FieldKeys") or "").split(",") if item.strip()]
    modified = aggregate(batch["rows"], fields)
    meta = batch["meta"]
    duration = ""
    if isinstance(meta["started_at"], datetime) and isinstance(meta["finished_at"], datetime):
        duration = f"，耗时 {(meta['finished_at'] - meta['started_at']).total_seconds():.1f}s"
    print(
        f"\n=== 落库批次（MODIFIED）任务={args.job_name} 期间={args.period} "
        f"run_id={meta['run_id']} batch={meta['batch_id']} row_count={meta['row_count']}{duration} ==="
    )
    print(f"FieldKeys（{len(fields)} 列）：{','.join(fields)}")
    print_side("落库批次汇总", modified)
    print(f"\n库存结存成本（期末结存金额 FENDAmount 合计）= {modified['totals']['FENDAmount']:,.2f}")
    print(f"库存结存数量（期末结存数量 FENDQty 合计）  = {modified['totals']['FENDQty']:,.4f}")
    top_material_cost(modified, args.top)

    problems: list[str] = []
    if not args.skip_live:
        rows, payload = await live_rows(args.period)
        baseline = aggregate(rows, fields)
        print(f"\n=== 金蝶实时取数（BASELINE）期间={args.period} 组织={payload['Model']['FACCTGORGID']['FNumber']} ===")
        print_side("金蝶实时汇总", baseline)
        problems.extend(diff_side(baseline, modified))
        if args.check_period_column:
            plain_fields = [field for field in fields if field != "FYearPeriod"]
            plain_params = json.loads(json.dumps(payload))
            plain_params["FieldKeys"] = ",".join(plain_fields)
            plain_params["Model"]["FIsDisplayPeriod"] = False
            plain_rows, _ = await live_rows(args.period, plain_params)
            plain = aggregate(plain_rows, plain_fields)
            print_side("金蝶实时汇总（20 列，FIsDisplayPeriod=false）", plain)
            problems.extend([f"20 列 vs 21 列：{item}" for item in diff_side(plain, modified)])

    print("\n=== 结论 ===")
    if problems:
        for item in problems:
            print(f"差异：{item}")
        print(f"校验不通过：{len(problems)} 项差异")
        return 1
    if args.skip_live:
        print("（--skip-live：未比对金蝶实时基线，仅确认落库批次可读且汇总规则可跑通）")
        return 0
    print("基线（金蝶实时）与接入后（落库批次）逐项一致，差异 0")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
