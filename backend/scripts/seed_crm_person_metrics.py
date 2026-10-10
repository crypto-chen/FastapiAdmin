"""初始化营销中心「业务员分析」指标（连接 + 元数据 + 同步任务 + 指标定义）。

数据源：CRM《订单分析接口文档》《订单发货分析接口文档》，域名
``http://crmapi.yonggubox.com``，均为 ``GET``、**无需登录/令牌**，
入参为 ``type``（1=内贸 2=外贸）+ ``month``（``YYYY-MM``）。

口径（已确认）：
- 业务员 = 订单**下单人** ``create_id``；映射链
  ``create_id`` → ``source_person``（``source_type='crm'``，``raw_json.id``）
  → 工号（``raw_json.number``）→ ``master_person.code``（标准人员）。
- 接单月 = 订单创建月 ``createtime``；出货月 = 发货单审核月 ``check_date``。
- 金额：内贸 ``remove_taxes_freight``（未税不含运费）、外贸 ``receivable_CNY``。
- 只统计有效订单 ``status=384``，作废（``status=522``）剔除；
  离职业务员的历史数据保留（不按人员在职状态过滤）。

三个指标（STF 为财务底稿科目编码，写入 ``metric_def.excel_code``）：
- ``marketing_person_order_intake_untaxed`` **接单未税** STF-13
  = Σ(内贸 ``remove_taxes_freight`` + 外贸 ``receivable_CNY``)，按 ``create_id`` 分组。
- ``marketing_person_goods_shipment_untaxed`` **货物出货未税** STF-14
  = Σ(发货数量 × 该订单未税单价)，发货明细按 ``order_number`` 关联订单明细取业务员与单价；
  订单明细按 ``lookback_periods``（默认 12 期）回看，因为部分订单在发货月之前创建。
- ``marketing_person_design_service_income`` **设计服务收入** STF-15
  = Σ(内贸 ``design_remove_taxes_freight`` + 外贸 ``design_cost``)，按 ``create_id`` 分组。

结果落 ``metric_value``：一行公司合计（``dept_code`` 为空）+ 每业务员一行
（``dept_code``/``person_code`` = 业务员编码，``dept_name``/``person_name`` = 姓名），
对外经 ``POST /open/v1/metrics/query`` 以 ``level=person`` 提供。

月指标，每日 02:30 重算当月；每月 1 日强制重拉上月并重算上月。

用法：
    python scripts/seed_crm_person_metrics.py
    python scripts/seed_crm_person_metrics.py --base-url http://crmapi.yonggubox.com
"""

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.crm.client import DEFAULT_BASE_URL  # noqa: E402
from app.modules.crm.model import CrmConnectionModel  # noqa: E402
from app.modules.metadata.model import (  # noqa: E402
    MetaSyncJobModel,
    SourceObjectModel,
    SourceSystemModel,
)
from app.modules.metadata.sync import register_meta_sync_job  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CONNECTION_NAME = "CRM 默认连接"
SOURCE_SYSTEM_CODE = "crm"
SYNC_CRON = "0 0 2 * * ?"  # 每天 02:00，早于指标调度的 02:30
CATEGORY = "营销中心-业务员"

# 整月取值：orderAnalyze 按订单创建月、orderShipments 按发货单审核月，均传 ``month``
MONTH_PARAMS: dict = {"month": "{{ now.strftime('%Y-%m') }}"}

ORDER_PATH = "/hs/order/orderAnalyze"
SHIPMENT_PATH = "/hs/order/orderShipments"
CUSTOMER_PATH = "/hs/customer/getCusotmerList"
QUOTE_PATH = "/hs/quote/getQuoteList"
RETURN_DETAIL_PATH = "/hs/getReturnOrderDetail"

# 整月闭区间（dateRange 写法，供按订单创建时间过滤的接口使用）
MONTH_DATE_RANGE: dict = {
    "dateRange": [
        "{{ now.replace(day=1).strftime('%Y-%m-%d') }}",
        "{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime('%Y-%m-%d') }}",
    ]
}

# 客户列表是「当前全量快照」（无时间参数、每次约 2.5 万行），按周同步即可；
# 指标计算遇到该期间没有批次时会自动按期间回补一次。
CUSTOMER_CRON = "0 0 2 ? * MON"

