"""初始化金蝶科目余额表元数据与 Cron 同步任务。

用法：
    python scripts/seed_account_balance_metadata.py
"""

import asyncio
import configparser
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INI_PATH = PROJECT_ROOT / "env" / "kindee_conf.ini"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.kingdee.model import KingdeeConnectionModel  # noqa: E402
from app.modules.metadata.model import (  # noqa: E402
    FieldMappingModel,
    MetaSyncJobModel,
    SourceFieldModel,
    SourceObjectModel,
    SourceSystemModel,
    StandardEntityModel,
    StandardFieldModel,
)
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

FIELD_KEYS = [
    "FBALANCEID",
    "FBALANCENAME",
    "FDETAILNUMBER",
    "FDETAILNAME",
    "FBEGINDEBIT",
    "FBEGINDEBITLOCAL",
    "FBEGINCREDIT",
    "FBEGINCREDITLOCAL",
    "FDEBIT",
    "FDEBITLOCAL",
    "FCREDIT",
    "FCREDITLOCAL",
    "FYTDDEBIT",
    "FYTDDEBITLOCAL",
    "FYTDCREDIT",
    "FYTDCREDITLOCAL",
    "FENDDEBIT",
    "FENDDEBITLOCAL",
    "FENDCREDIT",
    "FENDCREDITLOCAL",
]

FIELD_NAMES = {
    "FBALANCEID": "科目编码",
    "FBALANCENAME": "科目名称",
    "FDETAILNUMBER": "核算维度编码",
    "FDETAILNAME": "核算维度名称",
    "FBEGINDEBIT": "期初余额-原币（借）",
    "FBEGINDEBITLOCAL": "期初余额-本位币（借）",
    "FBEGINCREDIT": "期初余额-原币（贷）",
    "FBEGINCREDITLOCAL": "期初余额-本位币（贷）",
    "FDEBIT": "本期发生-原币（借）",
    "FDEBITLOCAL": "本期发生-本位币（借）",
    "FCREDIT": "本期发生-原币（贷）",
    "FCREDITLOCAL": "本期发生-本位币（贷）",
    "FYTDDEBIT": "本年累计-原币（借）",
    "FYTDDEBITLOCAL": "本年累计-本位币（借）",
    "FYTDCREDIT": "本年累计-原币（贷）",
    "FYTDCREDITLOCAL": "本年累计-本位币（贷）",
    "FENDDEBIT": "期末余额-原币（借）",
    "FENDDEBITLOCAL": "期末余额-本位币（借）",
    "FENDCREDIT": "期末余额-原币（贷）",
    "FENDCREDITLOCAL": "期末余额-本位币（贷）",
}

DIMENSIONS = {"FBALANCEID", "FBALANCENAME", "FDETAILNUMBER", "FDETAILNAME"}

OBJECT_VARIABLES = [
    {"name": "year", "value_type": "expression", "value": "now.strftime('%Y')", "description": "当前年份"},
    {"name": "month", "value_type": "expression", "value": "now.strftime('%m')", "description": "当前月份"},
    {"name": "day", "value_type": "expression", "value": "now.strftime('%d')", "description": "当前日"},
    {"name": "date", "value_type": "expression", "value": "now.strftime('%Y-%m-%d')", "description": "当前日期"},
    {"name": "org_code", "value_type": "expression", "value": "org_code", "description": "任务组织编码"},
]

REQUEST_PARAMS = {
    "FieldKeys": ",".join(FIELD_KEYS),
    "SchemeId": "",
    "StartRow": 0,
    "Limit": 2000,
    "IsVerifyBaseDataField": "true",
    "FilterString": [],
    "Model": {
        "FACCTBOOKID": {"FNumber": "{{org_code}}"},
        "FCURRENCY": "1",
        "FSTARTYEAR": "{{year}}",
        "FSTARTPERIOD": "{{month}}",
        "FENDYEAR": "{{year}}",
        "FBALANCELEVEL": "3",
        "FENDPERIOD": "{{month}}",
        "FSHOWDETAIL": True,
        "FFORBIDBALANCE": True,
        "FNOTPOSTVOUCHER": True,
        "FDEBITORCREDIT": False,
        "FBALANCEZERO": True,
        "FNOBUSINESS": False,
        "FPERIODNOBALANCE": True,
        "FYEARNOBALANCE": True,
        "FSHOWFULLNAME": False,
        "FDETAILSHOWACCT": False,
        "FSHOWDETAILONLY": False,
        "FEXCLUDEADJUSTVCH": False,
        "FFLEXDEBITORCREDIT": False,
        "FSHOWFLEXBYCOL": False,
    },
}


