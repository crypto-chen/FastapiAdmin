"""客户分析开放接口冒烟检查（文档《客户分析月度指标开放接口对接说明》的落地校验）。

用进程内 ASGI 调用 `/open/v1/customers**`，依赖替换掉开放令牌校验（不写库、不启服务），
断言文档里写明的返回结构：字段目录条数、summary 语义、合计行位置、敏感字段裁剪、错误码。

用法：
    cd backend
    python scripts/check_customer_open_api.py
"""

import asyncio
import io
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import httpx  # noqa: E402

from app import create_app  # noqa: E402
from app.modules.customer.fields import FIELD_DEFS  # noqa: E402
from app.modules.openapi.dependencies import get_open_client  # noqa: E402

FIELD_COUNT = len(FIELD_DEFS)
SENSITIVE_COUNT = sum(1 for _c, _n, _t, _g, sensitive, _s, _note in FIELD_DEFS if sensitive)

results: list[tuple[str, bool, str]] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'} | {name} | {detail}")


class FakeClient:
    """替代 open_client 表记录：只用权限开关，避免测试写库。"""

    def __init__(self, allow_customer_detail: bool = True, allow_cost_fields: bool = False) -> None:
        self.allow_customer_detail = allow_customer_detail
        self.allow_cost_fields = allow_cost_fields


async def call(app, path: str, client: FakeClient) -> httpx.Response:
    app.dependency_overrides[get_open_client] = lambda: client
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        return await ac.get(path, headers={"Authorization": "Bearer smoke"})


async def main() -> None:
    app = create_app()
    cost = FakeClient(allow_cost_fields=True)
    nocost = FakeClient(allow_cost_fields=False)
    denied = FakeClient(allow_customer_detail=False)

    r = await call(app, "/open/v1/customers/fields", cost)
    fields = r.json()["data"]["fields"]
    check("字段目录：开通成本字段时 = 注册表条数", len(fields) == FIELD_COUNT, f"{len(fields)} / {FIELD_COUNT}")
    check("字段目录：schema_version", bool(r.json()["data"]["schema_version"]), r.json()["data"]["schema_version"])

    r = await call(app, "/open/v1/customers/fields", nocost)
    codes = [f["field_code"] for f in r.json()["data"]["fields"]]
    check(
        "字段目录：关闭成本字段时剔除敏感项",
        len(codes) == FIELD_COUNT - SENSITIVE_COUNT and "CUS-28" not in codes,
        f"{len(codes)} / {FIELD_COUNT - SENSITIVE_COUNT}",
    )

    r = await call(app, "/open/v1/customers/fields", denied)
    check("权限：未开通 allow_customer_detail 返回 403/40101",
          r.status_code == 403 and r.json()["code"] == 40101, str(r.status_code))

    r = await call(app, "/open/v1/customers/fields", cost)
    r = await call(app, "/open/v1/customers?page_no=1&page_size=1", cost)
    first = r.json()["data"]
    period, version, total = first["period_value"], first["calc_version"], first["total"]
    check("明细：默认取最新期间/版本", bool(period) and version >= 1, f"{period} v{version}")
    row = first["rows"][0]["fields"]
    check("明细：每行 47 个 CUS 键（+核心列）", sum(1 for k in row if k.startswith("CUS-")) == FIELD_COUNT,
          f"{len(row)} 个键")
    check("明细：summary 在首页为 null（合计行不在首页）",
          all(v is None for v in first["summary"].values()) and total > 1, str(first["summary"]))

    page_size = 500
    last_page = -(-total // page_size)
    r = await call(app, f"/open/v1/customers?page_no={last_page}&page_size={page_size}", cost)
    data = r.json()["data"]
    last_row = data["rows"][-1]["fields"]
    check("明细：合计行是结果集最后一行", bool(last_row.get("is_aggregate")) and not data["has_more"],
          f"page {last_page}, rows {len(data['rows'])}")
    check("明细：末页 summary 有值",
          data["summary"]["intake_untaxed_sum"] == last_row.get("CUS-12")
          and data["summary"]["net_shipment_sum"] == last_row.get("CUS-16"),
          str(data["summary"]))
    check("明细：合计行 CUS-01/CUS-02 为空、customer_name=合计",
          last_row.get("CUS-01") is None and last_row.get("CUS-02") is None
          and last_row.get("customer_name") == "合计", "")

    r = await call(app, "/open/v1/customers?include_aggregate=false&page_size=1", cost)
    check("明细：include_aggregate=false 时 total 不带合计行",
          r.json()["data"]["total"] == total - 1, f"{r.json()['data']['total']} / {total - 1}")

    r = await call(app, "/open/v1/customers?page_size=2", nocost)
    fields_nocost: dict[str, Any] = r.json()["data"]["rows"][0]["fields"]
    check("明细：关闭成本字段时 CUS-xx 成本字段被剔除（核心列仍在）",
          "CUS-28" not in fields_nocost and "gross_profit" in fields_nocost, "")

    r = await call(app, f"/open/v1/customers/{row['customer_code']}", cost)
    detail = r.json()["data"]
    check("详情：返回 item/columns/period_value",
          r.json()["code"] == 0 and detail["period_value"] == period and "columns" in detail,
          f"{detail['period_value']}")

    r = await call(app, "/open/v1/customers/NOT-EXIST-CODE", cost)
    check("详情：客户无数据返回 code=-1/HTTP 500",
          r.status_code == 500 and r.json()["code"] == -1, str(r.json()["msg"]))

    r = await call(app, "/open/v1/customers?page_size=9999", cost)
    check("参数：page_size 越界返回 422/code=1",
          r.status_code == 422 and r.json()["code"] == 1, r.json()["msg"])

    failed = [name for name, ok, _ in results if not ok]
    print(f"\n合计 {len(results)} 项，通过 {len(results) - len(failed)} 项，失败 {len(failed)} 项")
    if failed:
        raise SystemExit("失败项：" + "；".join(failed))


if __name__ == "__main__":
    asyncio.run(main())
