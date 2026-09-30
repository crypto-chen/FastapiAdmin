"""金蝶云星空 WebAPI 客户端封装。

官方 SDK 是同步 requests 实现，这里统一通过 ``asyncio.to_thread`` 转异步，
避免阻塞 FastAPI 事件循环。连接凭据由 service 层解密后传入。
"""

import asyncio
import configparser
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _load_sdk_class() -> type:
    """延迟加载金蝶官方 SDK，避免未安装依赖时阻塞整个应用启动。"""
    try:
        from k3cloud_webapi_sdk.main import K3CloudApiSdk
    except ModuleNotFoundError as e:
        raise RuntimeError(
            "缺少金蝶云星空 SDK，请先安装 backend/vendor/kingdee.cdp.webapi.sdk-8.2.0-py3-none-any.whl"
        ) from e
    return K3CloudApiSdk


class KingdeeClientConfig(BaseModel):
    """已解密的金蝶连接配置。"""

    server_url: str
    acct_id: str
    username: str
    app_id: str
    app_secret: str
    lcid: int = 2052
    org_num: int = 0
    connect_timeout: int = 120
    request_timeout: int = 120
    proxy: str = ""


class KingdeeBillQueryRequest(BaseModel):
    """单据查询请求。"""

    form_id: str
    field_keys: str = ""
    filter_string: str = ""
    order_string: str = ""
    top_row_count: int = 0
    start_row: int = 0
    limit: int = 200


class KingdeeClient:
    """金蝶 WebAPI 客户端，按请求创建 SDK 实例。"""

    def __init__(self, config: KingdeeClientConfig) -> None:
        self.config = config

    @classmethod
    def from_ini(cls, path: str | Path, node: str = "config") -> "KingdeeClient":
        """从金蝶官方 ``conf.ini`` 风格配置文件构造客户端。"""
        conf = configparser.ConfigParser()
        conf.read(path, encoding="utf-8")

        def get(key: str, default: str = "") -> str:
            return conf.get(node, f"x-kdapi-{key}", fallback=default)

        def get_int(key: str, default: int) -> int:
            try:
                return conf.getint(node, f"x-kdapi-{key}", fallback=default)
            except (ValueError, TypeError):
                return default

        return cls(
            KingdeeClientConfig(
                server_url=get("serverurl"),
                acct_id=get("acctid"),
                username=get("username"),
                app_id=get("appid"),
                app_secret=get("appsec"),
                lcid=get_int("lcid", 2052),
                org_num=get_int("orgnum", 0),
                connect_timeout=get_int("connecttimeout", 120),
                request_timeout=get_int("requesttimeout", 120),
                proxy=get("proxy"),
            )
        )

    def _new_sdk(self):
        sdk_cls = _load_sdk_class()
        sdk = sdk_cls(server_url=self.config.server_url, timeout=self.config.request_timeout)
        sdk.InitConfig(
            acct_id=self.config.acct_id,
            user_name=self.config.username,
            app_id=self.config.app_id,
            app_secret=self.config.app_secret,
            server_url=self.config.server_url,
            lcid=self.config.lcid,
            org_num=self.config.org_num,
            connect_timeout=self.config.connect_timeout,
            request_timeout=self.config.request_timeout,
            proxy=self.config.proxy,
        )
        return sdk

    async def test_connection(self) -> bool:
        """调用数据中心列表接口验证配置是否可用。"""
        return await asyncio.to_thread(self._test_connection)

    def _test_connection(self) -> bool:
        sdk = self._new_sdk()
        response = sdk.GetDataCenters()
        self._parse_json(response)
        return True

    async def bill_query(self, request: KingdeeBillQueryRequest) -> tuple[list[str], list[dict]]:
        return await asyncio.to_thread(self._bill_query, request)

    async def view(self, form_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """查看单个业务对象（金蝶 ``View`` 接口）。"""
        return await asyncio.to_thread(self._view, form_id, data)

    async def get_sys_report_data(self, form_id: str, data: dict[str, Any]) -> dict[str, Any]:
        """查询金蝶系统报表数据（``GetSysReportData``）。"""
        return await asyncio.to_thread(self._get_sys_report_data, form_id, data)

    def _bill_query(self, request: KingdeeBillQueryRequest) -> tuple[list[str], list[dict]]:
        sdk = self._new_sdk()
        payload: dict[str, Any] = {
            "FormId": request.form_id,
            "FieldKeys": request.field_keys,
            "FilterString": request.filter_string,
            "OrderString": request.order_string,
            "TopRowCount": request.top_row_count,
            "StartRow": request.start_row,
            "Limit": request.limit,
            "SubSystemId": "",
        }
        response = sdk.ExecuteBillQuery(payload)
        data = self._parse_json(response)
        return self._normalize_rows(data, request.field_keys)

    def _view(self, form_id: str, data: dict[str, Any]) -> dict[str, Any]:
        sdk = self._new_sdk()
        response = sdk.View(form_id, data)
        return self._parse_json(response)

    def _get_sys_report_data(self, form_id: str, data: dict[str, Any]) -> dict[str, Any]:
        sdk = self._new_sdk()
        response = sdk.GetSysReportData(form_id, data)
        return self._parse_json(response)

    @staticmethod
    def _parse_json(response: str) -> Any:
        try:
            return json.loads(response)
        except (json.JSONDecodeError, TypeError) as e:
            raise RuntimeError(f"金蝶接口返回不是有效 JSON: {response[:500]}") from e

    @staticmethod
    def _normalize_rows(data: Any, field_keys: str = "") -> tuple[list[str], list[dict]]:
        """兼容官方 SDK 两种返回格式：

        - ExecuteBillQuery 返回 ``[[值1, 值2], ...]``，无表头，表头由 FieldKeys 提供；
        - BillQuery 或部分接口可能直接返回 ``[{"FName": "甲"}, ...]``。
        """
        rows: list[list[Any]] | list[dict[str, Any]] = []
        if isinstance(data, dict):
            if isinstance(data.get("Result"), list):
                data = data["Result"]
            elif isinstance(data.get("rows"), list):
                rows = data["rows"]
        if isinstance(data, list):
            rows = data

        if not rows:
            return [], []

        # 值数组 + 调用方提供 FieldKeys：直接用字段名列表作为表头
        if isinstance(rows[0], list):
            list_rows = [row for row in rows if isinstance(row, list)]
            if not list_rows:
                return [], []
            provided_fields = [field.strip() for field in field_keys.split(",") if field.strip()]
            if provided_fields:
                fields = provided_fields
                data_rows = list_rows
            else:
                # 兼容旧格式：首行是字段名、其余是数据
                if len(list_rows) < 2:
                    return [], []
                fields = [str(item) for item in list_rows[0]]
                data_rows = list_rows[1:]
            items = [{fields[i]: row[i] if i < len(row) else None for i in range(len(fields))} for row in data_rows]
            return fields, items

        if isinstance(rows[0], dict):
            items = [row for row in rows if isinstance(row, dict)]
            fields: list[str] = []
            if items:
                fields = list(items[0].keys())
            return fields, items

        return [], []