async def get_or_create(db, model, **kwargs):
    match_keys = {
        SourceSystemModel: ["code"],
        SourceObjectModel: ["system_id", "code"],
        SourceFieldModel: ["object_id", "field_key"],
        StandardEntityModel: ["code"],
        StandardFieldModel: ["entity_id", "field_code"],
    }.get(model, ["id"])
    conditions = [getattr(model, key) == kwargs[key] for key in match_keys if key in kwargs]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**kwargs)
        db.add(obj)
    else:
        for key, value in kwargs.items():
            setattr(obj, key, value)
    await db.flush()
    return obj


async def main() -> None:
    conf = configparser.ConfigParser()
    conf.read(INI_PATH, encoding="utf-8")

    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(select(KingdeeConnectionModel).where(KingdeeConnectionModel.name == "金蝶默认连接"))
        ).scalars().first()
        if connection is None:
            connection = KingdeeConnectionModel(
                name="金蝶默认连接",
                server_url=conf.get("config", "x-kdapi-serverurl", fallback=""),
                acct_id=conf.get("config", "x-kdapi-acctid", fallback=""),
                username=conf.get("config", "x-kdapi-username", fallback=""),
                app_id=conf.get("config", "x-kdapi-appid", fallback=""),
                app_secret=CryptoUtil.encrypt(conf.get("config", "x-kdapi-appsec", fallback="")),
                lcid=conf.getint("config", "x-kdapi-lcid", fallback=2052),
                org_num=conf.getint("config", "x-kdapi-orgnum", fallback=0),
                connect_timeout=conf.getint("config", "x-kdapi-connecttimeout", fallback=120),
                request_timeout=conf.getint("config", "x-kdapi-requesttimeout", fallback=120),
                status=0,
            )
            db.add(connection)
            await db.flush()

        system = await get_or_create(
            db,
            SourceSystemModel,
            code="kingdee",
            name="金蝶云星空",
            connector_type="kingdee",
            connection_id=connection.id,
            status=0,
        )
        source_object = await get_or_create(
            db,
            SourceObjectModel,
            system_id=system.id,
            code="GL_RPT_AccountBalance",
            name="科目余额表",
            query_type="sys_report",
            request_template=REQUEST_PARAMS,
            variables=OBJECT_VARIABLES,
            status=0,
        )
        standard_entity = await get_or_create(
            db,
            StandardEntityModel,
            code="account_balance",
            name="科目余额表",
            table_name="dwd_account_balance",
            status=0,
        )

        for field_key in FIELD_KEYS:
            source_field = await get_or_create(
                db,
                SourceFieldModel,
                object_id=source_object.id,
                field_key=field_key,
                field_name=FIELD_NAMES[field_key],
                data_type="string" if field_key in DIMENSIONS else "number",
                is_primary_key=field_key == "FBALANCEID",
                is_watermark=False,
                status=0,
            )
            standard_field = await get_or_create(
                db,
                StandardFieldModel,
                entity_id=standard_entity.id,
                field_code=field_key,
                field_name=FIELD_NAMES[field_key],
                data_type="string" if field_key in DIMENSIONS else "number",
                is_dimension=field_key in DIMENSIONS,
                is_measure=field_key not in DIMENSIONS,
                status=0,
            )
            exists_mapping = (
                await db.execute(
                    select(FieldMappingModel).where(
                        FieldMappingModel.source_field_id == source_field.id,
                        FieldMappingModel.standard_field_id == standard_field.id,
                    )
                )
            ).scalars().first()
            if exists_mapping is None:
                db.add(
                    FieldMappingModel(
                        source_object_id=source_object.id,
                        source_field_id=source_field.id,
                        standard_field_id=standard_field.id,
                        transform_type="direct",
                        order=0,
                        status=0,
                    )
                )

        for org_code in [str(code) for code in range(100, 114)]:
            job = (
                await db.execute(
                    select(MetaSyncJobModel).where(MetaSyncJobModel.name == f"科目余额表-组织{org_code}")
                )
            ).scalars().first()
            if job is None:
                job = MetaSyncJobModel(name=f"科目余额表-组织{org_code}", org_code=org_code)
                db.add(job)
            job.source_system_id = system.id
            job.source_object_id = source_object.id
            job.standard_entity_id = standard_entity.id
            job.cron_expr = "0 0 2 * * ?"
            job.request_params = REQUEST_PARAMS
            job.sync_mode = "full"
            job.status = 0
            await db.flush()

    await async_engine.dispose()
    print("科目余额表元数据初始化完成")


if __name__ == "__main__":
    asyncio.run(main())
