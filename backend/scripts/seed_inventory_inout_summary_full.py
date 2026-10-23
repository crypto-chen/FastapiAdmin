"""接入金蝶《存货收发存汇总表》（组织 100 · 全仓 · 全物料），声明式维护元数据与同步任务。

报表口径（请求参数见 ``REQUEST_PARAMS``，改口径只改这里）：

1. 取 ERP100 组织（组织编码 ``100``）的金蝶《存货收发存汇总表》
   （``HS_INOUTSTOCKSUMMARYRPT``，``GetSysReportData`` 系统报表）；
2. 核算体系 ``KJHSTX01_SYS`` + 核算组织 ``{{org_code}}`` + 会计政策 ``KJZC01_SYS`` +
   会计期间 = 当期年月（``{{year}}`` / ``{{period}}``）+ 单据状态 ``C``（已审核）；
3. **仓库不限**（模板里不填仓库区间 = 全部仓库）、**物料不限**，返回 21 列：会计期间 +
   物料（编码/名称/分组/规格型号/库存状态）+ 仓库 + 核算范围 + 4 组「数量 / 单价 / 金额」
   （期初结存、本期收入、本期发出、期末结存）。

两列成本口径（用户要的数据就在这两列）：

- **库存结存的成本** = 期末结存金额 ``FENDAmount``（配套期末结存数量 ``FENDQty``）；
- **物料的成本** = 期末结存单价 ``FENDPrice``（= 期末结存金额 ÷ 期末结存数量，实测相符）。

WebAPI 实测要点（踩坑记录）：

- ``FYearPeriod``（会计期间，值形如 ``2026.09``）**只有** ``FIsDisplayPeriod = true`` 时可查，
  否则报「标识为FYearPeriod的字段不存在」；
- ``FEXPENSEID`` / ``FEXPENSENAME``（费用项目）本报表按此参数组合取不到（同样报字段不存在），
  需要费用项目明细列时应置 ``FCHXEXPENSE = true``；
- 报表同一批结果同时返回**明细行**与**小计行**（物料编码以 ``-总计`` 结尾、仓库列为空），
  汇总时必须跳过小计行，否则金额被重复计入一倍；
- 来源对象 ``code`` 是数据源唯一标识（``HS_INOUTSTOCKSUMMARYRPT_FULL``），真正提交给金蝶的
  业务对象由请求模板里的 ``FormId`` 指定（``metadata/sync.py`` 的 ``resolve_report_target``）——
  既有的「存货收发存汇总表-组织100」（仓库区间 ``JXCPC``，机箱成品仓指标在用）已占用
  ``meta_source_object.code = HS_INOUTSTOCKSUMMARYRPT``，共用同一 code 会让指标引擎按 code
  反查来源对象时定位到歧义行，故本数据源用独立 code。

同步任务每天 05:00 取当期数据（单次约 20~25 页 / 4.6 万行 / 2~5 分钟）。

用法：
    python scripts/seed_inventory_inout_summary_full.py                 # 建/更新数据源与同步任务
    python scripts/seed_inventory_inout_summary_full.py --rollback      # 删除本脚本建的元数据（幂等）
    python scripts/seed_inventory_inout_summary_full.py --rollback --db-name xxx  # 对指定库执行回滚
"""

import argparse
import asyncio
import configparser
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INI_PATH = PROJECT_ROOT / "env" / "kindee_conf.ini"
ENV_PATH = PROJECT_ROOT / "env" / ".env.dev"
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
from app.modules.metadata.sync import register_meta_sync_job  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

CONNECTION_NAME = "金蝶默认连接"
SOURCE_SYSTEM_CODE = "kingdee"
# 提交给金蝶的业务对象（报表 FormId）
FORM_ID = "HS_INOUTSTOCKSUMMARYRPT"
# 数据源唯一标识：与既有「存货收发存汇总表-组织100」数据源区分开
SOURCE_OBJECT_CODE = "HS_INOUTSTOCKSUMMARYRPT_FULL"
SOURCE_OBJECT_NAME = "存货收发存汇总表（全仓·全物料）"
STANDARD_ENTITY_CODE = "inventory_inout_summary_full"
STANDARD_ENTITY_NAME = "存货收发存汇总表（全仓·全物料）"
STANDARD_TABLE_NAME = "dwd_inventory_inout_summary_full"
SYNC_JOB_NAME = "存货收发存汇总表-组织100（全仓全物料）"
SYNC_CRON = "0 0 5 * * ?;0 20 12 * * ?;0 20 18 * * ?"  # 每天 05:00/12:20/18:20

