"""把业务员指标（定义 + 元数据 + 可选结果）导出成可在服务器直接执行的 SQL。

适用场景：服务器不方便跑 seed 脚本，只想在数据库客户端里执行 SQL 时使用。

    cd backend
    python scripts/export_person_metrics_sql.py                 # 生成表结构 + 指标定义
    python scripts/export_person_metrics_sql.py --with-values    # 额外导出结果快照（临时方案）

生成到仓库根目录 ``deploy/person-metrics/``：

- ``01_schema.sql``：`metric_value.person_code/person_name`、`open_client.allow_person_detail`
  （用 information_schema 做过存在性判断，重复执行安全）
- ``02_defs.sql``：CRM 连接 / 来源系统 / 6 个来源对象 / 6 个同步任务 / 16 个指标定义 / 对接权限开关
  （全部幂等，可重复执行）
- ``03_values.sql``：【可选】当前已算出的业务员指标结果快照（临时让接口有数，回补脚本跑完会被新版本覆盖）

> 注意：**代码仍然必须部署**（取数引擎、开放接口 `level=person`、CRM 客户端修复都在 Python 里），
> SQL 只解决「表结构 + 指标定义 + 同步任务 + 权限」这几块数据。
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.base_model import MappedBase  # noqa: E402
from app.core.database import async_db_session, async_engine  # noqa: E402
from app.modules.metadata.model import (  # noqa: E402
    MetaSyncJobModel,
    SourceObjectModel,
    SourceSystemModel,
)
from app.modules.metric.model import MetricDefModel, MetricValueModel  # noqa: E402
from app.utils.import_util import ImportUtil  # noqa: E402

ImportUtil.find_models(MappedBase)

OUTPUT_DIR = PROJECT_ROOT.parent / "deploy" / "person-metrics"
PERSON_CATEGORY = "营销中心-业务员"
SYSTEM_CODE = "crm"
CONNECTION_NAME = "CRM 默认连接"
JOB_PREFIX = "CRM业务员指标-"


def sql_text(value) -> str:
    """字符串字面量（MySQL：反斜杠与单引号都要转义）。"""
    if value is None:
        return "NULL"
    text = str(value).replace("\\", "\\\\").replace("'", "''")
    return f"'{text}'"


def sql_json(value) -> str:
    if value is None:
        return "NULL"
    return sql_text(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def sql_dt(value) -> str:
    if value is None:
        return "NULL"
    return sql_text(value.strftime("%Y-%m-%d %H:%M:%S"))


def _header(title: str, notes: list[str]) -> list[str]:
    lines = [
        "-- " + "=" * 74,
        f"-- {title}",
        f"-- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "-- 由 backend/scripts/export_person_metrics_sql.py 生成，请勿手工修改",
    ]
    lines += [f"-- {note}" for note in notes]
    lines += ["-- " + "=" * 74, ""]
    return lines


def _guarded_add_column(table: str, column: str, definition: str) -> list[str]:
    """MySQL 8 不支持 ADD COLUMN IF NOT EXISTS：用 information_schema + 动态 SQL 兜住重复执行。"""
    # 动态 SQL 本身是一个字符串字面量：里面的单引号（如 COMMENT '...'）必须再转义一层
    escaped = definition.replace("'", "''")
    return [
        f"-- {table}.{column}",
        (
            "SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS "
            f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}' AND COLUMN_NAME = '{column}') = 0,"
        ),
        f"  'ALTER TABLE {table} ADD COLUMN {escaped}',",
        f"  'SELECT ''跳过：{table}.{column} 已存在'' AS note');",
        "PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;",
        "",
    ]


def _guarded_add_index(table: str, index: str, columns: str) -> list[str]:
    return [
        f"-- {table} 索引 {index}",
        (
            "SET @ddl := IF((SELECT COUNT(*) FROM information_schema.STATISTICS "
            f"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '{table}' AND INDEX_NAME = '{index}') = 0,"
        ),
        f"  'CREATE INDEX {index} ON {table} ({columns})',",
        f"  'SELECT ''跳过：索引 {index} 已存在'' AS note');",
        "PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;",
        "",
    ]


def render_schema() -> str:
    lines = _header(
        "业务员指标 - 表结构变更（可在数据库客户端直接执行，重复执行安全）",
        [
            "对应 alembic 迁移：203324073db9（metric_value 业务员列）、d81f6c2a7e35 / cd6a5655eba2（open_client 权限）",
            "推荐先用后端自带迁移：docker compose exec backend python main.py upgrade --env=prod",
            "若走本脚本，请在本文件执行完后按文末提示把 alembic_version 对齐",
        ],
    )
    lines += ["SET NAMES utf8mb4;", ""]
    lines += _guarded_add_column(
        "metric_value", "person_code", "person_code VARCHAR(64) NULL COMMENT '业务员编码(来源原始，未映射也保留)'"
    )
    lines += _guarded_add_column(
        "metric_value", "person_name", "person_name VARCHAR(255) NULL COMMENT '业务员姓名(来源原始)'"
    )
    lines += _guarded_add_index("metric_value", "ix_metric_value_person_code", "person_code")
    lines += _guarded_add_column(
        "open_client",
        "allow_person_detail",
        "allow_person_detail TINYINT(1) NOT NULL DEFAULT 0 COMMENT '是否允许查询业务员明细(默认不开放)'",
    )
    lines += [
        "-- " + "-" * 74,
        "-- 执行完上面语句后，让 alembic 版本与库状态一致（避免下次启动再重复加列）",
        "-- 选项 1（推荐）：改用后端迁移命令，本文件只作为检查参考：",
        "--     docker compose exec backend python main.py upgrade --env=prod",
        "-- 选项 2：手工对齐（仅当你确认服务器 alembic 已包含 b7c1d9e4f2a0 之前的全部迁移）：",
        "--     SELECT version_num FROM alembic_version;",
        "--     UPDATE alembic_version SET version_num = 'cd6a5655eba2';",
        "",
        "-- 客户端执行结果核对：应分别返回 person_code / person_name / allow_person_detail",
        "SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS",
        "WHERE TABLE_SCHEMA = DATABASE()",
        "  AND ((TABLE_NAME = 'metric_value' AND COLUMN_NAME IN ('person_code','person_name'))",
        "    OR (TABLE_NAME = 'open_client' AND COLUMN_NAME = 'allow_person_detail'));",
    ]
    return "\n".join(lines) + "\n"


def _connection_insert(row) -> list[str]:
    return [
        "-- 1) CRM 连接（服务器已存在同名连接时跳过；指标沿用系统里已有的 CRM 连接）",
        "INSERT INTO crm_connection",
        "  (uuid, name, base_url, timeout, status, description, is_deleted, created_time, updated_time)",
        "SELECT "
        + ", ".join(
            [
                sql_text(row.uuid),
                sql_text(row.name),
                sql_text(row.base_url),
                str(int(row.timeout or 30)),
                str(int(row.status or 0)),
                sql_text(row.description),
                "0",
                "NOW()",
                "NOW()",
            ]
        ),
        "FROM DUAL",
        f"WHERE NOT EXISTS (SELECT 1 FROM crm_connection WHERE name = {sql_text(row.name)});",
        "",
    ]


def _system_insert(row) -> list[str]:
    return [
        "-- 2) 来源系统 CRM（按 code 幂等）",
        "INSERT INTO meta_source_system",
        "  (uuid, code, name, connector_type, connection_id, status, description, is_deleted, created_time, updated_time)",
        "VALUES ("
        + ", ".join(
            [
                sql_text(row.uuid),
                sql_text(row.code),
                sql_text(row.name),
                sql_text(row.connector_type),
                f"(SELECT id FROM crm_connection WHERE name = {sql_text(CONNECTION_NAME)} LIMIT 1)",
                str(int(row.status or 0)),
                sql_text(row.description),
                "0",
                "NOW()",
                "NOW()",
            ]
        )
        + ")",
        "ON DUPLICATE KEY UPDATE name = VALUES(name), connector_type = VALUES(connector_type),",
        "  connection_id = VALUES(connection_id), status = VALUES(status), description = VALUES(description);",
        "",
    ]


def _object_insert(row) -> list[str]:
    return [
        f"-- 来源对象 {row.code}",
        "INSERT INTO meta_source_object",
        "  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)",
        "VALUES ("
        + ", ".join(
            [
                sql_text(row.uuid),
                f"(SELECT id FROM meta_source_system WHERE code = {sql_text(SYSTEM_CODE)} LIMIT 1)",
                sql_text(row.code),
                sql_text(row.name),
                sql_text(row.query_type),
                sql_json(row.request_template),
                sql_json(row.variables),
                sql_text(row.watermark_field),
                str(int(row.status or 0)),
                "0",
                "NOW()",
                "NOW()",
            ]
        )
        + ")",
        "ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),",
        "  request_template = VALUES(request_template), status = VALUES(status);",
        "",
    ]


def _job_insert(row) -> list[str]:
    return [
        f"-- 同步任务 {row.name}（cron {row.cron_expr}）",
        "INSERT INTO meta_sync_job",
        "  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,",
        "   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)",
        "SELECT "
        + ", ".join(
            [
                sql_text(row.uuid),
                sql_text(row.name),
                f"(SELECT id FROM meta_source_system WHERE code = {sql_text(SYSTEM_CODE)} LIMIT 1)",
                "(SELECT o.id FROM meta_source_object o WHERE o.code = "
                f"{sql_text((row.request_params or {}).get('__object_code__') or row._object_code)} LIMIT 1)",
                "NULL",
                "NULL",
                sql_text(row.cron_expr),
                sql_json(row.request_params),
                sql_json(row.variables),
                sql_text(row.sync_mode),
                sql_text(row.watermark_field),
                str(int(row.status or 0)),
                sql_text(row.description),
                "0",
                "NOW()",
                "NOW()",
            ]
        ),
        "FROM DUAL",
        f"WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = {sql_text(row.name)});",
        "",
    ]


def _metric_insert(row) -> list[str]:
    return [
        f"-- 指标 {row.excel_code or '-'} {row.code}",
        "INSERT INTO metric_def",
        "  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,",
        "   source_entity_id, version, status, description, is_deleted, created_time, updated_time)",
        "VALUES ("
        + ", ".join(
            [
                sql_text(row.uuid),
                sql_text(row.code),
                sql_text(row.name),
                sql_text(row.category),
                sql_text(row.excel_code),
                sql_text(row.period_type),
                str(int(row.sensitivity or 0)),
                sql_text(row.formula),
                sql_json(row.dimensions),
                sql_json(row.measures),
                "NULL",
                str(int(row.version or 1)),
                str(int(row.status or 0)),
                sql_text(row.description),
                "0",
                "NOW()",
                "NOW()",
            ]
        )
        + ")",
        "ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),",
        "  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),",
        "  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),",
        "  description = VALUES(description), version = VALUES(version);",
        "",
    ]


async def _load():
    from app.modules.crm.model import CrmConnectionModel

    async with async_db_session() as db:
        connection = (
            await db.execute(select(CrmConnectionModel).where(CrmConnectionModel.name == CONNECTION_NAME))
        ).scalars().first()
        system = (
            await db.execute(select(SourceSystemModel).where(SourceSystemModel.code == SYSTEM_CODE))
        ).scalars().first()
        jobs = (
            await db.execute(
                select(MetaSyncJobModel)
                .where(MetaSyncJobModel.name.like(f"{JOB_PREFIX}%"))
                .order_by(MetaSyncJobModel.id)
            )
        ).scalars().all()
        # 只导出业务员指标用到的来源对象（按同步任务反查），避免把 CRM 其它来源对象一起导出
        object_ids = sorted({int(job.source_object_id) for job in jobs})
        objects = (
            await db.execute(
                select(SourceObjectModel).where(SourceObjectModel.id.in_(object_ids)).order_by(SourceObjectModel.id)
            )
        ).scalars().all() if object_ids else []
        object_name_by_id = {int(item.id): str(item.code) for item in objects}
        metrics = (
            await db.execute(
                select(MetricDefModel)
                .where(MetricDefModel.category == PERSON_CATEGORY)
                .order_by(MetricDefModel.excel_code, MetricDefModel.id)
            )
        ).scalars().all()
        metric_ids = [int(item.id) for item in metrics]
        values = (
            await db.execute(
                select(MetricValueModel).where(MetricValueModel.metric_id.in_(metric_ids)).order_by(MetricValueModel.id)
            )
        ).scalars().all() if metric_ids else []
        for job in jobs:
            job._object_code = object_name_by_id.get(int(job.source_object_id), "")
        return connection, system, objects, jobs, metrics, values


async def main() -> None:
    parser = argparse.ArgumentParser(description="导出业务员指标的 SQL 脚本")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="输出目录")
    parser.add_argument("--with-values", action="store_true", help="同时导出已算出的结果快照（临时方案）")
    args = parser.parse_args()

    connection, system, objects, jobs, metrics, values = await _load()
    if connection is None or system is None or not metrics:
        raise SystemExit("开发库里没有找到 CRM 连接 / 来源系统 / 业务员指标（先跑 seed_crm_person_metrics.py）")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "01_schema.sql").write_text(render_schema(), encoding="utf-8")

    lines = _header(
        "业务员指标 - 元数据 / 来源对象 / 同步任务 / 指标定义（幂等，可重复执行）",
        [
            f"指标 {len(metrics)} 个，来源对象 {len(objects)} 个，同步任务 {len(jobs)} 个",
            "执行顺序：先 01_schema.sql，再本文件",
            "所有 INSERT 均按业务唯一键判重：连接按 name、来源系统/对象/指标按 code、同步任务按 name",
        ],
    )
    lines += ["SET NAMES utf8mb4;", "", "-- 0) 确认目标库", "SELECT DATABASE() AS current_db;", ""]
    lines += _connection_insert(connection)
    lines += _system_insert(system)
    lines += ["-- 3) 来源对象（业务员指标用到的 6 个 CRM 接口）", ""]
    for item in objects:
        lines += _object_insert(item)
    lines += ["-- 4) 同步任务（cron 与 seed 脚本一致：明细每天 02:00，客户列表每周一 02:00）", ""]
    for item in jobs:
        lines += _job_insert(item)
    lines += ["-- 5) 指标定义（16 个业务员指标，含 Excel 科目编码与取数配置）", ""]
    for item in metrics:
        lines += _metric_insert(item)
    lines += [
        "-- 6) 给对接方开「业务员明细」权限（把 app_id 换成实际值后取消注释执行）",
        f"-- UPDATE open_client SET allow_person_detail = 1 WHERE app_id = {sql_text('<对接方app_id>')};",
        "",
        "-- 7) 执行结果核对（指标应 16 行、同步任务应 6 行）",
        "SELECT COUNT(*) AS person_metric_count FROM metric_def WHERE category = '营销中心-业务员';",
        "SELECT id, name, cron_expr, status FROM meta_sync_job WHERE name LIKE 'CRM业务员指标%';",
        "SELECT code, name, excel_code FROM metric_def WHERE category = '营销中心-业务员' ORDER BY excel_code;",
    ]
    (out_dir / "02_defs.sql").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if args.with_values:
        code_by_id = {int(item.id): str(item.code) for item in metrics}
        value_lines = _header(
            "业务员指标 - 结果快照（可选，临时方案）",
            [
                f"{len(values)} 行 metric_value（业务员指标全部期间）",
                "用途：让服务器接口立刻有数；跑过 backfill_person_metrics.py 后会被新的 calc_version 覆盖",
                "metric_id 用 code 子查询解析，避免与服务器自增 ID 冲突",
            ],
        )
        value_lines += ["SET NAMES utf8mb4;", ""]
        periods = sorted({str(row.period_value) for row in values})
        for period in periods:
            value_lines += [
                f"-- 清理 {period} 已有的业务员指标结果（保证本文件可重复执行；仅影响业务员分类的指标）",
                "DELETE v FROM metric_value v",
                "  JOIN metric_def d ON d.id = v.metric_id",
                f"  WHERE d.category = '{PERSON_CATEGORY}' AND v.period_value = {sql_text(period)};",
                "",
            ]
        for row in values:
            code = code_by_id.get(int(row.metric_id))
            if not code:
                continue
            value_lines += [
                "INSERT INTO metric_value",
                "  (uuid, metric_id, run_id, period_type, period_value, org_id, dept_id, dept_code, dept_name,",
                "   person_id, person_code, person_name, value, version, calc_version, batch_id, filter_signature,",
                "   calc_time, is_deleted, created_time, updated_time)",
                "VALUES ("
                + ", ".join(
                    [
                        sql_text(row.uuid),
                        f"(SELECT id FROM metric_def WHERE code = {sql_text(code)} LIMIT 1)",
                        "NULL",
                        sql_text(row.period_type),
                        sql_text(row.period_value),
                        str(row.org_id) if row.org_id is not None else "NULL",
                        str(row.dept_id) if row.dept_id is not None else "NULL",
                        sql_text(row.dept_code),
                        sql_text(row.dept_name),
                        str(row.person_id) if row.person_id is not None else "NULL",
                        sql_text(row.person_code),
                        sql_text(row.person_name),
                        f"{float(row.value or 0):.4f}",
                        str(int(row.version or 1)),
                        str(int(row.calc_version or 1)),
                        sql_text(row.batch_id),
                        sql_text(row.filter_signature),
                        sql_dt(row.calc_time),
                        "0",
                        "NOW()",
                        "NOW()",
                    ]
                )
                + ");",
            ]
        (out_dir / "03_values.sql").write_text("\n".join(value_lines) + "\n", encoding="utf-8")

    await async_engine.dispose()
    print(f"已生成 SQL 到 {out_dir}")
    for path in sorted(out_dir.glob("*.sql")):
        print(f"  - {path.name}（{path.stat().st_size / 1024:.1f} KB）")


if __name__ == "__main__":
    asyncio.run(main())
