"""开放接口调用日志路由：按请求记录应用、路径、状态码与耗时。"""

import json
import time
from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Request, Response
from fastapi.routing import APIRoute
from starlette.background import BackgroundTask

from app.core.database import async_db_session
from app.core.exceptions import CustomException
from app.core.logger import logger
from app.utils.ip_local_util import get_client_ip

_SENSITIVE_KEYS: set[str] = {
    "app_secret",
    "secret",
    "secret_key",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
}
_REDACTED = "******"


def _redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: (_REDACTED if str(k).lower() in _SENSITIVE_KEYS else _redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


async def _write_open_log(log_data: dict[str, Any]) -> None:
    """落库调用日志（独立会话；失败只告警，不影响开放接口响应）。"""
    from app.modules.openapi.model import OpenApiLogModel  # 延迟导入，避免核心层依赖业务模型

    try:
        async with async_db_session() as session, session.begin():
            session.add(OpenApiLogModel(**log_data))
    except Exception:
        logger.exception("开放接口日志写入失败: path={}", log_data.get("path"))


class OpenApiLogRoute(APIRoute):
    """记录开放接口调用；参数与响应只落业务码/HTTP 码，不落完整响应体。"""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        original_route_handler = super().get_route_handler()

        async def custom_route_handler(request: Request) -> Response:
            start = time.perf_counter()
            try:
                response = await original_route_handler(request)
            except CustomException as exc:
                await _write_open_log(
                    self._log_payload(
                        request=request,
                        cost_ms=int((time.perf_counter() - start) * 1000),
                        http_status=exc.status_code,
                        response_code=exc.code,
                    )
                )
                raise
            except Exception as exc:
                http_status = int(getattr(exc, "status_code", 0) or 500)
                await _write_open_log(
                    self._log_payload(
                        request=request,
                        cost_ms=int((time.perf_counter() - start) * 1000),
                        http_status=http_status,
                        response_code=-1,
                    )
                )
                raise

            log_data = self._log_payload(
                request=request,
                cost_ms=int((time.perf_counter() - start) * 1000),
                http_status=response.status_code,
                response_code=self._extract_code(response),
            )
            response.background = BackgroundTask(_write_open_log, log_data)
            return response

        return custom_route_handler

    def _log_payload(
        self,
        request: Request,
        cost_ms: int,
        http_status: int,
        response_code: int,
    ) -> dict[str, Any]:
        client = getattr(request.state, "open_client", None)
        params = self._extract_params(request)
        app_id = getattr(client, "app_id", None) or params.get("app_id")
        return {
            "client_id": getattr(client, "id", None),
            "app_id": str(app_id) if app_id else None,
            "path": request.url.path,
            "method": request.method,
            "params": params or None,
            "response_code": response_code,
            "http_status": http_status,
            "cost_ms": cost_ms,
            "client_ip": (getattr(request.state, "open_client_ip", None) or get_client_ip(request)),
            "description": (self.summary or "")[:255] or None,
        }

    @staticmethod
    def _extract_params(request: Request) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        try:
            body = request._body if hasattr(request, "_body") else b""  # noqa: SLF001
        except Exception:
            body = b""
        if body:
            try:
                payload.update(_redact(json.loads(body.decode("utf-8"))))
            except (json.JSONDecodeError, UnicodeDecodeError):
                payload["body"] = "无法解析的请求体"
        if request.query_params:
            payload["query"] = dict(request.query_params)
        if request.path_params:
            payload["path"] = {k: str(v) for k, v in request.path_params.items()}
        return payload if len(json.dumps(payload, ensure_ascii=False, default=str)) <= 2000 else {"note": "请求参数过长"}

    @staticmethod
    def _extract_code(response: Response) -> int:
        try:
            if "application/json" not in response.headers.get("Content-Type", ""):
                return response.status_code
            body = json.loads(bytes(response.body).decode("utf-8"))
            return int(body.get("code", response.status_code))
        except Exception:
            return response.status_code
