"""企业微信打卡工时计算与客户端分批规则（离线，不发请求）。"""

from datetime import date, datetime

import pytest

from app.modules.erp.wecom.calc import (
    CN_TZ,
    DEFAULT_OFF_WORK_SEC,
    aggregate_worktime,
    daily_overtime_sec,
    iter_date_chunks,
    off_work_sec_from_rule,
    parse_checkin_item,
    seconds_to_hhmmss,
)
from app.modules.erp.wecom.client import WeComClient, WeComClientConfig


def _ts(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=CN_TZ).timestamp())


def _item(
    userid: str,
    work_date: date,
    *,
    regular_work_sec: int,
    latest_sec: int,
    earliest_sec: int = 32400,
    off_work_sec: int = 64800,
    name: str = "张三",
) -> dict:
    return {
        "base_info": {
            "acctid": userid,
            "name": name,
            "date": _ts(work_date),
            "rule_info": {"checkintime": [{"off_work_sec": off_work_sec}]},
        },
        "summary_info": {
            "regular_work_sec": regular_work_sec,
            "earliest_time": earliest_sec,
            "lastest_time": latest_sec,
        },
    }


def test_parse_checkin_item():
    work_date = date(2026, 7, 1)
    parsed = parse_checkin_item(_item("YG20001", work_date, regular_work_sec=32400, latest_sec=68400))

    assert parsed is not None
    assert parsed["userid"] == "YG20001"
    assert parsed["work_date"] == work_date
    assert parsed["regular_work_sec"] == 32400
    assert parsed["latest_sec"] == 68400
    assert parsed["off_work_sec"] == 64800
    assert parsed["cross_day"] is False
    assert parsed["raw_json"]["base_info"]["acctid"] == "YG20001"


def test_off_work_fallback_to_18h():
    assert off_work_sec_from_rule({}) == DEFAULT_OFF_WORK_SEC
    assert off_work_sec_from_rule({"rule_info": {"checkintime": []}}) == DEFAULT_OFF_WORK_SEC
    assert off_work_sec_from_rule({"rule_info": {"checkintime": [{"off_work_sec": 61200}]}}) == 61200


def test_regular_work_and_overtime_aggregate():
    rows = [
        {
            "userid": "YG20001",
            "name": "张三",
            "work_date": date(2026, 7, 1),
            "earliest_sec": 32400,
            "latest_sec": 68400,
            "regular_work_sec": 32400,
            "off_work_sec": 64800,
            "cross_day": False,
        },
        {
            "userid": "YG20001",
            "name": "张三",
            "work_date": date(2026, 7, 2),
            "earliest_sec": 32400,
            "latest_sec": 64800,
            "regular_work_sec": 3600,
            "off_work_sec": 64800,
            "cross_day": False,
        },
    ]
    summary = aggregate_worktime(rows, {"YG20001": "张三"})

    assert summary["regular"]["sec"] == 27000  # 32400-5400 + max(0, 3600-5400)
    assert summary["regular"]["hours"] == 7.5
    assert summary["regular"]["rawSec"] == 36000
    assert summary["regular"]["noonBreakSec"] == 10800
    assert summary["regular"]["workDays"] == 2
    assert summary["overtime"]["sec"] == 1800  # 18:60 - 18:00 - 30min
    assert summary["overtime"]["hours"] == 0.5
    assert summary["expectedUserCount"] == 1
    assert summary["userCount"] == 1
    assert summary["warning"] is None
    assert summary["byDay"][0]["regularHours"] == 7.5
    assert summary["byDay"][1]["regularHours"] == 0.0


def test_small_overtime_is_erased_by_meal_break():
    # 18:20 下班：超 20 分钟，扣 30 分钟饭后为 0
    assert daily_overtime_sec(66000, 64800) == 0


def test_cross_day_overtime():
    rows = [
        {
            "userid": "YG20002",
            "name": "李四",
            "work_date": date(2026, 7, 1),
            "earliest_sec": 32400,
            "latest_sec": 90000,  # 次日 01:00
            "regular_work_sec": 32400,
            "off_work_sec": 64800,
            "cross_day": True,
        }
    ]
    summary = aggregate_worktime(rows, {"YG20002": "李四"})

    assert summary["overtime"]["sec"] == 23400  # 25:00 - 18:00 - 0:30
    assert summary["overtime"]["hours"] == 6.5
    assert summary["overtime"]["crossDayCount"] == 1
    assert summary["overtime"]["detail"][0]["lastestTime"] == "25:00:00"
    assert summary["byUser"][0]["crossDays"] == 1


