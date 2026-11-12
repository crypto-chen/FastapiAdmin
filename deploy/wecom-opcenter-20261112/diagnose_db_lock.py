"""诊断迁移卡住：MySQL 长事务 / 元数据锁 / 当前 Alembic 版本。

在迁移卡住时另开一个终端执行（项目根目录）：

    python deploy/wecom-opcenter-20261112/diagnose_db_lock.py

重点看：
- State 含 Waiting for table metadata lock 的会话（Info 是等待的 ALTER）
- innodb_trx 里 trx_started 很早、trx_mysql_thread_id 对应的连接
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "dev")

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import pymysql  # noqa: E402, I001

from app.config.setting import settings  # noqa: E402


def main() -> None:
    print(
        "db=",
        settings.DATABASE_HOST,
        settings.DATABASE_PORT,
        settings.DATABASE_NAME,
        "type=",
        settings.DATABASE_TYPE,
    )
    conn = pymysql.connect(
        host=settings.DATABASE_HOST,
        port=int(settings.DATABASE_PORT),
        user=settings.DATABASE_USER,
        password=settings.DATABASE_PASSWORD,
        database=settings.DATABASE_NAME,
        charset="utf8mb4",
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
        autocommit=True,
    )
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), DATABASE(), NOW()")
            print("server:", cur.fetchone())

            cur.execute("SELECT version_num FROM alembic_version")
            print("alembic_version:", cur.fetchall())

            cur.execute("SHOW FULL PROCESSLIST")
            columns = [item[0] for item in cur.description]
            print("--- processlist ---")
            for row in cur.fetchall():
                item = dict(zip(columns, row))
                info = str(item.get("Info") or "").replace("\n", " ")[:180]
                print(
                    f"id={item.get('Id')} user={item.get('User')} db={item.get('db')} "
                    f"command={item.get('Command')} time={item.get('Time')} "
                    f"state={item.get('State')} info={info}"
                )

            print("--- innodb_trx (long transactions) ---")
            try:
                cur.execute(
                    "SELECT trx_id, trx_state, trx_started, "
                    "trx_mysql_thread_id, trx_query "
                    "FROM information_schema.innodb_trx ORDER BY trx_started"
                )
                for row in cur.fetchall():
                    print(row)
            except Exception as exc:  # noqa: BLE001
                print("innodb_trx unavailable:", exc)

            print("--- metadata_locks ---")
            try:
                cur.execute(
                    "SELECT OBJECT_TYPE, OBJECT_SCHEMA, OBJECT_NAME, "
                    "LOCK_TYPE, LOCK_STATUS, "
                    "OWNER_THREAD_ID FROM performance_schema.metadata_locks "
                    "WHERE OBJECT_NAME IN "
                    "('platform_metric_def','alembic_version','erp_wecom_connection',"
                    "'wecom_checkin_day','wecom_sync_run')"
                )
                for row in cur.fetchall():
                    print(row)
            except Exception as exc:  # noqa: BLE001
                print("metadata_locks unavailable:", exc)

            print("--- platform_metric_def indexes ---")
            try:
                cur.execute("SHOW INDEX FROM platform_metric_def")
                for row in cur.fetchall():
                    print(
                        "index:", row[2],
                        "column:", row[4],
                        "unique:", not bool(row[1]),
                    )
            except Exception as exc:  # noqa: BLE001
                print("indexes unavailable:", exc)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
