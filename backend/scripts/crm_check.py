"""CRM 订单/报价/出货/下推接口直连校验（不依赖数据库）。

接入前先跑这个脚本确认全部接口都能取到数，再执行
``scripts/seed_crm_marketing_metrics.py``（订单/报价 11 个指标）与
``scripts/seed_crm_shipment_metrics.py``（出货/设计服务/退款 4 个指标）、
``scripts/seed_crm_push_metrics.py``（订单下推周期 11 个指标）、
``scripts/seed_crm_worktime_metrics.py``（工时 2 个指标）、
``scripts/seed_crm_kpi_metrics.py``（KPI 4 个指标：履约率/平台推广 ROI/复购率/退货率）、
``scripts/seed_crm_inventory_metrics.py``（库存 3 个指标：外部订单库存 / 呆滞库存 >90 天 / 海柔库存）
落库成营销中心月指标。

注意：``/hs/push/getPush`` 不接收 ``dateRange``，只按「ERP 下推时间落在当月」+
``type`` 统计，传 ``--period`` 也不会改变其结果。
``/hs/KPI/getRepurchaseRate`` 也不接收 ``dateRange``，只接收 ``month``（``YYYY-MM``）。

用法：
    python scripts/crm_check.py
    python scripts/crm_check.py --period 2026-08
    python scripts/crm_check.py --base-url http://crmapi.yonggubox.com
"""

import argparse
import asyncio
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.crm.client import (  # noqa: E402
    DEFAULT_BASE_URL,
    CrmClient,
    CrmClientConfig,
    CrmError,
    month_date_range,
)

# (指标名, 接口路径, 额外请求参数)；
# 前 9 条与《订单未税金额接口文档》《报价单统计接口文档》一致，
# 中间 4 条与《HASH 接口文档》（出货统计 / 设计费 / 退款）一致，
# 其后的「正常工作时间 / 加班时间」同样来自《HASH 接口文档》（工时统计 QwApi，实时调企微打卡日报），
# 最后 10 条与《订单下推周期接口文档》一致：``*PushPeriod`` 的 ``data`` 是平均下推周期天数，
# ``getPush`` 已改口径为**下推未税金额（元）**——不再接收 ``type``，改成：下推时间 ``pushDateRange`` +
# 接单时间 ``createDateRange``（「本月接单本月下推 / 前期接单本月下推」靠接单范围区分）。
ENDPOINTS = [
    ("内贸订单（未税）", "/hs/order/getDtAmount", {}),
    ("外贸订单（未税）", "/hs/order/getFtAmount", {}),
    ("零售订单（未税）", "/hs/order/getRetailAmount", {}),
    ("批量订单（未税）", "/hs/order/getBatchAmount", {}),
    ("打样订单（未税）", "/hs/order/getSampleAmount", {}),
    ("备货订单（未税）", "/hs/order/getStockUpAmount", {}),
    ("设计费收入（未税）", "/hs/order/getDesignAmount", {}),
    ("报价次数/成功率", "/hs/quote/getQuoteStatistics", {"transformation": 0}),
    ("报价毛利率", "/hs/quote/getQuoteProfitRate", {}),
    ("批量出货（未税）", "/hs/getpiliangchuhuo", {}),
    ("打样出货（未税）", "/hs/getdayangchuhuo", {}),
    ("设计服务收入（未税）", "/hs/getShejifei", {}),
    ("退货/退款（负数）", "/hs/getReturnOrder", {}),
    # 库存接口（《HASH 接口文档》OutStock，控制器 app\api\controller\accounting\v1\OutStock）：
    # 两个接口的业务值都嵌在同名键里（data.data），故 main() 里统一按 res.data.data 展示。
    ("外部订单库存（未税）", "/hs/getNoChuHuo", {"__nested_data__": True}),
    ("呆滞库存（>90天，未税）", "/hs/get90NoChuHuo", {"__nested_data__": True}),
    # 海柔库存：按入库时间（startMoveInTime/endMoveInTime）过滤，dateRange 即入库时间区间
    ("海柔库存", "/hs/getHaiRou", {"__nested_data__": True}),
    ("正常工作时间（小时）", "/hs/getWorkTime", {"__worktime__": "regularWorkHours"}),
    ("加班时间（小时）", "/hs/getWorkTime", {"__worktime__": "overtimeHours"}),
    # getPush 金额指标：占位标记在 main() 里换成 pushDateRange / createDateRange
    ("本月接单本月下推（未税）", "/hs/push/getPush", {"__push_amount__": "same_month"}),
    ("前期接单本月下推（未税）", "/hs/push/getPush", {"__push_amount__": "prior_month"}),
    ("下推金额合计（未税）", "/hs/push/getPush", {"__push_amount__": "total"}),
    ("下推周期（天）", "/hs/push/getPushPeriod", {}),
    ("批量下推周期", "/hs/push/getBatchPushPeriod", {}),
    ("打样下推周期", "/hs/push/getSamplePushPeriod", {}),
    ("内贸下推周期", "/hs/push/getDtPushPeriod", {}),
    ("外贸下推周期", "/hs/push/getFtPushPeriod", {}),
    ("批量内贸下推周期", "/hs/push/getBatchDtPushPeriod", {}),
    ("批量外贸下推周期", "/hs/push/getBatchFtPushPeriod", {}),
    ("打样内贸下推周期", "/hs/push/getSampleDtPushPeriod", {}),
    ("打样外贸下推周期", "/hs/push/getSampleFtPushPeriod", {}),
    # KPI 接口（《KPI 接口文档》）：前三条取百分数/金额，复购率只接收 month（见 main 里的 __month__ 分支）
    ("订单履约率", "/hs/KPI/getOrderFulfillmentRate", {}),
    ("平台推广新客未税金额", "/hs/KPI/getPlatformPromotionRoi", {}),
    ("复购率", "/hs/KPI/getRepurchaseRate", {"__month__": True}),
    ("退货额", "/hs/KPI/getReturnAmount", {}),
]


