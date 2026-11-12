"""企业微信通讯录 / 打卡接口客户端。

- 通讯录：``department/list``、``user/list``（需要通讯录读取权限）；
- 打卡：``checkin/getcheckin_daydata``，单次最多 100 个 userid、日期跨度按 30 天切片；
- access_token 缓存在 Redis（TTL = expires_in - 300），Redis 不可用时退回进程内缓存；
- 网络错误/限频自动重试，token 失效自动刷新一次。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Iterable
from datetime import date, datetime, time
from typing import Any

import httpx
from pydantic import BaseModel

from app.config.setting import settings
from app.core.logger import logger
from app.modules.erp.wecom.calc import (
    CHECKIN_CHUNK_DAYS,
    CN_TZ,
    as_int,
    iter_date_chunks,
)

WECOM_API_BASE = "https://qyapi.weixin.qq.com/cgi-bin"
TOKEN_PATH = "/gettoken"
DEPARTMENT_LIST_PATH = "/department/list"
USER_LIST_PATH = "/user/list"
CHECKIN_DAYDATA_PATH = "/checkin/getcheckin_daydata"

USER_BATCH_SIZE = 100
TOKEN_URL_CACHE_TTL = 6000
RATE_LIMIT_ERRCODES = {45009, 45033}
TOKEN_ERRCODES = {40001, 42001, 41001}
PERMISSION_ERRCODES = {48002, 60011, 60020, 40013, 40056}

# 企微接口把 access_token 放在 URL 查询串里，httpx/httpcore 的 INFO/DEBUG 日志会原样打印。
# 这里压低这两个 logger，避免 token 落进日志文件。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class WeComError(RuntimeError):
    """企业微信接口返回非 0 errcode，或响应不是合法 JSON。"""

    def __init__(self, message: str, errcode: int | None = None, payload: dict | None = None) -> None:
        super().__init__(message)
        self.errcode = errcode
        self.payload = payload


class WeComClientConfig(BaseModel):
    """企业微信连接配置（secret 已解密）。"""

    corp_id: str
    checkin_secret: str
    contact_secret: str | None = None
    token_url: str | None = None
    base_url: str = WECOM_API_BASE
    timeout: int = 30
    retry_times: int = 3
    request_interval: float = 0.2


class WeComClient:
    """企业微信 API 客户端。"""

    def __init__(self, config: WeComClientConfig, redis: Any | None = None) -> None:
        self.config = config
        self._http_client: httpx.AsyncClient | None = None
        self._redis = redis
        self._owns_redis = False
        self._redis_disabled = False
        self._memory_tokens: dict[str, str] = {}

    @property
    def base_url(self) -> str:
        return (self.config.base_url or WECOM_API_BASE).rstrip("/")

    async def _http(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.config.timeout, connect=min(10, self.config.timeout)),
                follow_redirects=True,
            )
        return self._http_client

    async def _ensure_redis(self) -> Any | None:
        if self._redis_disabled:
            return None
        if self._redis is not None:
            return self._redis
        try:
            from redis.asyncio import Redis

            self._redis = Redis.from_url(settings.REDIS_URI, decode_responses=True)
            self._owns_redis = True
        except Exception as exc:  # noqa: BLE001 - 缓存不可用不影响取数
            self._redis_disabled = True
            logger.debug(f"企业微信 token 缓存未启用 Redis：{exc}")
        return self._redis

    async def aclose(self) -> None:
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None
        if self._owns_redis and self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:  # noqa: BLE001
                pass
            self._redis = None

    async def __aenter__(self) -> WeComClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    # ------------------------------------------------------------------ #
    # token
    # ------------------------------------------------------------------ #
    def _secret(self, kind: str) -> str:
        secret = self.config.contact_secret if kind == "contact" else self.config.checkin_secret
        if not secret:
            label = "通讯录" if kind == "contact" else "打卡"
            raise WeComError(f"企业微信连接未配置{label} Secret")
        return secret

    def _cache_key(self, kind: str) -> str:
        if self.config.token_url:
            digest = hashlib.sha1(self.config.token_url.encode()).hexdigest()[:16]
            return f"wecom:token:url:{digest}"
        secret = self._secret(kind)
        digest = hashlib.sha1(f"{self.config.corp_id}:{secret}".encode()).hexdigest()[:16]
        return f"wecom:token:{kind}:{digest}"

    async def _cache_get(self, key: str) -> str | None:
        redis = await self._ensure_redis()
        if redis is not None:
            try:
                value = await redis.get(key)
                if value:
                    return str(value)
            except Exception as exc:  # noqa: BLE001
                self._redis_disabled = True
                if self._owns_redis:
                    self._redis = None
                logger.debug(f"企业微信 token 读取 Redis 失败，改用进程内缓存：{exc}")
        return self._memory_tokens.get(key)

    async def _cache_set(self, key: str, value: str, ttl: int) -> None:
        self._memory_tokens[key] = value
        redis = await self._ensure_redis()
        if redis is not None:
            try:
                await redis.set(key, value, ex=max(60, ttl))
            except Exception as exc:  # noqa: BLE001
                self._redis_disabled = True
                if self._owns_redis:
                    self._redis = None
                logger.debug(f"企业微信 token 写入 Redis 失败，保留进程内缓存：{exc}")

    async def _cache_delete(self, key: str) -> None:
        self._memory_tokens.pop(key, None)
        redis = await self._ensure_redis()
        if redis is not None:
            try:
                await redis.delete(key)
            except Exception:  # noqa: BLE001
                pass

    async def _token(self, kind: str) -> str:
        if self.config.token_url:
            return await self._token_from_url()

        key = self._cache_key(kind)
        cached = await self._cache_get(key)
        if cached:
            return cached

        attempts = max(0, int(self.config.retry_times)) + 1
        for attempt in range(attempts):
            try:
                data = await self._raw_request(
                    "GET",
                    TOKEN_PATH,
                    params={"corpid": self.config.corp_id, "corpsecret": self._secret(kind)},
                )
                break
            except (httpx.HTTPError, WeComError):
                if attempt + 1 >= attempts:
                    raise
                await asyncio.sleep(min(2**attempt, 8))
        else:  # pragma: no cover - 循环必然 break 或 raise
            raise WeComError("企业微信获取 token 失败")
        errcode = as_int(data.get("errcode"))
        if errcode != 0:
            raise WeComError(
                f"企业微信获取 token 失败 {errcode}: {data.get('errmsg', '')}",
                errcode=errcode,
                payload=data,
            )
        token = str(data.get("access_token") or "")
        if not token:
            raise WeComError("企业微信获取 token 失败：响应没有 access_token", payload=data)
        expires_in = as_int(data.get("expires_in"), 7200)
        await self._cache_set(key, token, max(60, expires_in - 300))
        return token

    async def _token_from_url(self) -> str:
        """按 PHP 逻辑从既有 Token 服务取 token（响应为纯文本）。"""
        key = self._cache_key("url")
        cached = await self._cache_get(key)
        if cached:
            return cached

        attempts = max(0, int(self.config.retry_times)) + 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                token = await self._get_text(self.config.token_url or "")
                if token and "<" not in token and len(token) >= 20:
                    await self._cache_set(key, token, TOKEN_URL_CACHE_TTL)
                    return token
                last_error = WeComError("Token服务返回的不是有效 token")
            except (httpx.HTTPError, WeComError) as exc:
                last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(min(2**attempt, 8))
        raise WeComError(f"Token服务取 token 失败: {last_error}")

    # ------------------------------------------------------------------ #
    # HTTP
    # ------------------------------------------------------------------ #
    async def _raw_request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        http = await self._http()
        response = await http.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json_body,
        )
        if response.status_code >= 400:
            raise WeComError(
                f"企业微信 HTTP {response.status_code}: {response.text[:300]}",
                payload={"status_code": response.status_code},
            )
        try:
            data = response.json()
        except ValueError as exc:
            raise WeComError(f"企业微信返回非 JSON: {response.text[:300]}") from exc
        if not isinstance(data, dict):
            raise WeComError(f"企业微信返回结构异常: {type(data).__name__}")
        return data

    async def _get_text(self, url: str) -> str:
        if not url:
            raise WeComError("Token服务URL为空")
        http = await self._http()
        response = await http.get(url)
        if response.status_code >= 400:
            raise WeComError(f"Token服务 HTTP {response.status_code}: {response.text[:300]}")
        return response.text.strip()

    async def _call_api(
        self,
        method: str,
        path: str,
        *,
        secret_kind: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        attempts = max(0, int(self.config.retry_times)) + 1
        for attempt in range(attempts):
            token = await self._token(secret_kind)
            request_params = dict(params or {})
            request_params["access_token"] = token
            try:
                data = await self._raw_request(
                    method,
                    path,
                    params=request_params,
                    json_body=json_body,
                )
            except WeComError as exc:
                if exc.errcode in PERMISSION_ERRCODES:
                    raise
                if attempt + 1 < attempts:
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                raise
            except httpx.HTTPError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(min(2**attempt, 8))
                    continue
                raise WeComError(f"企业微信请求失败: {exc}") from exc

            errcode = as_int(data.get("errcode"))
            if errcode == 0:
                return data

            message = f"企业微信接口错误 {errcode}: {data.get('errmsg', '')}"
            if errcode in TOKEN_ERRCODES and attempt + 1 < attempts:
                await self._cache_delete(self._cache_key(secret_kind))
                continue
            if errcode in RATE_LIMIT_ERRCODES and attempt + 1 < attempts:
                await asyncio.sleep(min(2**attempt, 8))
                continue
            raise WeComError(message, errcode=errcode, payload=data)

        raise WeComError("企业微信接口重试次数已用尽")

    # ------------------------------------------------------------------ #
    # 通讯录
    # ------------------------------------------------------------------ #
    async def get_departments(self) -> list[dict[str, Any]]:
        data = await self._call_api("GET", DEPARTMENT_LIST_PATH, secret_kind="contact")
        departments = data.get("department")
        return departments if isinstance(departments, list) else []

    async def list_users(self, department_id: int = 1, fetch_child: bool = True) -> list[dict[str, Any]]:
        data = await self._call_api(
            "GET",
            USER_LIST_PATH,
            secret_kind="contact",
            params={"department_id": department_id, "fetch_child": 1 if fetch_child else 0},
        )
        users = data.get("userlist")
        return users if isinstance(users, list) else []

    # ------------------------------------------------------------------ #
    # 打卡
    # ------------------------------------------------------------------ #
    async def get_checkin_daydata(
        self,
        start: date,
        end: date,
        userids: Iterable[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """拉取打卡日报，返回 ``(datas, errors)``。

        日期按 30 天切片、人员按 100 人切片；单批失败只记录错误，不丢弃其它批次。
        """
        ids = sorted({str(item).strip() for item in userids if str(item).strip()})
        if not ids:
            return [], []

        datas: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for chunk_start, chunk_end in iter_date_chunks(start, end, CHECKIN_CHUNK_DAYS):
            start_ts = int(datetime.combine(chunk_start, time.min, tzinfo=CN_TZ).timestamp())
            end_ts = int(
                datetime.combine(chunk_end, time.max.replace(microsecond=0), tzinfo=CN_TZ).timestamp()
            )
            for offset in range(0, len(ids), USER_BATCH_SIZE):
                chunk = ids[offset : offset + USER_BATCH_SIZE]
                body = {
                    "starttime": start_ts,
                    "endtime": end_ts,
                    "useridlist": chunk,
                }
                try:
                    data = await self._call_api(
                        "POST",
                        CHECKIN_DAYDATA_PATH,
                        secret_kind="checkin",
                        json_body=body,
                    )
                except WeComError as exc:
                    if exc.errcode in PERMISSION_ERRCODES:
                        raise
                    errors.append(
                        {
                            "start": chunk_start.isoformat(),
                            "end": chunk_end.isoformat(),
                            "userids": len(chunk),
                            "errcode": exc.errcode,
                            "errmsg": str(exc),
                        }
                    )
                    continue

                batch = data.get("datas")
                if isinstance(batch, list):
                    datas.extend(batch)
                elif batch is not None:
                    errors.append(
                        {
                            "start": chunk_start.isoformat(),
                            "end": chunk_end.isoformat(),
                            "userids": len(chunk),
                            "errcode": as_int(data.get("errcode")),
                            "errmsg": "接口未返回 datas",
                        }
                    )
                if self.config.request_interval > 0:
                    await asyncio.sleep(self.config.request_interval)
        return datas, errors

    async def test_connection(self) -> dict[str, Any]:
        """连通性自检：通讯录部门 + 根部门人员。"""
        departments = await self.get_departments()
        users = await self.list_users(department_id=1, fetch_child=True)
        return {
            "departmentCount": len(departments),
            "userCount": len(users),
            "departments": [item.get("name") for item in departments[:10]],
            "users": [item.get("name") for item in users[:10]],
        }

