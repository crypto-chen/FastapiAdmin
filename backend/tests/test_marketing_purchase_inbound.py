"""营销中心采购入库金额（含税）取数执行器单元测试（纯函数，不依赖数据库与金蝶）。"""

from app.modules.metric.engine import extract_bill_amount

# 与 scripts/seed_marketing_purchase_inbound_metric.py 的 MEASURES.components 一致
INSTOCK_CONFIG = {
    "amount_field": "FBillAllAmount_LC",
    "dedupe_field": "FBillNo",
    "row_filters": [{"field": "FBillTypeID.FNumber", "op": "equals", "value": "RKD01_SYS"}],
}
RECEIVE_CONFIG = {
    "amount_field": "FAllAmount",
    "row_filters": [{"field": "F_NTHM_Base_re5.FName", "op": "not_contains", "value": "人力行政部"}],
}


def test_purchase_instock_standard_type_deduped_by_bill():
    rows = [
        # 标准采购入库单：两条分录，表头价税合计(本位币)同值，按单号去重只计一次
        {
            "FBillNo": "CGRK001",
            "FBillTypeID.FNumber": "RKD01_SYS",
            "FBillAllAmount_LC": 1000.0,
        },
        {
            "FBillNo": "CGRK001",
            "FBillTypeID.FNumber": "RKD01_SYS",
            "FBillAllAmount_LC": 1000.0,
        },
        # 非标准单据类型：不纳入
        {
            "FBillNo": "CGRK002",
            "FBillTypeID.FNumber": "RKD02_SYS",
            "FBillAllAmount_LC": 500.0,
        },
        # 另一张标准单
        {
            "FBillNo": "CGRK003",
            "FBillTypeID.FNumber": "RKD01_SYS",
            "FBillAllAmount_LC": 200.0,
        },
    ]

    extracted = extract_bill_amount(rows, [], INSTOCK_CONFIG)

    assert extracted["total"] == 1200.0  # 1000（去重）+ 200
    assert extracted["matched_rows"] == 2


def test_receive_bill_excludes_hr_dept_lines():
    rows = [
        {"FBillNo": "CGSL001", "F_NTHM_Base_re5.FName": "生产部", "FAllAmount": 100.0},
        {"FBillNo": "CGSL001", "F_NTHM_Base_re5.FName": "人力行政部", "FAllAmount": 50.0},
        # 费用承担部门为空：视为不含人力行政部，纳入
        {"FBillNo": "CGSL002", "F_NTHM_Base_re5.FName": None, "FAllAmount": 30.0},
        {"FBillNo": "CGSL003", "F_NTHM_Base_re5.FName": "", "FAllAmount": 20.0},
    ]

    extracted = extract_bill_amount(rows, [], RECEIVE_CONFIG)

    assert extracted["total"] == 150.0  # 100 + 30 + 20
    assert extracted["matched_rows"] == 3


def test_list_rows_use_field_order():
    """单据查询也可能返回值数组：按 FieldKeys 顺序取值。"""
    fields = ["FBillNo", "FBillTypeID.FNumber", "FBillAllAmount_LC"]
    rows = [
        ["CGRK001", "RKD01_SYS", "1,000.00"],
        ["CGRK002", "RKD01_SYS", "250.50"],
        ["CGRK003", "RKD09_SYS", "999.00"],
    ]

    extracted = extract_bill_amount(rows, fields, INSTOCK_CONFIG)

    assert extracted["total"] == 1250.5
    assert extracted["matched_rows"] == 2
