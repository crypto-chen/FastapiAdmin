"""生成《业务员指标开放接口对接说明》（供第三方系统对接使用）。

指标清单直接读数据库 ``metric_def``（分类 = ``营销中心-业务员``），
样例数据取自 ``metric_value`` 最新期间的真实结果，因此**新增/调整业务员指标后重跑本脚本即可更新文档**：

    cd backend
    python scripts/gen_person_metric_api_doc.py
    python scripts/gen_person_metric_api_doc.py --base-url https://data.example.com

文档面向第三方对接方：接入三步 + 指标清单 + 请求参数 + 真实返回样例 + 口径注意事项。
"""

import argparse
import asyncio
import json
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

DEFAULT_OUTPUT = PROJECT_ROOT.parent / "docs" / "业务员指标开放接口对接说明.md"
PERSON_CATEGORY = "营销中心-业务员"


def _cell(value: Any) -> str:
    """表格单元格转义：换行与竖线会让 Markdown 表格错位。"""
    if value is None or value == "":
        return "-"
    return str(value).replace("|", "\\|").replace("\n", " ").replace("\r", " ").strip()


def _rule(description: str | None) -> str:
    """取描述里的口径部分（去掉数据来源与调度说明，避免表格过长）。"""
    text = (description or "").strip()
    for marker in ("数据来源：", "月指标，"):
        index = text.find(marker)
        if index > 0:
            text = text[:index]
    return text.strip()


async def _load_metrics() -> list[dict[str, Any]]:
    """读取业务员维度指标定义 + 最新期间的结果概况。"""
    async with async_db_session() as db:
        defs = (
            await db.execute(
                select(MetricDefModel)
                .where(MetricDefModel.category == PERSON_CATEGORY, MetricDefModel.is_deleted == False)  # noqa: E712
                .order_by(MetricDefModel.excel_code.asc(), MetricDefModel.id.asc())
            )
        ).scalars().all()
        metrics: list[dict[str, Any]] = []
        for item in defs:
            latest = (
                await db.execute(
                    select(func.max(MetricValueModel.period_value)).where(
                        MetricValueModel.metric_id == item.id,
                        MetricValueModel.person_code.is_not(None),
                    )
                )
            ).scalars().first()
            period_value = str(latest) if latest else None
            person_count = total = None
            if period_value:
                calc_version = (
                    await db.execute(
                        select(func.max(MetricValueModel.calc_version)).where(
                            MetricValueModel.metric_id == item.id,
                            MetricValueModel.period_value == period_value,
                        )
                    )
                ).scalars().first()
                # 同一期间多次重算会保留历史行，这里只统计**最新计算版本**，避免行数虚高
                rows = (
                    await db.execute(
                        select(MetricValueModel.dept_code, MetricValueModel.value).where(
                            MetricValueModel.metric_id == item.id,
                            MetricValueModel.period_value == period_value,
                            MetricValueModel.calc_version == int(calc_version or 1),
                        )
                    )
                ).all()
                person_count = len([1 for dept_code, _ in rows if dept_code is not None])
                total_row = [float(value or 0) for dept_code, value in rows if dept_code is None]
                total = round(total_row[0], 4) if total_row else None
            metrics.append(
                {
                    "id": int(item.id),
                    "code": str(item.code),
                    "name": str(item.name),
                    "excel_code": item.excel_code,
                    "unit": resolve_metric_unit(item.name, item.measures),
                    "period_type": str(item.period_type or "month"),
                    "rule": _rule(item.description),
                    "latest_period": period_value,
                    "person_count": person_count,
                    "total": total,
                }
            )
        return metrics