# 一个来源对象一条：同一接口按 type 拆成内贸/外贸两条（来源对象 code 唯一）
SOURCE_OBJECTS = [
    {"code": f"{ORDER_PATH}?type=1", "name": "CRM 订单明细（内贸）"},
    {"code": f"{ORDER_PATH}?type=2", "name": "CRM 订单明细（外贸）"},
    {"code": f"{SHIPMENT_PATH}?type=1", "name": "CRM 发货明细（内贸）"},
    {"code": f"{SHIPMENT_PATH}?type=2", "name": "CRM 发货明细（外贸）"},
    {
        "code": CUSTOMER_PATH,
        "name": "CRM 客户列表（业务员客户数）",
        "with_month": False,  # 接口无时间参数：返回客户表当前全量
        "cron": CUSTOMER_CRON,
    },
    {"code": QUOTE_PATH, "name": "CRM 报价单明细（业务员报价）"},
    {
        "code": RETURN_DETAIL_PATH,
        "name": "CRM 退款订单明细（业务员退货退款）",
        "with_month": False,
        "request": MONTH_DATE_RANGE,  # 该接口用 dateRange，不认 month
        # 该路由曾一度 404（未发布），2026-10-09 已发布可用；status=0 正常参与每日同步
        "status": 0,
    },
]

# 有效订单过滤：status_field/status_allow 由引擎解释，剔除作废单 522
VALID_ORDER = {"status_field": "status", "status_allow": ["384"]}

# 订单类型 / 新老客户拆分（CRM 订单明细字段）：order_type 1=批量 2=打样 3=零售；is_new 1=新客户 2=老客户
SAMPLE_ORDER = {"row_filters": [{"field": "order_type", "op": "equals", "value": "2"}]}
BATCH_ORDER = {"row_filters": [{"field": "order_type", "op": "equals", "value": "1"}]}
NEW_CUSTOMER = {"row_filters": [{"field": "is_new", "op": "equals", "value": "1"}]}
OLD_CUSTOMER = {"row_filters": [{"field": "is_new", "op": "equals", "value": "2"}]}

DIMENSIONS = {"org": False, "dept": True, "person": True}


def intake_components(extra: dict | None = None) -> list[dict]:
    """接单类指标的内贸/外贸两个口径分支（金额字段不同，可选附加过滤条件）。"""
    return [
        {
            "label": "内贸",
            "source_object_code": f"{ORDER_PATH}?type=1",
            "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
            **(extra or {}),
        },
        {
            "label": "外贸",
            "source_object_code": f"{ORDER_PATH}?type=2",
            "amount_terms": [{"field": "receivable_CNY", "sign": 1}],
            **(extra or {}),
        },
    ]

