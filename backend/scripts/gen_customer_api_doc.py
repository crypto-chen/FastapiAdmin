"""生成《客户分析月度指标开放接口对接说明》（供外部系统对接使用）。

数据来源：

- 字段口径：``app/modules/customer/fields.py``（CUS-00 ~ CUS-47，财务底稿编码）
- 真实样例：``dwd_customer_analysis``（客户分析宽表，取最新计算版本）

重跑本脚本即可刷新文档（字段新增 / 期间回补后无需手工改文档）：

    cd backend
    python scripts/gen_customer_api_doc.py

文档面向外部对接方：接入三步 + 接口清单 + 全量字段口径 + 真实返回样例 + 增量与对账建议。
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.customer.fields import FIELD_DEFS  # noqa: E402

DEFAULT_OUTPUT = PROJECT_ROOT.parent / "docs" / "客户分析月度指标开放接口对接说明.md"
TITLE = "客户分析月度指标开放接口对接说明（外部系统）"

BASE_CODES = ("CUS-00", "CUS-01", "CUS-02")
SCHEMA_VERSION = "2026-10-14"

# 分组说明（文档 §5.2，方便对接方按主题建表）
GROUP_NOTES: list[tuple[str, str]] = [
    ("基础", "期间、客户编码、客户名称，所有行必有"),
    ("维度", "客户类型、地区、贸易类型、信用等级、账期、业务员、产品线大类、SKU、订单类型"),
    ("金额", "接单未税 → 对外出货净额 → 营销结算收入 10% 的金额链"),
    ("回款", "回款、回款及时率、订金回款比例（口径待定，本期未出数）"),
    ("应收", "应收余额、逾期应收、逾期率（账龄来源：金蝶应收账龄分析表）"),
    ("成本", "毛利、毛利率、边际贡献、结算收益等成本利润字段（敏感，受 allow_cost_fields 控制）"),
    ("库存", "理论库存、实际库存、库存周转天数、呆滞库存（口径待定，本期未出数）"),
    ("其他", "复购率、退货率、客单价、总客户数、客户层级、行业、下单频次"),
]


def _num(value: Any) -> str:
    """数字格式化：None → 空，float → 去多余 0，整数不带小数点。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        text_value = f"{value:.4f}".rstrip("0").rstrip(".")
        return text_value
    return str(value)


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=str)


