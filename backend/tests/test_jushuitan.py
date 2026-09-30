"""聚水潭对接单元测试：签名规则、时间分段、金额折算、路由注册。"""

from datetime import date, datetime

import pytest

from app.modules.erp.jushuitan.aggregate import parse_amount, summarize, to_untaxed
from app.modules.erp.jushuitan.client import (
    MAX_WINDOW_DAYS,
    JushuitanClient,
    JushuitanClientConfig,
    build_sign,
    month_range,
    split_windows,
)
from app.modules.erp.jushuitan.templates import MONTHLY_SALES_OUTBOUND_BIZ
from app.modules.metadata.sync import render_request_params
from app.modules.metric.engine import extract_sales_outbound, previous_period_value


def test_build_sign_matches_official_samples():
    """对齐官方签名文档（docId=70）给出的两个示例。"""
    auth_params = {
        "app_key": "5b53060f23d84ddf9703056e84fa5a2d",
        "timestamp": "1639128407",
        "grant_type": "authorization_code",
        "charset": "utf-8",
        "code": "123456",
    }
    assert build_sign("e9c5ca33fecb404b8e6cdbd0ef4a6d25", auth_params) == "05e3a51e19e0883afd1882ccd309e0b9"

    biz = '{"page_index":"1","page_size":"100","nicks":["老板"]}'
    business_params = {
        "app_key": "5b53060f23d84ddf9703056e84fa5a2d",
        "access_token": "d7b01bf0842a4742a9450e21ffd95f60",
        "timestamp": "1639128407",
        "version": "2",
        "charset": "utf-8",
        "biz": biz,
    }
    assert build_sign("e9c5ca33fecb404b8e6cdbd0ef4a6d25", business_params) == "395f5a78b446be465ac03a02491296c7"


def test_build_sign_skips_sign_and_empty_values():
    params = {"app_key": "k", "timestamp": "1", "sign": "ignored", "biz": ""}
    assert build_sign("secret", params) == build_sign("secret", {"app_key": "k", "timestamp": "1"})


def test_build_form_contains_required_fields():
    client = JushuitanClient(
        JushuitanClientConfig(app_key="ak", app_secret="as", access_token="at")
    )
    form = client.build_form({"status": "Confirmed"}, timestamp=1639128407)

    assert set(form) == {"app_key", "access_token", "timestamp", "charset", "version", "biz", "sign"}
    assert form["charset"] == "utf-8"
    assert form["version"] == "2"
    assert form["timestamp"] == "1639128407"
    assert form["biz"] == '{"status":"Confirmed"}'
    expected = build_sign("as", {k: v for k, v in form.items() if k != "sign"})
    assert form["sign"] == expected


def test_split_windows_respects_seven_day_limit_and_covers_range():
    begin = datetime(2026, 8, 1, 0, 0, 0)
    end = datetime(2026, 8, 31, 23, 59, 59)
    windows = split_windows(begin, end)

    assert windows[0][0] == begin
    assert windows[-1][1] == end
    for window_begin, window_end in windows:
        assert (window_end - window_begin).days <= MAX_WINDOW_DAYS
    # 相邻窗口首尾相接，不重叠、不缺失
    for (_, prev_end), (next_begin, _) in zip(windows, windows[1:], strict=False):
        assert prev_end == next_begin


def test_split_windows_single_day_range():
    begin = datetime(2026, 8, 5, 8, 0, 0)
    end = datetime(2026, 8, 5, 20, 0, 0)
    assert split_windows(begin, end) == [(begin, end)]


def test_split_windows_rejects_reversed_range():
    with pytest.raises(ValueError):
        split_windows(datetime(2026, 8, 2), datetime(2026, 8, 1))


def test_month_range():
    begin, end = month_range("2026-08")
    assert begin == datetime(2026, 8, 1, 0, 0, 0)
    assert end == datetime(2026, 8, 31, 23, 59, 59)

    begin, end = month_range("2026-12")
    assert begin == datetime(2026, 12, 1, 0, 0, 0)
    assert end == datetime(2026, 12, 31, 23, 59, 59)


def test_parse_amount_handles_strings_and_blanks():
    assert parse_amount("1,286.51") == 1286.51
    assert parse_amount("") == 0.0
    assert parse_amount(None) == 0.0
    assert parse_amount("-") == 0.0
    assert parse_amount(706.0) == 706.0


def test_to_untaxed():
    assert to_untaxed(113, 13, True) == pytest.approx(100.0)
    assert to_untaxed(113, 0, True) == 113
    assert to_untaxed(113, 13, False) == 113


def _outbound_rows() -> list[dict]:
    return [
        {
            "io_id": 1,
            "shop_id": 100,
            "shop_name": "天猫旗舰店",
            "pay_amount": 113,
            "items": [{"sale_amount": 113, "qty": 1}],
        },
        {
            "io_id": 2,
            "shop_id": 100,
            "shop_name": "天猫旗舰店",
            "pay_amount": 226,
            "items": [{"sale_amount": 226, "qty": 2}],
        },
    ]


