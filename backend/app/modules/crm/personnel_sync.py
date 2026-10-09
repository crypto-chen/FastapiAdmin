"""CRM 人员主数据同步：两个**手动任务**（组织架构 / 人员）。

- 任务一「同步 CRM 人员架构」：``GET /hs/base/getDepartment`` → ``source_org`` + ``source_dept``
- 任务二「同步 CRM 人员」：``GET /hs/base/getPersonnel``（组织树只用于解析所属组织/部门）
  → ``source_person``

两个任务都可独立执行，**不注册任何定时任务**（无 Cron / APScheduler 项）；
入口有三处，逻辑共用本模块：

1. 页面按钮：「系统映射管理 → 人工绑定」工具栏
2. 接口：``POST /system-mapping/sync/crm-org``、``/system-mapping/sync/crm-person``
3. 命令行：``python scripts/sync_crm_personnel.py --target {org|person|all}``

同步只写来源表，**不创建**标准组织/部门/人员（CRM 编码与金蝶不同，需在映射页人工绑定）。
解析规则见 :mod:`app.modules.crm.org_person`。
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.crm.client import CrmClient, CrmClientConfig
from app.modules.crm.org_person import (
    CRM_SOURCE_TYPE,
    CrmDeptRow,
    CrmOrgRow,
    CrmPersonRow,
    build_source_rows,
    fetch_departments,
    fetch_personnel,
)
from app.modules.masterdata.model import SourceDeptModel, SourceOrgModel, SourcePersonModel

# 接口触发时最多尝试次数（CRM 偶发网络抖动），与客户端内部重试叠加
SYNC_MAX_ATTEMPTS = 2
SYNC_RETRY_DELAY = 1.0


@dataclass(slots=True)
class CrmOrgSyncResult:
    """「同步 CRM 人员架构」结果统计。"""

    orgs_created: int = 0
    orgs_updated: int = 0
    depts_created: int = 0
    depts_updated: int = 0
    dept_total: int = 0

    def as_dict(self) -> dict[str, int]:
        return {key: int(value) for key, value in asdict(self).items()}


@dataclass(slots=True)
class CrmPersonSyncResult:
    """「同步 CRM 人员」结果统计。"""

    persons_created: int = 0
    persons_updated: int = 0
    person_total: int = 0
    person_active: int = 0

    def as_dict(self) -> dict[str, int]:
        return {key: int(value) for key, value in asdict(self).items()}


async def _with_retry(loader: Any) -> Any:
    """CRM 取数失败时重试一次，仍失败则抛出原始异常。"""
    last_error: Exception | None = None
    for attempt in range(SYNC_MAX_ATTEMPTS):
        try:
            return await loader()
        except Exception as exc:  # noqa: BLE001 - 网络/解析异常统一重试
            last_error = exc
            if attempt + 1 < SYNC_MAX_ATTEMPTS:
                await asyncio.sleep(SYNC_RETRY_DELAY)
    raise last_error or RuntimeError("CRM 接口调用失败")


async def fetch_crm_departments(config: CrmClientConfig | None = None) -> list[dict[str, Any]]:
    """拉取 CRM 组织/部门树（顶层节点为组织）。"""

    async def _load() -> list[dict[str, Any]]:
        async with CrmClient(config or CrmClientConfig()) as client:
            departments = await fetch_departments(client)
        if not departments:
            raise RuntimeError("未读取到 CRM 组织/部门数据")
        return departments

    return await _with_retry(_load)


async def fetch_crm_org_rows(
    config: CrmClientConfig | None = None,
) -> tuple[list[CrmOrgRow], list[CrmDeptRow]]:
    """取组织/部门树并拍平成「来源组织 + 来源部门」两行结构。"""
    departments = await fetch_crm_departments(config)
    orgs, depts, _ = build_source_rows(departments, [])
    return orgs, depts


async def fetch_crm_person_rows(config: CrmClientConfig | None = None) -> list[CrmPersonRow]:
    """取人员明细，并用组织树补出所属组织/部门（``departments``）。"""

    async def _load() -> list[CrmPersonRow]:
        async with CrmClient(config or CrmClientConfig()) as client:
            departments = await fetch_departments(client)
            personnel = await fetch_personnel(client)
        if not departments:
            raise RuntimeError("未读取到 CRM 组织/部门数据")
        return build_source_rows(departments, personnel)[2]

    return await _with_retry(_load)


async def _upsert_orgs(db: AsyncSession, rows: list[CrmOrgRow]) -> tuple[int, int]:
    created = updated = 0
    for row in rows:
        stmt = select(SourceOrgModel).where(
            SourceOrgModel.source_type == CRM_SOURCE_TYPE,
            SourceOrgModel.source_code == row.source_code,
        )
        obj = (await db.execute(stmt)).scalar_one_or_none()
        payload: dict[str, Any] = {
            "source_name": row.source_name,
            "source_parent_code": None,
            "raw_json": row.raw_json,
            "status": row.status,
        }
        if obj is None:
            db.add(SourceOrgModel(source_type=CRM_SOURCE_TYPE, source_code=row.source_code, **payload))
            created += 1
        else:
            for key, value in payload.items():
                setattr(obj, key, value)
            updated += 1
    return created, updated


async def _upsert_depts(db: AsyncSession, rows: list[CrmDeptRow]) -> tuple[int, int]:
    created = updated = 0
    for row in rows:
        stmt = select(SourceDeptModel).where(
            SourceDeptModel.source_type == CRM_SOURCE_TYPE,
            SourceDeptModel.source_org_code == row.source_org_code,
            SourceDeptModel.source_code == row.source_code,
        )
        obj = (await db.execute(stmt)).scalar_one_or_none()
        payload: dict[str, Any] = {
            "source_name": row.source_name,
            "source_parent_code": row.source_parent_code,
            "raw_json": row.raw_json,
            "status": row.status,
        }
        if obj is None:
            db.add(
                SourceDeptModel(
                    source_type=CRM_SOURCE_TYPE,
                    source_org_code=row.source_org_code,
                    source_code=row.source_code,
                    **payload,
                )
            )
            created += 1
        else:
            for key, value in payload.items():
                setattr(obj, key, value)
            updated += 1
    return created, updated


async def _upsert_persons(db: AsyncSession, rows: list[CrmPersonRow]) -> tuple[int, int]:
    created = updated = 0
    for row in rows:
        stmt = select(SourcePersonModel).where(
            SourcePersonModel.source_type == CRM_SOURCE_TYPE,
            SourcePersonModel.source_code == row.source_code,
        )
        obj = (await db.execute(stmt)).scalar_one_or_none()
        payload: dict[str, Any] = {
            "source_name": row.source_name,
            "source_org_code": row.source_org_code,
            "mobile": row.mobile,
            "email": row.email,
            "raw_json": row.raw_json,
            "status": row.status,
        }
        if obj is None:
            db.add(SourcePersonModel(source_type=CRM_SOURCE_TYPE, source_code=row.source_code, **payload))
            created += 1
        else:
            for key, value in payload.items():
                setattr(obj, key, value)
            updated += 1
    return created, updated


async def upsert_org_structure(
    db: AsyncSession,
    orgs: list[CrmOrgRow],
    depts: list[CrmDeptRow],
) -> CrmOrgSyncResult:
    """把来源组织/部门写入来源表（调用方负责事务提交）。"""
    result = CrmOrgSyncResult()
    result.orgs_created, result.orgs_updated = await _upsert_orgs(db, orgs)
    result.depts_created, result.depts_updated = await _upsert_depts(db, depts)
    result.dept_total = len(depts)
    return result


async def upsert_personnel(db: AsyncSession, persons: list[CrmPersonRow]) -> CrmPersonSyncResult:
    """把来源人员写入来源表（调用方负责事务提交）。"""
    result = CrmPersonSyncResult()
    result.persons_created, result.persons_updated = await _upsert_persons(db, persons)
    result.person_total = len(persons)
    result.person_active = sum(1 for person in persons if person.status == 0)
    return result


async def sync_crm_org_structure(
    db: AsyncSession,
    config: CrmClientConfig | None = None,
) -> CrmOrgSyncResult:
    """手动任务一：同步 CRM 人员架构（来源组织 + 来源部门）。"""
    orgs, depts = await fetch_crm_org_rows(config)
    return await upsert_org_structure(db, orgs, depts)


async def sync_crm_personnel(
    db: AsyncSession,
    config: CrmClientConfig | None = None,
) -> CrmPersonSyncResult:
    """手动任务二：同步 CRM 人员（来源人员）。

    ``db`` 的事务由调用方管理：接口走请求级事务（``db_getter`` 成功即提交），
    脚本用 ``async_db_session() + begin()``。
    """
    persons = await fetch_crm_person_rows(config)
    return await upsert_personnel(db, persons)
