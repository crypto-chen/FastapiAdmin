"""业务员金额指标按指定日期字段归期的单元测试（纯函数，不依赖数据库）。"""

from app.modules.metric.engine import extract_person_amount


ROWS = [
    {
        "number": "A",
        "create_id": "p1",
        "status": "384",
        "remove_taxes_freight": "100",
        "collectiontime": "2026-10-05",
    },
    {
        "number": "B",
        "create_id": "p1",
        "status": "384",
        "remove_taxes_freight": "200",
        "collectiontime": "2026-09-30",
    },
    {
        "number": "C",
        "create_id": "p2",
        "status": "384",
        "remove_taxes_freight": "300",
        "collectiontime": "2026-10-20",
    },
    {
        "number": "D",
        "create_id": "p2",
        "status": "522",
        "remove_taxes_freight": "400",
        "collectiontime": "2026-10-20",
    },
]

CONFIG = {
    "person_field": "create_id",
    "status_field": "status",
    "status_allow": ["384"],
    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
}


def test_without_period_field_keeps_all_valid_rows():
    result = extract_person_amount(ROWS, [], CONFIG)

    assert result["total"] == 600.0
    assert result["matched_rows"] == 3
    assert result["persons"]["p1"]["value"] == 300.0


def test_collection_period_filters_rows_by_collectiontime_month():
    result = extract_person_amount(
        ROWS, [], {**CONFIG, "period_field": "collectiontime"}, "month", "2026-10"
    )

    assert result["total"] == 400.0
    assert result["matched_rows"] == 2
    assert result["persons"] == {
        "p1": {"value": 100.0, "rows": 1},
        "p2": {"value": 300.0, "rows": 1},
    }


def test_collection_period_can_land_in_previous_month():
    result = extract_person_amount(
        ROWS, [], {**CONFIG, "period_field": "collectiontime"}, "month", "2026-09"
    )

    assert result["total"] == 200.0
    assert result["persons"] == {"p1": {"value": 200.0, "rows": 1}}