METRICS = [
    {
        "code": "marketing_person_order_intake_untaxed",
        "name": "营销中心业务员接单未税",
        "excel_code": "STF-13",
        "rule": "接单未税（元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，"
        "只统计有效订单 status=384（剔除作废 522），按订单创建月 createtime 落到当期，"
        "按业务员（下单人 create_id）分组。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "unit": "元",
            **VALID_ORDER,
            "components": [
                {
                    "label": "内贸",
                    "source_object_code": f"{ORDER_PATH}?type=1",
                    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
                },
                {
                    "label": "外贸",
                    "source_object_code": f"{ORDER_PATH}?type=2",
                    "amount_terms": [{"field": "receivable_CNY", "sign": 1}],
                },
            ],
        },
    },
    {
        "code": "marketing_person_goods_shipment_untaxed",
        "name": "营销中心业务员货物出货未税",
        "excel_code": "STF-14",
        "rule": "货物出货未税（元）= Σ(发货数量 send_qty × 该订单未税单价)，"
        "未税单价 = 订单未税金额 ÷ 订单数量（内贸 remove_taxes_freight、外贸 receivable_CNY，status=384）；"
        "发货月按发货单审核月 check_date，业务员取所属订单的下单人 create_id；"
        "订单明细按 12 期回看，覆盖发货月之前创建的订单。",
        "measures": {
            "kind": "crm_shipment_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "lookback_periods": 12,
            "backfill_lookback": True,
            "unit": "元",
            "components": [
                {
                    "label": "内贸",
                    "shipment_source_object_code": f"{SHIPMENT_PATH}?type=1",
                    "order_source_object_code": f"{ORDER_PATH}?type=1",
                    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
                    **VALID_ORDER,
                },
                {
                    "label": "外贸",
                    "shipment_source_object_code": f"{SHIPMENT_PATH}?type=2",
                    "order_source_object_code": f"{ORDER_PATH}?type=2",
                    "amount_terms": [{"field": "receivable_CNY", "sign": 1}],
                    **VALID_ORDER,
                },
            ],
        },
    },
    {
        "code": "marketing_person_design_service_income",
        "name": "营销中心业务员设计服务收入",
        "excel_code": "STF-15",
        "rule": "设计服务收入（元）= Σ(内贸 design_remove_taxes_freight + 外贸 design_cost)，"
        "只统计有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组；"
        "当月无设计服务收入的业务员不输出行（按 0 处理）。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "unit": "元",
            **VALID_ORDER,
            "components": [
                {
                    "label": "内贸",
                    "source_object_code": f"{ORDER_PATH}?type=1",
                    "amount_terms": [{"field": "design_remove_taxes_freight", "sign": 1}],
                },
                {
                    "label": "外贸",
                    "source_object_code": f"{ORDER_PATH}?type=2",
                    "amount_terms": [{"field": "design_cost", "sign": 1}],
                },
            ],
        },
    },
    {
        "code": "marketing_person_goods_shipment_qty",
        "name": "营销中心业务员出货数量",
        "excel_code": "STF-68",
        "rule": "出货数量 = Σ发货数量 send_qty，发货月按发货单审核月 check_date，"
        "业务员取所属订单的下单人 create_id；订单明细按 12 期回看以取得业务员归属。",
        "measures": {
            "kind": "crm_shipment_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "value_mode": "qty",
            "lookback_periods": 12,
            "backfill_lookback": True,
            "unit": "个",
            "components": [
                {
                    "label": "内贸",
                    "shipment_source_object_code": f"{SHIPMENT_PATH}?type=1",
                    "order_source_object_code": f"{ORDER_PATH}?type=1",
                    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
                    **VALID_ORDER,
                },
                {
                    "label": "外贸",
                    "shipment_source_object_code": f"{SHIPMENT_PATH}?type=2",
                    "order_source_object_code": f"{ORDER_PATH}?type=2",
                    "amount_terms": [{"field": "receivable_CNY", "sign": 1}],
                    **VALID_ORDER,
                },
            ],
        },
    },
    {
        "code": "marketing_person_order_push_untaxed",
        "name": "营销中心业务员下推金额",
        "excel_code": "STF-23",
        "rule": "下推金额（元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，"
        "取已下推订单（erp_push_status=1）且 **下推时间 erp_push_date 落在当期**，"
        "只统计有效订单 status=384，按业务员（下单人 create_id）分组；"
        "订单明细按 12 期回看（下推月通常晚于建单月）。",
        "measures": {
            "kind": "crm_order_push_person",
            "group_by": "person",
            "person_field": "create_id",
            "stat": "amount",
            "push_status_field": "erp_push_status",
            "push_status_allow": ["1"],
            "push_date_field": "erp_push_date",
            "cycle_start_field": "createtime",
            "lookback_periods": 12,
            "backfill_lookback": True,
            "unit": "元",
            **VALID_ORDER,
            "components": [
                {
                    "label": "内贸",
                    "source_object_code": f"{ORDER_PATH}?type=1",
                    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
                },
                {
                    "label": "外贸",
                    "source_object_code": f"{ORDER_PATH}?type=2",
                    "amount_terms": [{"field": "receivable_CNY", "sign": 1}],
                },
            ],
        },
    },
    {
        "code": "marketing_person_order_push_period",
        "name": "营销中心业务员下推周期",
        "excel_code": "STF-24",
        "rule": "下推周期（天）= Σ(下推时间 erp_push_date − 建单时间 createtime) ÷ 下推订单数，"
        "按业务员分别计算（订单数加权，不是各订单周期的简单平均）：取已下推订单"
        "（erp_push_status=1）且下推时间落在当期、订单有效 status=384；"
        "公司合计同样按「天数和 ÷ 订单数和」加权。",
        "measures": {
            "kind": "crm_order_push_person",
            "group_by": "person",
            "person_field": "create_id",
            "stat": "period_days",
            "push_status_field": "erp_push_status",
            "push_status_allow": ["1"],
            "push_date_field": "erp_push_date",
            "cycle_start_field": "createtime",
            "lookback_periods": 12,
            "backfill_lookback": True,
            "unit": "天",
            **VALID_ORDER,
            "components": [
                {
                    "label": "内贸",
                    "source_object_code": f"{ORDER_PATH}?type=1",
                    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
                },
                {
                    "label": "外贸",
                    "source_object_code": f"{ORDER_PATH}?type=2",
                    "amount_terms": [{"field": "receivable_CNY", "sign": 1}],
                },
            ],
        },
    },
    {
        "code": "marketing_person_sample_order_intake_untaxed",
        "name": "营销中心业务员打样接单业绩（未税）",
        "excel_code": "STF-38",
        "rule": "打样接单业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，"
        "取订单类型 order_type=2（打样）、有效订单 status=384，按订单创建月 createtime 落到当期，"
        "按业务员（下单人 create_id）分组。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "unit": "元",
            **VALID_ORDER,
            **SAMPLE_ORDER,
            "components": intake_components(SAMPLE_ORDER),
        },
    },
    {
        "code": "marketing_person_batch_order_intake_untaxed",
        "name": "营销中心业务员批量接单业绩（未税）",
        "excel_code": "STF-39",
        "rule": "批量接单业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，"
        "取订单类型 order_type=1（批量）、有效订单 status=384，按订单创建月 createtime 落到当期，"
        "按业务员（下单人 create_id）分组。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "unit": "元",
            **VALID_ORDER,
            **BATCH_ORDER,
            "components": intake_components(BATCH_ORDER),
        },
    },
    {
        "code": "marketing_person_new_customer_intake_untaxed",
        "name": "营销中心业务员新客户业绩（未税）",
        "excel_code": "STF-40",
        "rule": "新客户业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，"
        "取客户标识 is_new=1（新客户）、有效订单 status=384，按订单创建月 createtime 落到当期，"
        "按业务员（下单人 create_id）分组。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "unit": "元",
            **VALID_ORDER,
            **NEW_CUSTOMER,
            "components": intake_components(NEW_CUSTOMER),
        },
    },
    {
        "code": "marketing_person_old_customer_intake_untaxed",
        "name": "营销中心业务员老客户业绩（未税）",
        "excel_code": "STF-41",
        "rule": "老客户业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，"
        "取客户标识 is_new=2（老客户）、有效订单 status=384，按订单创建月 createtime 落到当期，"
        "按业务员（下单人 create_id）分组。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "unit": "元",
            **VALID_ORDER,
            **OLD_CUSTOMER,
            "components": intake_components(OLD_CUSTOMER),
        },
    },
    {
        "code": "marketing_person_old_customer_order_count",
        "name": "营销中心业务员本月下单老客户数量",
        "excel_code": "STF-48",
        "rule": "本月下单老客户数量（家）= 当期订单中 **is_new=2（老客户）** 的客户去重数，"
        "按订单创建月 createtime 落当期，只统计有效订单 status=384，按业务员（下单人 create_id）分组；"
        "同一客户当月多单只算一次、跨内贸外贸也只算一次；公司合计取全部业务员的客户并集。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "value_mode": "count_customers",
            "customer_field": "customer",
            "unit": "家",
            **VALID_ORDER,
            **OLD_CUSTOMER,
            "components": intake_components(OLD_CUSTOMER),
        },
    },
    {
        "code": "marketing_person_total_customer_count",
        "name": "营销中心业务员总客户数量",
        "excel_code": "STF-47",
        "rule": "总客户数量（家）= 客户表中**所属业务员（principal_id）**为本业务员的客户数量；"
        "来源 CRM 客户列表接口（未分页全量，当前快照），未分配业务员（principal_id 为空）的客户不计入；"
        "该指标是时点快照口径，历史期间取重算时点最新的客户列表批次。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "principal_id",
            "value_mode": "count_customers",
            "customer_field": "id",
            "exclude_empty_person": True,
            "unit": "家",
            # 客户表没有订单状态字段：不按 status 过滤
            "status_field": None,
            "status_allow": [],
            "components": [
                {
                    "label": "客户列表",
                    "source_object_code": CUSTOMER_PATH,
                }
            ],
        },
    },
    {
        "code": "marketing_person_repurchase_rate",
        "name": "营销中心业务员复购率",
        "excel_code": "STF-49",
        "rule": "复购率（%）= 本月下单老客户数量 ÷ 总客户数量 × 100%，**按业务员分别计算**"
        "（分子为「营销中心业务员本月下单老客户数量」STF-48，分母为「营销中心业务员总客户数量」STF-47，"
        "同为当月、同一业务员）；分母为 0 的业务员不输出行；"
        "公司合计 = Σ分子 ÷ Σ分母 × 100。",
        "measures": {
            "kind": "metric_ratio_person",
            "numerator_metric_codes": ["marketing_person_old_customer_order_count"],
            "denominator_metric_codes": ["marketing_person_total_customer_count"],
            "ratio_scale": 100,
            "unit": "%",
        },
    },
    {
        "code": "marketing_person_quote_count",
        "name": "营销中心业务员报价次数",
        "excel_code": "STF-10",
        "rule": "报价次数（次）= 当期已审核报价单（quote_bills.status='E'）条数，"
        "按报价日期 date 落在当期，按业务员（报价单 create_id）分组。",
        "measures": {
            "kind": "crm_quote_person",
            "group_by": "person",
            "person_field": "create_id",
            "stat": "count",
            "unit": "次",
            "components": [{"label": "报价单", "source_object_code": QUOTE_PATH}],
        },
    },
    {
        "code": "marketing_person_quote_success_rate",
        "name": "营销中心业务员报价成功率",
        "excel_code": "STF-11",
        "rule": "报价成功率（%）= 已转订单的报价单数 ÷ 报价次数 × 100%，按业务员分别计算"
        "（接口 transformation=1 表示该报价单已关联有效内贸/外贸订单，status=384）；"
        "公司合计 = Σ已转单数 ÷ Σ报价次数 × 100；报价次数为 0 的业务员不输出行。",
        "measures": {
            "kind": "crm_quote_person",
            "group_by": "person",
            "person_field": "create_id",
            "stat": "success_rate",
            "transformation_field": "transformation",
            "transformation_allow": ["1"],
            "unit": "%",
            "components": [{"label": "报价单", "source_object_code": QUOTE_PATH}],
        },
    },
    {
        "code": "marketing_person_quote_gross_profit_rate",
        "name": "营销中心业务员报价毛利率",
        "excel_code": "STF-12",
        "rule": "报价毛利率（%）=（报价未税 −（材料成本 + 加工费））÷ 报价未税 × 100%，按业务员分别计算"
        "（公司合计 = Σ(未税 − 料工费) ÷ Σ未税 × 100）；"
        "接口字段 not_tax_all_quote_amount = 报价未税总价、material_labor_cost = 料工费；"
        "**注意**：当前接口的 material_labor_cost = materialCost × qty（含附件费、**不含** processCost 加工费），"
        "待 CRM 侧改成 (materialCost + processCost) × qty 后本指标自动按新口径取数，无需改本系统。",
        "measures": {
            "kind": "crm_quote_person",
            "group_by": "person",
            "person_field": "create_id",
            "stat": "gross_profit_rate",
            "amount_field": "not_tax_all_quote_amount",
            "cost_field": "material_labor_cost",
            "unit": "%",
            "components": [{"label": "报价单", "source_object_code": QUOTE_PATH}],
        },
    },
    {
        # 「接单量」= 当期有效订单条数（内贸 + 外贸），客单价的分母；
        # 财务底稿编码待补：确定后填 excel_code 并重跑本脚本即可
        "code": "marketing_person_order_count",
        "name": "营销中心业务员接单量",
        "excel_code": None,
        "rule": "接单量（单）= 当期有效订单条数（status=384，剔除作废），"
        "内贸 + 外贸订单明细按订单创建月 createtime 落当期，按业务员（下单人 create_id）分组；"
        "不按订单类型/是否出货过滤，也不看金额。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "value_mode": "count_orders",
            "unit": "单",
            **VALID_ORDER,
            "components": intake_components(),
        },
    },
    {
        "code": "marketing_person_order_price",
        "name": "营销中心业务员客单价",
        "excel_code": "STF-50",
        "rule": "客单价（元/单）= 接单未税（STF-13）÷ 接单量（当期有效订单条数），**按业务员分别相除**；"
        "分子取「营销中心业务员接单未税」，分母取「营销中心业务员接单量」，同为当月、同一业务员；"
        "公司合计 = Σ接单未税 ÷ Σ接单量；接单量为 0 的业务员不输出行。",
        "measures": {
            "kind": "metric_ratio_person",
            "numerator_metric_codes": ["marketing_person_order_intake_untaxed"],
            "denominator_metric_codes": ["marketing_person_order_count"],
            "ratio_scale": 1,
            "unit": "元/单",
        },
    },
    {
        "code": "marketing_person_unship_order_inventory",
        "name": "营销中心业务员库存（未出货订单）",
        "excel_code": "STF-25",
        "rule": "库存（元）= 业务员名下**未出货订单**（orderAnalyze 的 chuhuo ≠ 1）的有效订单"
        "（status=384）未税金额合计（内贸 remove_taxes_freight + 外贸 receivable_CNY），"
        "按业务员（下单人 create_id）分组；订单明细按 24 期回看（未出货订单可能很久以前建单），"
        "同一订单只在其建单月的批次里出现，不会重复计算。"
        "**注意**：订单明细表没有成本字段（material_cost/process_cost 实测全为 0/NULL），"
        "因此暂以**未税金额**作为订单库存金额口径；与公司口径「营销中心外部订单库存（未税）」"
        "（来源 /hs/getNoChuHuo，不限建单月）存在差异，业务员版受 24 期回看窗口限制、偏低。",
        "measures": {
            "kind": "crm_order_push_person",
            "group_by": "person",
            "person_field": "create_id",
            "stat": "amount",
            "period_filter": False,  # 存量口径：只看「未出货」，不按下推/其它时间过滤
            "push_status_allow": [],  # 不按下推状态过滤
            "lookback_periods": 24,
            "backfill_lookback": True,
            "unit": "元",
            **VALID_ORDER,
            "row_filters": [{"field": "chuhuo", "op": "not_equals", "value": "1"}],
            "components": [
                {
                    "label": "内贸",
                    "source_object_code": f"{ORDER_PATH}?type=1",
                    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
                },
                {
                    "label": "外贸",
                    "source_object_code": f"{ORDER_PATH}?type=2",
                    "amount_terms": [{"field": "receivable_CNY", "sign": 1}],
                },
            ],
        },
    },
    {
        "code": "marketing_person_return_refund_untaxed",
        "name": "营销中心业务员退货退款",
        "excel_code": "STF-16",
        "rule": "退货退款（元，**负数口径**）= Σ退款订单金额，按业务员（退款单 create_id）分组；"
        "数据源为 CRM《退款订单明细》`/hs/getReturnOrderDetail`（已按退款状态 status=522 + "
        "订单创建月 createtime 过滤）；内贸取 account（= receivable − taxes，去税）、"
        "外贸取 receivable_CNY（人民币应收）；实测 2026-09 明细 4 条合计 5,658.99，"
        "与公司口径 /hs/getReturnOrder 完全一致。"
        "与公司口径「营销中心退货/退款（负数）」一致按负数入账，"
        "便于对外出货净额 = 出货未税 + 设计服务收入 + 退货退款（负数）。",
        "measures": {
            "kind": "crm_person_amount",
            "group_by": "person",
            "person_field": "create_id",
            "unit": "元",
            # 接口自身已按 status=522 过滤，这里不再按订单状态过滤
            "status_field": None,
            "status_allow": [],
            "components": [
                {
                    "label": "退款订单明细",
                    "source_object_code": RETURN_DETAIL_PATH,
                    # 内贸 account / 外贸 receivable_CNY 两个字段都取 -1；
                    # 缺的那个字段 _parse_amount(None)=0，不会重复计入
                    "amount_terms": [
                        {"field": "account", "sign": -1},
                        {"field": "receivable_CNY", "sign": -1},
                    ],
                }
            ],
        },
    },
    {
        "code": "marketing_person_external_shipment_net_untaxed",
        "name": "营销中心业务员对外出货净额",
        "excel_code": "STF-17",
        "rule": "对外出货净额（元）= 货物出货未税（STF-14）+ 设计服务收入（STF-15）+ 退货退款（STF-16，负数），"
        "**按业务员分别相加**（kind=metric_sum_person，逐个业务员取三个组成指标的当期结果相加）；"
        "公司合计 = Σ各业务员；某个业务员当月没有某个组成指标的行时按 0 计入；"
        "三项口径同源（都按业务员维度算好后相加），与公司口径「营销中心对外出货未税销售额（净额）」一致。",
        "measures": {
            "kind": "metric_sum_person",
            "component_metric_codes": [
                "marketing_person_goods_shipment_untaxed",
                "marketing_person_design_service_income",
                "marketing_person_return_refund_untaxed",
            ],
            "unit": "元",
        },
    },
    {
        "code": "marketing_person_settlement_income",
        "name": "营销中心业务员营销结算收入10%",
        "excel_code": "STF-18",
        "rule": "营销结算收入10%（元）= 对外出货净额（STF-17）× 10%，**按业务员分别折算**"
        "（kind=metric_sum_person + scale=0.1，逐个业务员取当期净额乘 10%）；公司合计 = Σ各业务员；"
        "与公司口径「营销中心总收益（营销结算收入）」= 对外出货未税净额 × 10% 一致。",
        "measures": {
            "kind": "metric_sum_person",
            "component_metric_codes": ["marketing_person_external_shipment_net_untaxed"],
            "scale": 0.1,
            "unit": "元",
        },
    },
    {
        "code": "marketing_person_variable_expense_allocation",
        "name": "营销中心业务员变动费用分摊",
        "excel_code": "STF-26",
        "rule": "变动费用分摊（元）= 业务员收入（STF-18 营销结算收入10%）÷ 总收入（ORD-01 营销中心接单金额·未税）"
        "× 变动费用合计（CM-01），按业务员分别计算（kind=metric_alloc_person）；"
        "分母与费用池都取公司口径指标的当期合计行；"
        "**口径已确认（业务确认保持 ORD-01 作分母）**：各业务员分摊额合计小于 CM-01 变动费用合计属预期，"
        "差额部分不参与业务员分摊；如需改成「按各业务员收入占比分摊（合计=费用池）」，"
        "把 base_metric_codes 置空即可（改用 Σ业务员基数作分母）。",
        "measures": {
            "kind": "metric_alloc_person",
            "share_metric_codes": ["marketing_person_settlement_income"],
            "base_metric_codes": ["marketing_order_intake_untaxed"],
            "pool_metric_codes": ["marketing_variable_expense_total"],
            "unit": "元",
        },
    },
    {
        "code": "marketing_person_fixed_expense_allocation",
        "name": "营销中心业务员固定费用分摊",
        "excel_code": "STF-28",
        "rule": "固定费用分摊（元）= 业务员收入（STF-18 营销结算收入10%）÷ 总收入（ORD-01 营销中心接单金额·未税）"
        "× 固定费用合计（CM-04），按业务员分别计算（kind=metric_alloc_person）；"
        "分母与费用池都取公司口径指标的当期合计行，口径与 STF-26 变动费用分摊保持一致"
        "（**已确认以 ORD-01 作分母**：各业务员分摊额合计小于固定费用合计属预期，差额不参与业务员分摊）。",
        "measures": {
            "kind": "metric_alloc_person",
            "share_metric_codes": ["marketing_person_settlement_income"],
            "base_metric_codes": ["marketing_order_intake_untaxed"],
            "pool_metric_codes": ["marketing_fixed_expense_total"],
            "unit": "元",
        },
    },
    {
        "code": "marketing_person_contribution_margin",
        "name": "营销中心业务员边际贡献",
        "excel_code": "STF-27",
        "rule": "边际贡献（元）= 营销结算收入10%（STF-18）− 变动费用分摊（STF-26），"
        "按业务员分别相减（kind=metric_diff_person，加项 − 减项，缺失项按 0）；公司合计 = Σ各业务员；"
        "与公司口径「营销中心边际贡献」= 总收益（营销结算收入）− 变动费用合计 同思路。",
        "measures": {
            "kind": "metric_diff_person",
            "addend_metric_codes": ["marketing_person_settlement_income"],
            "subtrahend_metric_codes": ["marketing_person_variable_expense_allocation"],
            "unit": "元",
        },
    },
    {
        "code": "marketing_person_hq_allocation",
        "name": "营销中心业务员总部分摊",
        "excel_code": "STF-29",
        "rule": "总部分摊（元）= 对外出货净额（STF-17）× 8%，**按业务员分别折算**"
        "（kind=metric_sum_person + scale=0.08，逐个业务员取当期净额乘 8%）；公司合计 = Σ各业务员。",
        "measures": {
            "kind": "metric_sum_person",
            "component_metric_codes": ["marketing_person_external_shipment_net_untaxed"],
            "scale": 0.08,
            "unit": "元",
        },
    },
    {
        "code": "marketing_person_settlement_profit",
        "name": "营销中心业务员结算收益",
        "excel_code": "STF-30",
        "rule": "结算收益（元）= 边际贡献（STF-27）− 固定费用分摊（STF-28）− 总部分摊（STF-29），"
        "按业务员分别相减（kind=metric_diff_person，加项 1 个、减项 2 个，缺失项按 0）；"
        "公司合计 = Σ各业务员。",
        "measures": {
            "kind": "metric_diff_person",
            "addend_metric_codes": ["marketing_person_contribution_margin"],
            "subtrahend_metric_codes": [
                "marketing_person_fixed_expense_allocation",
                "marketing_person_hq_allocation",
            ],
            "unit": "元",
        },
    },
    {
        "code": "marketing_person_sales_per_capita",
        "name": "营销中心业务员人均销售额",
        "excel_code": "STF-36",
        "rule": "人均销售额（元）= 对外出货净额（STF-17），按业务员分别取值"
        "（kind=metric_sum_person，单一组成指标；业务员维度下即为该业务员的当期销售额）。"
        "如需按人数折算（如「净额合计 ÷ 业务员人数」或「÷ 在职营销人员数」），"
        "增配 scale 或再引入人数类指标即可，口径请与业务确认。",
        "measures": {
            "kind": "metric_sum_person",
            "component_metric_codes": ["marketing_person_external_shipment_net_untaxed"],
            "unit": "元",
        },
    },
]