async def collect() -> dict[str, Any]:
    """从数据库取文档所需的真实数据。"""
    data: dict[str, Any] = {
        "periods": [],
        "latest_period": None,
        "latest_version": 0,
        "sample_period": None,
        "sample_version": 0,
        "detail_rows": 0,
        "quality_flags": [],
        "code_stats": {},
        "aggregate": None,
        "top_rows": [],
        "latest_detail": None,
        "runs": [],
    }
    async with async_db_session() as db:
        rows = (
            await db.execute(
                text(
                    "select period_value, calc_version, count(*) as c "
                    "from dwd_customer_analysis group by period_value, calc_version "
                    "order by period_value desc, calc_version desc"
                )
            )
        ).all()
        data["periods"] = [{"period": r[0], "version": int(r[1]), "rows": int(r[2])} for r in rows]
        if not rows:
            return data
        data["latest_period"] = rows[0][0]
        data["latest_version"] = int(rows[0][1])

        # 样例期间：取「最近一个已完整结束的月份」（即 < 当前月的最新期间），当月数据不完整不用于样例
        current_month = datetime.now().strftime("%Y-%m")
        closed = [p for p in data["periods"] if p["period"] < current_month]
        sample = closed[0] if closed else data["periods"][0]
        data["sample_period"] = sample["period"]
        data["sample_version"] = sample["version"]

        period, version = data["sample_period"], data["sample_version"]
        data["detail_rows"] = int(
            (
                await db.execute(
                    text(
                        "select count(*) from dwd_customer_analysis "
                        "where period_value=:p and calc_version=:v and is_aggregate=0"
                    ),
                    {"p": period, "v": version},
                )
            ).scalar()
            or 0
        )
        flags = (
            await db.execute(
                text(
                    "select data_quality_flag, count(*) from dwd_customer_analysis "
                    "where period_value=:p and calc_version=:v group by 1 order by 2 desc"
                ),
                {"p": period, "v": version},
            )
        ).all()
        data["quality_flags"] = [(r[0], int(r[1])) for r in flags]

        agg = (
            await db.execute(
                text(
                    "select customer_name, order_count, intake_untaxed, net_shipment, "
                    "gross_profit, data_quality_flag, extra from dwd_customer_analysis "
                    "where period_value=:p and calc_version=:v and is_aggregate=1 limit 1"
                ),
                {"p": period, "v": version},
            )
        ).first()
        if agg is not None:
            data["aggregate"] = {
                "customer_name": agg[0],
                "order_count": agg[1],
                "intake_untaxed": agg[2],
                "net_shipment": agg[3],
                "gross_profit": agg[4],
                "extra": json.loads(agg[6]) if isinstance(agg[6], str) else (agg[6] or {}),
            }

        # 字段出数统计（非空行数）
        extra_rows = (
            await db.execute(
                text(
                    "select extra from dwd_customer_analysis "
                    "where period_value=:p and calc_version=:v and is_aggregate=0"
                ),
                {"p": period, "v": version},
            )
        ).all()
        stats: dict[str, int] = {}
        for (extra,) in extra_rows:
            if isinstance(extra, str):
                extra = json.loads(extra or "{}")
            for key, value in (extra or {}).items():
                if not key.startswith("CUS-"):
                    continue
                if value in (None, "", 0, 0.0):
                    continue
                stats[key] = stats.get(key, 0) + 1
        if data["aggregate"]:
            for key, value in data["aggregate"]["extra"].items():
                if key.startswith("CUS-") and value not in (None, "", 0, 0.0):
                    stats.setdefault(key, 0)
        data["code_stats"] = stats

        top = (
            await db.execute(
                text(
                    "select customer_code, customer_name, salesman_name, order_count, "
                    "intake_untaxed, net_shipment, gross_profit, data_quality_flag, extra "
                    "from dwd_customer_analysis "
                    "where period_value=:p and calc_version=:v and is_aggregate=0 "
                    "order by intake_untaxed desc limit 3"
                ),
                {"p": period, "v": version},
            )
        ).all()
        for row in top:
            extra = json.loads(row[8]) if isinstance(row[8], str) else (row[8] or {})
            data["top_rows"].append(
                {
                    "customer_code": row[0],
                    "customer_name": row[1],
                    "salesman_name": row[2],
                    "order_count": row[3],
                    "intake_untaxed": float(row[4] or 0),
                    "net_shipment": float(row[5] or 0),
                    "gross_profit": float(row[6] or 0),
                    "data_quality_flag": row[7],
                    "fields": {k: v for k, v in extra.items() if k.startswith("CUS-")},
                }
            )

        runs = (
            await db.execute(
                text(
                    "select id, period_value, calc_version, status, customer_count, order_count, "
                    "intake_untaxed_sum, net_shipment_sum, master_customer_count, finished_at "
                    "from dwd_customer_build_run order by id desc limit 5"
                )
            )
        ).all()
        data["runs"] = [
            {
                "id": int(r[0]),
                "period": r[1],
                "version": int(r[2]),
                "status": r[3],
                "customer_count": int(r[4] or 0),
                "order_count": int(r[5] or 0),
                "intake_untaxed_sum": float(r[6] or 0),
                "net_shipment_sum": float(r[7] or 0),
                "master_customer_count": int(r[8] or 0),
                "finished_at": str(r[9] or ""),
            }
            for r in runs
        ]

        # 单客户详情样例：详情接口固定取「最新期间 + 最新版本」，这里按同样口径取一行真实数据
        latest = (
            await db.execute(
                text(
                    "select customer_code, extra from dwd_customer_analysis "
                    "where period_value=:p and calc_version=:v and is_aggregate=0 "
                    "order by intake_untaxed desc limit 1"
                ),
                {"p": data["latest_period"], "v": data["latest_version"]},
            )
        ).first()
        if latest is not None:
            latest_extra = json.loads(latest[1]) if isinstance(latest[1], str) else (latest[1] or {})
            data["latest_detail"] = {
                "period": data["latest_period"],
                "version": data["latest_version"],
                "customer_code": latest[0],
                "item": {code: latest_extra.get(code) for code, *_rest in FIELD_DEFS},
            }
    return data


def _page_sample(data: dict[str, Any], page_size: int = 3) -> dict[str, Any]:
    """按 open_controller 的真实返回结构拼「首页」样例响应（合计行不在首页，summary 为 null）。"""
    total = data["detail_rows"] + (1 if data["aggregate"] else 0)
    rows = [
        {"customer_code": item["customer_code"], "fields": item["fields"]}
        for item in data["top_rows"][:page_size]
    ]
    return {
        "code": 0,
        "msg": "查询客户分析成功",
        "status_code": 200,
        "success": True,
        "data": {
            "schema_version": SCHEMA_VERSION,
            "period_value": data["sample_period"],
            "calc_version": data["sample_version"],
            "total": total,
            "page_no": 1,
            "page_size": page_size,
            "has_more": True,
            "summary": {
                "customer_count": None,
                "order_count": None,
                "intake_untaxed_sum": None,
                "net_shipment_sum": None,
            },
            "rows": rows,
        },
    }