def test_warning_when_actual_users_too_low():
    active = {f"YG2000{i}": f"员工{i}" for i in range(1, 11)}
    rows = [
        {
            "userid": "YG20001",
            "name": "员工1",
            "work_date": date(2026, 7, 1),
            "regular_work_sec": 32400,
            "latest_sec": 64800,
            "off_work_sec": 64800,
        }
    ]
    summary = aggregate_worktime(rows, active)

    assert summary["expectedUserCount"] == 10
    assert summary["userCount"] == 1
    assert summary["warning"]["errcode"] == -3
    assert len(summary["missingUsers"]) == 9


def test_same_user_same_day_is_not_double_counted():
    rows = [
        {
            "userid": "YG20001",
            "name": "张三",
            "work_date": date(2026, 7, 1),
            "regular_work_sec": 32400,
            "latest_sec": 64800,
            "off_work_sec": 64800,
        },
        {
            "userid": "YG20001",
            "name": "张三",
            "work_date": date(2026, 7, 1),
            "regular_work_sec": 28800,
            "latest_sec": 64800,
            "off_work_sec": 64800,
        },
    ]
    summary = aggregate_worktime(rows, {"YG20001": "张三"})

    assert summary["regular"]["workDays"] == 1
    assert summary["regular"]["sec"] == 23400  # 最后一条 28800-5400


def test_seconds_to_hhmmss_supports_cross_day():
    assert seconds_to_hhmmss(0) == "00:00:00"
    assert seconds_to_hhmmss(64800) == "18:00:00"
    assert seconds_to_hhmmss(90000) == "25:00:00"


def test_iter_date_chunks_are_inclusive_and_capped():
    chunks = list(iter_date_chunks(date(2026, 1, 1), date(2026, 3, 15), 30))

    assert chunks[0] == (date(2026, 1, 1), date(2026, 1, 30))
    assert chunks[-1][1] == date(2026, 3, 15)
    assert all((end - start).days + 1 <= 30 for start, end in chunks)


@pytest.mark.asyncio
async def test_client_batches_100_userids(monkeypatch):
    client = WeComClient(
        WeComClientConfig(corp_id="corp", checkin_secret="secret", request_interval=0)
    )
    calls: list[list[str]] = []

    async def fake_call(method, path, *, secret_kind, params=None, json_body=None):
        calls.append(json_body["useridlist"])
        return {"errcode": 0, "datas": []}

    monkeypatch.setattr(client, "_call_api", fake_call)
    userids = [f"YG{i:05d}" for i in range(250)]
    datas, errors = await client.get_checkin_daydata(date(2026, 7, 1), date(2026, 7, 1), userids)

    assert [len(chunk) for chunk in calls] == [100, 100, 50]
    assert datas == []
    assert errors == []
    await client.aclose()


@pytest.mark.asyncio
async def test_token_url_mode_uses_php_token_service(monkeypatch):
    client = WeComClient(
        WeComClientConfig(
            corp_id="",
            checkin_secret="",
            token_url="http://token.service/getAccessToken",
            request_interval=0,
        )
    )
    calls: list[str] = []

    async def fake_get_text(url: str) -> str:
        calls.append(url)
        return "token-from-php-service"

    async def fake_cache_get(key: str):
        return None

    async def fake_cache_set(key: str, value: str, ttl: int):
        return None

    monkeypatch.setattr(client, "_get_text", fake_get_text)
    monkeypatch.setattr(client, "_cache_get", fake_cache_get)
    monkeypatch.setattr(client, "_cache_set", fake_cache_set)

    token = await client._token("checkin")
    assert token == "token-from-php-service"
    assert calls == ["http://token.service/getAccessToken"]
    assert client._cache_key("checkin").startswith("wecom:token:url:")
    await client.aclose()


