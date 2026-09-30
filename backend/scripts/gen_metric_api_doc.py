"""生成《指标接口清单与调用方案》文档（供外部系统 / AI 读取）。

指标清单直接读数据库 `metric_def`，因此**新增指标后重跑本脚本即可更新文档**：

    cd backend
    python scripts/gen_metric_api_doc.py
    python scripts/gen_metric_api_doc.py --base-url https://data.example.com   # 指定对外域名
    python scripts/gen_metric_api_doc.py --output ../docs/指标接口清单与调用方案.md

文档面向外部对接方与大模型阅读：结构化表格 + 明确字段约束 + 可直接照抄的请求示例。
"""

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.modules.metric.units import resolve_metric_unit  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

DEFAULT_OUTPUT = PROJECT_ROOT.parent / "docs" / "指标接口清单与调用方案.md"
PERIOD_TYPE_CN = {"day": "日", "week": "周", "month": "月", "year": "年"}


def _cell(value: Any) -> str:
    """表格单元格转义：换行与竖线会让 Markdown 表格错位。"""
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


async def _load_metrics() -> list[dict[str, Any]]:
    async with async_db_session() as db:
        metrics = (
            (
                await db.execute(
                    select(MetricDefModel)
                    .where(MetricDefModel.is_deleted == False)  # noqa: E712
                    .order_by(MetricDefModel.id.asc())
                )
            )
            .scalars()
            .all()
        )
        stats_rows = (
            await db.execute(
                select(
                    MetricValueModel.metric_id,
                    func.min(MetricValueModel.period_value).label("min_period"),
                    func.max(MetricValueModel.period_value).label("max_period"),
                    func.count(func.distinct(MetricValueModel.period_value)).label("period_count"),
                    func.max(MetricValueModel.calc_time).label("last_calc_time"),
                ).group_by(MetricValueModel.metric_id)
            )
        ).all()
        stats = {row.metric_id: row for row in stats_rows}

        result: list[dict[str, Any]] = []
        for metric in metrics:
            row = stats.get(metric.id)
            dimensions = metric.dimensions or {}
            dims = list(dimensions.keys()) if isinstance(dimensions, dict) else []
            has_org_dim = bool(dimensions.get("org", True)) if isinstance(dimensions, dict) else True
            result.append(
                {
                    "code": metric.code,
                    "name": metric.name,
                    "excel_code": metric.excel_code,
                    "period_type": metric.period_type,
                    "status": int(metric.status or 0),
                    "unit": resolve_metric_unit(metric.name, metric.measures),
                    "dimensions": dims,
                    "has_org_dim": has_org_dim,
                    "description": metric.description,
                    "min_period": getattr(row, "min_period", None),
                    "max_period": getattr(row, "max_period", None),
                    "period_count": getattr(row, "period_count", 0) or 0,
                    "last_calc_time": getattr(row, "last_calc_time", None),
                }
            )
        return result


def _period_hint(period_type: str) -> str:
    return {"day": "2026-09-28", "week": "2026-W39", "month": "2026-09", "year": "2026"}.get(period_type, "2026-09")