async def _load_sample(metrics: list[dict[str, Any]], persons: int = 2, long_metrics: int = 3):
    """取真实结果做样例：长表用前 N 个指标 × M 个业务员，宽表用全部指标 × M 个业务员。

    样例期间取**指标覆盖最多**的期间（同一期间多次重算只取最新 calc_version），
    这样宽表样例行不会出现大面积 null（线索类指标是滚动近 30 天、期间与自然月不同）。
    """
    # 每个指标各自的最新期间与最新版本，再挑出覆盖指标数最多的期间做样例
    async with async_db_session() as db:
        per_metric: dict[int, tuple[str, int]] = {}
        for item in metrics:
            latest_period = (
                await db.execute(
                    select(func.max(MetricValueModel.period_value)).where(
                        MetricValueModel.metric_id == item["id"],
                        MetricValueModel.person_code.is_not(None),
                    )
                )
            ).scalars().first()
            if not latest_period:
                continue
            calc_version = (
                await db.execute(
                    select(func.max(MetricValueModel.calc_version)).where(
                        MetricValueModel.metric_id == item["id"],
                        MetricValueModel.period_value == str(latest_period),
                    )
                )
            ).scalars().first()
            per_metric[int(item["id"])] = (str(latest_period), int(calc_version or 1))
    coverage: dict[str, int] = {}
    for _period, _version in per_metric.values():
        coverage[_period] = coverage.get(_period, 0) + 1
    period_value = max(coverage, key=lambda p: (coverage[p], p)) if coverage else None
    if not period_value:
        return {"period_value": None, "persons": [], "long_items": [], "wide_rows": []}
    metric_ids = [m["id"] for m in metrics]
    async with async_db_session() as db:
        versions: dict[int, int] = {}
        for metric_id in metric_ids:
            latest = (
                await db.execute(
                    select(func.max(MetricValueModel.calc_version)).where(
                        MetricValueModel.metric_id == metric_id,
                        MetricValueModel.period_value == period_value,
                    )
                )
            ).scalars().first()
            if latest:
                versions[metric_id] = int(latest)
        rows = (
            await db.execute(
                select(
                    MetricValueModel.metric_id,
                    MetricValueModel.period_value,
                    MetricValueModel.person_id,
                    MetricValueModel.person_code,
                    MetricValueModel.person_name,
                    MetricValueModel.value,
                    MetricValueModel.calc_version,
                ).where(
                    MetricValueModel.metric_id.in_(metric_ids),
                    MetricValueModel.period_value == period_value,
                    MetricValueModel.person_code.is_not(None),
                )
            )
        ).all()
    code_by_id = {m["id"]: m["code"] for m in metrics}
    meta_by_id = {m["id"]: m for m in metrics}
    picked_rows = [
        row for row in rows if versions.get(int(row[0])) and int(row[6]) == versions[int(row[0])]
    ]
    # 挑一个指标（优先「接单未税」）作为排序依据，取排名靠前的业务员做样例
    order_metric = next(
        (m["id"] for m in metrics if m["code"] == "marketing_person_order_intake_untaxed"),
        metrics[0]["id"] if metrics else None,
    )
    ranking = sorted(
        [row for row in picked_rows if int(row[0]) == order_metric],
        key=lambda row: -float(row[5] or 0),
    )
    sample_keys = [
        (row[2], row[3], row[4]) for row in ranking[:persons]
    ]
    # 长表样例优先用带 Excel 科目编码的指标（配套的「接单量」等无编码指标不作为示例列）
    long_pool = [m for m in metrics if m.get("excel_code")] or metrics
    long_ids = [m["id"] for m in long_pool[:long_metrics]]
    long_items = [
        {
            "metric_code": code_by_id[int(row[0])],
            "metric_name": meta_by_id[int(row[0])]["name"],
            "excel_code": meta_by_id[int(row[0])]["excel_code"],
            "period_value": row[1],
            "person_id": row[2],
            "person_code": row[3],
            "person_name": row[4],
            "value": round(float(row[5] or 0), 4),
            "calc_version": int(row[6]),
        }
        for row in picked_rows
        if int(row[0]) in long_ids and (row[2], row[3], row[4]) in sample_keys
    ]
    long_items.sort(key=lambda item: (item["person_code"] or "", item["metric_code"] or ""))
    wide_rows: list[dict[str, Any]] = []
    for person_id, person_code, person_name in sample_keys:
        row: dict[str, Any] = {
            "period_value": period_value,
            "org_code": None,
            "org_name": None,
            "dept_code": person_code,
            "dept_name": person_name,
            "person_id": person_id,
            "person_code": person_code,
            "person_name": person_name,
        }
        for item in metrics:
            row[item["code"]] = None
        for value_row in picked_rows:
            if (value_row[2], value_row[3], value_row[4]) == (person_id, person_code, person_name):
                row[code_by_id[int(value_row[0])]] = round(float(value_row[5] or 0), 4)
        wide_rows.append(row)
    return {
        "period_value": period_value,
        "persons": [{"person_id": p[0], "person_code": p[1], "person_name": p[2]} for p in sample_keys],
        "long_items": long_items,
        "wide_rows": wide_rows,
        "columns": list(wide_rows[0].keys()) if wide_rows else [],
    }


