"""开放接口：按应用限制可读指标（metric_scope）。"""

from types import SimpleNamespace

from app.modules.openapi.schema import OpenClientCreateSchema
from app.modules.openapi.service import OpenApiService


def _client(scope):
    return SimpleNamespace(metric_scope=scope)


def test_empty_scope_allows_all_metrics() -> None:
    assert OpenApiService._metric_allowed(_client(None), "OPC-COST-01")
    assert OpenApiService._metric_allowed(_client([]), "marketing_office_expense")


def test_scope_limits_to_selected_codes() -> None:
    client = _client(["OPC-COST-01", "OPC-COST-12"])
    assert OpenApiService._metric_allowed(client, "OPC-COST-01")
    assert OpenApiService._metric_allowed(client, "OPC-COST-12")
    assert not OpenApiService._metric_allowed(client, "OPC-COST-02")
    assert not OpenApiService._metric_allowed(client, "marketing_office_expense")


def test_create_schema_accepts_metric_scope() -> None:
    data = OpenClientCreateSchema(
        app_id="bi_report",
        name="BI 报表",
        metric_scope=["OPC-COST-01", "OPC-COST-02"],
    )
    assert data.metric_scope == ["OPC-COST-01", "OPC-COST-02"]
