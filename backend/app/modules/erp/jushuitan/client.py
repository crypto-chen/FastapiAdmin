"""聚水潭开放平台客户端。

接口文档：https://openweb.jushuitan.com/dev-doc?docType=8&docId=34 （销售出库查询）
调用规则：https://openweb.jushuitan.com/doc?docId=30 （API调用说明）
签名规则：https://openweb.jushuitan.com/doc?docId=70

要点（按官方文档）：

1. 只支持 ``POST``，``Content-Type: application/x-www-form-urlencoded;charset=UTF-8``；
   公共参数 ``app_key/access_token/timestamp/charset/version/sign`` 与业务参数 ``biz``
   一起放在表单里，不放 Query。
2. ``biz`` 是 JSON 字符串：复杂参数整串参与签名，内部字段不拆开排序。
3. ``sign = md5(app_secret + 按键字典序拼接的 key+value 串)``，拼接时跳过 ``sign``
   与空值；待签名串以 UTF-8 编码，中文参与签名时**不做** URL 编码。
4. 频率限制：并发 5 次/秒、100 次/分钟，超限返回 ``code=199/200``。
5. 销售出库查询的时间段「间隔不能超过七天」，且只有 ``date_type=2`` 才是按**出库时间**过滤。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import AsyncIterator
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field

DEFAULT_BASE_URL = "https://openapi.jushuitan.com"
TEST_BASE_URL = "https://dev-api.jushuitan.com"

# 销售出库查询接口路径（docType=8 & docId=34）
SALES_OUTBOUND_QUERY_PATH = "/open/orders/out/simple/query"
# 店铺查询（用于连通性自检，docId=1）
SHOPS_QUERY_PATH = "/open/shops/query"

# 文档硬约束：modified_begin/modified_end 间隔不能超过 7 天
MAX_WINDOW_DAYS = 7
# 文档硬约束：销售出库查询 page_size 默认 30、最大 50
MAX_PAGE_SIZE = 50
# 100 次/分钟 → 两次请求间隔不小于 0.6 秒，留一点余量
MIN_REQUEST_INTERVAL = 0.62
# 出库单状态：已出库
STATUS_CONFIRMED = "Confirmed"
# date_type：2 = 按出库时间（io_date）过滤
DATE_TYPE_IO_DATE = 2
# 聚水潭限流错误码，可重试
RATE_LIMIT_CODES = {199, 200}
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class JushuitanError(RuntimeError):
    """聚水潭接口返回非 0 code，或响应不是合法 JSON。"""

    def __init__(self, message: str, code: int | None = None, payload: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.payload = payload


class JushuitanClientConfig(BaseModel):
    """已解密的聚水潭连接配置。"""

    app_key: str
    app_secret: str
    access_token: str
    base_url: str = DEFAULT_BASE_URL
    timeout: int = 30
    retry_times: int = 3
    min_request_interval: float = MIN_REQUEST_INTERVAL


class SalesOutboundQuery(BaseModel):
    """销售出库查询 ``biz`` 参数（docId=34）。

    默认即为「出库状态=已出库 + 按出库时间过滤」：``status=Confirmed``、``date_type=2``。
    """

    shop_id: int | None = Field(default=None, description="店铺编码；查线下单据时传 0 并置 is_offline_shop=true")
    is_offline_shop: bool | None = Field(default=None, description="是否线下店铺")
    status: str | None = Field(default=STATUS_CONFIRMED, description="单据状态；Confirmed=已出库")
    modified_begin: str = Field(..., description="起始时间 yyyy-MM-dd HH:mm:ss（含）")
    modified_end: str = Field(..., description="结束时间 yyyy-MM-dd HH:mm:ss（含），与起始间隔不超过 7 天")
    date_type: int = Field(default=DATE_TYPE_IO_DATE, description="时间类型 0=修改时间，2=出库时间")
    page_index: int = Field(default=1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(default=MAX_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="每页条数，最大 50")
    wms_co_id: int | None = Field(default=None, description="出库仓编号")
    is_get_total: bool = Field(default=True, description="是否返回总条数/总页数")
    archive: bool | None = Field(default=None, description="是否查询归档数据")

    def to_biz(self) -> dict[str, Any]:
        """转成接口 ``biz`` 字典，剔除未传字段。"""
        return self.model_dump(exclude_none=True)


def build_sign(app_secret: str, params: dict[str, Any]) -> str:
    """按官方规则生成 sign。

    ``md5(app_secret + 字典序 key+value 串)``，跳过 ``sign`` 与空值，UTF-8 编码。
    """
    pieces = [app_secret]
    for key in sorted(params.keys()):
        if key == "sign":
            continue
        value = params[key]
        if value is None or value == "":
            continue
        pieces.append(f"{key}{value}")
    return hashlib.md5("".join(pieces).encode("utf-8")).hexdigest()


class JushuitanClient:
    """聚水潭开放平台客户端；连接凭据由 service 层解密后传入。"""

    def __init__(self, config: JushuitanClientConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    # ------------------------------------------------------------------ #
    # 基础设施
    # ------------------------------------------------------------------ #
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

    async def __aenter__(self) -> JushuitanClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _throttle(self) -> None:
        """全局最小请求间隔，避免触发 100 次/分钟的频次限制。"""
        interval = max(float(self.config.min_request_interval), 0.0)
        if interval <= 0:
            return
        async with self._lock:
            wait = interval - (time.monotonic() - self._last_request_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    # ------------------------------------------------------------------ #
    # 通用请求
    # ------------------------------------------------------------------ #
    def build_form(self, biz: dict[str, Any] | None = None, timestamp: int | None = None) -> dict[str, str]:
        """组装一次请求的表单参数（含 sign）。"""
        form: dict[str, Any] = {
            "app_key": self.config.app_key,
            "access_token": self.config.access_token,
            "timestamp": int(timestamp if timestamp is not None else time.time()),
            "charset": "utf-8",
            "version": "2",
            "biz": json.dumps(biz or {}, ensure_ascii=False, separators=(",", ":")),
        }
        form["sign"] = build_sign(self.config.app_secret, form)
        return {key: str(value) for key, value in form.items()}

    async def call(self, path: str, biz: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用一个开放平台接口，返回 ``data`` 字段（失败抛 :class:`JushuitanError`）。"""
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(max(int(self.config.retry_times), 1)):
            await self._throttle()
            client = await self._http()
            try:
                response = await client.post(
                    url,
                    data=self.build_form(biz),
                    headers={"Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as e:
                last_error = JushuitanError(f"聚水潭接口请求失败：{e}")
                await asyncio.sleep(min(2 ** attempt, 5))
                continue

            if not isinstance(payload, dict):
                raise JushuitanError(f"聚水潭接口返回格式异常：{str(payload)[:300]}")

            code = payload.get("code")
            if code == 0:
                data = payload.get("data")
                return data if isinstance(data, dict) else {"datas": data or []}

            message = str(payload.get("msg") or payload.get("message") or "接口返回失败")
            if code in RATE_LIMIT_CODES and attempt < int(self.config.retry_times) - 1:
                last_error = JushuitanError(f"聚水潭触发限流(code={code})：{message}", code=code, payload=payload)
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise JushuitanError(f"聚水潭接口返回错误(code={code})：{message}", code=code, payload=payload)

        raise last_error or JushuitanError("聚水潭接口请求失败")

    # ------------------------------------------------------------------ #
    # 业务接口
    # ------------------------------------------------------------------ #
    async def test_connection(self) -> dict[str, Any]:
        """连通性自检：调用店铺查询，返回首个店铺信息（无店铺时返回空字典）。"""
        data = await self.call(SHOPS_QUERY_PATH, {"page_index": 1, "page_size": 1})
        shops = data.get("datas") if isinstance(data.get("datas"), list) else []
        return shops[0] if shops else {}

    async def query_sales_outbound(self, biz: SalesOutboundQuery | dict[str, Any]) -> dict[str, Any]:
        """单次销售出库查询（一页）。"""
        payload = biz.to_biz() if isinstance(biz, SalesOutboundQuery) else dict(biz)
        return await self.call(SALES_OUTBOUND_QUERY_PATH, payload)

    async def query_sales_outbound_page(
        self,
        begin: datetime,
        end: datetime,
        page_index: int = 1,
        page_size: int = MAX_PAGE_SIZE,
        **extra: Any,
    ) -> dict[str, Any]:
        """按时间段查询一页销售出库单。"""
        query = SalesOutboundQuery(
            modified_begin=begin.strftime(TIME_FORMAT),
            modified_end=end.strftime(TIME_FORMAT),
            page_index=page_index,
            page_size=page_size,
            **extra,
        )
        return await self.query_sales_outbound(query)

    async def iter_sales_outbound(
        self,
        begin: datetime,
        end: datetime,
        page_size: int = MAX_PAGE_SIZE,
        **extra: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """按时间段翻页拉取销售出库单，自动处理「间隔不超过 7 天」的分段。

        产出所有出库单字典（``datas`` 元素），按 ``io_id`` 去重。
        """
        seen: set[Any] = set()
        for window_begin, window_end in split_windows(begin, end):
            page_index = 1
            while True:
                data = await self.query_sales_outbound_page(
                    window_begin, window_end, page_index=page_index, page_size=page_size, **extra
                )
                rows = data.get("datas") if isinstance(data.get("datas"), list) else []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    key = row.get("io_id") or row.get("o_id") or json.dumps(row, sort_keys=True, default=str)
                    if key in seen:
                        continue
                    seen.add(key)
                    yield row
                has_next = bool(data.get("has_next"))
                page_count = data.get("page_count")
                if not rows or (not has_next and not (isinstance(page_count, int) and page_index < page_count)):
                    break
                page_index += 1


def split_windows(begin: datetime, end: datetime, max_days: int = MAX_WINDOW_DAYS) -> list[tuple[datetime, datetime]]:
    """把时间范围切成不超过 ``max_days`` 天的窗口（接口硬约束）。"""
    if end < begin:
        raise ValueError("结束时间不能早于起始时间")
    windows: list[tuple[datetime, datetime]] = []
    cursor = begin
    step = max(int(max_days), 1)
    while cursor <= end:
        window_end = min(cursor + _step_delta(step), end)
        windows.append((cursor, window_end))
        if window_end >= end:
            break
        cursor = window_end
    return windows


def _step_delta(days: int):
    from datetime import timedelta

    return timedelta(days=days)


def month_range(period_value: str | date | datetime) -> tuple[datetime, datetime]:
    """月度期间值 → ``[月初 00:00:00, 月末 23:59:59]`` 时间范围。"""
    if isinstance(period_value, datetime):
        start = period_value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif isinstance(period_value, date):
        start = datetime(period_value.year, period_value.month, 1)
    else:
        text = str(period_value).strip()
        fmt = "%Y-%m" if len(text) == 7 else "%Y-%m-%d"
        parsed = datetime.strptime(text, fmt)
        start = datetime(parsed.year, parsed.month, 1)
    if start.month == 12:
        next_month = datetime(start.year + 1, 1, 1)
    else:
        next_month = datetime(start.year, start.month + 1, 1)
    from datetime import timedelta

    return start, next_month - timedelta(seconds=1)
