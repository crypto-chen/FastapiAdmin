"""企业微信通讯录、打卡同步与工时统计服务。"""

from __future__ import annotations

import calendar
import json
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.base_schema import PageResultSchema
from app.core.exceptions import CustomException
from app.modules.masterdata.model import SourceOrgModel, SourcePersonModel
from app.utils.crypto_util import CryptoUtil

from .calc import (
    CHECKIN_CHUNK_DAYS,
    DEFAULT_MARKETING_PREFIX,
    DEFAULT_OFF_WORK_SEC,
    MAX_RANGE_DAYS,
    NOON_BREAK_SEC,
    aggregate_worktime,
    as_int,
    daily_overtime_sec,
    iter_date_chunks,
    parse_checkin_item,
    seconds_to_hhmmss,
)
from .client import WeComClient, WeComClientConfig, WeComError
from .model import WeComCheckinDayModel, WeComConnectionModel, WeComSyncRunModel
from .schema import (
    WeComCheckinOutSchema,
    WeComConnectionCreateSchema,
    WeComConnectionOutSchema,
    WeComConnectionUpdateSchema,
    WeComEmployeeOutSchema,
    WeComSyncRunOutSchema,
    WeComWorktimeResultSchema,
)

WECOM_SOURCE_TYPE = "wecom"
SYNC_TYPE_ROSTER = "roster"
SYNC_TYPE_CHECKIN = "checkin"
SYNC_STATUS_RUNNING = "running"
SYNC_STATUS_SUCCESS = "success"
SYNC_STATUS_PARTIAL = "partial"
SYNC_STATUS_FAILED = "failed"


# ---------------------------------------------------------------------- #
# 连接配置
# ---------------------------------------------------------------------- #
def _to_connection_out(obj: WeComConnectionModel) -> WeComConnectionOutSchema:
    out = WeComConnectionOutSchema.model_validate(obj)
    out.has_checkin_secret = bool(obj.checkin_secret)
    out.has_contact_secret = bool(obj.contact_secret)
    out.has_token_url = bool(obj.token_url)
    return out


async def get_connection(
    db: AsyncSession,
    connection_id: int | None = None,
) -> WeComConnectionModel:
    """取启用的连接；不传 ID 时取第一个。"""
    stmt = select(WeComConnectionModel).where(
        WeComConnectionModel.status == 0,
        WeComConnectionModel.is_deleted.is_(False),
    )
    if connection_id is not None:
        stmt = stmt.where(WeComConnectionModel.id == connection_id)
    obj = (await db.execute(stmt.order_by(WeComConnectionModel.id.asc()).limit(1))).scalars().first()
    if obj is None:
        raise CustomException(msg="没有启用的企业微信连接，请先创建并配置 Secret")
    return obj


async def get_connection_detail(db: AsyncSession, connection_id: int) -> WeComConnectionOutSchema:
    obj = await db.get(WeComConnectionModel, connection_id)
    if obj is None or obj.is_deleted:
        raise CustomException(msg="企业微信连接不存在")
    return _to_connection_out(obj)


async def list_connections(
    db: AsyncSession,
    name: str | None = None,
    status: int | None = None,
) -> list[WeComConnectionOutSchema]:
    conditions = [WeComConnectionModel.is_deleted.is_(False)]
    if name:
        conditions.append(WeComConnectionModel.name.like(f"%{name}%"))
    if status is not None:
        conditions.append(WeComConnectionModel.status == status)
    rows = (
        await db.execute(
            select(WeComConnectionModel).where(*conditions).order_by(WeComConnectionModel.id.asc())
        )
    ).scalars()
    return [_to_connection_out(row) for row in rows]