def _last_page_sample(data: dict[str, Any], page_size: int = 500) -> dict[str, Any]:
    """最后一页样例：合计行落在本页，summary 有值。"""
    agg = data["aggregate"] or {}
    agg_extra = agg.get("extra", {})
    total = data["detail_rows"] + (1 if data["aggregate"] else 0)
    last_page = -(-total // page_size)
    return {
        "code": 0,
        "msg": "查询客户分析成功",
        "status_code": 200,
        "success": True,
        "data": {
            "schema_version": SCHEMA_VERSION,
            "period_value": data["sample_period"],
            "calc_version": data["sample_version"],
            "total": total,
            "page_no": last_page,
            "page_size": page_size,
            "has_more": False,
            "summary": {
                "customer_count": agg_extra.get("CUS-43"),
                "order_count": agg.get("order_count"),
                "intake_untaxed_sum": float(agg.get("intake_untaxed") or 0),
                "net_shipment_sum": float(agg.get("net_shipment") or 0),
            },
            "rows": [
                {
                    "customer_code": None,
                    "fields": {
                        "is_aggregate": True,
                        "customer_code": None,
                        "customer_name": "合计",
                        "CUS-01": None,
                        "CUS-02": None,
                        "CUS-12": float(agg.get("intake_untaxed") or 0),
                        "CUS-16": float(agg.get("net_shipment") or 0),
                        "CUS-43": agg_extra.get("CUS-43"),
                    },
                }
            ],
        },
    }


def _field_table(data: dict[str, Any]) -> str:
    stats: dict[str, int] = data["code_stats"]
    detail_rows = data["detail_rows"] or 0
    lines = [
        "| 字段编码 | 字段名称 | 类型 | 分组 | 敏感 | 底稿来源 | 口径 / 说明 | 本期出数行数 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for code, name, data_type, group, sensitive, source, note in FIELD_DEFS:
        hit = stats.get(code, 0)
        if code in stats and hit == 0:
            shown = "仅合计行"
        elif hit == 0:
            shown = "—（本期未出数）"
        else:
            shown = f"{hit:,} / {detail_rows:,}"
        lines.append(
            f"| `{code}` | {name} | {data_type} | {group} | {'是' if sensitive else '否'} | {source} | {note} | {shown} |"
        )
    return "\n".join(lines)


def _code_list(group: str, data: dict[str, Any]) -> str:
    codes = [f"`{code}`" for code, _n, _t, g, *_rest in FIELD_DEFS if g == group]
    stats: dict[str, int] = data["code_stats"]
    implemented = [
        code
        for code, _n, _t, g, *_rest in FIELD_DEFS
        if g == group and stats.get(code, 0) > 0
    ]
    return f"{'、'.join(codes)}（本期出数：{'、'.join('`' + c + '`' for c in implemented) or '无'}）"


def build_doc(data: dict[str, Any]) -> str:
    agg = data["aggregate"] or {}
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    sensitive_codes = [code for code, *_rest in FIELD_DEFS if _rest[3]]
    sample = data["sample_period"] or "-"
    version = data["sample_version"] or 0
    total = data["detail_rows"] + (1 if data["aggregate"] else 0)

    doc: list[str] = []
    add = doc.append

    add(f"# {TITLE}")
    add("")
    add("> 版本：v1.0")
    add(f"> 生成时间：{generated}（**由 `backend/scripts/gen_customer_api_doc.py` 从数据库生成，请勿手工修改**）")
    add("> 接口前缀：`/open/v1`（与内部管理端 `/customer/*` 物理隔离，网关只需放行 `/open/**`）")
    add("> 对外服务地址：`https://<后台域名>`（开发环境 `http://127.0.0.1:8001`）")
    add("> 粒度：**年月 × 客户**（一行一客户一期间），字段口径 = 财务底稿 `CUS-00 ~ CUS-47`")
    add(f"> 样例期间：`{sample}`（calc_version={version}，共 {total:,} 行，样例数值为真实结果，可直接用于联调比对）")
    add("")
    add("---")
    add("")
    add("## 1. 这是什么")
    add("")
    add("本系统是**数据中台 / 指标计算层**：从 CRM、金蝶取明细，按「年月 × 客户」算成客户分析指标，")
    add("再通过 `/open/v1/customers` 交付给 BI、数据仓库、CRM/ERP、Excel 插件等外部系统。")
    add("调用方只拿 `app_id` / `app_secret` 换令牌后取数，**不需要自己拼明细、也不接触业务库**。")
    add("")
    add("对接方需要知道的三件事：")
    add("")
    add("1. **粒度**：一次取数返回「某个月 × 某客户」的指标值，一个客户一行；另有 1 行合计（`fields.CUS-01` 为空、且 `is_aggregate` 为真）。")
    add("2. **权限**：接入应用必须开通 **`allow_customer_detail`**，否则接口返回 403；成本毛利类字段另需 `allow_cost_fields`。")
    add("3. **版本**：同一期间可重算多次，`calc_version` 递增；**不传版本取该期间最新版本**，历史版本仍可按 `calc_version` 回溯。")
    add("")
    add("---")
    add("")
    add("## 2. 接入三步")
    add("")
    add("1. **申请接入**：向平台管理员申请，拿到 `app_id`、`app_secret`（密钥只下发一次），并确认：")
    add("   - 已开通客户分析查询权限 `allow_customer_detail`（**必须**，否则 403）；")
    add("   - 是否需要成本毛利类敏感字段（`allow_cost_fields`）；")
    add("   - 是否配置 IP 白名单（`ip_whitelist`）。")
    add("2. **换令牌**：`POST /open/v1/auth/token`，拿 `access_token`（默认有效期 7200 秒，过期重换即可）。")
    add("3. **拉数据**：带 `Authorization: Bearer <access_token>` 调 `GET /open/v1/customers`。")
    add("")
    add("```bash")
    add("# 1) 换令牌")
    add("curl -X POST \"https://<后台域名>/open/v1/auth/token\" \\")
    add("  -H \"Content-Type: application/json\" \\")
    add("  -d '{\"app_id\":\"<你的app_id>\",\"app_secret\":\"<你的密钥>\"}'")
    add("")
    add(f"# 2) 拉某个期间的客户分析明细（样例期间 {sample}）")
    add(f"curl -X GET \"https://<后台域名>/open/v1/customers?period_value={sample}&page_no=1&page_size=500\" \\")
    add("  -H \"Authorization: Bearer <access_token>\"")
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
    add("{ \"app_id\": \"your_app\", \"app_secret\": \"******\" }")
    add("```")
    add("")
    add("```json")
    add(
        _json(
            {
                "code": 0,
                "msg": "获取令牌成功",
                "data": {"access_token": "eyJhbGciOi...", "token_type": "Bearer", "expires_in": 7200},
                "status_code": 200,
                "success": True,
            }
        )
    )
    add("```")
    add("")
    add("业务接口统一带 `Authorization: Bearer <access_token>`。")
    add("")
    add("> **判断成功看 `code == 0` 或 `success == true`**，不要看 `code` 是否等于 200；真正的 HTTP 状态码在 `status_code` 字段。")
    add("")
    add("建议：令牌过期前 5 分钟主动续期；收到 `401` 时重新换令牌后重试一次。")
    add("")
    add("### 3.2 应用级权限（管理员侧配置）")
    add("")
    add("| 配置项 | 作用 | 默认 |")
    add("| --- | --- | --- |")
    add("| `allow_customer_detail` | **必须开启**，否则 `/open/v1/customers/**` 全部返回 403 | 关闭 |")
    add(
        f"| `allow_cost_fields` | 是否允许读取成本毛利类敏感字段（{len(sensitive_codes)} 个：{'、'.join('`' + c + '`' for c in sensitive_codes)}）；关闭时字段目录与数据都会剔除 | 关闭 |"
    )
    add("| `ip_whitelist` | 调用方 IP 白名单（逗号分隔，支持 `192.168.1.*`），不在名单内返回 403 | 空（不限） |")
    add("| `rate_limit` | 每分钟最大请求数（换令牌另有固定上限 30 次/分钟） | 600 |")
    add("| `token_ttl_seconds` | 令牌有效期（秒），最小 300 | 7200 |")
    add("")
    add("---")
    add("")
    add("## 4. 接口清单")
    add("")
    add("| 方法 | 路径 | 用途 | 需要令牌 |")
    add("| --- | --- | --- | --- |")
    add("| POST | `/open/v1/auth/token` | 应用凭证换访问令牌 | 否 |")
    add("| GET | `/open/v1/customers/fields` | 字段目录（编码、名称、类型、分组、是否敏感、schema 版本） | 是 |")
    add("| GET | `/open/v1/customers` | **客户分析明细拉取（主接口）** | 是 |")
    add("| GET | `/open/v1/customers/{customer_code}` | 单客户详情（固定取最新期间 + 最新版本） | 是 |")
    add("")
    add("> 客户维度指标**不在** `/open/v1/metrics/query` 里（该接口的 `level` 只支持 `org` / `dept` / `person` / `all`）。")
    add("> 想要「业务员维度的客户类指标」，用 `POST /open/v1/metrics/query` + `level=person`，指标编码见《业务员指标开放接口对接说明》")
    add("> （`STF-40` 新客户业绩、`STF-41` 老客户业绩、`STF-47` 总客户数量、`STF-48` 本月下单老客户数量、`STF-49` 复购率）。")
    add("")
    add("---")
    add("")
    add("## 5. 接口详情")
    add("")
    add("### 5.1 字段目录 `GET /open/v1/customers/fields`")
    add("")
    add("外部系统**先拉字段目录**，再按需拼装自己的表结构；字段增删时 `schema_version` 会变化。")
    add("")
    add("```json")
    add(
        _json(
            {
                "code": 0,
                "msg": "查询字段目录成功",
                "data": {
                    "schema_version": SCHEMA_VERSION,
                    "fields": [
                        {
                            "field_code": "CUS-12",
                            "field_name": "接单未税",
                            "data_type": "number",
                            "group": "金额",
                            "sensitive": False,
                            "excel_code": "CUS-12",
                            "source": "CRM",
                            "note": "Σ 销售订单未税金额",
                            "stored_in": "extra",
                        }
                    ],
                },
                "status_code": 200,
                "success": True,
            }
        )
    )
    add("```")
    add("")
    add("| 返回字段 | 说明 |")
    add("| --- | --- |")
    add("| `schema_version` | 字段集版本（日期串）；变化说明字段集有调整，外部可据此加列/重建表 |")
    add("| `field_code` | 字段编码 `CUS-xx`（**外部系统只认这个，不要依赖中文名**） |")
    add("| `data_type` | `string` / `number` |")
    add("| `group` | 分组：基础、维度、金额、回款、应收、成本、库存、其他 |")
    add("| `sensitive` | 是否成本毛利类敏感字段（受 `allow_cost_fields` 控制） |")
    add("| `source` | 底稿来源：系统 / CRM / ERP / 财经 / 合同 / 计算 |")
    add("| `note` | 口径说明 |")
    add("| `stored_in` | `core`（物理列）/ `extra`（扩展区），对外使用可忽略 |")
    add("")
    add("### 5.2 明细拉取 `GET /open/v1/customers`")
    add("")
    add("**请求参数**")
    add("")
    add("| 参数 | 类型 | 必填 | 默认 | 说明 |")
    add("| --- | --- | --- | --- | --- |")
    add(f"| `period_value` | string | 否 | 最新期间（`{data['latest_period']}`） | 期间 `YYYY-MM`，按所属月份归档 |")
    add(f"| `calc_version` | int | 否 | 该期间最新版本（当前 `{data['latest_version']}`） | 计算版本，最新版本号随时间回补递增 |")
    add("| `customer_code` | string | 否 | - | 客户编码，**模糊匹配** |")
    add("| `customer_name` | string | 否 | - | 客户名称，**模糊匹配** |")
    add("| `salesman_code` | string | 否 | - | 业务员编码，**精确匹配**（仅供参考筛选，业务字段里出姓名） |")
    add("| `order_type` | string | 否 | - | 订单类型，模糊匹配（如 `批量`、`打样`） |")
    add("| `product_line` | string | 否 | - | 产品线大类，模糊匹配 |")
    add("| `include_aggregate` | bool | 否 | `true` | 是否返回合计行（`is_aggregate=true` 的那一行） |")
    add("| `page_no` | int | 否 | 1 | 页码 |")
    add("| `page_size` | int | 否 | 500 | 每页条数，**上限 2000** |")
    add("")
    add("> 说明：`order_type` / `product_line` 存的是「多值拼接串」（如 `批量/打样`），按包含关系过滤；")
    add("> 因此这两个条件会先在数据库取页、再在应用层过滤，**建议与 `period_value` 一起使用**，避免分页漏行。")
    add("")
    add("**响应**")
    add("")
    add("**排序**：明细行在前、**合计行固定排在结果集最后一行**（先按 `is_aggregate` 升序，再按 `CUS-12` 接单未税降序）。")
    add("")
    add("**样例 1：首页**（`page_size=3`，真实返回，字段值取自 2026-09 v6）")
    add("")
    add("```json")
    add(_json(_page_sample(data)))
    add("```")
    add("")
    add("> 注意：**`summary` 只有在当前页里出现合计行时才有值**（合计行在最后一页），首页请求会返回 4 个 `null`。")
    add("> 需要期间汇总时用「样例 2」的取法，不要依赖首页的 `summary`。")
    add(">")
    add("> 样例里省略了值为 `null` 的键；**实际返回每一行都带全部 47 个 `CUS-xx` 键 + 内部核心列（单行 66 个键）**。")
    add("")
    add("**样例 2：最后一页**（`page_size=500`，合计行落在本页）")
    add("")
    add("```json")
    add(_json(_last_page_sample(data)))
    add("```")
    add("")
    add("取合计行的两种做法：")
    add("")
    add("1. 直接翻到最后一页：`page_no = ceil(total / page_size)`（本期样例 total=21,576、page_size=500 → 第 44 页）；")
    add("2. 只要合计不要明细时，外部系统按 `data_quality_flag == \"aggregate\"` 筛出该行即可（`include_aggregate` 必须保持 `true`）。")
    add("")
    add("| 返回字段 | 说明 |")
    add("| --- | --- |")
    add("| `data.schema_version` | 字段集版本 |")
    add("| `data.period_value` / `data.calc_version` | 实际命中的期间与版本（**分页请求之间请带上这两个值，防止重算换版导致翻页串行**） |")
    add("| `data.total` | 本次条件下总行数（含合计行；`include_aggregate=false` 时不含） |")
    add("| `data.has_more` | 是否还有下一页（等价于 `page_no * page_size < total`） |")
    add("| `data.summary` | 期间汇总：`customer_count`（`CUS-43` 客户主档总数）、`order_count`、`intake_untaxed_sum`（`CUS-12`）、`net_shipment_sum`（`CUS-16`）；**当页无合计行时四项均为 `null`** |")
    add("| `data.rows[]` | 每行 `{ customer_code, fields }`；**所有 CUS-xx 指标值都在 `fields` 里**，按字段编码取值 |")
    add("")
    add("合计行识别方式：`fields[\"is_aggregate\"] == true`（或 `data_quality_flag == \"aggregate\"`），该行 `customer_code`、")
    add("`CUS-01`、`CUS-02` 都为空串/`null`，中文名只出现在核心列 `customer_name`（值为 `合计`）；其 `CUS-12` / `CUS-16` / `CUS-43` 即公司合计。")
    add("")
    add("字段取值约定：`fields` 里 **47 个 `CUS-xx` 键恒定存在**，该口径本期不产出时值为 `null`（不是缺键、也不是 0），")
    add("外部建表请统一按「键存在、值可空」处理。")
    add("")
    add("除 `CUS-xx` 外，`fields` 里还有几个**内部核心列**，可一并使用（样例中为简洁未展开）：")
    add("")
    add("| 核心列 | 说明 |")
    add("| --- | --- |")
    add("| `customer_code` / `customer_name` | 客户编码 / 名称（与 `CUS-01` / `CUS-02` 同值；合计行为 `null` / `合计`） |")
    add("| `is_aggregate` | 是否合计行（`true` 为合计） |")
    add("| `order_count` | 接单量（订单条数） |")
    add("| `intake_untaxed` / `net_shipment` | 接单未税 / 对外出货净额（与 `CUS-12` / `CUS-16` 同值） |")
    add("| `gross_profit` / `contribution_margin` | 毛利 / 边际贡献（**核心列，不受 `allow_cost_fields` 裁剪**，见 §9） |")
    add("| `data_quality_flag` | 行类型：`ok` / `ar_only` / `aggregate` |")
    add("| `salesman_code` / `salesman_name` | 业务员编码 / 姓名（编码仅供筛选追溯） |")
    add("| `period_value` / `calc_version` / `customer_id` / `id` | 期间、版本与内部主键 |")
    add("")
    add("### 5.3 单客户详情 `GET /open/v1/customers/{customer_code}`")
    add("")
    add("固定取**最新期间 + 最新版本**（不接受 `period_value`），返回该客户的 `item` 与字段目录 `columns`：")
    add("")
    add("```json")
    detail = data.get("latest_detail") or {}
    add(
        _json(
            {
                "code": 0,
                "msg": "查询客户详情成功",
                "data": {
                    "schema_version": SCHEMA_VERSION,
                    "period_value": detail.get("period"),
                    "item": detail.get("item", {}),
                    "columns": [
                        {
                            "field_code": "CUS-12",
                            "field_name": "接单未税",
                            "data_type": "number",
                            "group": "金额",
                            "sensitive": False,
                            "excel_code": "CUS-12",
                            "source": "CRM",
                            "note": "Σ 销售订单未税金额",
                            "stored_in": "extra",
                        }
                    ],
                },
                "status_code": 200,
                "success": True,
            }
        )
    )
    add("```")
    add("")
    if detail:
        add(
            f"> 上例为 `GET /open/v1/customers/{detail.get('customer_code')}` 的真实返回（期间 `{detail.get('period')}`，"
            f"最新版本 v{detail.get('version')}）：`item` 同样含 47 个 `CUS-xx` 键（未产出口径为 `null`）+ 内部核心列。"
        )
        add("")
    add("> **客户在该期间没有数据时返回 `code=-1`、HTTP 500**（`msg` 形如「客户 X 在期间 Y 没有数据」）；")
    add("> 外部系统请先按 `customer_code` 从明细接口确认该客户存在，再取详情，并按 `success=false` 兜底。")
    add("")
    add("---")
    add("")
    add("## 6. 字段清单（CUS-00 ~ CUS-47）")
    add("")
    add(f"“本期出数行数”统计自样例期间 `{sample}`（calc_version={version}，明细行 {data['detail_rows']:,} 行）中该字段**非空**的行数；")
    add("`—（本期未出数）` 表示该字段口径待上游确认、本期不产出，外部系统请留空处理。")
    add("")
    add(_field_table(data))
    add("")
    add("### 6.1 分组速查")
    add("")
    add("| 分组 | 含义 | 字段 |")
    add("| --- | --- | --- |")
    for group, note in GROUP_NOTES:
        add(f"| {group} | {note} | {_code_list(group, data)} |")
    add("")
    add("### 6.2 关键口径")
    add("")
    add("| 字段 | 口径 |")
    add("| --- | --- |")
    add("| `CUS-12` 接单未税 | Σ 当期有效订单未税金额（内贸 `remove_taxes_freight` + 外贸 `receivable_CNY`，status=384），按客户聚合 |")
    add("| `CUS-13` 货物出货未税 | Σ 发货数量 × 订单未税单价，按发货单审核月归属 |")
    add("| `CUS-16` 对外出货净额 | `CUS-13 + CUS-14`（设计服务收入）`+ CUS-15`（退货退款，负数） |")
    add("| `CUS-17` 营销结算收入10% | `CUS-16 × 10%` |")
    add("| `CUS-21` 应收余额 / `CUS-22` 逾期应收 | 金蝶应收账龄分析表时点余额，按客户往来单位匹配；`CUS-23` 逾期率 = `CUS-22 ÷ CUS-21` |")
    add("| `CUS-28` 毛利 | `CUS-16 − 实际成本`（标准成本口径，未出货订单成本已计入，月度合计可能为负） |")
    add("| `CUS-30` 边际贡献 | `CUS-17 − (CUS-16 ÷ REV-01) × CM-01`，按当期公司口径指标分摊 |")
    add("| `CUS-32` 结算收益 | `CUS-30 − (CUS-16 ÷ REV-01) × CM-04 − (CUS-16 ÷ REV-01) × PER-02` |")
    add("| `CUS-40` 复购率 | 期间内重复下单客户占比（本月有订单且本月前已有订单） |")
    add("| `CUS-42` 客单价 | `CUS-12 ÷ 接单量` |")
    add("| `CUS-43` 总客户数 | CRM 客户主档时点总数，**只在合计行输出** |")
    add("")
    add("多值字段（`CUS-05` 贸易类型、`CUS-09` 产品线大类、`CUS-10` SKU、`CUS-11` 订单类型）同一客户当月多个取值时，")
    add("按「金额降序、同额名称升序、`/` 分隔」拼接，例如 `批量/打样`；`CUS-08` 业务员同样拼接，且**只出姓名**（如 `李新晖`）。")
    add("")
    add("### 6.3 行集与数据质量标记")
    add("")
    add("| `data_quality_flag` | 含义 | 本期行数 |")
    add("| --- | --- | --- |")
    flag_note = {
        "ok": "本月有订单的正常行（订单类 + 应收类字段均有效）",
        "ar_only": "本月无订单但有应收余额/逾期应收：订单类字段为 0，应收类字段照出",
        "aggregate": "合计行",
    }
    for flag, count in data["quality_flags"]:
        add(f"| `{flag}` | {flag_note.get(flag, '-')} | {count:,} |")
    add("")
    add("---")
    add("")
    add("## 7. 分页、增量与对账")
    add("")
    add("1. **分页**：`page_size` 上限 2000；翻页期间固定 `period_value` + `calc_version`，用 `has_more` 判断结束。")
    add("2. **增量**：本接口按「期间 + 版本」全量分页，没有时间戳增量。做法是**期间级替换**：")
    add("   - 首次同步：对需要的历史期间逐期拉全量落库；")
    add("   - 日常同步：每天拉当月（`period_value` 不传即最新期间），按 `customer_code` 覆盖写入；")
    add("   - 月末定稿：拉上月，`calc_version` 变化即视为数据已重算，重新覆盖该期间全量。")
    add("3. **对账**（合计行在结果集最后一行，见 §5.2 样例 2）：")
    add("   - 明细行 `CUS-12` 求和 = 合计行 `CUS-12` = `summary.intake_untaxed_sum`；本期样例 "
        f"{_num(float(agg.get('intake_untaxed') or 0))}。")
    add(f"   - 明细行 `CUS-16` 求和 = 合计行 `CUS-16` = `summary.net_shipment_sum`；本期样例 {_num(float(agg.get('net_shipment') or 0))}。")
    add("   - 明细行 `CUS-16` ≠ 明细行 `CUS-13` 求和（还含设计服务收入与退货退款），核对时用 `CUS-16`。")
    add("   - `summary.customer_count`（`CUS-43`）是客户主档时点总数，**不等于**明细行数，不要拿它做行数校验。")
    add("   - `total` 含合计行 → 明细行数 = `total − 1`（`include_aggregate=false` 时 `total` 即明细行数）。")
    add("4. **重算节奏**：每天 02:20 重算最近 3 期（含当月，接在订单全链路 02:10 之后）；每月 1 日先结转上月再回补最近 3 期。")
    add("   写入按「期间 + 版本」全量替换，外部按 `calc_version` 变化触发覆盖即可，不会读到半量数据。")
    add("")
    add("最近 5 次构建批次（同库 `dwd_customer_build_run`）：")
    add("")
    add("| 批次 | 期间 | 版本 | 状态 | 客户数 | 订单数 | 接单未税 | 出货净额 | 客户主档 | 完成时间 |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for run in data["runs"]:
        add(
            f"| {run['id']} | {run['period']} | v{run['version']} | {run['status']} | {run['customer_count']:,} | "
            f"{run['order_count']:,} | {_num(run['intake_untaxed_sum'])} | {_num(run['net_shipment_sum'])} | "
            f"{run['master_customer_count']:,} | {run['finished_at']} |"
        )
    add("")
    add("---")
    add("")
    add("## 8. 错误码")
    add("")
    add("| `code` | HTTP | 场景 | 处理建议 |")
    add("| --- | --- | --- | --- |")
    add("| `0` | 200 | 成功 | - |")
    add("| `40100` | 401 | 未带令牌 / 令牌过期或失效 / 应用不存在 | 重新换令牌后重试一次 |")
    add("| `40101` | 403 | 应用已停用 / 凭证过期 / 未开通 `allow_customer_detail` / IP 不在白名单 | 联系管理员开通或调整配置 |")
    add("| `40103` | 429 | 调用频率超限 | 按 `msg` 提示的秒数退避重试 |")
    add("| `1` | 422 | 查询参数不合法（如 `page_size` > 2000、`page_no` < 1），`data` 为逐字段校验明细 | 修正参数后重试 |")
    add("| `-1` | 500 | 单客户详情：该客户在最新期间没有数据 | 先确认客户编码存在，再取详情 |")
    add("")
    add("失败响应示例（未开通权限）：")
    add("")
    add("```json")
    add(
        _json(
            {
                "code": 40101,
                "msg": "应用未开通客户分析查询权限",
                "data": None,
                "status_code": 403,
                "success": False,
            }
        )
    )
    add("```")
    add("")
    add("参数校验失败示例（`page_size=9999`）：")
    add("")
    add("```json")
    add(
        _json(
            {
                "code": 1,
                "msg": "Input should be less than or equal to 2000",
                "data": [
                    {
                        "type": "less_than_equal",
                        "loc": ["query", "page_size"],
                        "msg": "Input should be less than or equal to 2000",
                        "input": "9999",
                    }
                ],
                "status_code": 422,
                "success": False,
            }
        )
    )
    add("```")
    add("")
    add("---")
    add("")
    add("## 9. 常见问题")
    add("")
    add("| 现象 | 原因 | 处理 |")
    add("| --- | --- | --- |")
    add("| 全部接口 403 | 应用未开通 `allow_customer_detail` | 让管理员在开放应用里勾选后重试 |")
    add("| 字段目录少了成本毛利字段 | 未开通 `allow_cost_fields` | 按需申请；开通后字段目录与数据同时可见 |")
    add("| 未开通 `allow_cost_fields`，但 `fields.gross_profit` / `fields.contribution_margin` 仍有值 | 这两个是核心列，裁剪开关目前只作用于 `CUS-xx` 成本字段 | 需要完全屏蔽时联系管理员评估；对接方入库时按需忽略这两列 |")
    add("| 某字段整列为空 | 该字段口径待上游补数据（见 §6 出数行数为 `—`） | 以 0 或空值落库，不要按 0 参与比率分母 |")
    add("| `data.summary` 四项全是 `null` | 合计行不在当前页（合计行固定排在结果集最后一行） | 翻到最后一页取，或自己按明细行求和；见 §5.2 |")
    add("| 47 个 `CUS-xx` 键都在、但很多值是 `null` | 未产出口径统一以 `null` 占位（键恒定存在） | 按可空列建表；比率类字段遇 `null` 按「无数据」处理，不按 0 |")
    add("| 明细行数远大于订单客户数 | 本期行集含「本月无订单但有应收」的客户（`ar_only`） | 按 `data_quality_flag` 过滤：只看订单类用 `ok` |")
    add("| 翻页时同一客户出现两次 | 期间被重算，`calc_version` 变了 | 翻页期间固定 `calc_version` |")
    add("| `CUS-43` 总客户数在明细行取不到 | 该字段只写合计行 | 取合计行（`is_aggregate=true`）或最后一页的 `summary.customer_count` |")
    add("| 单客户详情返回 500 / `code=-1` | 该客户在最新期间没有数据（详情接口不接受 `period_value`） | 先用明细接口按 `customer_code` 确认存在，再取详情 |")
    add("")
    add("---")
    add("")
    add("## 10. 附：字段口径来源")
    add("")
    add("- 字段注册表（唯一事实来源）：`backend/app/modules/customer/fields.py`")
    add("- 构建逻辑：`backend/app/modules/customer/build.py`（订单全链路宽表 → 客户聚合 → CUS 指标）")
    add("- 开放接口：`backend/app/modules/customer/open_controller.py`")
    add("- 报表方案与逐项口径：`docs/营销中心客户分析报表方案.md`")
    add("- 本文件生成脚本：`backend/scripts/gen_customer_api_doc.py`（重跑即可刷新数据与字段）")
    add("- 接口冒烟校验：`backend/scripts/check_customer_open_api.py`（15 项断言：字段目录、summary 语义、合计行位置、敏感字段裁剪、错误码）")
    add("")
    return "\n".join(doc)


async def main() -> None:
    parser = argparse.ArgumentParser(description="生成客户分析月度指标开放接口对接说明")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help=f"输出路径，默认 {DEFAULT_OUTPUT}")
    args = parser.parse_args()

    data = await collect()
    if not data["periods"]:
        raise SystemExit("dwd_customer_analysis 无数据，请先执行 scripts/run_customer_build.py")
    content = build_doc(data)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    await async_engine.dispose()
    print(
        f"已生成 {output}（字段 {len(FIELD_DEFS)} 个，样例期间 {data['sample_period']} v{data['sample_version']}，"
        f"明细行 {data['detail_rows']:,}）"
    )


if __name__ == "__main__":
    asyncio.run(main())
