"""离线校验零售推送迁移（无需连接业务库）。

在临时 SQLite 库上只创建旧版 ``open_client`` 表，然后单独执行
``retailpush01`` / ``f246...`` / ``retailshop01`` 的 upgrade/downgrade，确认：

- 三张零售表可建可删；
- ``open_client`` 两个新字段可加可删；
- downgrade 后回到旧结构。

用法::

    python scripts/check_retail_migration.py
"""

from __future__ import annotations

import importlib.util
import tempfile
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

MIGRATION_DIR = Path(__file__).resolve().parents[1] / "app" / "alembic" / "versions"
MIGRATION_PATHS = (
    MIGRATION_DIR / "2026_10_23_1200_retailpush01.py",
    MIGRATION_DIR / "2026_10_23_1146_f246db8af3ec.py",
    MIGRATION_DIR / "2026_10_27_1200_retailshop01.py",
)

OLD_OPEN_CLIENT = """
CREATE TABLE open_client (
    id INTEGER NOT NULL PRIMARY KEY,
    app_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    secret_hash VARCHAR(255) NOT NULL,
    status INTEGER NOT NULL DEFAULT 0,
    uuid VARCHAR(64) NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    created_time DATETIME NOT NULL,
    updated_time DATETIME NOT NULL,
    deleted_time DATETIME
)
"""


def _load_migration(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"无法加载迁移文件: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "retail_migration_check.db"
        engine = create_engine(f"sqlite:///{db_path}")
        migrations = [_load_migration(path, f"retailpush_migration_{index}") for index, path in enumerate(MIGRATION_PATHS)]
        with engine.begin() as connection:
            connection.execute(text(OLD_OPEN_CLIENT))
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                for migration in migrations:
                    migration.upgrade()

            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            expected_tables = {
                "retail_sync_batch",
                "retail_order",
                "retail_order_item",
                "retail_shop",
            }
            assert expected_tables <= tables, f"缺少表: {expected_tables - tables}"
            open_client_columns = {item["name"] for item in inspector.get_columns("open_client")}
            assert {"allow_retail_sync", "retail_sync_job_id"} <= open_client_columns
            allow_column = next(
                item for item in inspector.get_columns("open_client") if item["name"] == "allow_retail_sync"
            )
            assert allow_column["default"] is None, f"allow_retail_sync 仍保留默认值: {allow_column['default']}"
            order_indexes = {item["name"] for item in inspector.get_indexes("retail_order")}
            assert "ix_retail_order_period_shop" in order_indexes
            item_indexes = {item["name"] for item in inspector.get_indexes("retail_order_item")}
            assert "ix_retail_order_item_sku" in item_indexes
            shop_indexes = {item["name"] for item in inspector.get_indexes("retail_shop")}
            assert "ix_retail_shop_site" in shop_indexes
            print("UPGRADE OK: 4 tables + 2 open_client columns + indexes")

            with Operations.context(context):
                for migration in reversed(migrations):
                    migration.downgrade()

            inspector = inspect(connection)
            tables = set(inspector.get_table_names())
            assert not (expected_tables & tables), f"downgrade 后仍存在表: {expected_tables & tables}"
            open_client_columns = {item["name"] for item in inspector.get_columns("open_client")}
            assert not ({"allow_retail_sync", "retail_sync_job_id"} & open_client_columns)
            print("DOWNGRADE OK: retail tables and open_client columns removed")
        engine.dispose()


if __name__ == "__main__":
    main()
