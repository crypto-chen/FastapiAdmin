"""业务员下推金额按收款日期归期的单元测试（纯函数，不依赖数据库）。"""

from app.modules.metric.engine import extract_push_person_stat

ROWS = [
    {
        "number": "A",
        "create_id": "p1",
        "status": "384",
        "erp_push_status": "1",
        "erp_push_date": "2026-08-10",
        "collectiontime": "2026-09-05",
        "createtime": "2026-08-01 00:00:00",
        "remove_taxes_freight": "100",
    },
    {
        "number": "B",
        "create_id": "p1",
        "status": "384",
        "erp_push_status": "1",
        "erp_push_date": "2026-09-10",
        "collectiontime": "2026-08-05",
        "createtime": "2026-09-06 00:00:00",
        "remove_taxes_freight": "200",
    },
    {
        "number": "C",
        "create_id": "p2",
        "status": "384",
        "erp_push_status": "1",
        "erp_push_date": "2026-09-15",
        "collectiontime": "2026-09-20",
        "createtime": "2026-09-10 00:00:00",
        "remove_taxes_freight": "300",
    },
    {
        "number": "D",
        "create_id": "p2",
        "status": "384",
        "erp_push_status": "2",
        "erp_push_date": "2026-09-15",
        "collectiontime": "2026-09-20",
        "createtime": "2026-09-10 00:00:00",
        "remove_taxes_freight": "400",
    },
    {
        "number": "E",
        "create_id": "p2",
        "status": "522",
        "erp_push_status": "1",
        "erp_push_date": "2026-09-15",
        "collectiontime": "2026-09-20",
        "createtime": "2026-09-10 00:00:00",
        "remove_taxes_freight": "500",
    },
]

CONFIG = {
    "person_field": "create_id",
    "status_field": "status",
    "status_allow": ["384"],
    "push_status_field": "erp_push_status",
    "push_status_allow": ["1"],
    "push_date_field": "erp_push_date",
    "amount_terms": [{"field": "remove_taxes_freight", "sign": 1}],
    "stat": "amount",
}


def test_push_amount_period_uses_collectiontime():
    result = extract_push_person_stat(
        ROWS, [], {**CONFIG, "period_field": "collectiontime"}, "month", "2026-09"
    )

    assert result["total"] == 400.0
    assert result["matched_rows"] == 2
    assert result["persons"] == {
        "p1": {"value": 100.0, "orders": 1, "days": 9.0},
        "p2": {"value": 300.0, "orders": 1, "days": 5.0},
    }


def test_push_amount_period_defaults_to_push_date():
    result = extract_push_person_stat(ROWS, [], CONFIG, "month", "2026-09")

    assert result["total"] == 500.0
    assert result["matched_rows"] == 2
    assert result["persons"] == {
        "p1": {"value": 200.0, "orders": 1, "days": 4.0},
        "p2": {"value": 300.0, "orders": 1, "days": 5.0},
    }
