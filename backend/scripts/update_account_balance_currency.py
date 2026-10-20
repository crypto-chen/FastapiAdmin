"""把科目余额表取数改为「综合本位币」口径（FCURRENCY=0）。

背景：原模板 ``FCURRENCY=1`` 只取人民币，美元等外币业务未纳入统计。
``FCURRENCY=-1`` 会按币别拆行并额外返回合计行，直接求和会翻倍；
``FCURRENCY=0`` 一次返回全部币种折算后的本位币金额（一维度一行），是本脚本采用的取值。

同时更新来源对象模板与全部同步任务（幂等）。

用法：
    python scripts/update_account_balance_currency.py
"""

import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import MetaSyncJobModel, SourceObjectModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

OBJECT_CODE = "GL_RPT_AccountBalance"
TARGET_CURRENCY = "0"


def patch_params(params: dict | None) -> tuple[dict, bool]:
    """把请求模板里的 Model.FCURRENCY 改为综合本位币，返回 (新参数, 是否有改动)。"""
    payload = dict(params or {})
    model = dict(payload.get("Model") or {})
    changed = str(model.get("FCURRENCY")) != TARGET_CURRENCY
    model["FCURRENCY"] = TARGET_CURRENCY
    payload["Model"] = model
    return payload, changed


async def main() -> None:
    async with async_db_session() as db, db.begin():
        source_object = (
            await db.execute(select(SourceObjectModel).where(SourceObjectModel.code == OBJECT_CODE))
        ).scalars().first()
        if source_object is None:
            raise SystemExit(f"来源对象不存在: {OBJECT_CODE}")

        source_object.request_template, template_changed = patch_params(source_object.request_template)
        jobs = (
            await db.execute(select(MetaSyncJobModel).where(MetaSyncJobModel.source_object_id == source_object.id))
        ).scalars().all()
        changed_jobs = 0
        for job in jobs:
            job.request_params, changed = patch_params(job.request_params)
            changed_jobs += int(changed)

        print(
            f"来源对象模板{'已更新' if template_changed else '无变化'}；"
            f"同步任务 {len(jobs)} 个，其中 {changed_jobs} 个改为 FCURRENCY={TARGET_CURRENCY}"
        )

    await async_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
