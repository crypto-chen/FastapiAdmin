"""客户分析（CUS）取数来源探测：直连 CRM，打印每个接口当前返回的字段清单。

用途：客户分析月度指标开工前，确认「客户 / 订单 / 出货 / 退款 / 产品 / 字典」等
接口现在到底给哪些字段（CRM 2026-10-13 裁剪过 orderAnalyze，字段会变）。

用法：
    python scripts/probe_cus_sources.py
    python scripts/probe_cus_sources.py --month 2026-09
"""

from __future__ import annotations

import argparse
import sys

import httpx

BASE_URL = "http://crmapi.yonggubox.com"


def month_range(month: str) -> str:
    year, mon = (int(part) for part in month.split("-"))
    last = [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mon - 1]
    return f"{month}-01,{month}-{last:02d}"


def build_targets(month: str) -> list[tuple[str, str, dict]]:
    rng = month_range(month)
    return [
        ("订单明细（内贸）", "/hs/order/orderAnalyze", {"type": 1, "month": month}),
        ("订单明细（外贸）", "/hs/order/orderAnalyze", {"type": 2, "month": month}),
        ("发货明细（内贸）", "/hs/order/orderShipments", {"type": 1, "month": month}),
        ("发货明细（外贸）", "/hs/order/orderShipments", {"type": 2, "month": month}),
        ("退款订单明细", "/hs/getReturnOrderDetail", {"dateRange": rng}),
        ("退货退款（金额）", "/hs/getReturnOrder", {"dateRange": rng}),
        ("报价单明细", "/hs/quote/getQuoteList", {"dateRange": rng}),
        ("设计服务收入", "/hs/getShejifei", {"dateRange": rng}),
        ("客户主档（全量）", "/hs/customer/getCusotmerList", {}),
        ("客户主档（按业务员）", "/hs/customer/getCusotmerList", {"principal_id": "23,15"}),
        ("客户主档（按名称）", "/hs/customer/getCusotmerList", {"name": "江西精致能源技术有限公司"}),
        ("产品线字典", "/hs/product/getProductCategory", {}),
        ("产品型号字典", "/hs/product/getProductModel", {}),
        ("基础字典", "/hs/base/getBaseCategoryList", {}),
        ("人员字典", "/hs/base/getPersonnel", {}),
        ("部门字典", "/hs/base/getDepartment", {}),
        ("外部订单库存", "/hs/getNoChuHuo", {"dateRange": rng}),
        ("呆滞库存90天", "/hs/get90NoChuHuo", {"dateRange": rng}),
    ]


def summarize(payload) -> str:
    if isinstance(payload, list):
        if not payload:
            return "list(空)"
        first = payload[0]
        keys = list(first.keys()) if isinstance(first, dict) else [f"<{type(first).__name__}>"]
        return f"list({len(payload)} 行) 字段={keys}"
    if isinstance(payload, dict):
        out = []
        for key, value in payload.items():
            if isinstance(value, list):
                out.append(f"{key}=list({len(value)})")
            elif isinstance(value, dict):
                out.append(f"{key}=dict{list(value.keys())[:12]}")
            else:
                text = str(value)
                out.append(f"{key}={text[:40]}")
        return "dict " + "; ".join(out)
    return f"{type(payload).__name__}={str(payload)[:80]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default="2026-09")
    parser.add_argument("--base-url", default=BASE_URL)
    args = parser.parse_args()

    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for name, path, params in build_targets(args.month):
            try:
                resp = client.get(f"{args.base_url}{path}", params=params)
                try:
                    body = resp.json()
                except ValueError:
                    print(f"[{name}] {path} HTTP {resp.status_code} 非 JSON，前 120 字符：{resp.text[:120]}")
                    continue
                data = body.get("data") if isinstance(body, dict) else body
                print(f"[{name}] {path} params={params} HTTP {resp.status_code} code={body.get('code') if isinstance(body, dict) else '-'}")
                print(f"    {summarize(data)}")
            except Exception as exc:  # noqa: BLE001
                print(f"[{name}] {path} 请求失败: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
