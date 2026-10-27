"""连通性自测：换令牌 + 读平台渠道分析指标。

用法::

    python deploy/platform-analysis-api-20261027/test_platform_analysis.py \
      --base-url http://120.237.174.243:6479 \
      --app-id apipost_test --app-secret <secret> --period 2026-10

只用标准库，服务器不需要额外依赖。
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request


def _request(url: str, method: str = "GET", payload: dict | None = None, token: str | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"http_status": exc.code, "body": body}


def main() -> None:
    parser = argparse.ArgumentParser(description="平台渠道分析指标连通性自测")
    parser.add_argument("--base-url", default="http://120.237.174.243:6479")
    parser.add_argument("--app-id", required=True)
    parser.add_argument("--app-secret", required=True)
    parser.add_argument("--period", default=None, help="期间 YYYY-MM，缺省全部")
    parser.add_argument("--shop-id", type=int, default=None)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    token_res = _request(f"{base}/open/v1/auth/token", "POST", {"app_id": args.app_id, "app_secret": args.app_secret})
    token = (token_res.get("data") or {}).get("access_token")
    if not token:
        print("换令牌失败：", json.dumps(token_res, ensure_ascii=False))
        raise SystemExit(1)
    print(f"换令牌成功，有效期 {token_res['data'].get('expires_in')} 秒")

    params = {}
    if args.period:
        params["period_value"] = args.period
    if args.shop_id is not None:
        params["shop_id"] = args.shop_id
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    res = _request(f"{base}/open/v1/retail/platform/analysis{query}", token=token)
    if res.get("code") != 0:
        print("查询失败：", json.dumps(res, ensure_ascii=False))
        if res.get("code") == 40102:
            print("提示：在「系统管理 → 开放接口应用」编辑该应用，打开「平台渠道分析」开关")
        raise SystemExit(1)

    data = res["data"]
    print(f"app_id={data.get('app_id')} 税={data.get('tax_rate')}% 结算={data.get('settlement_rate')}%")
    print("TOTAL:", json.dumps(data.get("total"), ensure_ascii=False))
    for row in (data.get("items") or [])[:10]:
        print(
            f"  {row['period_value']} shop={row['shop_id']} {row.get('shop_name') or '-'} "
            f"接单={row['intake_untaxed']} 出货={row['shipment_untaxed']} "
            f"退货={row['return_untaxed']} 净额={row['net_shipment_untaxed']} "
            f"结算={row['settlement_income_untaxed']} 退货率={row['return_rate']}"
        )
    print(f"共 {len(data.get('items') or [])} 行")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"调用异常：{exc}")
        sys.exit(1)
