"""CRM 订单未税金额接口客户端。

接口文档：《订单未税金额接口文档》。域名 ``http://crmapi.yonggubox.com``，
全部接口均为 ``GET``、**无需登录/令牌**，公共参数只有 ``dateRange``
（报价/订单日期范围，缺省本月）。统一返回
``{"code": 1, "msg": "", "time": ..., "data": 数值}``。

``dateRange`` 支持数组、逗号串、波浪号串三种写法，区间为闭区间（含首尾）；
这里统一按数组写法 ``dateRange[]=start&dateRange[]=end`` 传参。
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Any

import httpx
from pydantic import BaseModel

DEFAULT_BASE_URL = "http://crmapi.yonggubox.com"
DATE_FMT = "%Y-%m-%d"


class CrmError(RuntimeError):
    """CRM 接口返回非成功 ``code``，或响应不是合法 JSON。"""

    def __init__(self, message: str, code: Any = None, payload: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload


class CrmClientConfig(BaseModel):
    """CRM 连接配置（无需凭据，只有域名与超时）。"""

    base_url: str = DEFAULT_BASE_URL
    timeout: int = 30
    retry_times: int = 3


class CrmClient:
    """CRM 开放接口客户端。"""

    def __init__(self, config: CrmClientConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return (self.config.base_url or DEFAULT_BASE_URL).rstrip("/")

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout, follow_redirects=True)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> CrmClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def call(
        self,
        path: str,
        date_range: list[str] | tuple[str, ...] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET 一个 CRM 接口，返回原始 JSON 响应（失败抛 :class:`CrmError`）。

        ``date_range`` 按数组写法传 ``dateRange[]``；``extra_params`` 里的键原样透传
        （**列表值自动补 ``[]``**：CRM 是 PHP 应用，重复键不加 ``[]`` 只会保留最后一个值，
        区间参数会退化成单点），用于 ``transformation``、``pushDateRange`` 等接口参数。
        ``path`` 允许自带查询串（如 ``/hs/push/getPush?type=2``，用于同一接口按参数
        拆成多个来源对象）；无额外参数时传 ``params=None``，避免 httpx 用空序列覆盖掉
        路径里的查询串。
        """
        params: list[tuple[str, str]] = []
        if date_range:
            params = [("dateRange[]", str(item)) for item in date_range if item]
        for key, value in (extra_params or {}).items():
            if value is None or value == "":
                continue
            if isinstance(value, (list, tuple)):
                # PHP 数组写法：key[]=v1&key[]=v2；写成重复的 key 只会取到最后一个值
                params.extend((f"{key}[]", str(item)) for item in value if item is not None)
            else:
                params.append((str(key), str(value)))

        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(max(int(self.config.retry_times), 1)):
            client = await self._http()
            try:
                # params 为空时传 None：httpx 收到空序列会把 URL 自带的查询串丢掉
                response = await client.get(url, params=params or None)
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as e:
                last_error = CrmError(f"CRM 接口请求失败：{e}")
                await asyncio.sleep(min(2**attempt, 5))
                continue

            if not isinstance(payload, dict):
                raise CrmError(f"CRM 接口返回格式异常：{str(payload)[:300]}")

            code = payload.get("code")
            # 文档成功码为 1；兼容 0（部分网关约定）
            if code in (1, 0):
                return payload
            message = str(payload.get("msg") or "接口返回失败")
            raise CrmError(f"CRM 接口返回错误(code={code})：{message}", code=code, payload=payload)

        raise last_error or CrmError("CRM 接口请求失败")

    async def fetch_amount(
        self,
        path: str,
        date_range: list[str] | tuple[str, ...] | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> float:
        """取一个金额接口的 ``data`` 数值（无法解析为数值时按 0 处理）。"""
        payload = await self.call(path, date_range, extra_params)
        return parse_amount(payload.get("data"))


def parse_amount(value: Any) -> float:
    """把接口 ``data`` 解析成 float；兼容 ``None`` / 空串 / 带千分位字符串。"""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if not text or text in {"-", "--"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def month_date_range(period_value: str | date | datetime) -> tuple[str, str]:
    """月度期间值 → ``[月初, 月末]``（闭区间，与文档默认本月口径一致）。

    支持 ``YYYY-MM`` / ``YYYY-MM-DD`` / ``YYYY``（按 1 月处理）。
    """
    if isinstance(period_value, datetime):
        start = period_value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif isinstance(period_value, date):
        start = datetime(period_value.year, period_value.month, 1)
    else:
        text = str(period_value).strip()
        fmt = "%Y-%m" if len(text) == 7 else ("%Y" if len(text) == 4 else DATE_FMT)
        parsed = datetime.strptime(text, fmt)
        start = datetime(parsed.year, parsed.month, 1)
    next_month = datetime(start.year + 1, 1, 1) if start.month == 12 else datetime(start.year, start.month + 1, 1)
    end = next_month - timedelta(days=1)
    return start.strftime(DATE_FMT), end.strftime(DATE_FMT)