ORG_CODE = "100"
ACCT_SYSTEM_CODE = "KJHSTX01_SYS"
ACCT_POLICY_CODE = "KJZC01_SYS"
CURRENCY_CODE = "PRE001"
DOC_STATUS_AUDITED = "C"

# 报表返回列：FieldKeys 的顺序即返回值的顺序（实测确认，不可随意调序）
# (字段Key, 字段名称, 是否度量)
SOURCE_FIELDS = [
    ("FYearPeriod", "会计期间", False),
    ("FMATERIALBASEID", "物料编码", False),
    ("FMATERIALNAME", "物料名称", False),
    ("FMATERIALGROUP", "物料分组", False),
    ("FMODEL", "规格型号", False),
    ("FSTOCKSTATUSNAME", "库存状态", False),
    ("FSTOCKId", "仓库", False),
    ("FACCTGRANGEID", "核算范围编码", False),
    ("FACCTGRANGENAME", "核算范围名称", False),
    ("FINITQty", "期初结存数量", True),
    ("FINITPrice", "期初结存单价", True),
    ("FINITAMOUNT", "期初结存金额", True),
    ("FRECEIVEQty", "本期收入数量", True),
    ("FRECEIVEPrice", "本期收入单价", True),
    ("FRECEIVEAmount", "本期收入金额", True),
    ("FSENDQty", "本期发出数量", True),
    ("FSENDPrice", "本期发出单价", True),
    ("FSENDAmount", "本期发出金额", True),
    ("FENDQty", "期末结存数量", True),
    ("FENDPrice", "期末结存单价", True),
    ("FENDAmount", "期末结存金额", True),
]
FIELD_KEYS = [field_key for field_key, _name, _is_measure in SOURCE_FIELDS]
FIELD_NAMES = {field_key: field_name for field_key, field_name, _is_measure in SOURCE_FIELDS}
MEASURE_FIELD_KEYS = {field_key for field_key, _name, is_measure in SOURCE_FIELDS if is_measure}
PRIMARY_KEY_FIELD = "FMATERIALBASEID"

# 期间变量：{{ year }} / {{ period }} 由元数据同步任务按取数期间渲染
# （回补历史期间时按该期间 1 日渲染，见 metadata/sync.py 的 resolve_period_datetime）
OBJECT_VARIABLES = [
    {"name": "year", "value_type": "expression", "value": "now.strftime('%Y')", "description": "会计年度"},
    {"name": "period", "value_type": "expression", "value": "now.strftime('%m')", "description": "会计期间"},
]

REQUEST_PARAMS = {
    # 数据源 code ≠ 金蝶 FormId，这里显式声明提交对象
    "FormId": FORM_ID,
    "FieldKeys": ",".join(FIELD_KEYS),
    "SchemeId": "",
    "StartRow": 0,
    "Limit": 2000,
    "IsVerifyBaseDataField": "true",
    "FilterString": [],
    "Model": {
        "FACCTGSYSTEMID": {"FNumber": ACCT_SYSTEM_CODE},
        "FACCTGORGID": {"FNumber": "{{org_code}}"},
        "FACCTPOLICYID": {"FNumber": ACCT_POLICY_CODE},
        "FYear": "{{year}}",
        "FPeriod": "{{period}}",
        "FENDYEAR": "{{year}}",
        "FEndPeriod": "{{period}}",
        "FMATERIALID": {"FNumber": ""},
        "FENDMATERIALID": {"FNumber": ""},
        "FACCTGRANGEID": {"FNumber": ""},
        "FOwnerID": {"FNumber": ""},
        # 仓库区间留空 = 全部仓库（填起止同一编码才锁定单一仓库）
        "FSTOCKId": {"FNumber": ""},
        "FENDSTOCKID": {"FNumber": ""},
        "FSTOCKORGID": {"FNumber": ""},
        "FMATERTYPEID": {"FNUMBER": ""},
        "FCOMBOTotalType": "0",
        "FDimType": "1",
        "FCHXEXPENSE": False,
        "FCHXTotal": False,
        "FCHXNOINOUT": False,
        "FCHXNOCOSTALLOT": False,
        # FYearPeriod（会计期间）列只有打开「显示各期间明细」才可查
        "FIsDisplayPeriod": True,
        "FCHXNOSTOCKADJ": False,
        "FCOMBOSTATUS": DOC_STATUS_AUDITED,
        "FCURRENCYID": {"FNumber": CURRENCY_CODE},
    },
}