@pytest.mark.asyncio
async def test_sync_checkin_is_idempotent(tmp_path, monkeypatch):
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.base_model import MappedBase
    from app.modules.erp.wecom.model import (
        WeComCheckinDayModel,
        WeComConnectionModel,
        WeComSyncRunModel,
    )
    from app.modules.erp.wecom.service import sync_checkin
    from app.modules.masterdata.model import SourceOrgModel, SourcePersonModel
    from app.modules.system.dept.model import DeptModel
    from app.modules.system.user.model import UserModel

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc_info):
            return None

        async def get_checkin_daydata(self, start, end, userids):
            work_date = date(2026, 7, 1)
            return [
                _item("YG20001", work_date, regular_work_sec=32400, latest_sec=68400),
                _item("YG20002", work_date, regular_work_sec=32400, latest_sec=64800),
            ], []

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wecom.db'}")
    tables = [
        DeptModel.__table__,
        UserModel.__table__,
        SourceOrgModel.__table__,
        SourcePersonModel.__table__,
        WeComCheckinDayModel.__table__,
        WeComSyncRunModel.__table__,
        WeComConnectionModel.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all, tables=tables)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(
        "app.modules.erp.wecom.service.build_client",
        lambda connection: FakeClient(),
    )

    async with factory() as db:
        db.add_all(
            [
                SourcePersonModel(source_type="wecom", source_code="YG20001", source_name="张三", status=0),
                SourcePersonModel(source_type="wecom", source_code="YG20002", source_name="李四", status=0),
                WeComConnectionModel(
                    name="test",
                    corp_id="corp",
                    checkin_secret="secret",
                    status=0,
                ),
            ]
        )
        await db.commit()

        work_date = date(2026, 7, 1)
        first = await sync_checkin(db, work_date, work_date)
        await db.commit()
        second = await sync_checkin(db, work_date, work_date)
        await db.commit()

        rows = (await db.execute(select(WeComCheckinDayModel))).scalars().all()
        assert first["created"] == 2
        assert first["updated"] == 0
        assert second["created"] == 0
        assert second["updated"] == 2
        assert len(rows) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_wecom_dept_worktime_excludes_by_accounts_and_includes_children(tmp_path):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.base_model import MappedBase
    from app.modules.erp.wecom.model import WeComCheckinDayModel
    from app.modules.masterdata.model import SourceOrgModel, SourcePersonModel
    from app.modules.metric.engine import _compute_wecom_dept_worktime
    from app.modules.system.dept.model import DeptModel
    from app.modules.system.user.model import UserModel

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'dept.db'}")
    tables = [
        DeptModel.__table__,
        UserModel.__table__,
        SourceOrgModel.__table__,
        SourcePersonModel.__table__,
        WeComCheckinDayModel.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all, tables=tables)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        db.add_all(
            [
                SourceOrgModel(source_type="wecom", source_code="14", source_name="品类与流量部", source_parent_code="1", status=0),
                SourceOrgModel(source_type="wecom", source_code="107", source_name="品类组", source_parent_code="14", status=0),
                SourcePersonModel(source_type="wecom", source_code="YG20001", source_name="甲", source_org_code="14", status=0),
                SourcePersonModel(source_type="wecom", source_code="YG20002", source_name="乙", source_org_code="107", status=0),
                SourcePersonModel(source_type="wecom", source_code="YG20002by", source_name="乙BY", source_org_code="107", status=0),
                SourcePersonModel(source_type="wecom", source_code="YG20003", source_name="离职", source_org_code="14", status=1),
                WeComCheckinDayModel(
                    userid="YG20001",
                    name="甲",
                    work_date=date(2026, 9, 1),
                    earliest_sec=32400,
                    latest_sec=68400,
                    regular_work_sec=32400,
                    off_work_sec=64800,
                    cross_day=False,
                ),
                WeComCheckinDayModel(
                    userid="YG20002",
                    name="乙",
                    work_date=date(2026, 9, 1),
                    earliest_sec=32400,
                    latest_sec=64800,
                    regular_work_sec=32400,
                    off_work_sec=64800,
                    cross_day=False,
                ),
                WeComCheckinDayModel(
                    userid="YG20002by",
                    name="乙BY",
                    work_date=date(2026, 9, 1),
                    earliest_sec=32400,
                    latest_sec=68400,
                    regular_work_sec=32400,
                    off_work_sec=64800,
                    cross_day=False,
                ),
            ]
        )
        await db.commit()

        config = {
            "department_code": "14",
            "include_children": True,
            "exclude_userid_suffixes": ["by"],
            "value_field": "regular",
        }
        regular = await _compute_wecom_dept_worktime(db, config, "month", "2026-09")
        assert regular[0] == 15.0  # 两个人各 7.5h；by 账号与离职人员不计
        assert regular[1] == 2  # 打卡行数
        assert regular[2] == "14"
        assert regular[4] == 2  # 参与人数

        overtime = await _compute_wecom_dept_worktime(
            db, {**config, "value_field": "overtime"}, "month", "2026-09"
        )
        assert overtime[0] == 0.5

    await engine.dispose()