def test_summarize_untaxed_amount_by_order():
    summary = summarize(_outbound_rows(), amount_source="order.pay_amount", tax_rate=13, tax_inclusive=True)
    assert summary["order_count"] == 2
    assert summary["item_qty"] == 3
    assert summary["tax_inclusive_amount"] == 339
    assert summary["untaxed_amount"] == pytest.approx(300.0)


def test_summarize_untaxed_amount_by_items():
    summary = summarize(_outbound_rows(), amount_source="items.sale_amount", tax_rate=13, tax_inclusive=True)
    assert summary["tax_inclusive_amount"] == 339
    assert summary["untaxed_amount"] == pytest.approx(300.0)


def test_summarize_without_tax_rate_keeps_amount():
    summary = summarize(_outbound_rows(), amount_source="order.pay_amount")
    assert summary["untaxed_amount"] == 339


def test_summarize_by_shop():
    rows = _outbound_rows() + [
        {
            "io_id": 3,
            "shop_id": 200,
            "shop_name": "抖音店",
            "pay_amount": 56.5,
            "items": [{"sale_amount": 56.5, "qty": 1}],
        }
    ]
    summary = summarize(rows, amount_source="order.pay_amount", tax_rate=13, tax_inclusive=True, by_shop=True)
    assert set(summary["by_shop"]) == {"100", "200"}
    assert summary["by_shop"]["100"]["untaxed_amount"] == pytest.approx(300.0)
    assert summary["by_shop"]["200"]["untaxed_amount"] == pytest.approx(50.0)
    assert summary["by_shop"]["200"]["shop_name"] == "抖音店"


def test_summarize_rejects_unknown_amount_source():
    with pytest.raises(ValueError):
        summarize(_outbound_rows(), amount_source="order.not_exists")


def test_summarize_auto_fallback_covers_both_platform_types():
    """items.auto：淘系只有买家实付、跨境只有金额，两种都要能取到。"""
    rows = [
        {"io_id": 1, "shop_id": 100, "items": [{"qty": 1, "buyer_paid_amount": 100.0}]},
        {"io_id": 2, "shop_id": 200, "items": [{"qty": 1, "sale_amount": 50.0, "buyer_paid_amount": 0}]},
    ]
    summary = summarize(rows, amount_source="items.auto", tax_rate=13, tax_inclusive=True)
    assert summary["tax_inclusive_amount"] == 150.0
    assert summary["untaxed_amount"] == pytest.approx(150.0 / 1.13)
    assert summary["item_qty"] == 2


def test_summarize_auto_fallback_custom_order():
    rows = [{"io_id": 1, "items": [{"sale_amount": 100.0, "seller_income_amount": 90.0}]}]
    assert summarize(rows, amount_source="items.auto")["tax_inclusive_amount"] == 100.0
    picked = summarize(rows, amount_source="items.auto", auto_fields=["seller_income_amount"])
    assert picked["tax_inclusive_amount"] == 90.0


def test_monthly_biz_template_renders_period():
    """按月模板渲染：出库状态=已出库、按出库时间取整月。"""
    params = render_request_params(MONTHLY_SALES_OUTBOUND_BIZ, now=datetime(2026, 8, 1))
    assert params["status"] == "Confirmed"
    assert params["date_type"] == 2
    assert params["modified_begin"] == "2026-08-01 00:00:00"
    assert params["modified_end"] == "2026-08-31 23:59:59"

    feb = render_request_params(MONTHLY_SALES_OUTBOUND_BIZ, now=datetime(2026, 2, 1))
    assert feb["modified_end"] == "2026-02-28 23:59:59"

    leap = render_request_params(MONTHLY_SALES_OUTBOUND_BIZ, now=datetime(2028, 2, 1))
    assert leap["modified_end"] == "2028-02-29 23:59:59"

    december = render_request_params(MONTHLY_SALES_OUTBOUND_BIZ, now=datetime(2026, 12, 1))
    assert december["modified_end"] == "2026-12-31 23:59:59"


def test_extract_sales_outbound_for_metric():
    """指标引擎取数：度量值 = 未税金额，命中行数 = 单据数。"""
    config = {
        "kind": "sales_outbound_amount",
        "source_object_code": "/open/orders/out/simple/query",
        "amount_source": "order.pay_amount",
        "tax_rate": 13,
        "tax_inclusive": True,
        "by_shop": True,
    }
    extracted = extract_sales_outbound(_outbound_rows(), config)
    assert extracted["total"] == pytest.approx(300.0)
    assert extracted["order_count"] == 2
    assert extracted["matched_rows"] == 2
    assert extracted["departments"]["100"]["value"] == pytest.approx(300.0)
    assert extracted["departments"]["100"]["name"] == "天猫旗舰店"


def test_previous_period_value_for_settlement():
    """次月 1 日结转要算的是上个月，而不是当前月。"""
    assert previous_period_value("month", date(2026, 10, 1)) == "2026-09"
    assert previous_period_value("month", date(2026, 1, 1)) == "2025-12"
    assert previous_period_value("month", date(2026, 3, 15)) == "2026-02"
    assert previous_period_value("day", date(2026, 3, 1)) == "2026-02-28"
    assert previous_period_value("year", date(2026, 1, 1)) == "2025"
