"""CRM 连接配置与订单指标取数服务。"""

from __future__ import annotations

from app.modules.crm.client import CrmClient, CrmClientConfig, CrmError, month_date_range, parse_amount
from app.modules.crm.model import CrmConnectionModel

__all__ = ["CrmError", "build_client", "fetch_crm_amount", "month_date_range", "parse_amount"]


def build_client(connection: CrmConnectionModel) -> CrmClient:
    """按连接配置构造 CRM 客户端（无需凭据）。"""
    return CrmClient(
        CrmClientConfig(
            base_url=connection.base_url,
            timeout=int(connection.timeout or 30),
        )
    )


async def fetch_crm_amount(
    connection: CrmConnectionModel,
    path: str,
    date_range: list[str] | tuple[str, ...] | None = None,
    extra_params: dict | None = None,
) -> float:
    """调用一个 CRM 金额接口，返回未税金额数值。"""
    async with build_client(connection) as client:
        return await client.fetch_amount(path, date_range, extra_params)
