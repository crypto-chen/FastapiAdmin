"""订单宽表客户匹配：编码优先、ID 仅在唯一时兜底。"""

from app.modules.order.build import build_record


def _row(**overrides):
    row = {
        "id": 1,
        "number": "DY202610-00001",
        "type": "1",
        "status": "384",
        "createtime": "2026-10-01 10:00:00",
        "collectiontime": "2026-10-01",
        "qty": "1.00",
        "remove_taxes_freight": "100.00",
        "material_cost_total": "60.00",
        "process_cost_total": "20.00",
        "customer": 123,
        "customer_code": "LS20260101000123",
        "create_id": "35",
        "is_new": "1",
    }
    row.update(overrides)
    return row


def _build(row, customer_map, customer_by_id=None):
    record, _quality = build_record(
        row,
        "domestic",
        "2026-10",
        1,
        customer_map,
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        {},
        customer_by_id=customer_by_id,
    )
    assert record is not None
    return record


def test_customer_code_wins_over_colliding_id():
    customer_map = {
        "LS20260101000123": {
            "name": "零售客户",
            "number": "LS20260101000123",
            "principal_id": 9,
            "is_retail": 1,
        },
        "20200101-000123": {
            "name": "定制客户",
            "number": "20200101-000123",
            "principal_id": 8,
            "is_retail": 0,
        },
    }
    # 同一 ID 两张表都有 → 调用方不会放进 customer_by_id
    record = _build(_row(), customer_map, customer_by_id={})

    assert record.extra["customer_number"] == "LS20260101000123"
    assert record.extra["customer_name"] == "零售客户"
    assert record.extra["customer_is_retail"] == 1


def test_missing_code_falls_back_to_unique_id():
    customer_map = {
        "20200101-000123": {
            "name": "定制客户",
            "number": "20200101-000123",
            "principal_id": 8,
            "is_retail": 0,
        }
    }
    record = _build(
        _row(customer_code=None),
        customer_map,
        customer_by_id={123: customer_map["20200101-000123"]},
    )

    assert record.extra["customer_number"] == "20200101-000123"
    assert record.extra["customer_name"] == "定制客户"
    assert record.extra["customer_is_retail"] == 0


def test_no_code_no_unique_id_keeps_order_code_empty():
    record = _build(_row(customer_code=None), {}, customer_by_id={})

    assert record.extra.get("customer_number") is None
    assert record.extra.get("customer_is_retail") is None