async def main() -> None:
    parser = argparse.ArgumentParser(description="CRM 订单未税金额接口直连校验")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="接口域名（默认正式环境）")
    parser.add_argument("--period", default=None, help="月度期间，如 2026-08；不传取接口默认本月")
    parser.add_argument("--timeout", type=int, default=30, help="读取超时(秒)")
    args = parser.parse_args()

    # 不传 --period 时显式取当前月（等价于接口默认「本月」，但能让两个金额指标算出不同值）
    date_range = list(month_date_range(args.period or date.today()))

    def push_amount_params(scope: str) -> dict:
        """getPush 金额指标的两个范围：下推时间固定本月，接单时间按 scope 取本月 / 早于本月 / 全部。"""
        if not date_range:
            return {}  # 不传参数时由接口按默认本月返回
        start, end = date_range
        if scope == "same_month":
            return {"pushDateRange": [start, end], "createDateRange": [start, end]}
        if scope == "total":
            # 合计 = 不限接单月（等价于「本月接单本月下推 + 前期接单本月下推」）
            return {"pushDateRange": [start, end], "createDateRange": ["2000-01-01", end]}
        prev_end = (datetime.strptime(start, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        return {"pushDateRange": [start, end], "createDateRange": ["2000-01-01", prev_end]}

    # 复购率接口只接收 month（YYYY-MM），由期间范围的首日推出目标月份
    month_param = date_range[0][:7]

    client = CrmClient(CrmClientConfig(base_url=args.base_url, timeout=args.timeout))
    results: dict[str, object] = {}
    try:
        for name, path, extra in ENDPOINTS:
            call_range = date_range
            worktime_field: str | None = None
            nested_data = False
            if "__push_amount__" in extra:
                extra = push_amount_params(str(extra["__push_amount__"]))
                call_range = None  # getPush 不接收 dateRange
            elif extra.get("__month__"):
                # 复购率接口不接收 dateRange，改传 month（YYYY-MM）
                extra = {"month": month_param}
                call_range = None
            elif extra.get("__nested_data__"):
                # 库存接口：响应 {"code":1,"data":{"data": 金额}}，业务值在 data.data
                nested_data = True
                extra = {}
            elif "__worktime__" in extra:
                # 工时接口返回 data 是「正常工时 + 加班工时 + 每人每天明细」的结构体，
                # 只打印两个指标字段，避免 80 多人的明细把控制台刷满
                worktime_field = str(extra["__worktime__"])
                extra = {}
            try:
                payload = await client.call(path, call_range, extra)
                data = payload.get("data")
                results[name] = data
                if worktime_field:
                    picked = (data or {}).get(worktime_field) if isinstance(data, dict) else None
                    results[name] = picked
                    print(
                        f"OK   {name:<16} {path:<28} = {float(picked or 0):,.2f}"
                        f"（在职营销人员 {int((data or {}).get('userCount') or 0)} 人）"
                    )
                elif nested_data:
                    picked = (data or {}).get("data") if isinstance(data, dict) else None
                    results[name] = picked
                    print(f"OK   {name:<16} {path:<28} = {float(picked or 0):,.2f}")
                elif isinstance(data, dict):
                    print(f"OK   {name:<16} {path:<28} = {data}")
                else:
                    print(f"OK   {name:<16} {path:<28} = {float(data or 0):,.2f}")
            except CrmError as e:
                results[name] = f"失败：{e}"
                print(f"FAIL {name:<16} {path:<28} {e}")
    finally:
        await client.aclose()

    print()
    print(json.dumps({"期间": args.period or "本月", "结果": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
