"""MES 订单接口新增字段的单元测试：负责人、单价、是否重要、是否全检。"""

from app.modules.mes.service import _to_item
from app.modules.order.build import build_record
from app.modules.order.fields import FIELD_BY_CODE, SOURCE_KEYS
from app.modules.order.model import OrderFullChainModel


def _row(**overrides):
    row = {
        "id": 182963,
        "number": "DY202611-00035",
        "status": "384",
        "createtime": "2026-11-01 09:00:00",
        "qty": "10",
        "price": "600.00",
        "remove_taxes_freight": "5544.55",
        "principal_id": 100094,
        "important": "1",
        "is_full_inspection": "2",
    }
    row.update(overrides)
    return row


def _build(row, person_index=None):
    record, _quality = build_record(
        row,
        "domestic",
        "2026-11",
        1,
        {},
        person_index or {},
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


def test_build_record_maps_principal_price_and_flags():
    record = _build(_row(), person_index={"100094": {"person_name": "王敏"}})
    extra = record.extra

    assert extra["principal_id"] == 100094
    assert extra["principal_name"] == "王敏"
    assert extra["price"] == 600.0
    assert extra["important"] == 1
    assert extra["is_full_inspection"] == 2


def test_build_record_missing_new_fields_stay_null():
    record = _build(
        _row(principal_id=None, price=None, important=None, is_full_inspection=None)
    )
    extra = record.extra

    assert extra["principal_id"] is None
    assert extra["principal_name"] is None
    assert extra["price"] is None
    assert extra["important"] is None
    assert extra["is_full_inspection"] is None


def test_mes_item_uses_latest_person_name_and_typed_values():
    row = OrderFullChainModel(
        order_number="DY202611-00035",
        period_value="2026-11",
        calc_version=1,
        trade_type="domestic",
        qty=10,
        extra={
            "principal_id": "100094",
            "principal_name": "旧负责人快照",
            "price": "600.00",
            "important": "1",
            "is_full_inspection": "2",
        },
    )

    item = _to_item(row, {"100094": "王敏（新）"})

    assert item["principal_id"] == 100094
    assert item["principal_name"] == "王敏（新）"
    assert item["price"] == 600.0
    assert item["important"] == 1
    assert item["is_full_inspection"] == 2


def test_mes_item_falls_back_to_snapshot_when_person_missing():
    row = OrderFullChainModel(
        order_number="DY202611-00035",
        period_value="2026-11",
        calc_version=1,
        trade_type="domestic",
        qty=10,
        extra={"principal_id": 999999, "principal_name": "已离职负责人"},
    )

    item = _to_item(row, {})

    assert item["principal_id"] == 999999
    assert item["principal_name"] == "已离职负责人"
    assert item["price"] is None
    assert item["important"] is None
    assert item["is_full_inspection"] is None


def test_field_catalog_and_source_keys_registered():
    assert FIELD_BY_CODE["principal_id"][1] == "负责人ID"
    assert FIELD_BY_CODE["principal_name"][1] == "负责人（业务员）"
    assert FIELD_BY_CODE["price"][1] == "单价"
    assert "重要" in FIELD_BY_CODE["important"][1]
    assert "全检" in FIELD_BY_CODE["is_full_inspection"][1]
    assert SOURCE_KEYS["principal_id"] == ["principal_id"]
    assert SOURCE_KEYS["price"] == ["price"]
    assert SOURCE_KEYS["important"] == ["important"]
    assert SOURCE_KEYS["is_full_inspection"] == ["is_full_inspection"]