def _render(metrics: list[dict[str, Any]], base_url: str) -> str:
    enabled = [m for m in metrics if m["status"] == 0]
    disabled = [m for m in metrics if m["status"] != 0]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = []
    add = lines.append
    add("# 核算指标接口清单与调用方案")
    add("")
    add(f"> 文档生成时间：{now}（**由 `backend/scripts/gen_metric_api_doc.py` 从数据库自动生成，请勿手工修改**）")
    add(f"> 对外服务地址：`{base_url}`")
    add(f"> 当前可读指标：{len(enabled)} 个（停用 {len(disabled)} 个不对外）")
    add("")
    add("## AI 阅读指引")
    add("")
    add("1. 调用任何接口前先执行「第 2 节：获取令牌」，拿到 `access_token` 并在后续请求头带 `Authorization: Bearer <token>`。")
    add("2. 指标标识**只能取自第 5 节清单**（系统指标编码或 Excel 科目编码），不得自行编造；清单里没有的标识会返回 `errors`（指标不存在）。")
    add("3. 只想拿一个总数 → 「第 4.4 节：只取合计」；要按组织拆分 → 第 4.3 节。")
    add("4. 判断成功看响应体 `code == 0`（不是 HTTP 200 以外的值），失败原因见第 6 节错误码。")
    add("5. 数值保留 4 位小数；单位见第 5 节（元 / 次 / % / 天）；只返回存在的行，缺失期间按 0 处理。")
    add("6. 第 5 节标注「组织维度=无」的指标不要传 `org_codes`，否则会被过滤成空结果。")
    add("7. 返回的每行都同时带 `metric_code`（系统编码）与 `excel_code`（财务 Excel 科目编码），可直接与财务底稿对账。")
    add("")
    add("---")
    add("")
    add("## 1. 接入三步")
    add("")
    add("1. 向管理员申请：拿到 `app_id`、`app_secret`（密钥仅下发一次，请妥善保管）。")
    add("2. 换令牌：`POST /open/v1/auth/token`，响应 `data.access_token` 即令牌（默认有效期 7200 秒）。")
    add("3. 取数：`POST /open/v1/metrics/query`，请求头带令牌。")
    add("")
    add("```bash")
    add(f'# 1) 换令牌（{base_url}）')
    add(f'curl -X POST "{base_url}/open/v1/auth/token" \\')
    add('  -H "Content-Type: application/json" \\')
    add('  -d \'{"app_id":"<你的app_id>","app_secret":"<你的app_secret>"}\'')
    add("")
    add("# 2) 取某个指标的当月合计")
    add(f'curl -X POST "{base_url}/open/v1/metrics/query" \\')
    add('  -H "Content-Type: application/json" \\')
    add('  -H "Authorization: Bearer <access_token>" \\')
    add('  -d \'{"metrics":["marketing_office_expense"],"total_only":true}\'')
    add("```")
    add("")
    add("---")
    add("")
    add("## 2. 获取令牌")
    add("")
    add("- 方法：`POST`，路径：`/open/v1/auth/token`，请求头：`Content-Type: application/json`")
    add("")
    add("请求体：")
    add("")
    add("```json")
    add('{ "app_id": "<app_id>", "app_secret": "<app_secret>" }')
    add("```")
    add("")
    add("响应：")
    add("")
    add("```json")
    add("{")
    add('  "code": 0,')
    add('  "msg": "获取令牌成功",')
    add('  "success": true,')
    add('  "status_code": 200,')
    add('  "data": { "access_token": "eyJ...", "token_type": "Bearer", "expires_in": 7200 }')
    add("}")
    add("```")
    add("")
    add("| 响应字段 | 类型 | 说明 |")
    add("|---|---|---|")
    add("| `data.access_token` | string | 访问令牌，放入 `Authorization: Bearer <token>` |")
    add("| `data.expires_in` | int | 有效期（秒），过期或收到 `40100` 时重新获取 |")
    add("| `data.token_type` | string | 固定为 `Bearer` |")
    add("")
    add("---")
    add("")
    add("## 3. 接口清单")
    add("")
    add("| 方法 | 路径 | 用途 | 需要令牌 |")
    add("|---|---|---|---|")
    add("| POST | `/open/v1/auth/token` | 应用凭证换访问令牌 | 否 |")
    add("| GET | `/open/v1/metrics` | 查询可读指标目录（编码、名称、期间类型、口径说明） | 是 |")
    add("| POST | `/open/v1/metrics/query` | 批量取数（主接口，支持合计/明细、长表/宽表） | 是 |")
    add("| GET | `/open/v1/orgs` | 查询可见组织字典（编码、名称、上级、层级） | 是 |")
    add("| POST | `/open/v1/metrics/{code}/run` | 触发指标重算（默认未开放，需管理员开启） | 是 |")
    add("")
    add("所有业务接口前缀固定为 `/open/v1`，响应体统一为 `{code, msg, data, success, status_code}`。")
    add("")
    add("---")
    add("")
    add("## 4. 取数接口 `POST /open/v1/metrics/query`")
    add("")
    add("### 4.1 请求字段")
    add("")
    add("| 字段 | 类型 | 必填 | 默认 | 说明 |")
    add("|---|---|---|---|---|")
    add("| `metrics` | string[] | 是 | - | 指标标识数组，单次上限 20 个；可传系统指标编码（`marketing_office_expense`）或 Excel 科目编码（`EXP-01-a`），均见第 5 节 |")
    add("| `period_type` | string | 否 | `month` | `month` / `day` / `week` / `year`，须与指标的期间类型一致 |")
    add("| `period_start` | string | 否 | 当前期间 | 起始期间（含）；月 `2026-09`、日 `2026-09-28`、年 `2026` |")
    add("| `period_end` | string | 否 | 同 `period_start` | 结束期间（含）；单次跨度上限：月 36、日 366、年 10 |")
    add("| `org_codes` | string[] | 否 | 授权范围内全部组织 | 组织编码，例如 `[\"100\",\"101\"]`；编码见 `/open/v1/orgs` |")
    add("| `level` | string | 否 | `org` | `org` 组织合计行；`dept` 核算维度明细行；`all` 全部（后两者需应用开通明细权限） |")
    add("| `format` | string | 否 | `long` | `long` 长表（一行一个指标×期间×组织）；`wide` 宽表（指标做列） |")
    add("| `total_only` | bool | 否 | `false` | `true` 只返回合计：结果在 `totals`，`items` 为空 |")
    add("| `include_meta` | bool | 否 | `true` | 是否返回指标名称、单位、口径说明 |")
    add("")
    add("### 4.2 响应字段")
    add("")
    add("| 字段 | 类型 | 说明 |")
    add("|---|---|---|")
    add("| `code` | int | `0` 表示成功，其它值见第 6 节 |")
    add("| `data.items` | object[] | 明细行（长表）；`total_only=true` 时为空数组 |")
    add("| `data.totals` | object[] | 合计行（仅 `total_only=true`）：`metric_code`/`period_value`/`value`/`org_count`/`calc_time` |")
    add("| `data.rows` | object[] | 宽表行（仅 `format=wide`） |")
    add("| `data.metrics` | object[] | 本次请求指标的元信息（`code`/`name`/`excel_code`/`period_type`/`unit`/`dimensions`/`description`） |")
    add("| `data.errors` | object[] | 不可读的指标及原因（如「指标不存在」「指标已停用」） |")
    add("| `data.summary` | object | 汇总：`metric_count`/`item_count`/`period_count`/`org_count`/`total` |")
    add("")
    add("指标元信息字段（`data.metrics[]`）：")
    add("")
    add("| 字段 | 类型 | 说明 |")
    add("|---|---|---|")
    add("| `code` | string | 系统指标编码，用于 `metrics` 入参 |")
    add("| `name` | string | 指标名称 |")
    add("| `excel_code` | string | **Excel 科目编码**（财务底稿编码，如 `EXP-01-a`）；无对应编码时为 `null` |")
    add("| `period_type` | string | 期间类型 `month`/`day`/`week`/`year` |")
    add("| `unit` | string | 单位：元 / 次 / % / 天 |")
    add("| `dimensions` | string[] | 维度配置键（如 `org`、`dept`） |")
    add("| `description` | string | 口径说明 |")
    add("")
    add("明细行字段：")
    add("")
    add("| 字段 | 类型 | 说明 |")
    add("|---|---|---|")
    add("| `metric_code` | string | 指标编码 |")
    add("| `metric_name` | string | 指标名称（`include_meta=true` 时返回） |")
    add("| `excel_code` | string | **Excel 科目编码**（如 `EXP-01-a`），与财务底稿对账用 |")
    add("| `period_value` | string | 期间值，如 `2026-09` |")
    add("| `org_code` / `org_name` | string | 组织编码与名称；未映射组织的行可能为 `null` |")
    add("| `dept_code` / `dept_name` | string | 核算维度（部门/客户）；`level=org` 时恒为 `null` |")
    add("| `value` | number | 指标值（单位见 `data.metrics[].unit`，4 位小数） |")
    add("| `calc_version` | int | 计算版本，接口默认只返回最新版本 |")
    add("| `calc_time` | string | 该值计算时间 `YYYY-MM-DD HH:MM:SS`，用于判断数据新鲜度 |")
    add("| `batch_id` | string | 取数批次号，排查数据来源时使用 |")
    add("")
    add("### 4.3 示例：按组织取数（长表）")
    add("")
    add("```json")
    add("{")
    add('  "metrics": ["marketing_office_expense", "marketing_travel_expense"],')
    add('  "period_type": "month",')
    add('  "period_start": "2026-08",')
    add('  "period_end": "2026-09",')
    add('  "org_codes": ["100", "101"]')
    add("}")
    add("```")
    add("")
    add("```json")
    add("{")
    add('  "code": 0, "msg": "查询成功", "success": true, "status_code": 200,')
    add('  "data": {')
    add('    "period_type": "month", "period_start": "2026-08", "period_end": "2026-09", "level": "org",')
    add('    "calc_version_policy": "latest",')
    add('    "metrics": [ { "code": "marketing_office_expense", "name": "营销中心办公费用", "excel_code": "EXP-01-a", "unit": "元" } ],')
    add('    "items": [')
    add('      { "metric_code": "marketing_office_expense", "metric_name": "营销中心办公费用",')
    add('        "excel_code": "EXP-01-a", "period_value": "2026-09",')
    add('        "org_code": "101", "org_name": "佛山永锢科技有限公司",')
    add('        "dept_code": null, "dept_name": null, "value": 6871.01, "calc_version": 1,')
    add('        "calc_time": "2026-09-27 03:59:42", "batch_id": "20260927035941310160" }')
    add("    ],")
    add('    "errors": [],')
    add('    "summary": { "metric_count": 2, "item_count": 4, "period_count": 2, "org_count": 2, "total": 10252.35 }')
    add("  }")
    add("}")
    add("```")
    add("")
    add("### 4.4 示例：只取合计（推荐「只要一个数」的场景）")
    add("")
    add("```json")
    add('{ "metrics": ["marketing_office_expense"], "total_only": true }')
    add("```")
    add("")
    add("```json")
    add("{")
    add('  "code": 0, "msg": "查询成功", "success": true,')
    add('  "data": {')
    add('    "period_type": "month", "period_start": "2026-09", "period_end": "2026-09", "total_only": true,')
    add('    "totals": [')
    add('      { "metric_code": "marketing_office_expense", "metric_name": "营销中心办公费用",')
    add('        "excel_code": "EXP-01-a", "period_value": "2026-09", "value": 6871.01, "calc_version": 1,')
    add('        "calc_time": "2026-09-27 03:59:42", "org_count": 14 }')
    add("    ],")
    add('    "items": [], "errors": [],')
    add('    "summary": { "metric_count": 1, "item_count": 14, "org_count": 14, "total": 6871.01 }')
    add("  }")
    add("}")
    add("```")
    add("")
    add("- 不传 `period_start`/`period_end` 时取当前期间；要看多个月趋势就传区间，`totals` 按期间各返回一行。")
    add("- 一个指标取一个数：`data.totals[0].value`。")
    add('- `metrics` 也可以直接传 Excel 科目编码，例如 `{ "metrics": ["EXP-01-a"], "total_only": true }`，效果与传 `marketing_office_expense` 完全一致。')
    add("")
    add("### 4.5 示例：宽表（指标作为列）")
    add("")
    add("```json")
    add('{ "metrics": ["marketing_office_expense", "marketing_travel_expense"], "format": "wide", "period_start": "2026-09", "period_end": "2026-09" }')
    add("```")
    add("")
    add("```json")
    add('{ "code": 0, "data": {')
    add('  "columns": ["period_value", "org_code", "org_name", "dept_code", "dept_name", "marketing_office_expense", "marketing_travel_expense"],')
    add('  "rows": [ { "period_value": "2026-09", "org_code": "101", "org_name": "佛山永锢科技有限公司", "dept_code": null, "dept_name": null,')
    add('              "marketing_office_expense": 6871.01, "marketing_travel_expense": 2333.98 } ] } }')
    add("```")
    add("")
    add("### 4.6 取数行为约定")
    add("")
    add("1. **只返回存在的行**：某组织某期间没有数据时不会补 0，请按 0 处理。")
    add("2. **默认最新计算版本**：同一「指标 × 期间」若多次重算，只返回 `calc_version` 最大的结果。")
    add("3. **月指标为累计值**：当日重算的是当月累计数；月数据在次月 1 日补算一次，建议每天 08:00 之后取数。")
    add("4. **部分指标不可读不报错**：混入不存在/停用的编码时接口仍返回 `code=0`，这些编码在 `data.errors` 中；若全部不可读则返回 `403`。")
    add("5. **限流**：业务接口默认每应用 600 次/分钟，换令牌接口 30 次/分钟；超限返回 `429 / 40103`。")
    add("6. **无组织维度的指标**（如 CRM 报价类、出库总量类）：不按组织拆分，返回行 `org_code` 为 `null`、`org_count` 为 `0`；**请求时不要传 `org_codes`**，否则会被过滤成空。")
    add("")
    add("---")
    add("")
    add("## 5. 指标清单")
    add("")
    add(f"共 {len(enabled)} 个可读指标；`最新期间` 表示该指标当前已算出的最新期间。")
    add("")
    add("| # | 指标编码（`metrics` 传这个） | 指标名称 | Excel 科目编码 | 期间类型 | 单位 | 组织维度 | 最新期间 | 已算期间数 |")
    add("|---|---|---|---|---|---|---|---|---|")
    for index, metric in enumerate(enabled, start=1):
        period_cn = PERIOD_TYPE_CN.get(metric["period_type"], metric["period_type"])
        add(
            f"| {index} | `{metric['code']}` | {_cell(metric['name'])} | {_cell(metric['excel_code'] or '')} "
            f"| {period_cn}(`{metric['period_type']}`) | {_cell(metric['unit'])} "
            f"| {'有' if metric['has_org_dim'] else '无（整表一个总量）'} "
            f"| {_cell(metric['max_period'])} | {metric['period_count']} |"
        )
    if not enabled:
        add("| - | - | 暂无启用指标 | - | - | - | - | - | - |")
    add("")
    add("### 5.1 各指标口径说明")
    add("")
    for metric in enabled:
        add(f"#### `{metric['code']}` {metric['name']}")
        add("")
        add(f"- 期间类型：{PERIOD_TYPE_CN.get(metric['period_type'], metric['period_type'])}（`{metric['period_type']}`，期间格式示例 `{_period_hint(metric['period_type'])}`）")
        add(f"- Excel 科目编码：{_cell(metric['excel_code'] or '')}")
        add(f"- 单位：{metric['unit']}（数值保留 4 位小数）")
        dims = "、".join(metric["dimensions"]) if metric["dimensions"] else "无"
        add(f"- 组织维度：{'有（可按组织拆分）' if metric['has_org_dim'] else '无（不传 org_codes，只取合计）'}")
        add(f"- 维度配置键：{dims}")
        add(f"- 数据可用区间：{_cell(metric['min_period'])} ~ {_cell(metric['max_period'])}，最近计算时间 {_cell(metric['last_calc_time'])}")
        add(f"- 口径说明：{metric['description'] or '（未填写）'}")
        add("")
    add("### 5.2 Excel 科目编码对照表")
    add("")
    add("按 Excel 科目编码排序，便于财务底稿 ↔ 接口字段互查；缺失编码的指标见文末「待补充」。")
    add("")
    add("| Excel 科目编码 | 指标编码（`metrics` 也可传这个） | 指标名称 |")
    add("|---|---|---|")
    coded = sorted(
        [m for m in enabled if m["excel_code"]],
        key=lambda item: (item["excel_code"].split("-")[0], item["excel_code"]),
    )
    for metric in coded:
        add(f"| `{metric['excel_code']}` | `{metric['code']}` | {_cell(metric['name'])} |")
    if not coded:
        add("| - | - | 暂无 |")
    uncoded = [m for m in enabled if not m["excel_code"]]
    if uncoded:
        add("")
        add(f"**待补充 Excel 科目编码（{len(uncoded)} 个）**：财务底稿编码确定后在 `metric_def.excel_code` 补录，重跑本脚本即可刷新。")
        add("")
        add("| 指标编码 | 指标名称 |")
        add("|---|---|")
        for metric in uncoded:
            add(f"| `{metric['code']}` | {_cell(metric['name'])} |")
    add("")
    if disabled:
        add("### 5.3 暂不开放（已停用）")
        add("")
        for metric in disabled:
            add(f"- `{metric['code']}` {metric['name']}（停用，调用会返回 `errors`）")
        add("")
    add("---")
    add("")
    add("## 6. 错误码与处理")
    add("")
    add("| 业务码 `code` | HTTP | 含义 | 处理建议 |")
    add("|---|---|---|---|")
    add("| 0 | 200 | 成功 | - |")
    add("| 40100 | 401 | 未带令牌 / 令牌无效 / 令牌过期 | 重新换令牌（第 2 节），注意 `Bearer` 后有空格 |")
    add("| 40101 | 403 | 应用被停用 / 凭证过期 / IP 不在白名单 | 联系管理员 |")
    add("| 40102 | 403 | 指标或层级未授权（如未开通核算维度明细） | 去掉 `level=dept/all` 或联系管理员开通 |")
    add("| 40103 | 429 | 超过调用频率 | 按 `msg` 中的建议秒数退避重试 |")
    add("| 40104 | 400 | 参数非法（期间格式、跨度超限、指标数超限等） | 按第 4.1 节修正参数 |")
    add("| 40105 | 500 | 服务内部错误 | 把响应 `msg` 与请求时间反馈给管理员 |")
    add("")
    add("## 7. 常见问题")
    add("")
    add("1. **`items`/`totals` 为空**：该期间还没算。先用 `GET /open/v1/metrics` 确认编码存在，再联系管理员触发重算。")
    add("2. **数值与后台页面不一致**：确认返回的 `calc_version` / `calc_time`；页面重算后需重新请求。")
    add("3. **`org_code` 为 `null`**：该行属于未映射到标准组织的机构，仅在未限制组织范围时出现。")
    add("4. **要部门/客户明细**：默认只给组织合计，需要管理员在「开放接口 → 接入应用」里开启「核算维度明细」。")
    add("5. **想要一次性全量**：把 `period_start`/`period_end` 放到上限（月 36 个）分批取，避免单次请求过大。")
    add("")
    add("## 8. 更新本文件")
    add("")
    add("新增或修改指标后（`metric_def` 表变更），执行：")
    add("")
    add("```bash")
    add("cd backend")
    add("python scripts/gen_metric_api_doc.py --base-url https://<对外域名>")
    add("```")
    add("")
    add(f"生成结果会覆盖本文件；指标数量、口径说明、可用期间都会随数据库刷新。当前生成时间：{now}。")
    add("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="生成指标接口清单与调用方案文档")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help=f"输出路径，默认 {DEFAULT_OUTPUT}")
    parser.add_argument("--base-url", default="https://<后台域名>", help="文档中展示的对外服务地址")
    args = parser.parse_args()

    metrics = await _load_metrics()
    content = _render(metrics, args.base_url.rstrip("/"))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    await async_engine.dispose()
    print(f"文档已生成：{output}（可读指标 {len([m for m in metrics if m['status'] == 0])} 个 / 全部 {len(metrics)} 个）")


if __name__ == "__main__":
    asyncio.run(main())
