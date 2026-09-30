"""聚水潭销售出库「零售出库未税总金额」直连校验（不依赖数据库）。

拿到 app_key / app_secret / access_token 后先跑这个脚本确认能取到数，
再执行 scripts/seed_jushuitan_metric.py 落库成月度指标。

用法：
    python scripts/jushuitan_check.py --app-key xx --app-secret yy --access-token zz --period 2026-08
    python scripts/jushuitan_check.py --access-token zz --period 2026-08 --tax-rate 13 --sample 3

凭据也可用环境变量提供：JST_APP_KEY / JST_APP_SECRET / JST_ACCESS_TOKEN。
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.modules.erp.jushuitan.aggregate import AMOUNT_SOURCES, summarize  # noqa: E402
from app.modules.erp.jushuitan.client import (  # noqa: E402
    DEFAULT_BASE_URL,
    JushuitanClient,
    JushuitanClientConfig,
    JushuitanError,
    month_range,
)

# 常见错误码 → 处理动作（文档：https://openweb.jushuitan.com/doc?docId=30）
ERROR_HINTS = {
    10: "签名无效：检查 app_secret 是否与 app_key 配对。",
    100: "access_token 已超时：重新授权获取新的 access_token。",
    110: "IP 不在白名单：把报错信息里的 IP 加到开放平台后台『应用详情 - IP白名单』（服务器换机房/换出口 IP 后要同步更新）。",
    140: "参数不符合规范：检查 biz 字段类型（app_key 无效也会返回此码，确认用的是正式环境地址）。",
    199: "调用超过并发限制（5 次/秒），客户端会自动重试。",
    200: "调用超过频次限制（100 次/分钟），客户端会自动重试。",
}


async def main() -> None:
    parser = argparse.ArgumentParser(description="聚水潭销售出库未税总金额直连校验")
    parser.add_argument("--app-key", default=os.getenv("JST_APP_KEY", ""), help="开发者应用 app_key")
    parser.add_argument("--app-secret", default=os.getenv("JST_APP_SECRET", ""), help="开发者应用 app_secret")
    parser.add_argument("--access-token", default=os.getenv("JST_ACCESS_TOKEN", ""), help="商家授权 access_token")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="接口地址（默认正式环境）")
    parser.add_argument("--period", required=True, help="月度期间，如 2026-08")
    parser.add_argument("--shop-id", type=int, default=None, help="店铺编码；不传表示全部店铺")
    parser.add_argument("--offline", action="store_true", help="只查线下店铺单据")
    parser.add_argument("--status", default="Confirmed", help="单据状态，默认 Confirmed=已出库；传 all 表示不过滤")
    parser.add_argument(
        "--amount-source",
        default="items.auto",
        choices=sorted(AMOUNT_SOURCES),
        help="取数口径，默认 items.auto（明细行内先金额、再买家实付、后卖家实收）",
    )
    parser.add_argument("--tax-rate", type=float, default=0.0, help="税率(%%)，用于含税→未税折算；默认 0")
    parser.add_argument("--page-size", type=int, default=50, help="每页条数，最大 50")
    parser.add_argument("--max-rows", type=int, default=20000, help="最多拉取行数")
    parser.add_argument("--sample", type=int, default=0, help="打印前 N 条出库单原始数据")
    args = parser.parse_args()

    missing = [
        name
        for name, value in (
            ("--app-key", args.app_key),
            ("--app-secret", args.app_secret),
            ("--access-token", args.access_token),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"缺少凭据：{', '.join(missing)}")

    begin, end = month_range(args.period)
    extra: dict = {"date_type": 2}
    if args.shop_id is not None:
        extra["shop_id"] = args.shop_id
    if args.offline:
        extra["is_offline_shop"] = True
    if args.status and args.status.lower() != "all":
        extra["status"] = args.status

    client = JushuitanClient(
        JushuitanClientConfig(
            base_url=args.base_url,
            app_key=args.app_key,
            app_secret=args.app_secret,
            access_token=args.access_token,
        )
    )
    try:
        shops = await client.test_connection()
        print("授权自检：", "通过" if shops else "通过（未返回店铺，可能是线下/未启用店铺）")
        if shops:
            print("首个店铺：", json.dumps(shops, ensure_ascii=False))

        rows: list[dict] = []
        async for row in client.iter_sales_outbound(begin, end, page_size=args.page_size, **extra):
            rows.append(row)
            if len(rows) >= args.max_rows:
                break
    except JushuitanError as e:
        raise SystemExit(f"取数失败：{e}\n处理建议：{ERROR_HINTS.get(e.code, '对照开放平台错误码文档排查')}") from e
    finally:
        await client.aclose()

    summary = summarize(rows, amount_source=args.amount_source, tax_rate=args.tax_rate, tax_inclusive=True)
    result = {
        "期间": args.period,
        "出库时间范围": [begin.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")],
        "取数口径": args.amount_source,
        "税率(%)": args.tax_rate,
        "单据数": summary["order_count"],
        "商品数量": summary["item_qty"],
        "含税金额": summary["tax_inclusive_amount"],
        "未税总金额": summary["untaxed_amount"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.sample:
        for row in rows[: args.sample]:
            print(json.dumps(row, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    asyncio.run(main())
