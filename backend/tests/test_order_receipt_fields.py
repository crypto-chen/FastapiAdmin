"""orderAnalyze 回款/线索字段接入订单全链路的单元测试（纯函数，不依赖数据库）。"""

from datetime import date

from app.modules.order.build import SCHEMA_VERSION, build_record
from app.modules.order.fields import FIELD_BY_CODE, SOURCE_KEYS


def _row(**overrides):
    row = {
        "id": 182963,
        "number": "DY202611-00035",
        "status": "384",
        "createtime": "2026-11-01 09:00:00",
        "qty": "10",
        "remove_taxes_freight": "2450.00",
        "receivable": "2768.50",
        "material_cost_total": "1000.00",
        "process_cost_total": "500.00",
        "deposit": "2450.00",
        "claim_amount": "1225.00",
        "deposit_claim_amount": "1000.00",
        "first_receipt_date": "2026-11-06 13:50:16",
        "clue_id": "93817",
    }
    row.update(overrides)
    return row


def _build(row):
    record, _quality = build_record(
        row,
        "domestic",
        "2026-11",
        1,
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
    )
    assert record is not None
    return record


def test_receipt_fields_are_mapped_and_derived():
    record = _build(_row())
    extra = record.extra

    assert extra["claim_amount"] == 1225.0
    assert extra["deposit_claim_amount"] == 1000.0
    assert extra["first_receipt_date"] == "2026-11-06"
    assert extra["clue_id"] == 93817
    assert extra["intake_taxed"] == 2768.5
    assert record.order_date == date(2026, 11, 1)
    # claim_amount 是含税到账，回款率分母用含税应收 receivable，而不是未税金额
    assert extra["receipt_rate"] == round(1225 / 2768.5, 6)
    assert extra["deposit_receipt_rate"] == round(1000 / 2450, 6)
    assert extra["receipt_cycle"] == 5.0
    assert extra["schema_version"] == SCHEMA_VERSION


def test_missing_receipt_fields_stay_null():
    record = _build(
        _row(
            claim_amount=None,
            deposit_claim_amount=None,
            first_receipt_date=None,
            clue_id=None,
        )
    )
    extra = record.extra

    assert extra["claim_amount"] is None
    assert extra["deposit_claim_amount"] is None
    assert extra["first_receipt_date"] is None
    assert extra["clue_id"] is None
    assert extra["receipt_rate"] is None
    assert extra["deposit_receipt_rate"] is None
    assert extra["receipt_cycle"] is None


def test_zero_deposit_does_not_divide_by_zero():
    record = _build(_row(deposit="0.00", deposit_claim_amount="100.00"))
    assert record.extra["deposit_receipt_rate"] is None


def test_field_catalog_uses_new_ord_codes():
    assert FIELD_BY_CODE["claim_amount"][5] == "ORD-29"
    assert FIELD_BY_CODE["intake_taxed"][5] == "ORD-13-a"
    assert FIELD_BY_CODE["first_receipt_date"][5] == "ORD-28"
    assert FIELD_BY_CODE["deposit_claim_amount"][5] == "ORD-16-a"
    assert FIELD_BY_CODE["receipt_cycle"][5] == "ORD-31"
    assert FIELD_BY_CODE["clue_id"][5] == "ORD-69"
    # 旧字段保留编码，但不再占用 ORD 指标编码，避免同一指标出现两列
    assert FIELD_BY_CODE["payment_amount"][5] == ""
    assert FIELD_BY_CODE["payment_date"][5] == ""


def test_source_keys_point_to_order_analyze_fields():
    assert SOURCE_KEYS["claim_amount"] == ["claim_amount"]
    assert SOURCE_KEYS["deposit_claim_amount"] == ["deposit_claim_amount"]
    assert SOURCE_KEYS["first_receipt_date"] == ["first_receipt_date"]
    assert SOURCE_KEYS["clue_id"] == ["clue_id"]