DESCRIPTION = (
    "存货收发存汇总表（GetSysReportData）：核算组织 {{org_code}}（100）、"
    "会计期间=当期、仓库不限、物料不限、单据状态=已审核；"
    "返回 21 列（会计期间 / 物料编码·名称·分组·规格型号·库存状态 / 仓库 / 核算范围 + "
    "期初结存·本期收入·本期发出·期末结存 各 数量·单价·金额）；"
    "库存结存成本取期末结存金额 FENDAmount，物料成本取期末结存单价 FENDPrice"
)


def load_env_file(path: Path) -> dict[str, str]:
    """读取 ``key = value`` 形式的 .env（只要数据库连接四项）。"""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text.startswith("#") or "=" not in text:
            continue
        key, _, value = text.partition("=")
        values[key.strip()] = value.strip().strip("'\"")
    return values


async def get_or_create(db, model, match_keys: list[str], values: dict, defaults: dict | None = None):
    conditions = [getattr(model, key) == values[key] for key in match_keys if key in values]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**{**(defaults or {}), **values})
        db.add(obj)
    else:
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
    await db.flush()
    return obj


async def setup() -> None:
    conf = configparser.ConfigParser()
    conf.read(INI_PATH, encoding="utf-8")

    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(
                select(KingdeeConnectionModel).where(KingdeeConnectionModel.name == CONNECTION_NAME)
            )
        ).scalars().first()
        if connection is None:
            connection = KingdeeConnectionModel(
                name=CONNECTION_NAME,
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
            ["code"],
            {"code": SOURCE_SYSTEM_CODE, "name": "金蝶云星空", "connector_type": "kingdee"},
            {"connection_id": connection.id, "status": 0},
        )
        system.connection_id = connection.id

        source_object = await get_or_create(
            db,
            SourceObjectModel,
            ["system_id", "code"],
            {"system_id": system.id, "code": SOURCE_OBJECT_CODE},
            {
                "name": SOURCE_OBJECT_NAME,
                "query_type": "sys_report",
                "request_template": REQUEST_PARAMS,
                "variables": OBJECT_VARIABLES,
                "status": 0,
            },
        )
        source_object.query_type = "sys_report"
        source_object.request_template = REQUEST_PARAMS
        source_object.variables = OBJECT_VARIABLES

        standard_entity = await get_or_create(
            db,
            StandardEntityModel,
            ["code"],
            {"code": STANDARD_ENTITY_CODE},
            {"name": STANDARD_ENTITY_NAME, "table_name": STANDARD_TABLE_NAME, "status": 0},
        )

        for field_key in FIELD_KEYS:
            is_measure = field_key in MEASURE_FIELD_KEYS
            source_field = await get_or_create(
                db,
                SourceFieldModel,
                ["object_id", "field_key"],
                {"object_id": source_object.id, "field_key": field_key},
                {
                    "field_name": FIELD_NAMES[field_key],
                    "data_type": "number" if is_measure else "string",
                    "is_primary_key": field_key == PRIMARY_KEY_FIELD,
                    "is_watermark": False,
                    "status": 0,
                },
            )
            standard_field = await get_or_create(
                db,
                StandardFieldModel,
                ["entity_id", "field_code"],
                {"entity_id": standard_entity.id, "field_code": field_key},
                {
                    "field_name": FIELD_NAMES[field_key],
                    "data_type": "number" if is_measure else "string",
                    "is_dimension": not is_measure,
                    "is_measure": is_measure,
                    "status": 0,
                },
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

        job = (
            await db.execute(select(MetaSyncJobModel).where(MetaSyncJobModel.name == SYNC_JOB_NAME))
        ).scalars().first()
        if job is None:
            job = MetaSyncJobModel(name=SYNC_JOB_NAME)
            db.add(job)
        job.source_system_id = system.id
        job.source_object_id = source_object.id
        job.standard_entity_id = standard_entity.id
        job.org_code = ORG_CODE
        job.cron_expr = SYNC_CRON
        job.request_params = REQUEST_PARAMS
        job.variables = []
        job.sync_mode = "full"
        job.status = 0
        job.description = DESCRIPTION
        await db.flush()
        job_id = job.id

        print(f"金蝶连接 id={connection.id}")
        print(f"来源系统 id={system.id} code={system.code}")
        print(f"来源对象 id={source_object.id} code={source_object.code}（FormId={FORM_ID}）")
        print(f"标准实体 id={standard_entity.id} code={standard_entity.code} 字段 {len(FIELD_KEYS)} 个")
        print(f"同步任务 id={job_id} name={job.name} cron={job.cron_expr} org={job.org_code}")

    job = await _load_job(job_id)
    if job is not None:
        register_meta_sync_job(job)
    await async_engine.dispose()
    print("存货收发存汇总表（全仓·全物料）数据源初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


ROLLBACK_STATEMENTS: list[tuple[str, str]] = [
    ("meta_sync_run", "delete from meta_sync_run where job_id in (select id from meta_sync_job where name = %s)"),
    ("meta_sync_job", "delete from meta_sync_job where name = %s"),
    (
        "meta_field_mapping",
        "delete from meta_field_mapping where source_object_id in "
        "(select id from meta_source_object where code = %s)",
    ),
    (
        "meta_source_field",
        "delete from meta_source_field where object_id in "
        "(select id from meta_source_object where code = %s)",
    ),
    (
        "meta_standard_field",
        "delete from meta_standard_field where entity_id in "
        "(select id from meta_standard_entity where code = %s)",
    ),
    ("meta_standard_entity", "delete from meta_standard_entity where code = %s"),
    ("meta_source_object", "delete from meta_source_object where code = %s"),
]


def rollback_key(table: str) -> str:
    """回滚语句的匹配键：同步任务按任务名，来源侧按数据源 code，标准侧按实体 code。"""
    if table.startswith("meta_sync"):
        return SYNC_JOB_NAME
    if table in {"meta_field_mapping", "meta_source_field", "meta_source_object"}:
        return SOURCE_OBJECT_CODE
    return STANDARD_ENTITY_CODE


def rollback(db_name: str) -> int:
    """删除本脚本创建/维护的元数据行（幂等），返回删除总行数。"""
    import pymysql

    env = load_env_file(ENV_PATH)
    connection = pymysql.connect(
        host=env.get("DATABASE_HOST", "localhost"),
        port=int(env.get("DATABASE_PORT", "3306")),
        user=env.get("DATABASE_USER", "root"),
        password=env.get("DATABASE_PASSWORD", ""),
        database=db_name,
        charset="utf8mb4",
        autocommit=False,
    )
    total = 0
    try:
        with connection.cursor() as cursor:
            for table, statement in ROLLBACK_STATEMENTS:
                cursor.execute(statement, (rollback_key(table),))
                affected = cursor.rowcount
                total += max(affected, 0)
                print(f"{table}: 删除 {affected} 行")
        connection.commit()
    finally:
        connection.close()
    print(f"回滚完成（库 {db_name}），共删除 {total} 行")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="接入金蝶《存货收发存汇总表》（全仓·全物料）")
    parser.add_argument("--rollback", action="store_true", help="删除本脚本创建的元数据（幂等）")
    parser.add_argument(
        "--db-name",
        default="",
        help="回滚目标库名（缺省取 env/.env.dev 的 DATABASE_NAME，用于在副本库上验证回滚）",
    )
    args = parser.parse_args()

    if args.rollback:
        db_name = args.db_name or load_env_file(ENV_PATH).get("DATABASE_NAME", "fastapiadmin")
        rollback(db_name)
        return
    asyncio.run(setup())


if __name__ == "__main__":
    main()