async def get_or_create(db, model, match: dict, defaults: dict | None = None):
    conditions = [getattr(model, key) == value for key, value in match.items()]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**{**(defaults or {}), **match})
        db.add(obj)
    else:
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
    await db.flush()
    return obj


async def main() -> None:
    parser = argparse.ArgumentParser(description="初始化营销中心业务员分析指标")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="CRM 接口域名")
    parser.add_argument("--connection-name", default=CONNECTION_NAME, help="连接名称")
    parser.add_argument("--cron", default=SYNC_CRON, help="同步 Cron（6 段，默认每天 02:00）")
    args = parser.parse_args()

    job_ids: list[int] = []
    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(select(CrmConnectionModel).where(CrmConnectionModel.name == args.connection_name))
        ).scalars().first()
        if connection is None:
            connection = CrmConnectionModel(name=args.connection_name, base_url=args.base_url, status=0)
            db.add(connection)
            await db.flush()
        else:
            connection.base_url = args.base_url
            connection.status = 0

        system = await get_or_create(
            db,
            SourceSystemModel,
            {"code": SOURCE_SYSTEM_CODE},
            {
                "name": "CRM",
                "connector_type": "crm",
                "connection_id": connection.id,
                "status": 0,
                "description": "CRM 订单/发货明细接口（业务员维度，无需鉴权）",
            },
        )
        system.connection_id = connection.id
        system.connector_type = "crm"

        for spec in SOURCE_OBJECTS:
            code = spec["code"]
            # 多数明细接口按 month 取整月；客户列表这类无时间参数的接口传空模板；
            # 退款明细这类用 dateRange 的接口由 spec["request"] 直接给定模板
            request_template = dict(spec.get("request") or (MONTH_PARAMS if spec.get("with_month", True) else {}))
            source_object = await get_or_create(
                db,
                SourceObjectModel,
                {"system_id": system.id, "code": code},
                {
                    "name": spec["name"],
                    "query_type": "api",
                    "request_template": request_template,
                    "status": 0,
                },
            )
            source_object.request_template = request_template

            job = (
                await db.execute(
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"CRM业务员指标-{spec['name']}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"CRM业务员指标-{spec['name']}")
                db.add(job)
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.org_code = None
            job.cron_expr = str(spec.get("cron") or args.cron)
            job.request_params = request_template
            job.sync_mode = "full"
            job.status = int(spec.get("status", 0))
            job.description = f"CRM 接口 {code}，按 month 取整月明细（未分页，单月约 1.3k 行）"
            if int(spec.get("status", 0)) == 1:
                job.description = (
                    f"CRM 接口 {code}，按 dateRange 取整月明细；"
                    "生产环境路由未发布前保持停用（启用后需 backfill 回补）"
                )
            await db.flush()
            job_ids.append(job.id)

        for spec in METRICS:
            metric = (
                await db.execute(select(MetricDefModel).where(MetricDefModel.code == spec["code"]))
            ).scalars().first()
            if metric is None:
                metric = MetricDefModel(code=spec["code"])
                db.add(metric)
            metric.name = spec["name"]
            metric.category = CATEGORY
            metric.excel_code = spec.get("excel_code")
            metric.period_type = "month"
            metric.sensitivity = 0
            metric.dimensions = DIMENSIONS
            metric.measures = spec["measures"]
            metric.formula = spec["rule"]
            metric.source_entity_id = None
            metric.status = 0
            metric.description = (
                f"{spec['rule']} "
                "数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》"
                f"（{ORDER_PATH} / {SHIPMENT_PATH}，GET、无需鉴权，month 为整月）；"
                "业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。"
                "月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。"
            )
            await db.flush()
            print(f"指标定义已就绪: id={metric.id} code={metric.code} excel={metric.excel_code} name={metric.name}")

        print(f"CRM 连接 id={connection.id}，来源系统 id={system.id}，同步任务 {job_ids}")

    for job_id in job_ids:
        job = await _load_job(job_id)
        if job is not None:
            register_meta_sync_job(job)
    await async_engine.dispose()
    print("营销中心业务员分析指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