@pytest.mark.asyncio
async def test_query_monthly_worktime_by_period_and_user(tmp_path):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.base_model import MappedBase
    from app.modules.erp.wecom.model import WeComCheckinDayModel
    from app.modules.erp.wecom.service import query_monthly_worktime
    from app.modules.masterdata.model import SourceOrgModel, SourcePersonModel
    from app.modules.system.dept.model import DeptModel
    from app.modules.system.user.model import UserModel

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'monthly.db'}")
    tables = [
        DeptModel.__table__,
        UserModel.__table__,
        SourceOrgModel.__table__,
        SourcePersonModel.__table__,
        WeComCheckinDayModel.__table__,
    ]
    async with engine.begin() as conn:
        await conn.run_sync(MappedBase.metadata.create_all, tables=tables)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as db:
        db.add_all(
            [
                SourcePersonModel(source_type="wecom", source_code="YG20001", source_name="甲", status=0),
                SourcePersonModel(source_type="wecom", source_code="YG20002", source_name="乙", status=0),
                SourcePersonModel(source_type="wecom", source_code="YG20002by", source_name="乙BY", status=0),
                WeComCheckinDayModel(
                    userid="YG20001",
                    name="甲",
                    work_date=date(2026, 9, 1),
                    earliest_sec=32400,
                    latest_sec=68400,
                    regular_work_sec=32400,
                    off_work_sec=64800,
                    cross_day=False,
                ),
                WeComCheckinDayModel(
                    userid="YG20002",
                    name="乙",
                    work_date=date(2026, 9, 1),
                    earliest_sec=32400,
                    latest_sec=64800,
                    regular_work_sec=32400,
                    off_work_sec=64800,
                    cross_day=False,
                ),
                WeComCheckinDayModel(
                    userid="YG20002by",
                    name="乙BY",
                    work_date=date(2026, 9, 1),
                    earliest_sec=32400,
                    latest_sec=68400,
                    regular_work_sec=32400,
                    off_work_sec=64800,
                    cross_day=False,
                ),
            ]
        )
        await db.commit()

        result = await query_monthly_worktime(
            db,
            periods=["2026-09", "2026-10"],
            include_zero=True,
            exclude_backup_accounts=True,
        )
        assert result["summary"]["userCount"] == 2  # by 账号被排除
        assert result["summary"]["rowCount"] == 4  # 2 人 × 2 个月
        sep = {item["userid"]: item for item in result["items"] if item["period"] == "2026-09"}
        oct_ = {item["userid"]: item for item in result["items"] if item["period"] == "2026-10"}
        assert sep["YG20001"]["regularHours"] == 7.5
        assert sep["YG20001"]["overtimeHours"] == 0.5
        assert sep["YG20002"]["overtimeHours"] == 0.0
        assert oct_["YG20001"]["regularHours"] == 0.0

        explicit = await query_monthly_worktime(
            db,
            periods=["2026-09"],
            userids=["YG20002by"],
            exclude_backup_accounts=False,
        )
        assert explicit["summary"]["rowCount"] == 1
        assert explicit["items"][0]["userid"] == "YG20002by"
        assert explicit["items"][0]["overtimeHours"] == 0.5

        zero = await query_monthly_worktime(
            db,
            periods=["2026-10"],
            userids=["NO_SUCH_USER"],
            include_zero=True,
        )
        assert zero["items"][0]["regularHours"] == 0.0
        assert zero["items"][0]["overtimeHours"] == 0.0

    await engine.dispose()

