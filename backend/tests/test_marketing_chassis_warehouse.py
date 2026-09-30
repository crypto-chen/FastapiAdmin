"""营销中心机箱成品仓取数执行器单元测试（纯函数，不依赖数据库与金蝶）。"""

from app.modules.metric.engine import extract_inventory_ledger

# 与 scripts/seed_marketing_chassis_warehouse_metric.py 的 SOURCE_FIELDS 保持一致
FIELDS = [
    "FMATERIALBASEID",
    "FMATERIALNAME",
    "FSTOCKId",
    "FSTOCKPLACENAME",
    "FACCTGRANGEID",
    "FACCTGRANGENAME",
    "FUNITNAME",
    "FINITQty",
    "FINITAMOUNT",
    "FRECEIVEQty",
    "FRECEIVEAmount",
    "FSENDQty",
    "FSENDAmount",
    "FENDQty",
    "FENDAmount",
]

# 与 seed 脚本 MEASURES 一致
CONFIG = {
    "amount_field": "FENDAmount",
    "qty_field": "FENDQty",
    "stock_field": "FSTOCKId",
    "material_field": "FMATERIALBASEID",
    "subtotal_suffix": "-总计",
}


def _row(material, name, stock, location, end_qty, end_amount):
    """按 FieldKeys 顺序造一行报表数据（其余列省略为空）。"""
    return [
        material,
        name,
        stock,
        location,
        "HSFW000001_SYS",
        "默认核算范围",
        "Pcs",
        "",
        "",
        "",
        "",
        "",
        "",
        end_qty,
        end_amount,
    ]


def test_detail_rows_are_summed_and_subtotals_skipped():
    rows = [
        # 明细行（仓库=机箱成品仓，仓位不同）：合计 = 161.7 - 40.69 + 8.58 = 129.59
        _row("BCP0000605", "D后机脚", "机箱成品仓", "D12", "5", "161.7"),
        _row("BCP0000605", "D后机脚", "机箱成品仓", "001", "3", "-40.69"),
        _row("BCP0000605", "D后机脚", "机箱成品仓", "D4", "1", "8.58"),
        # 小计行：仓库列为空、物料编码带 -总计；若参与汇总会把金额重复计算一倍
        _row("BCP0000605-总计", "D后机脚", "", "", "9", "129.59"),
    ]

    extracted = extract_inventory_ledger(rows, FIELDS, CONFIG)

    assert extracted["total"] == 129.59
    assert extracted["qty_total"] == 9.0
    assert extracted["matched_rows"] == 3
    assert extracted["departments"] == {}


def test_rows_without_stock_are_skipped():
    """仓库列为空的行（如物料合计行）必须跳过，避免重复计入。"""
    rows = [
        _row("BCP0000001", "下盖", "机箱成品仓", "", "2", "10.5"),
        _row("BCP0000001", "下盖", "", "", "2", "10.5"),
    ]

    extracted = extract_inventory_ledger(rows, FIELDS, CONFIG)

    assert extracted["total"] == 10.5
    assert extracted["matched_rows"] == 1


def test_amount_field_can_switch_to_quantity():
    """amount_field 改成 FENDQty 时取期末结存数量口径。"""
    rows = [
        _row("BCP0000002", "上盖", "机箱成品仓", "", "7", "70"),
    ]

    extracted = extract_inventory_ledger(rows, FIELDS, {**CONFIG, "amount_field": "FENDQty"})

    assert extracted["total"] == 7.0
    assert extracted["qty_total"] == 7.0
