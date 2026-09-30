"""初始化聚水潭「零售出库未税总金额」月度指标（连接 + 元数据 + 同步任务 + 指标定义）。

口径：销售出库查询（/open/orders/out/simple/query），**出库状态=已出库（Confirmed）**，
**按出库时间（date_type=2）**取整月单据，金额口径 ``order.pay_amount``（应付金额），
按 ``含税金额 / (1 + 税率)`` 折算未税；税率不填时未税=含税。

用法：
    python scripts/seed_jushuitan_metric.py --app-key xx --app-secret yy --access-token zz
    python scripts/seed_jushuitan_metric.py --tax-rate 13 --amount-source order.pay_amount

凭据也可用环境变量提供：JST_APP_KEY / JST_APP_SECRET / JST_ACCESS_TOKEN。
执行后：
    1) 每天 02:00 自动同步当月数据（cron ``0 0 2 * * ?``，与金蝶同步任务一致），
       02:30 由指标调度重算当月；每月 1 日再强制重拉上月并重算上月（月末最后一天的数据补齐）；
    2) 手动算指标：python scripts/run_metric_calc.py --code retail_outbound_untaxed_amount --period 2026-08
       （该指标不按组织拆分，不要传 --org）。
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.erp.jushuitan.model import JushuitanConnectionModel  # noqa: E402
from app.modules.erp.jushuitan.templates import MONTHLY_SALES_OUTBOUND_BIZ  # noqa: E402
from app.modules.metadata.model import (  # noqa: E402
    MetaSyncJobModel,
    SourceFieldModel,
    SourceObjectModel,
    SourceSystemModel,
    StandardEntityModel,
    StandardFieldModel,
)
from app.modules.metadata.sync import register_meta_sync_job  # noqa: E402
from app.modules.metric.model import MetricDefModel  # noqa: E402
from app.utils.crypto_util import CryptoUtil  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

SOURCE_OBJECT_CODE = "/open/orders/out/simple/query"
METRIC_CODE = "retail_outbound_untaxed_amount"

# 出库时间按月搜索：期间变量在取数时渲染（now = 期间首日 00:00），
# 历史期间回补时 now 会被替换成目标期间，而不是当前时间。
REQUEST_PARAMS = MONTHLY_SALES_OUTBOUND_BIZ

# 出库单字段（落库的来源字段，供元数据页面展示与后续映射）
SOURCE_FIELDS = [
    ("io_id", "出库单号", True),
    ("o_id", "内部单号", False),
    ("so_id", "线上单号", False),
    ("io_date", "出库时间", False),
    ("status", "单据状态", False),
    ("shop_id", "店铺编码", False),
    ("shop_name", "店铺名称", False),
    ("pay_amount", "应付金额(含税)", False),
    ("paid_amount", "支付金额", False),
    ("freight", "买家支付运费", False),
    ("wms_co_id", "分仓编号", False),
]


async def get_or_create(db, model, match: dict, defaults: dict | None = None):
    conditions = [getattr(model, key) == value for key, value in match.items()]
    obj = (await db.execute(select(model).where(*conditions))).scalars().first()
    if obj is None:
        obj = model(**{**(defaults or {}), **match})
        db.add(obj)
    else:
        for key, value in (defaults or {}).items():
            setattr(obj, key, value)
    await db.flush()
    return obj


async def main() -> None:
    parser = argparse.ArgumentParser(description="初始化聚水潭零售出库未税金额指标")
    parser.add_argument("--app-key", default=os.getenv("JST_APP_KEY", ""), help="开发者应用 app_key")
    parser.add_argument("--app-secret", default=os.getenv("JST_APP_SECRET", ""), help="开发者应用 app_secret")
    parser.add_argument("--access-token", default=os.getenv("JST_ACCESS_TOKEN", ""), help="商家授权 access_token")
    parser.add_argument("--name", default="聚水潭默认连接", help="连接名称")
    parser.add_argument("--base-url", default="https://openapi.jushuitan.com", help="接口地址")
    parser.add_argument("--shop-id", type=int, default=None, help="默认店铺编码")
    parser.add_argument("--offline", action="store_true", help="只取线下店铺单据")
    parser.add_argument("--amount-source", default="items.auto", help="取数口径（默认 items.auto 明细兜底）")
    parser.add_argument(
        "--auto-fields",
        default=None,
        help="items.auto 的兜底字段顺序，逗号分隔，如 seller_income_amount,buyer_paid_amount,sale_amount",
    )
    parser.add_argument("--tax-rate", type=float, default=0.0, help="税率(%%)，用于含税→未税折算")
    parser.add_argument("--by-shop", action="store_true", help="是否按店铺拆分结果")
    parser.add_argument("--cron", default="0 0 2 * * ?", help="同步 Cron（6 段，默认每天 02:00，早于指标调度的 02:30）")
    args = parser.parse_args()

    if not args.app_key or not args.app_secret or not args.access_token:
        raise SystemExit("请提供 --app-key/--app-secret/--access-token（或对应环境变量）")

    async with async_db_session() as db, db.begin():
        connection = (
            await db.execute(select(JushuitanConnectionModel).where(JushuitanConnectionModel.name == args.name))
        ).scalars().first()
        if connection is None:
            connection = JushuitanConnectionModel(
                name=args.name,
                base_url=args.base_url,
                app_key=args.app_key,
                app_secret=CryptoUtil.encrypt(args.app_secret),
                access_token=CryptoUtil.encrypt(args.access_token),
                shop_id=args.shop_id,
                is_offline_shop=1 if args.offline else 0,
                timeout=30,
                status=0,
            )
            db.add(connection)
            await db.flush()
        else:
            connection.base_url = args.base_url
            connection.app_key = args.app_key
            connection.app_secret = CryptoUtil.encrypt(args.app_secret)
            connection.access_token = CryptoUtil.encrypt(args.access_token)
            connection.shop_id = args.shop_id
            connection.is_offline_shop = 1 if args.offline else 0
            connection.status = 0

        system = await get_or_create(
            db,
            SourceSystemModel,
            {"code": "jushuitan"},
            {
                "name": "聚水潭",
                "connector_type": "jushuitan",
                "connection_id": connection.id,
                "status": 0,
                "description": "聚水潭开放平台（销售出库查询）",
            },
        )
        system.connection_id = connection.id
        system.connector_type = "jushuitan"

        source_object = await get_or_create(
            db,
            SourceObjectModel,
            {"system_id": system.id, "code": SOURCE_OBJECT_CODE},
            {
                "name": "销售出库单",
                "query_type": "api",
                "request_template": REQUEST_PARAMS,
                "watermark_field": "io_id",
                "status": 0,
            },
        )

        entity = await get_or_create(
            db,
            StandardEntityModel,
            {"code": "retail_outbound"},
            {"name": "零售出库单", "table_name": "dwd_retail_outbound", "status": 0},
        )

        for field_key, field_name, is_pk in SOURCE_FIELDS:
            await get_or_create(
                db,
                SourceFieldModel,
                {"object_id": source_object.id, "field_key": field_key},
                {
                    "field_name": field_name,
                    "data_type": "string",
                    "is_primary_key": is_pk,
                    "is_watermark": False,
                    "status": 0,
                },
            )
            await get_or_create(
                db,
                StandardFieldModel,
                {"entity_id": entity.id, "field_code": field_key},
                {
                    "field_name": field_name,
                    "data_type": "string",
                    "is_dimension": not field_key.endswith("amount"),
                    "is_measure": field_key.endswith("amount"),
                    "status": 0,
                },
            )

        job = (
            await db.execute(
                select(MetaSyncJobModel).where(MetaSyncJobModel.name == "聚水潭销售出库-按出库时间取数")
            )
        ).scalars().first()
        if job is None:
            job = MetaSyncJobModel(name="聚水潭销售出库-按出库时间取数")
            db.add(job)
        job.source_system_id = system.id
        job.source_object_id = source_object.id
        job.standard_entity_id = entity.id
        job.org_code = None
        job.cron_expr = args.cron
        job.request_params = REQUEST_PARAMS
        job.sync_mode = "full"
        job.status = 0
        job.description = "出库状态=已出库、按出库时间取整月单据（接口限制单段≤7天，客户端自动分段）"
        await db.flush()
        job_id = job.id

        metric = (
            await db.execute(select(MetricDefModel).where(MetricDefModel.code == METRIC_CODE))
        ).scalars().first()
        if metric is None:
            metric = MetricDefModel(code=METRIC_CODE)
            db.add(metric)
        metric.name = "零售出库未税总金额"
        metric.period_type = "month"
        metric.sensitivity = 0
        metric.source_entity_id = entity.id
        metric.dimensions = {"org": False, "shop": bool(args.by_shop)}
        metric.measures = {
            "kind": "sales_outbound_amount",
            "source_object_code": SOURCE_OBJECT_CODE,
            "amount_source": args.amount_source,
            "tax_rate": args.tax_rate,
            "tax_inclusive": True,
            "by_shop": bool(args.by_shop),
        }
        if args.auto_fields:
            metric.measures["auto_fields"] = [f.strip() for f in args.auto_fields.split(",") if f.strip()]
        metric.formula = (
            f"SUM({args.amount_source}) WHERE 出库状态=已出库(Confirmed) AND 出库时间∈期间"
            + (f" / (1 + {args.tax_rate}%)" if args.tax_rate else "")
        )
        metric.description = (
            "聚水潭销售出库查询（docId=34）：出库状态=已出库、按出库时间取整月单据，"
            f"金额口径 {args.amount_source}，未税 = 含税金额 / (1 + 税率)。"
        )
        metric.status = 0
        await db.flush()
        print(f"聚水潭连接 id={connection.id}，来源系统 id={system.id}，来源对象 id={source_object.id}，同步任务 id={job_id}")
        print(f"指标定义已就绪: id={metric.id} code={metric.code} name={metric.name}")

    job = await _load_job(job_id)
    if job is not None:
        register_meta_sync_job(job)
    await async_engine.dispose()
    print("聚水潭零售出库未税金额指标初始化完成")


async def _load_job(job_id: int) -> MetaSyncJobModel | None:
    async with async_db_session() as db:
        return await db.get(MetaSyncJobModel, job_id)


if __name__ == "__main__":
    asyncio.run(main())