async def page_connections(
    db: AsyncSession,
    page_no: int,
    page_size: int,
    name: str | None = None,
    status: int | None = None,
) -> PageResultSchema[WeComConnectionOutSchema]:
    conditions = [WeComConnectionModel.is_deleted.is_(False)]
    if name:
        conditions.append(WeComConnectionModel.name.like(f"%{name}%"))
    if status is not None:
        conditions.append(WeComConnectionModel.status == status)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(WeComConnectionModel).where(*conditions)
            )
        ).scalar()
        or 0
    )
    offset = max(0, (page_no - 1) * page_size)
    rows = (
        await db.execute(
            select(WeComConnectionModel)
            .where(*conditions)
            .order_by(WeComConnectionModel.id.asc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars()
    return PageResultSchema[WeComConnectionOutSchema](
        page_no=page_no,
        page_size=page_size,
        total=total,
        has_next=offset + page_size < total,
        items=[_to_connection_out(row) for row in rows],
    )


async def create_connection(
    db: AsyncSession,
    data: WeComConnectionCreateSchema,
    user_id: int | None = None,
) -> WeComConnectionOutSchema:
    token_url = (data.token_url or "").strip() or None
    if not data.checkin_secret and not token_url:
        raise CustomException(msg="创建连接时必须配置打卡 Secret 或 Token 服务 URL")
    if not data.corp_id.strip() and not token_url:
        raise CustomException(msg="未配置 Token 服务 URL 时必须填写 corp_id")
    exists = (
        await db.execute(
            select(WeComConnectionModel).where(
                WeComConnectionModel.name == data.name,
                WeComConnectionModel.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if exists is not None:
        raise CustomException(msg="创建失败，连接名称已存在")

    obj = WeComConnectionModel(
        name=data.name,
        corp_id=data.corp_id.strip() or "token-mode",
        checkin_secret=CryptoUtil.encrypt(data.checkin_secret) if data.checkin_secret else None,
        contact_secret=CryptoUtil.encrypt(data.contact_secret) if data.contact_secret else None,
        token_url=token_url,
        agent_id=data.agent_id,
        timeout=data.timeout,
        status=data.status,
        description=data.description,
        created_id=user_id,
        updated_id=user_id,
    )
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return _to_connection_out(obj)


async def update_connection(
    db: AsyncSession,
    connection_id: int,
    data: WeComConnectionUpdateSchema,
    user_id: int | None = None,
) -> WeComConnectionOutSchema:
    obj = await db.get(WeComConnectionModel, connection_id)
    if obj is None or obj.is_deleted:
        raise CustomException(msg="更新失败，企业微信连接不存在")
    exists = (
        await db.execute(
            select(WeComConnectionModel).where(
                WeComConnectionModel.name == data.name,
                WeComConnectionModel.id != connection_id,
                WeComConnectionModel.is_deleted.is_(False),
            )
        )
    ).scalars().first()
    if exists is not None:
        raise CustomException(msg="更新失败，连接名称已存在")

    obj.name = data.name
    obj.corp_id = data.corp_id.strip() or obj.corp_id
    obj.agent_id = data.agent_id
    obj.timeout = data.timeout
    obj.status = data.status
    obj.description = data.description
    obj.updated_id = user_id
    if data.token_url:
        obj.token_url = data.token_url
    if data.checkin_secret:
        obj.checkin_secret = CryptoUtil.encrypt(data.checkin_secret)
    if data.contact_secret:
        obj.contact_secret = CryptoUtil.encrypt(data.contact_secret)
    if not obj.token_url and not obj.checkin_secret:
        raise CustomException(msg="连接必须配置打卡 Secret 或 Token 服务 URL")
    await db.flush()
    await db.refresh(obj)
    return _to_connection_out(obj)


async def delete_connections(db: AsyncSession, ids: list[int], user_id: int | None = None) -> None:
    if not ids:
        raise CustomException(msg="删除失败，删除对象不能为空")
    await db.execute(
        update(WeComConnectionModel)
        .where(WeComConnectionModel.id.in_(ids), WeComConnectionModel.is_deleted.is_(False))
        .values(is_deleted=True, deleted_time=datetime.now(UTC), deleted_id=user_id)
    )


def build_client(connection: WeComConnectionModel) -> WeComClient:
    """解密连接配置并构建企微客户端。"""
    token_url = connection.token_url or None
    if token_url:
        return WeComClient(
            WeComClientConfig(
                corp_id=connection.corp_id or "token-mode",
                checkin_secret="",
                contact_secret=None,
                token_url=token_url,
                timeout=connection.timeout,
            )
        )
    checkin_secret = CryptoUtil.decrypt(connection.checkin_secret) if connection.checkin_secret else ""
    contact_secret = CryptoUtil.decrypt(connection.contact_secret) if connection.contact_secret else None
    if not checkin_secret:
        raise CustomException(msg="企业微信连接未配置打卡 Secret")
    return WeComClient(
        WeComClientConfig(
            corp_id=connection.corp_id,
            checkin_secret=checkin_secret,
            contact_secret=contact_secret,
            token_url=None,
            timeout=connection.timeout,
        )
    )


async def test_connection(db: AsyncSession, connection_id: int) -> dict[str, Any]:
    connection = await get_connection(db, connection_id)
    async with build_client(connection) as client:
        try:
            return await client.test_connection()
        except WeComError as exc:
            raise CustomException(msg=f"企业微信连接测试失败：{exc}") from exc


# ---------------------------------------------------------------------- #
# 通讯录同步
# ---------------------------------------------------------------------- #
async def sync_roster(
    db: AsyncSession,
    connection_id: int | None = None,
) -> dict[str, int]:
    """同步部门与人员到 ``source_org`` / ``source_person``（source_type=wecom）。"""
    connection = await get_connection(db, connection_id)
    started_at = datetime.now(UTC)
    async with build_client(connection) as client:
        try:
            departments = await client.get_departments()
            users = await client.list_users()
        except WeComError as exc:
            raise CustomException(msg=f"企业微信通讯录同步失败：{exc}") from exc

    if not departments and not users:
        raise CustomException(msg="企业微信通讯录未返回数据，请检查通讯录读取权限")

    existing_orgs = {
        row.source_code: row
        for row in (
            await db.execute(
                select(SourceOrgModel).where(SourceOrgModel.source_type == WECOM_SOURCE_TYPE)
            )
        ).scalars()
    }
    org_created = org_updated = 0
    seen_orgs: set[str] = set()
    for dept in departments:
        dept_id = str(dept.get("id") or "").strip()
        if not dept_id:
            continue
        seen_orgs.add(dept_id)
        parent_id = dept.get("parentid")
        parent_code = str(parent_id) if parent_id not in (None, 0, "0", "") else None
        payload = {
            "source_name": str(dept.get("name") or dept_id),
            "source_parent_code": parent_code,
            "raw_json": dept,
            "status": 0,
            "is_deleted": False,
        }
        obj = existing_orgs.get(dept_id)
        if obj is None:
            db.add(
                SourceOrgModel(
                    source_type=WECOM_SOURCE_TYPE,
                    source_code=dept_id,
                    **payload,
                )
            )
            org_created += 1
        else:
            for key, value in payload.items():
                setattr(obj, key, value)
            org_updated += 1

    existing_persons = {
        row.source_code: row
        for row in (
            await db.execute(
                select(SourcePersonModel).where(SourcePersonModel.source_type == WECOM_SOURCE_TYPE)
            )
        ).scalars()
    }
    person_created = person_updated = 0
    seen_persons: set[str] = set()
    for user in users:
        userid = str(user.get("userid") or "").strip()
        if not userid or userid in seen_persons:
            continue
        seen_persons.add(userid)
        department_ids = user.get("department") or []
        main_department = user.get("main_department")
        if main_department in (None, "") and department_ids:
            main_department = department_ids[0]
        payload = {
            "source_name": str(user.get("name") or userid),
            "source_org_code": str(main_department) if main_department not in (None, "") else None,
            "mobile": user.get("mobile") or None,
            "email": user.get("email") or None,
            "raw_json": user,
            "status": 0 if as_int(user.get("status"), 1) == 1 else 1,
            "is_deleted": False,
        }
        obj = existing_persons.get(userid)
        if obj is None:
            db.add(
                SourcePersonModel(
                    source_type=WECOM_SOURCE_TYPE,
                    source_code=userid,
                    **payload,
                )
            )
            person_created += 1
        else:
            for key, value in payload.items():
                setattr(obj, key, value)
            person_updated += 1

    await db.flush()

    # 企微已删除/离职的人员与部门保留历史行，只置为失效，不做物理删除
    if seen_persons:
        await db.execute(
            update(SourcePersonModel)
            .where(
                SourcePersonModel.source_type == WECOM_SOURCE_TYPE,
                SourcePersonModel.source_code.notin_(list(seen_persons)),
            )
            .values(status=1)
        )
    if seen_orgs:
        await db.execute(
            update(SourceOrgModel)
            .where(
                SourceOrgModel.source_type == WECOM_SOURCE_TYPE,
                SourceOrgModel.source_code.notin_(list(seen_orgs)),
            )
            .values(status=1)
        )

    run = WeComSyncRunModel(
        sync_type=SYNC_TYPE_ROSTER,
        status=SYNC_STATUS_SUCCESS,
        expected_users=len(seen_persons),
        actual_users=len(seen_persons),
        rows_upserted=org_created + org_updated + person_created + person_updated,
        started_at=started_at,
        finished_at=datetime.now(UTC),
    )
    db.add(run)
    await db.flush()
    return {
        "departments": len(seen_orgs),
        "users": len(seen_persons),
        "orgs_created": org_created,
        "orgs_updated": org_updated,
        "persons_created": person_created,
        "persons_updated": person_updated,
    }


# ---------------------------------------------------------------------- #
# 打卡同步
# ---------------------------------------------------------------------- #
def _chunked(items: list[str], size: int = 900) -> Iterable[list[str]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


async def _crm_marketing_users(
    db: AsyncSession,
    prefix: str,
    marketing_only: bool = True,
) -> tuple[dict[str, str], int]:
    """从 CRM 来源人员取「工号 -> 姓名」，口径对齐 PHP 的 yg_admin。

    返回 ``(唯一工号映射, 行数)``；行数用于 expectedUserCount（CRM 工号可能重复）。
    """
    rows = (
        await db.execute(
            select(SourcePersonModel).where(
                SourcePersonModel.source_type == "crm",
                SourcePersonModel.status == 0,
                SourcePersonModel.is_deleted.is_(False),
            )
        )
    ).scalars()
    users: dict[str, str] = {}
    row_count = 0
    for row in rows:
        raw = row.raw_json or {}
        number = str(raw.get("number") or "").strip()
        if not number:
            continue
        raw_status = str(raw.get("status") or "").strip().lower()
        if raw_status and raw_status != "normal":
            continue
        if marketing_only and not number.startswith(prefix):
            continue
        row_count += 1
        users.setdefault(number, str(raw.get("nickname") or row.source_name or number))
    return users, row_count


async def sync_checkin(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    connection_id: int | None = None,
    userids: list[str] | None = None,
    only_marketing: bool = False,
) -> dict[str, Any]:
    """拉取每日打卡并写入 ``wecom_checkin_day``（按 userid + work_date 幂等）。"""
    if end_date < start_date:
        raise CustomException(msg="结束日期不能早于开始日期")
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise CustomException(msg=f"单次同步跨度不能超过 {MAX_RANGE_DAYS} 天")

    connection = await get_connection(db, connection_id)
    if userids is None:
        if only_marketing:
            crm_users, _ = await _crm_marketing_users(db, DEFAULT_MARKETING_PREFIX)
            if crm_users:
                userids = list(crm_users)
    if userids is None:
        stmt = select(SourcePersonModel.source_code).where(
            SourcePersonModel.source_type == WECOM_SOURCE_TYPE,
            SourcePersonModel.status == 0,
            SourcePersonModel.is_deleted.is_(False),
        )
        if only_marketing:
            stmt = stmt.where(SourcePersonModel.source_code.like(f"{DEFAULT_MARKETING_PREFIX}%"))
        userids = list((await db.execute(stmt)).scalars())
    ids = sorted({str(item).strip() for item in userids if str(item).strip()})
    if not ids:
        raise CustomException(msg="没有可同步的人员，请先同步企微通讯录或检查工号前缀")

    started_at = datetime.now(UTC)
    run = WeComSyncRunModel(
        sync_type=SYNC_TYPE_CHECKIN,
        date_from=start_date,
        date_to=end_date,
        status=SYNC_STATUS_RUNNING,
        expected_users=len(ids),
        started_at=started_at,
    )
    db.add(run)
    await db.flush()

    created = updated = 0
    actual_users: set[str] = set()
    errors: list[dict[str, Any]] = []
    try:
        async with build_client(connection) as client:
            for chunk_start, chunk_end in iter_date_chunks(start_date, end_date, CHECKIN_CHUNK_DAYS):
                datas, chunk_errors = await client.get_checkin_daydata(chunk_start, chunk_end, ids)
                errors.extend(chunk_errors)
                parsed = [row for row in (parse_checkin_item(item) for item in datas) if row]
                if not parsed:
                    continue

                # 同一人同一天只保留最后一条
                unique = {(row["userid"], row["work_date"]): row for row in parsed}
                existing_rows = (
                    await db.execute(
                        select(WeComCheckinDayModel).where(
                            WeComCheckinDayModel.work_date >= chunk_start,
                            WeComCheckinDayModel.work_date <= chunk_end,
                        )
                    )
                ).scalars()
                existing = {(row.userid, row.work_date): row for row in existing_rows}

                for (userid, work_date), row in unique.items():
                    obj = existing.get((userid, work_date))
                    if obj is None:
                        db.add(
                            WeComCheckinDayModel(
                                userid=userid,
                                name=row["name"],
                                work_date=work_date,
                                earliest_sec=row["earliest_sec"],
                                latest_sec=row["latest_sec"],
                                regular_work_sec=row["regular_work_sec"],
                                off_work_sec=row["off_work_sec"],
                                cross_day=row["cross_day"],
                                raw_json=row.get("raw_json"),
                                synced_at=datetime.now(UTC),
                            )
                        )
                        created += 1
                    else:
                        obj.name = row["name"]
                        obj.earliest_sec = row["earliest_sec"]
                        obj.latest_sec = row["latest_sec"]
                        obj.regular_work_sec = row["regular_work_sec"]
                        obj.off_work_sec = row["off_work_sec"]
                        obj.cross_day = row["cross_day"]
                        obj.raw_json = row.get("raw_json")
                        obj.synced_at = datetime.now(UTC)
                        updated += 1
                    actual_users.add(userid)
                await db.flush()
    except Exception as exc:
        run.status = SYNC_STATUS_FAILED
        run.error_msg = str(exc)[:4000]
        run.finished_at = datetime.now(UTC)
        await db.flush()
        raise

    run.actual_users = len(actual_users)
    run.rows_upserted = created + updated
    run.finished_at = datetime.now(UTC)
    if errors or not actual_users:
        run.status = SYNC_STATUS_PARTIAL
        if errors:
            run.error_msg = json.dumps(errors, ensure_ascii=False)[:4000]
        else:
            run.error_msg = "企微未返回打卡数据"
    else:
        run.status = SYNC_STATUS_SUCCESS
    await db.flush()

    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "expected_users": len(ids),
        "actual_users": len(actual_users),
        "created": created,
        "updated": updated,
        "errors": errors,
    }


# ---------------------------------------------------------------------- #
# 查询与工时计算
# ---------------------------------------------------------------------- #
async def calc_worktime(
    db: AsyncSession,
    start_date: date,
    end_date: date,
    marketing_only: bool = True,
    prefix: str = DEFAULT_MARKETING_PREFIX,
    person_source: str = "crm",
) -> WeComWorktimeResultSchema:
    """按旧 PHP 口径统计正常工时与加班，数据全部读本地库。"""
    if end_date < start_date:
        raise CustomException(msg="结束日期不能早于开始日期")
    if (end_date - start_date).days + 1 > MAX_RANGE_DAYS:
        raise CustomException(msg=f"单次查询跨度不能超过 {MAX_RANGE_DAYS} 天")

    actual_source = "wecom"
    expected_override: int | None = None
    if person_source == "crm":
        active_users, crm_rows = await _crm_marketing_users(db, prefix, marketing_only=marketing_only)
        if active_users:
            actual_source = "crm"
            expected_override = crm_rows
    else:
        active_users = {}
    if not active_users:
        stmt = select(SourcePersonModel.source_code, SourcePersonModel.source_name).where(
            SourcePersonModel.source_type == WECOM_SOURCE_TYPE,
            SourcePersonModel.status == 0,
            SourcePersonModel.is_deleted.is_(False),
        )
        if marketing_only:
            stmt = stmt.where(SourcePersonModel.source_code.like(f"{prefix}%"))
        active_users = {
            str(userid): str(name or userid)
            for userid, name in (await db.execute(stmt)).all()
            if str(userid).strip()
        }
        actual_source = "wecom"

    rows: list[dict[str, Any]] = []
    for chunk in _chunked(sorted(active_users)):
        result = await db.execute(
            select(WeComCheckinDayModel).where(
                WeComCheckinDayModel.work_date >= start_date,
                WeComCheckinDayModel.work_date <= end_date,
                WeComCheckinDayModel.userid.in_(chunk),
            )
        )
        for row in result.scalars():
            rows.append(
                {
                    "userid": row.userid,
                    "name": row.name,
                    "work_date": row.work_date,
                    "earliest_sec": row.earliest_sec,
                    "latest_sec": row.latest_sec,
                    "regular_work_sec": row.regular_work_sec,
                    "off_work_sec": row.off_work_sec,
                    "cross_day": row.cross_day,
                }
            )

    summary = aggregate_worktime(rows, active_users, expected_user_count=expected_override)
    result = {
        "regularWorkHours": summary["regular"]["hours"],
        "overtimeHours": summary["overtime"]["hours"],
        "regularWork": summary["regular"],
        "overtime": summary["overtime"],
        "expectedUserCount": summary["expectedUserCount"],
        "userCount": summary["userCount"],
        "byUser": summary["byUser"],
        "byDay": summary["byDay"],
        "missingUsers": summary["missingUsers"],
        "warning": summary["warning"],
        "personSource": actual_source,
    }
    return WeComWorktimeResultSchema(**result)


def recent_month_periods(count: int = 12) -> list[str]:
    """最近 N 个月（含当前月），升序返回 YYYY-MM。"""
    today = date.today()
    year, month = today.year, today.month
    periods: list[str] = []
    for _ in range(max(1, count)):
        periods.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return sorted(periods)


def _month_bounds(period: str) -> tuple[date, date]:
    try:
        first = datetime.strptime(period, "%Y-%m")
    except ValueError as exc:
        raise CustomException(msg=f"月份格式应为 YYYY-MM: {period}") from exc
    start = first.date().replace(day=1)
    end = date(first.year, first.month, calendar.monthrange(first.year, first.month)[1])
    return start, end


async def query_monthly_worktime(
    db: AsyncSession,
    periods: list[str],
    userids: list[str] | None = None,
    include_zero: bool = False,
    exclude_backup_accounts: bool = True,
) -> dict[str, Any]:
    """按「员工工号 × 月份」返回正常工时与加班工时。

    - ``userids=None``：取企微在职且工号以 YG 开头的全部人员；
    - ``userids`` 显式传入：按传入工号查询（可含非 YG 工号）；
    - 默认排除 ``by`` 结尾的备用账号，避免同一人重复计算；
    - ``include_zero=True`` 时，无打卡记录的员工/月份补 0 行。
    """
    normalized_periods = sorted({str(item).strip() for item in periods if str(item).strip()})
    if not normalized_periods:
        raise CustomException(msg="请至少传入一个月份 YYYY-MM")
    if len(normalized_periods) > 36:
        raise CustomException(msg="单次最多查询 36 个月")

    explicit = userids is not None
    ids = sorted({str(item).strip() for item in (userids or []) if str(item).strip()})
    if exclude_backup_accounts:
        ids = [item for item in ids if not item.lower().endswith("by")]

    users: dict[str, str] = {}
    if explicit:
        if not ids:
            return {
                "periods": normalized_periods,
                "items": [],
                "summary": {
                    "periodCount": len(normalized_periods),
                    "userCount": 0,
                    "rowCount": 0,
                    "totalRegularHours": 0.0,
                    "totalOvertimeHours": 0.0,
                },
                "warning": {"code": "NO_USER", "message": "没有有效的工号"},
            }
        users = {uid: uid for uid in ids}
        roster_rows = (
            await db.execute(
                select(SourcePersonModel.source_code, SourcePersonModel.source_name).where(
                    SourcePersonModel.source_type == WECOM_SOURCE_TYPE,
                    SourcePersonModel.source_code.in_(ids),
                )
            )
        ).all()
        users.update(
            {
                str(userid): str(name or userid)
                for userid, name in roster_rows
                if str(userid).strip()
            }
        )
    else:
        stmt = select(SourcePersonModel.source_code, SourcePersonModel.source_name).where(
            SourcePersonModel.source_type == WECOM_SOURCE_TYPE,
            SourcePersonModel.status == 0,
            SourcePersonModel.is_deleted.is_(False),
            SourcePersonModel.source_code.like("YG%"),
        )
        if exclude_backup_accounts:
            stmt = stmt.where(SourcePersonModel.source_code.notlike("%by"))
        users = {
            str(userid): str(name or userid)
            for userid, name in (await db.execute(stmt)).all()
            if str(userid).strip()
        }

    warning: dict[str, Any] | None = None
    if not users:
        warning = {
            "code": "ROSTER_EMPTY",
            "message": "企微通讯录未同步，或没有在职 YG 工号人员",
        }

    items: list[dict[str, Any]] = []
    if users:
        userid_list = sorted(users)
        for period in normalized_periods:
            start_date, end_date = _month_bounds(period)
            rows = (
                await db.execute(
                    select(WeComCheckinDayModel).where(
                        WeComCheckinDayModel.work_date >= start_date,
                        WeComCheckinDayModel.work_date <= end_date,
                        WeComCheckinDayModel.userid.in_(userid_list),
                    )
                )
            ).scalars().all()
            parsed = [
                {
                    "userid": row.userid,
                    "name": row.name,
                    "work_date": row.work_date,
                    "earliest_sec": row.earliest_sec,
                    "latest_sec": row.latest_sec,
                    "regular_work_sec": row.regular_work_sec,
                    "off_work_sec": row.off_work_sec,
                    "cross_day": row.cross_day,
                }
                for row in rows
            ]
            summary = aggregate_worktime(parsed, users)
            by_user = {str(item["userid"]): item for item in summary["byUser"]}
            for userid in userid_list:
                bucket = by_user.get(userid)
                if bucket is None and not include_zero:
                    continue
                items.append(
                    {
                        "period": period,
                        "userid": userid,
                        "name": users.get(userid) or (bucket or {}).get("name") or userid,
                        "workDays": int((bucket or {}).get("workDays") or 0),
                        "regularHours": float((bucket or {}).get("regularHours") or 0),
                        "overtimeHours": float((bucket or {}).get("overtimeHours") or 0),
                        "regularSec": int((bucket or {}).get("regularSec") or 0),
                        "overtimeSec": int((bucket or {}).get("overtimeSec") or 0),
                        "crossDays": int((bucket or {}).get("crossDays") or 0),
                    }
                )

    total_regular = round(sum(item["regularHours"] for item in items), 2)
    total_overtime = round(sum(item["overtimeHours"] for item in items), 2)
    return {
        "periods": normalized_periods,
        "items": items,
        "summary": {
            "periodCount": len(normalized_periods),
            "userCount": len(users),
            "rowCount": len(items),
            "totalRegularHours": total_regular,
            "totalOvertimeHours": total_overtime,
        },
        "warning": warning,
    }


async def query_employees(
    db: AsyncSession,
    keyword: str | None,
    status: int | None,
    dept_code: str | None,
    page_no: int,
    page_size: int,
) -> PageResultSchema[WeComEmployeeOutSchema]:
    conditions = [
        SourcePersonModel.source_type == WECOM_SOURCE_TYPE,
        SourcePersonModel.is_deleted.is_(False),
    ]
    if keyword:
        conditions.append(
            or_(
                SourcePersonModel.source_name.like(f"%{keyword}%"),
                SourcePersonModel.source_code.like(f"%{keyword}%"),
            )
        )
    if status is not None:
        conditions.append(SourcePersonModel.status == status)
    if dept_code:
        conditions.append(SourcePersonModel.source_org_code == dept_code)

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(SourcePersonModel).where(*conditions)
            )
        ).scalar()
        or 0
    )
    offset = max(0, (page_no - 1) * page_size)
    rows = (
        await db.execute(
            select(SourcePersonModel)
            .where(*conditions)
            .order_by(SourcePersonModel.source_code.asc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars()
    items = [
        WeComEmployeeOutSchema(
            userid=row.source_code,
            name=row.source_name,
            mobile=row.mobile,
            email=row.email,
            dept_code=row.source_org_code,
            status=row.status,
            updated_time=row.updated_time,
        )
        for row in rows
    ]
    return PageResultSchema[WeComEmployeeOutSchema](
        page_no=page_no,
        page_size=page_size,
        total=total,
        has_next=offset + page_size < total,
        items=items,
    )


async def query_checkins(
    db: AsyncSession,
    userid: str | None,
    start_date: date,
    end_date: date,
    page_no: int,
    page_size: int,
) -> PageResultSchema[WeComCheckinOutSchema]:
    conditions = [
        WeComCheckinDayModel.work_date >= start_date,
        WeComCheckinDayModel.work_date <= end_date,
    ]
    if userid:
        conditions.append(WeComCheckinDayModel.userid == userid)

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(WeComCheckinDayModel).where(*conditions)
            )
        ).scalar()
        or 0
    )
    offset = max(0, (page_no - 1) * page_size)
    rows = (
        await db.execute(
            select(WeComCheckinDayModel)
            .where(*conditions)
            .order_by(WeComCheckinDayModel.work_date.desc(), WeComCheckinDayModel.userid.asc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars()

    items: list[WeComCheckinOutSchema] = []
    for row in rows:
        regular_sec = max(0, row.regular_work_sec - NOON_BREAK_SEC) if row.regular_work_sec > 0 else 0
        overtime_sec = daily_overtime_sec(row.latest_sec or 0, row.off_work_sec or DEFAULT_OFF_WORK_SEC)
        items.append(
            WeComCheckinOutSchema(
                userid=row.userid,
                name=row.name,
                work_date=row.work_date,
                earliest_time=seconds_to_hhmmss(row.earliest_sec),
                latest_time=seconds_to_hhmmss(row.latest_sec),
                off_work_time=seconds_to_hhmmss(row.off_work_sec or DEFAULT_OFF_WORK_SEC),
                regular_work_sec=row.regular_work_sec,
                regular_hours=round(regular_sec / 3600, 2),
                overtime_sec=overtime_sec,
                overtime_hours=round(overtime_sec / 3600, 2),
                cross_day=row.cross_day,
            )
        )
    return PageResultSchema[WeComCheckinOutSchema](
        page_no=page_no,
        page_size=page_size,
        total=total,
        has_next=offset + page_size < total,
        items=items,
    )


async def query_sync_runs(
    db: AsyncSession,
    sync_type: str | None,
    status: str | None,
    page_no: int,
    page_size: int,
) -> PageResultSchema[WeComSyncRunOutSchema]:
    conditions = [WeComSyncRunModel.is_deleted.is_(False)]
    if sync_type:
        conditions.append(WeComSyncRunModel.sync_type == sync_type)
    if status:
        conditions.append(WeComSyncRunModel.status == status)

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(WeComSyncRunModel).where(*conditions)
            )
        ).scalar()
        or 0
    )
    offset = max(0, (page_no - 1) * page_size)
    rows = (
        await db.execute(
            select(WeComSyncRunModel)
            .where(*conditions)
            .order_by(WeComSyncRunModel.id.desc())
            .offset(offset)
            .limit(page_size)
        )
    ).scalars()
    return PageResultSchema[WeComSyncRunOutSchema](
        page_no=page_no,
        page_size=page_size,
        total=total,
        has_next=offset + page_size < total,
        items=[WeComSyncRunOutSchema.model_validate(row) for row in rows],
    )

