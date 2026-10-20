from datetime import datetime

from app.modules.metadata.sync import render_request_params
from scripts.seed_crm_push_metrics import METRICS, PUSH_AMOUNT_PARAMS, SOURCE_OBJECTS


def test_push_amount_sources_use_type_codes():
    specs = {spec["path"]: spec for spec in SOURCE_OBJECTS}
    assert specs["/hs/push/getPush?type=1"]["params"] == PUSH_AMOUNT_PARAMS
    assert specs["/hs/push/getPush?type=2"]["params"] == PUSH_AMOUNT_PARAMS


def test_push_amount_metrics_point_to_type_codes():
    metrics = {metric["code"]: metric for metric in METRICS}
    assert metrics["marketing_order_push_same_month"]["path"] == "/hs/push/getPush?type=1"
    assert metrics["marketing_order_push_prior_month"]["path"] == "/hs/push/getPush?type=2"


def test_push_amount_date_range_is_full_month():
    rendered = render_request_params(PUSH_AMOUNT_PARAMS, now=datetime(2026, 9, 1))
    assert rendered == {"dateRange": ["2026-09-01 00:00:00", "2026-09-30 23:59:59"]}
