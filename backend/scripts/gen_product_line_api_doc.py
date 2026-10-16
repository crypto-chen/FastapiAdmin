"""生成《产品线指标开放接口对接说明》Markdown（外部系统对接用）。

从 ``app.modules.product.fields``（字段注册表，含可出性状态）与数据库实测结果生成，
保证文档与代码同源；**请勿手工修改生成的 md**，改口径改 ``fields.py`` 后重跑本脚本。

用法：
    python scripts/gen_product_line_api_doc.py --base-url https://<后台域名>
    python scripts/gen_product_line_api_doc.py --base-url https://x --period 2026-09 --out ../docs/产品线指标开放接口对接说明.md
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select  # noqa: E402

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.product.fields import FIELD_DEFS, STATUS_LABELS  # noqa: E402
from app.modules.product.model import ProductLineAnalysisModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SCHEMA_VERSION = "2026-10-16"
LEVEL_NAMES = {0: "产品线 × SKU 明细", 1: "产品线小计", 2: "全表合计"}


async def load_stats(period: str) -> dict:
    async with async_db_session() as db:
        if not period:
            period = (
                await db.execute(select(func.max(ProductLineAnalysisModel.period_value)))
            ).scalar() or ""
        version = (
            await db.execute(
                select(func.max(ProductLineAnalysisModel.calc_version)).where(
                    ProductLineAnalysisModel.period_value == period
                )
            )
        ).scalar()
        if version is None:
            return {"period_value": period, "calc_version": 0, "rows": {}, "lines": [], "total": {}}
        base = (
            ProductLineAnalysisModel.period_value == period,
            ProductLineAnalysisModel.calc_version == version,
        )
        rows = (
            await db.execute(
                select(ProductLineAnalysisModel.is_aggregate, func.count())
                .where(*base)
                .group_by(ProductLineAnalysisModel.is_aggregate)
            )
        ).all()
        lines = (
            (
                await db.execute(
                    select(ProductLineAnalysisModel)
                    .where(*base, ProductLineAnalysisModel.is_aggregate == 1)
                    .order_by(ProductLineAnalysisModel.net_shipment.desc())
                    .limit(5)
                )
            )
            .scalars()
            .all()
        )
        total = (
            await db.execute(
                select(ProductLineAnalysisModel).where(*base, ProductLineAnalysisModel.is_aggregate == 2)
            )
        ).scalars().first()
        sku_count = (
            await db.execute(
                select(func.count(func.distinct(ProductLineAnalysisModel.sku))).where(
                    *base, ProductLineAnalysisModel.is_aggregate == 0
                )
            )
        ).scalar() or 0
    return {
        "period_value": period,
        "calc_version": int(version),
        "rows": {int(k): int(v) for k, v in rows},
        "sku_count": int(sku_count),
        "lines": [
            {
                "name": item.product_line_code,
                "order_count": item.order_count,
                "ship_qty": float(item.ship_qty or 0),
                "net_shipment": float(item.net_shipment or 0),
                "intake_untaxed": float(item.intake_untaxed or 0),
                "settlement_income": float((item.extra or {}).get("PRD-27") or 0),
            }
            for item in lines
        ],
        "total": (
            {
                "order_count": int(total.order_count),
                "ship_qty": float(total.ship_qty or 0),
                "intake_untaxed": float(total.intake_untaxed or 0),
                "net_shipment": float(total.net_shipment or 0),
                "settlement_income": float((total.extra or {}).get("PRD-27") or 0),
                "hq_allocation": float((total.extra or {}).get("PRD-33") or 0),
            }
            if total
            else {}
        ),
    }


def field_sections() -> tuple[list[tuple[str, list]], list[str]]:
    groups: list[tuple[str, list]] = []
    sensitive: list[str] = []
    for item in FIELD_DEFS:
        code, name, data_type, group, is_sensitive, source, status, note = item
        if is_sensitive:
            sensitive.append(code)
        existing = next((g for g in groups if g[0] == group), None)
        if existing is None:
            existing = (group, [])
            groups.append(existing)
        existing[1].append(item)
    return groups, sensitive


def build_doc(base_url: str, stats: dict) -> str:
    period = stats["period_value"]
    rows = stats["rows"]
    detail_rows = rows.get(0, 0)
    groups, sensitive = field_sections()
    ready = [item[0] for item in FIELD_DEFS if item[6] == "ready"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    add = lines.append

    add("# 产品线指标开放接口对接说明（外部系统）")
    add("")
    add("> 版本：v1.0")
    add(f"> 生成时间：{now}（**由 `backend/scripts/gen_product_line_api_doc.py` 从字段注册表与数据库生成，请勿手工修改**）")
    add(f"> 接口前缀：`/open/v1`（与内部管理端 `/api/v1/product/*` 物理隔离，网关只需放行 `/open/**`）")
    add(f"> 对外服务地址：`{base_url}`（开发环境 `http://127.0.0.1:8001`）")
    add(f"> schema_version：`{SCHEMA_VERSION}`（字段口径变化时会递增，请在对接侧做兼容判断）")
    add(f"> 粒度：**年月 × 产品线大类 × SKU**（另有产品线小计与全表合计行），字段口径 = 财务底稿 `PRD-00 ~ PRD-44`")
    add(
        f"> 样例期间：`{period}`（calc_version={stats['calc_version']}，"
        f"明细 {detail_rows} 行 + 小计 {rows.get(1, 0)} 行 + 合计 {rows.get(2, 0)} 行，"
        f"SKU {stats.get('sku_count', 0)} 个）"
    )
    add("")
    add("---")
    add("")
    add("## 1. 这是什么")
    add("")
    add("本系统从 CRM（订单、发货、产品型号字典）与金蝶（科目余额表、生产订单等）取明细，")
    add("按「年月 × 产品线大类 × SKU」算成产品线分析指标，再通过 `/open/v1/product-lines` 交付给")
    add("BI、数据仓库、报表系统、Excel 插件等外部系统。调用方只拿 `app_id` / `app_secret` 换令牌后取数，")
    add("**不需要自己拼明细、也不接触业务库**。")
    add("")
    add("对接方需要知道的三件事：")
    add("")
    add(f"1. **粒度**：一次取数返回「某个月 × 产品线大类 × SKU」的指标值；")
    add("   另有产品线小计行（`level=1`）与全表合计行（`level=2`），用 `aggregate_level` 选择。")
    add("2. **权限**：接入应用必须开通 **`allow_product_line_detail`**，否则接口返回 403；")
    add(f"   成本/毛利/边际类字段（{len(sensitive)} 个）另需 `allow_cost_fields`。")
    add("3. **版本**：同一期间可重算多次，`calc_version` 递增；**不传版本取该期间最新版本**，历史版本仍可按 `calc_version` 回溯。")
    add("")
    add("---")
    add("")
    add("## 2. 接入三步")
    add("")
    add("1. **申请接入**：向平台管理员申请，拿到 `app_id`、`app_secret`（密钥只下发一次），并确认：")
    add("   - 已开通产品线分析查询权限 `allow_product_line_detail`（**必须**，否则 403）；")
    add("   - 是否需要成本类敏感字段（`allow_cost_fields`）；")
    add("   - 是否配置 IP 白名单（`ip_whitelist`）。")
    add("2. **换令牌**：`POST /open/v1/auth/token`，拿 `access_token`（默认有效期 7200 秒，过期重换即可）。")
    add("3. **拉数据**：带 `Authorization: Bearer <access_token>` 调 `GET /open/v1/product-lines`。")
    add("")
    add("```bash")
    add("# 1) 换令牌")
    add(f'curl -X POST "{base_url}/open/v1/auth/token" \\')
    add('  -H "Content-Type: application/json" \\')
    add('  -d \'{"app_id":"<你的app_id>","app_secret":"<你的密钥>"}\'')
    add("")
    add("# 2) 拉产品线 × SKU 明细（样例期间 2026-09）")
    add(f'curl -X GET "{base_url}/open/v1/product-lines?period_value={period}&aggregate_level=detail&page_no=1&page_size=500" \\')
    add('  -H "Authorization: Bearer <access_token>"')
    add("")
    add("# 3) 只拉产品线小计（做汇总报表用这个，一次 10 行左右）")
    add(f'curl -X GET "{base_url}/open/v1/product-lines?period_value={period}&aggregate_level=line" \\')
    add('  -H "Authorization: Bearer <access_token>"')
    add("```")
    add("")
    add("---")
    add("")
    add("## 3. 鉴权与权限")
    add("")
    add("### 3.1 换令牌（client_credentials）")
    add("")
    add("```")
    add("POST /open/v1/auth/token")
    add("Content-Type: application/json")
    add("")
    add('{ "app_id": "your_app", "app_secret": "******" }')
    add("```")
    add("")
    add("返回：")
    add("")
    add("```json")
    add('{ "code": 0, "msg": "获取令牌成功", "data": { "access_token": "<jwt>", "expires_in": 7200 } }')
    add("```")
    add("")
    add("### 3.2 应用级权限（管理员侧配置）")
    add("")
    add("| 开关 | 字段 | 作用 |")
    add("| --- | --- | --- |")
    add("| 产品线分析明细 | `open_client.allow_product_line_detail` | 关闭时 `/open/v1/product-lines*` 一律 403 |")
    add("| 成本类字段 | `open_client.allow_cost_fields` | 关闭时目录与数据一起剔除成本/毛利/边际字段 |")
    add("| IP 白名单 | `open_client.ip_whitelist` | 非空时只允许名单内 IP 换令牌 |")
    add("| 到期时间 | `open_client.expire_time` | 到期后拒绝换令牌 |")
    add("")
    add("权限**每次请求读库判断**，管理员改完开关无需重启服务。")
    add("")
    add("---")
    add("")
    add("## 4. 接口清单")
    add("")
    add("| 接口 | 方法 | 说明 |")
    add("| --- | --- | --- |")
    add("| `/open/v1/auth/token` | POST | 应用凭证换访问令牌 |")
    add("| `/open/v1/product-lines/fields` | GET | 字段目录（含中文名、分组、口径、可出性状态） |")
    add("| `/open/v1/product-lines` | GET | 拉取产品线分析（明细 / 小计 / 合计） |")
    add("")
    add("---")
    add("")
    add("## 5. 接口详情")
    add("")
    add("### 5.1 字段目录 `GET /open/v1/product-lines/fields`")
    add("")
    add("无需参数。返回 `schema_version` 与字段数组：")
    add("")
    add("```json")
    add('{ "field_code": "PRD-26", "field_name": "对外出货净额", "data_type": "number",')
    add('  "group": "金额", "sensitive": false, "source": "计算", "status": "ready",')
    add('  "status_label": "现用可出", "excel_code": "PRD-26", "stored_in": "core" }')
    add("```")
    add("")
    add("### 5.2 明细拉取 `GET /open/v1/product-lines`")
    add("")
    add("| 参数 | 类型 | 默认 | 说明 |")
    add("| --- | --- | --- | --- |")
    add("| `period_value` | string | 最新期间 | 期间 `YYYY-MM` |")
    add("| `calc_version` | int | 最新版本 | 计算版本 |")
    add(f"| `aggregate_level` | string | `detail` | `detail`=产品线×SKU 明细、`line`=产品线小计+全表合计、`all`=全部 |")
    add("| `product_line` | string | - | 产品线大类（模糊匹配） |")
    add("| `sku` | string | - | SKU（模糊匹配） |")
    add("| `salesman` | string | - | 业务员姓名（模糊，匹配多值拼接串） |")
    add("| `order_type` | string | - | 订单类型（批量/打样/零售/备货，模糊） |")
    add("| `platform` | string | - | 平台（模糊） |")
    add("| `shop` | string | - | 店铺（模糊） |")
    add("| `page_no` | int | 1 | 页码 |")
    add("| `page_size` | int | 500 | 每页数量（≤2000） |")
    add("")
    add("返回：")
    add("")
    add("```json")
    add("{")
    add('  "code": 0, "msg": "查询产品线分析成功",')
    add('  "data": {')
    add(f'    "schema_version": "{SCHEMA_VERSION}",')
    add(f'    "period_value": "{period}", "calc_version": {stats["calc_version"]},')
    add(f'    "total": {detail_rows}, "page_no": 1, "page_size": 500, "has_more": false,')
    add('    "summary": { "line_count": 10, "sku_count": 189, "order_count": 1419,')
    add('                 "intake_untaxed_sum": 7913807.89, "ship_untaxed_sum": 4434803.16,')
    add('                 "net_shipment_sum": 4460020.74, "settlement_income_sum": 446002.074 },')
    add('    "rows": [')
    add('      { "product_line": "壳体", "sku": "L10A", "level": 0,')
    add('        "fields": { "PRD-00": "2026-09", "PRD-01": "壳体", "PRD-02": "L10A",')
    add('                    "PRD-11": 1178.0, "PRD-16": 135678.6238, "PRD-17": 115.1771,')
    add('                    "PRD-22": 132530.39, "PRD-26": 203624.2, "PRD-27": 20362.42,')
    add('                    "PRD-33": 4072.484, "PRD-X01": 48, "PRD-X03": 172.8559 } }')
    add("    ]")
    add("  }")
    add("}")
    add("```")
    add("")
    add("> `fields` 里的键就是字段目录的 `field_code`，与财务底稿编码一一对应；")
    add("> 不传 `allow_cost_fields` 时，`sensitive=true` 的键会被整段剔除（不会出现 `null`）。")
    add("")
    add("### 5.3 行集说明")
    add("")
    add("| `level` | 含义 | 行数（样例期间） | 说明 |")
    add("| --- | --- | --- | --- |")
    add(f"| 0 | 产品线 × SKU 明细 | {detail_rows} | 一行一「产品线大类 × SKU」 |")
    add(f"| 1 | 产品线小计 | {rows.get(1, 0)} | 该产品线全部 SKU 汇总，`sku` 为空 |")
    add(f"| 2 | 全表合计 | {rows.get(2, 0)} | `product_line` 为「全部产品线」 |")
    add("")
    add("---")
    add("")
    add("## 6. 字段清单")
    add("")
    add("### 6.1 分组速查")
    add("")
    for group, items in groups:
        codes = "、".join(item[0] for item in items)
        add(f"- **{group}**（{len(items)} 项）：{codes}")
    add("")
    add(f"### 6.2 逐项口径（共 {len(FIELD_DEFS)} 项）")
    add("")
    add("| 编码 | 名称 | 类型 | 分组 | 底稿来源 | 可出性 | 口径/说明 |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for group, items in groups:
        for code, name, data_type, _group, is_sensitive, source, status, note in items:
            flag = "🔒" if is_sensitive else ""
            add(
                f"| {code}{flag} | {name} | {data_type} | {group} | {source} | "
                f"{STATUS_LABELS.get(status, status)} | {note.replace('|', '/')} |"
            )
    add("")
    add(f"> 🔒 = 敏感字段（共 {len(sensitive)} 个），需 `allow_cost_fields` 才会返回：{'、'.join(sensitive)}")
    add(f"> 现用可出字段 {len(ready)} 个；其余为待补/待定/不做，详见 `docs/营销中心产品线分析报表方案.md`。")
    add("")
    add("### 6.3 关键口径")
    add("")
    add("1. **产品线大类**：CRM 产品型号字典（`/hs/product/getProductModel`）沿父链上卷后的**原值**，不建对照表；")
    add("   型号未命中时用订单行的产品系列兜底（覆盖 97.88% → 99.82%）。")
    add("2. **SKU**：型号字典的 `model`（如 `L10A`），不是 id、不是名称。")
    add("3. **标准成本**：取自 CRM 销售订单行（`PRD-17` 单位标准成本、`PRD-16` 标准成本小计 = 单位标准成本 × 出货数量）。")
    add("4. **实际成本**：取自 ERP 金蝶成本计算单 `CB_CostCalBill`（按销售订单号取，参数已打通，待建同步任务）。")
    add("5. **出货数量**：CRM 发货明细 `/hs/shipments/getShipmentsDetail`（发货时间口径）按订单 ID 关联，")
    add("   未命中回退 `/hs/order/orderShipments`（审核日期口径）；每单来源见 `extra.ship_qty_source`。")
    add("6. **PRD-33 总部分摊** = 对外出货净额 × 2.00%（与底稿 27×2% 一致）；**PRD-27 营销结算收入10%** = 对外出货净额 × 10%。")
    add("")
    add("---")
    add("")
    add("## 7. 分页、增量与对账")
    add("")
    add("1. **分页**：按 `page_no` 递增翻页，`has_more=false` 表示取完；`total` 是当前筛选条件下的总行数。")
    add("2. **增量**：本接口是**期间快照**语义，不是流水增量。建议按「期间 + `calc_version`」判重，")
    add("   同一期间出现更高 `calc_version` 时整期覆盖（重算后旧版本仍在，可用 `calc_version` 取历史）。")
    add("3. **对账**：`summary.net_shipment_sum` 应等于该期间**全表合计行**的 `PRD-26`；")
    add("   产品线小计之和应等于合计行（误差 0）。")
    add("")
    add(f"### 7.1 样例期间实测值（{period}，calc_version={stats['calc_version']}，可直接用于联调比对）")
    add("")
    total = stats.get("total") or {}
    if total:
        add("| 指标 | 数值 |")
        add("| --- | --- |")
        add(f"| 订单行数（PRD-X01 合计） | {total.get('order_count')} |")
        add(f"| 出货数量（PRD-11 合计） | {total.get('ship_qty')} |")
        add(f"| 接单未税（PRD-22 合计） | {total.get('intake_untaxed')} |")
        add(f"| 对外出货净额（PRD-26 合计） | {total.get('net_shipment')} |")
        add(f"| 营销结算收入10%（PRD-27 合计） | {total.get('settlement_income')} |")
        add(f"| 总部分摊（PRD-33 合计） | {total.get('hq_allocation')} |")
        add("")
    if stats.get("lines"):
        add("产品线 Top5（按对外出货净额）：")
        add("")
        add("| 产品线 | 订单行 | 出货数量 | 接单未税 | 对外出货净额 | 结算收入10% |")
        add("| --- | --- | --- | --- | --- | --- |")
        for item in stats["lines"]:
            add(
                f"| {item['name']} | {item['order_count']} | {item['ship_qty']} | "
                f"{item['intake_untaxed']} | {item['net_shipment']} | {item['settlement_income']} |"
            )
        add("")
    add("> CRM 是实时业务库，历史月份数据会随后续改单变化；开发机与生产环境的历史值可能有小差异，属正常现象。")
    add("")
    add("---")
    add("")
    add("## 8. 错误码")
    add("")
    add("| HTTP | code | 含义 | 处理 |")
    add("| --- | --- | --- | --- |")
    add("| 200 | 0 | 成功 | - |")
    add("| 401 | 40101 | app_id / app_secret 不正确，或令牌失效/过期 | 重新换令牌；确认密钥 |")
    add("| 401 | 40101 | 调用方 IP 不在白名单 | 联系管理员加白名单 |")
    add("| 403 | 40101 | 应用未开通产品线分析查询权限 | 联系管理员打开 `allow_product_line_detail` |")
    add("| 429 | - | 超过每分钟请求上限（默认 600） | 降低频率或申请提额 |")
    add("| 500 | - | 服务端异常 | 联系平台方，附 `request_id` |")
    add("")
    add("---")
    add("")
    add("## 9. 常见问题")
    add("")
    add("| 现象 | 原因 / 处理 |")
    add("| --- | --- |")
    add("| 403「应用未开通产品线分析查询权限」 | 管理员未打开 `allow_product_line_detail` |")
    add("| 返回里没有成本字段 | 应用未开 `allow_cost_fields`（字段被整体剔除，不是返回 null） |")
    add("| `total` 与预期差很多 | `aggregate_level` 默认 `detail`，只算明细行；小计/合计要用 `line` |")
    add("| 某产品线 `sku` 为空 | 那是小计行（`level=1`），不是明细 |")
    add("| 期间没数据 | 该期间未构建：等每日 02:30 自动构建，或请平台方手工构建 |")
    add("| `PRD-16` 等成本项为空 | 该行订单没有成本字段（CRM 订单行未填），覆盖约 85% |")
    add("")
    add("---")
    add("")
    add("## 10. 附：数据来源与构建节奏")
    add("")
    add("| 来源 | 对象 | 用途 | 同步节奏 |")
    add("| --- | --- | --- | --- |")
    add("| CRM | `/hs/order/orderAnalyze?type=1\\|2` | 订单明细（金额、客户、业务员、成本） | 每日 02:00 |")
    add("| CRM | `/hs/product/getProductModel` | 产品型号字典（SKU、产品线大类） | 每周一 02:00 |")
    add("| CRM | `/hs/product/getProductCategory` | 产品系列字典（上卷产品线大类） | 每周一 02:00 |")
    add("| CRM | `/hs/shipments/getShipmentsDetail` | 发货明细（出货数量，发货时间口径） | 每日 02:00 |")
    add("| CRM | `/hs/order/orderShipments?type=1\\|2` | 发货明细（出货数量兜底，审核日期口径） | 每日 02:00 |")
    add("| 金蝶 | `GL_RPT_AccountBalance` 等 | 科目余额表（费用、库存相关） | 每日 02:00 |")
    add("")
    add("- 订单全链路宽表 `dwd_order_full_chain` 每日 02:00 重建；产品线宽表在 02:30 之后按依赖构建。")
    add("- 每月 1 日自动重拉上月批次并重算上月，避免月末最后一天单据丢失。")
    add("- 产品线宽表：`dwd_product_line_analysis`（期间 × 产品线大类 × SKU × calc_version）；构建批次表：`dwd_product_line_build_run`。")
    add("")
    return "\n".join(lines) + "\n"


async def main() -> None:
    parser = argparse.ArgumentParser(description="生成产品线开放接口对接说明")
    parser.add_argument("--base-url", default="https://<后台域名>", help="对外服务地址")
    parser.add_argument("--period", default="", help="样例期间，缺省取最新")
    parser.add_argument(
        "--out",
        default=str(PROJECT_ROOT.parent / "docs" / "产品线指标开放接口对接说明.md"),
        help="输出路径",
    )
    args = parser.parse_args()

    stats = await load_stats(args.period)
    doc = build_doc(args.base_url, stats)
    Path(args.out).write_text(doc, encoding="utf-8")
    print(f"已生成 {args.out}（{len(doc)} 字符，期间 {stats.get('period_value')} v{stats.get('calc_version')}）")
    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
