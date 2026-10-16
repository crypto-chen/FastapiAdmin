"""存货收发存汇总表（全仓·全物料）数据接入的纯函数测试（不依赖数据库与金蝶）。"""

import importlib.util
from pathlib import Path

import pytest

from app.modules.metadata.sync import resolve_report_target

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, SCRIPTS_DIR / f"{module_name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


seed = _load("seed_inventory_inout_summary_full")
check = _load("check_inventory_inout_summary")


# --------------------------------------------------------------------------- #
# 取数目标解析：来源对象 code 与提交给金蝶的 FormId 解耦
# --------------------------------------------------------------------------- #
def test_report_target_uses_template_form_id():
    """模板声明了 FormId：以模板为准，且把该键从提交参数里摘掉。"""
    form_id, params = resolve_report_target(seed.SOURCE_OBJECT_CODE, seed.REQUEST_PARAMS)
    assert form_id == seed.FORM_ID == "HS_INOUTSTOCKSUMMARYRPT"
    assert "FormId" not in params
    assert params["FieldKeys"] == seed.REQUEST_PARAMS["FieldKeys"]
    assert seed.REQUEST_PARAMS["FormId"] == seed.FORM_ID  # 原模板不被就地修改


def test_report_target_keeps_legacy_behaviour_without_form_id():
    """模板没写 FormId（既有数据源）：FormId 取来源对象 code，参数原样提交。"""
    params = {"FieldKeys": "FBillNo", "StartRow": 0, "Limit": 2000}
    form_id, sent = resolve_report_target("GL_RPT_AccountBalance", params)
    assert form_id == "GL_RPT_AccountBalance"
    assert sent is params


@pytest.mark.parametrize("declared", ["", "   ", None])
def test_report_target_falls_back_when_form_id_blank(declared):
    """FormId 为空/空白：回退到来源对象 code，同时仍然摘掉该键。"""
    params = {"FormId": declared, "FieldKeys": "FBillNo"}
    form_id, sent = resolve_report_target("HS_INOUTSTOCKSUMMARYRPT_FULL", params)
    assert form_id == "HS_INOUTSTOCKSUMMARYRPT_FULL"
    assert sent == {"FieldKeys": "FBillNo"}


# --------------------------------------------------------------------------- #
# 数据源声明（脚本常量）
# --------------------------------------------------------------------------- #
def test_field_keys_match_declared_fields():
    keys = [key for key, _name, _is_measure in seed.SOURCE_FIELDS]
    assert keys == seed.FIELD_KEYS
    assert seed.REQUEST_PARAMS["FieldKeys"] == ",".join(seed.FIELD_KEYS)
    assert len(keys) == 21
    # 库存结存成本 / 物料成本 两列必须在列清单里
    assert {"FENDQty", "FENDPrice", "FENDAmount"} <= set(keys)
    assert seed.MEASURE_FIELD_KEYS == {
        "FINITQty",
        "FINITPrice",
        "FINITAMOUNT",
        "FRECEIVEQty",
        "FRECEIVEPrice",
        "FRECEIVEAmount",
        "FSENDQty",
        "FSENDPrice",
        "FSENDAmount",
        "FENDQty",
        "FENDPrice",
        "FENDAmount",
    }


def test_model_scope_is_org100_all_warehouses():
    model = seed.REQUEST_PARAMS["Model"]
    # 核算组织走 {{org_code}} 占位，由同步任务的 org_code（=100）在取数时渲染
    assert model["FACCTGORGID"]["FNumber"] == "{{org_code}}"
    assert seed.ORG_CODE == "100"
    assert model["FACCTGSYSTEMID"]["FNumber"] == "KJHSTX01_SYS"
    assert model["FACCTPOLICYID"]["FNumber"] == "KJZC01_SYS"
    assert model["FYear"] == "{{year}}" and model["FPeriod"] == "{{period}}"
    assert model["FENDYEAR"] == "{{year}}" and model["FEndPeriod"] == "{{period}}"
    assert model["FCOMBOSTATUS"] == "C"
    # 仓库区间留空 = 全部仓库（只填一端会失效，两端都填同一编码才锁定单一仓库）
    assert model["FSTOCKId"]["FNumber"] == "" and model["FENDSTOCKID"]["FNumber"] == ""
    # FYearPeriod 列要求打开「显示各期间明细」
    assert model["FIsDisplayPeriod"] is True


# --------------------------------------------------------------------------- #
# 校验脚本的汇总规则：与指标引擎 extract_inventory_ledger 一致
# --------------------------------------------------------------------------- #
def _row(material, stock, end_qty, end_price, end_amount):
    """按 seed.FIELD_KEYS 顺序造一行（当期字段省略为空）。"""
    values = dict.fromkeys(seed.FIELD_KEYS, "")
    values["FYearPeriod"] = "2026.09"
    values["FMATERIALBASEID"] = material
    values["FSTOCKId"] = stock
    values["FENDQty"] = end_qty
    values["FENDPrice"] = end_price
    values["FENDAmount"] = end_amount
    return [values[key] for key in seed.FIELD_KEYS]


def test_aggregate_skips_subtotal_and_empty_stock_rows():
    rows = [
        _row("BCP0000605", "机箱成品仓", "10", "2.825", "28.25"),
        _row("BCP0000605", "海柔仓", "5", "1", "5"),
        _row("BCP0000605-总计", "", "", "", "33.25"),  # 小计行：跳过
        _row("BCP0000606", "", "3", "1", "3"),  # 无仓库行：跳过
    ]
    stat = check.aggregate(rows, seed.FIELD_KEYS)
    assert stat["rows"] == 4
    assert stat["detail_rows"] == 2
    assert stat["subtotal_rows"] == 1
    assert stat["rows_without_stock"] == 1
    assert stat["totals"]["FENDAmount"] == pytest.approx(33.25)
    assert stat["totals"]["FENDQty"] == pytest.approx(15)
    assert stat["non_null"]["FENDPrice"] == 2


def test_aggregate_treats_blank_and_bad_values_as_zero():
    rows = [
        _row("A", "仓1", "", "", "161.7"),  # 数量/单价为空、金额有值（实测存在）
        _row("B", "仓2", "2", "abc", ""),  # 脏值按 0 计，不抛异常
    ]
    stat = check.aggregate(rows, seed.FIELD_KEYS)
    assert stat["totals"]["FENDAmount"] == pytest.approx(161.7)
    assert stat["totals"]["FENDQty"] == pytest.approx(2)
    # 非空行数按「字符串非空」统计：第二行单价是脏值 "abc"（计入非空、按 0 参与合计）
    assert stat["non_null"]["FENDPrice"] == 1