def _render(metrics: list[dict[str, Any]], sample: dict[str, Any], base_url: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    period = sample.get("period_value") or "-"
    lines: list[str] = []
    add = lines.append
    add("# 业务员指标开放接口对接说明")
    add("")
    add(f"> 生成时间：{now}（**由 `backend/scripts/gen_person_metric_api_doc.py` 从数据库自动生成，请勿手工修改**）")
    add(f"> 对外服务地址：`{base_url}`")
    add(f"> 指标范围：分类「{PERSON_CATEGORY}」，共 {len(metrics)} 个；指标粒度 = **年月 × 业务员**")
    add(f"> 样例期间：{period}（样例数值为真实结果，可直接用于联调比对）")
    add("")
    add("## 1. 这是什么")
    add("")
    add("本系统是**数据中台 / 指标计算层**：从 CRM 等来源系统取明细，按「年月 × 业务员」算成指标，")
    add("再通过开放接口交付给其他系统。调用方只需拿 `app_id` / `app_secret` 换令牌后取数，")
    add("**不需要自己拼明细、也不接触业务库**。")
    add("")
    add("对接方需要知道的三件事：")
    add("")
    add("1. **粒度**：每次取数返回的是「某个月 × 某业务员」的指标值，一个业务员一行。")
    add("2. **权限**：调用方的接入应用需要开通「业务员明细」权限（`allow_person_detail`），否则 `level=person` 会被拒绝（403）。")
    add("3. **合计**：`total_only=true` 只回公司合计；业务员明细用 `level=person`。")
    add("")
    add("## 2. 接入三步")
    add("")
    add("### 2.1 申请接入应用")
    add("")
    add("向平台管理员申请，拿到 `app_id` 与 `app_secret`（密钥仅下发一次，请妥善保存），并确认两件事：")
    add("")
    add("- 已开通**业务员明细**权限（`allow_person_detail`）")
    add("- 授权范围（组织 / 指标）是否覆盖你需要的指标")
    add("")
    add("### 2.2 换取访问令牌")
    add("")
    add("```bash")
    add(f"curl -X POST \"{base_url}/open/v1/auth/token\" \\")
    add("  -H \"Content-Type: application/json\" \\")
    add("  -d '{\"app_id\":\"<你的app_id>\",\"app_secret\":\"<你的app_secret>\"}'")
    add("```")
    add("")
    add("```json")
    add("{")
    add("  \"code\": 0,")
    add("  \"msg\": \"获取令牌成功\",")
    add("  \"data\": { \"access_token\": \"eyJ...\", \"token_type\": \"Bearer\", \"expires_in\": 7200 }")
    add("}")
    add("```")
    add("")
    add("### 2.3 取数")
    add("")
    add("```bash")
    add(f"curl -X POST \"{base_url}/open/v1/metrics/query\" \\")
    add("  -H \"Content-Type: application/json\" \\")
    add("  -H \"Authorization: Bearer <access_token>\" \\")
    add("  -d '{")
    add("    \"metrics\": [\"STF-13\", \"STF-10\"],")
    add("    \"period_start\": \"" + str(period) + "\",")
    add("    \"period_end\": \"" + str(period) + "\",")
    add("    \"level\": \"person\",")
    add("    \"format\": \"long\"")
    add("  }'")
    add("```")
    add("")
    add("## 3. 接口清单")
    add("")
    add("| 方法 | 路径 | 用途 | 需要令牌 |")
    add("| --- | --- | --- | --- |")
    add("| POST | `/open/v1/auth/token` | 应用凭证换访问令牌 | 否 |")
    add("| POST | `/open/v1/metrics/query` | **批量取数（主接口）** | 是 |")
    add("| GET | `/open/v1/metrics` | 查询可读指标目录（编码、名称、单位、口径） | 是 |")
    add("| GET | `/open/v1/orgs` | 查询可见组织字典 | 是 |")
    add("")
    add("## 4. 请求参数（`POST /open/v1/metrics/query`）")
    add("")
    add("| 字段 | 类型 | 必填 | 默认 | 说明 |")
    add("| --- | --- | --- | --- | --- |")
    add("| `metrics` | string[] | 是 | - | 指标标识，可用系统编码或 Excel 科目编码（如 `marketing_person_order_intake_untaxed` / `STF-13`），单次上限 20 个 |")
    add("| `period_type` | string | 否 | `month` | 业务员指标均为月指标，保持 `month` |")
    add("| `period_start` | string | 否 | 当前月 | 起始期间（含），格式 `YYYY-MM` |")
    add("| `period_end` | string | 否 | 同 `period_start` | 结束期间（含）；跨月取数时按月各返回一行 |")
    add("| `level` | string | 否 | `org` | **业务员明细必须传 `person`**；`org`=公司合计，`dept`=核算维度明细，`all`=全部 |")
    add("| `person_ids` | int[] | 否 | 全部 | 业务员主ID（内部标准人员ID），如 `[139,140]` |")
    add("| `person_codes` | string[] | 否 | 全部 | 业务员编码（CRM 用户名），如 `[\"lixinhui\"]` |")
    add("| `format` | string | 否 | `long` | `long` 长表（一行一个「指标×业务员×期间」）/ `wide` 宽表（指标做列） |")
    add("| `total_only` | bool | 否 | `false` | 只回公司合计（结果在 `totals`，`items` 为空） |")
    add("| `include_meta` | bool | 否 | `true` | 是否返回指标口径元信息 |")
    add("")
    add("> 说明：业务员指标没有组织维度，**不要传 `org_codes`**（传了会按组织过滤成空结果）。")
    add("")
    add("## 5. 业务员指标清单")
    add("")
    if sample.get("period_value"):
        add(
            "下表逐指标给出**最新期间**、该期间的公司合计（取该指标最新计算版本）与有结果的业务员个数；"
            "线索类（STF-42/43/44）是**近 30 天滚动口径**，期间值与自然月不同，请以表中期间为准。"
        )
    else:
        add("下表为公司口径汇总列（尚未算出业务员维度结果时不展示数值）。")
    add("")
    add("| Excel 科目编码 | 指标编码（`metrics` 传这个） | 指标名称 | 单位 | 最新期间 | 该期合计 | 业务员数 | 口径 |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for item in metrics:
        add(
            "| "
            + " | ".join(
                [
                    f"`{_cell(item['excel_code'])}`",
                    f"`{_cell(item['code'])}`",
                    _cell(item["name"]),
                    _cell(item["unit"]),
                    _cell(item.get("latest_period")),
                    _cell(item["total"]),
                    _cell(item["person_count"]),
                    _cell(item["rule"]),
                ]
            )
            + " |"
        )
    add("")
    add("## 6. 返回数据样例（真实数据）")
    add("")
    add("### 6.1 长表：`level=person` + `format=long`")
    add("")
    add("每个业务员每个指标一行：")
    add("")
    add("```json")
    add(
        json.dumps(
            {
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "period_type": "month",
                    "period_start": period,
                    "period_end": period,
                    "level": "person",
                    "items": sample.get("long_items", []),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    add("```")
    add("")
    add("### 6.2 宽表：`level=person` + `format=wide`")
    add("")
    add("一个业务员一行，全部业务员指标做列（未取数的指标为 `null`，请按 0 处理）：")
    clue_period = next(
        (m["latest_period"] for m in metrics if m["code"] == "marketing_person_clue_count_30d"), None
    )
    if clue_period and clue_period != period:
        add("")
        add(
            f"> 线索类 STF-42/43/44 是**近 30 天滚动口径**，最新期间为 `{clue_period}`（与自然月不同），"
            f"所以在本期（{period}）样例里为 `null`；要取线索数据请把 `period_start`/`period_end` 传 `{clue_period}`。"
        )
    add("")
    add("```json")
    add(
        json.dumps(
            {
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "columns": sample.get("columns", []),
                    "rows": sample.get("wide_rows", []),
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    add("```")
    add("")
    add("### 6.3 只取公司合计：`total_only=true`")
    add("")
    add("```json")
    add(
        json.dumps(
            {
                "code": 0,
                "msg": "查询成功",
                "data": {
                    "totals": [
                        {
                            "metric_code": item["code"],
                            "metric_name": item["name"],
                            "excel_code": item["excel_code"],
                            "period_value": item["latest_period"],
                            "value": item["total"],
                            "person_count": item["person_count"],
                        }
                        for item in metrics[:3]
                    ],
                    "items": [],
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    add("```")
    add("")
    add("## 7. 返回字段说明")
    add("")
    add("| 字段 | 类型 | 说明 |")
    add("| --- | --- | --- |")
    add("| `metric_code` | string | 指标编码 |")
    add("| `metric_name` | string | 指标名称（`include_meta=true` 时返回） |")
    add("| `excel_code` | string | Excel 科目编码（财务底稿对照，如 `STF-13`） |")
    add("| `period_value` | string | 期间值 `YYYY-MM` |")
    add("| `person_id` | int | **业务员主ID**（内部标准人员ID），对接主键建议用它 |")
    add("| `person_code` | string | 业务员编码（CRM 用户名，如 `lixinhui`） |")
    add("| `person_name` | string | 业务员姓名 |")
    add("| `value` | number | 指标值（保留 4 位小数，单位见指标清单） |")
    add("| `calc_version` | int | 计算版本（每次重算递增） |")
    add("| `calc_time` | string | 计算时间（北京时间），用于判断数据新鲜度 |")
    add("")
    add("## 8. 口径注意事项（务必阅读）")
    add("")
    add("1. **合计 ≠ 业务员行相加**：平均值类（下推周期）与去重计数类（总客户数、老客户数）")
    add("   的公司合计按「Σ分子 ÷ Σ分母」或「客户并集」计算。要合计请用 `total_only=true`，")
    add("   不要把 `level=person` 的行直接相加。")
    add("2. **期间口径**：接单类取订单创建月；出货类取发货单审核月；报价类取报价日期；")
    add("   下推类取 ERP 下推时间；客户列表为**当前快照**（历史期间取重算时点的客户归属）。")
    add("3. **业务员归属**：订单/报价类取**下单人 `create_id`**；总客户数取客户表**负责人 `principal_id`**。")
    add("   线索类（STF-42/43/44）取线索表**负责人 `principal_id`**；总客户数与线索类未分配负责人的记录不计入。")
    add("4. **缺失即 0**：某业务员某月没有数据时不返回该行，请按 0 处理。")
    add("5. **数据刷新**：每日 02:00 同步来源明细、02:30 重算当月；次月 1 日重算上月并结转。")
    add("   月数据建议在次月 1 日 08:00 之后再取。")
    add("6. **线索类为近 30 天滚动口径（STF-42/43/44）**：窗口 = 取数时点往前 30 天，**不按自然月**，")
    add("   每天随重算滚动更新；调用时请把 `period_start`/`period_end` 传当期（`YYYY-MM`）即可，")
    add("   跨月对比仅作参考（它是滚动值，不是月度累计）。")
    add("7. **分摊类按业务员收入占比计算（STF-26/28 变动/固定费用分摊）**：")
    add("   `业务员收入（STF-18）÷ 总收入（ORD-01） × 费用池（CM-01/CM-04）`；")
    add("   由于分母是 ORD-01 接单金额，各业务员分摊额合计**小于**费用池合计数（差额不参与业务员分摊），属预期口径。")
    add("8. **库存（STF-25）为未出货订单金额，不是成本**：订单明细没有成本字段，")
    add("   暂以未出货订单（`chuhuo ≠ 1`）的**未税金额**计，并按 24 期回看；与公司口径「外部订单库存（未税）」存在窗口差异。")
    add("9. **两个「人均」指标按业务口径其值等于对应指标（STF-36 = STF-17、STF-37 = STF-30）**：")
    add("   业务员维度下即为该业务员自身的销售额 / 结算收益；如需按人数折算，请在调用侧另行除以人数。")
    add("")
    add("## 9. 错误码")
    add("")
    add("| 业务码 `code` | HTTP | 含义 | 处理建议 |")
    add("| --- | --- | --- | --- |")
    add("| 0 | 200 | 成功 | - |")
    add("| 40100 | 401 | 未带令牌 / 令牌无效或过期 | 重新换令牌 |")
    add("| 40101 | 403 | 应用停用 / 凭证过期 / IP 不在白名单 | 联系管理员 |")
    add("| 40102 | 403 | 未开通业务员明细（`level=person`）等权限 | 联系管理员开通 `allow_person_detail` |")
    add("| 40103 | 429 | 超过调用频率 | 按 `msg` 建议秒数退避重试 |")
    add("| 40104 | 400 | 参数非法（期间格式、指标数超 20 等） | 修正参数 |")
    add("| 40105 | 500 | 服务内部错误 | 反馈 `msg` 与请求时间 |")
    add("")
    add("## 10. 更新本文件")
    add("")
    add("业务员指标新增或口径调整后，执行：")
    add("")
    add("```bash")
    add("cd backend")
    add(f"python scripts/gen_person_metric_api_doc.py --base-url {base_url}")
    add("```")
    add("")
    add("生成结果会覆盖本文件（指标数量、口径说明、样例数据都会随数据库刷新）。")
    add("")
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="生成业务员指标开放接口对接说明")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help=f"输出路径，默认 {DEFAULT_OUTPUT}")
    parser.add_argument("--base-url", default="https://<后台域名>", help="文档中展示的对外服务地址")
    args = parser.parse_args()

    metrics = await _load_metrics()
    sample = await _load_sample(metrics)
    content = _render(metrics, sample, args.base_url)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    await async_engine.dispose()
    print(f"已生成 {output}（业务员指标 {len(metrics)} 个，样例期间 {sample.get('period_value')}）")


if __name__ == "__main__":
    asyncio.run(main())
