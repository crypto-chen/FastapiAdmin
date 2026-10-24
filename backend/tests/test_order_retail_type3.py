"""orderAnalyze type=3（零售）映射到订单全链路的单元测试（纯函数，不依赖数据库）。"""

from app.modules.order.build import build_record, is_void_order, to_id_list


def _retail_row(**overrides):
    row = {
        "id": 24067,
        "number": "LS202609-00089",
        "type": "2",  # 零售单行内 type：2 = 外贸
        "status": "384",
        "createtime": "2026-09-01 10:00:00",
        "collectiontime": "2026-09-01",
        "qty": "2.00",
        "remove_taxes_freight": "100.00",
        "material_cost_total": "60.00",
        "process_cost_total": "20.00",
        "customer": "27456",
        "create_id": "35",
        "is_new": "1",
        "source": "184",
        "source_platform": "914",
        "country": "128",
    }
    row.update(overrides)
    return row


def test_retail_row_uses_retail_intake_and_order_type_3():
    record, quality = build_record(
        _retail_row(),
        "export",  # 行内 type=2 → 外贸，但仍应取零售金额口径
        "2026-09",
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
        is_retail=True,
    )

    assert record is not None
    assert record.order_type == "3"
    assert record.trade_type == "export"
    assert float(record.intake_untaxed) == 100.0
    assert record.extra["order_type_code"] == "3"
    assert record.extra["order_type"] == "零售"
    assert record.extra["unit_cost"] == 40.0
    assert "cost_missing" not in quality


def test_void_retail_order_is_skipped():
    assert is_void_order(_retail_row(status="522")) is True
    assert is_void_order(_retail_row(status="384")) is False


def test_multi_model_ids_are_split_and_deduplicated():
    assert to_id_list("486,486") == [486]
    assert to_id_list("12,13") == [12, 13]
    assert to_id_list("240,226,240") == [240, 226]
    assert to_id_list(None) == []
