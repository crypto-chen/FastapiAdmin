"""清理服务器本地 autogen 迁移分支，恢复单 head（默认只预演）。

背景：服务器 dev 启动时会自动生成迁移，历史上留下了大量未跟踪的
``backend/app/alembic/versions/*.py``，导致 ``alembic_version`` 出现两个 head
（例如 ``232a54eb51ca`` + ``wecomtoken01``），升级时会跑一条无关的慢 ALTER。

本脚本只做两件事：
1. 把 ``git status`` 里未跟踪的迁移文件移到备份目录（不删除）；
2. 从 ``alembic_version`` 删除除 ``wecomtoken01`` 之外的版本行。

用法（项目根目录，默认只打印计划）：

    python deploy/wecom-opcenter-20261112/cleanup_server_autogen.py
    python deploy/wecom-opcenter-20261112/cleanup_server_autogen.py --apply
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

os.environ.setdefault("ENVIRONMENT", "dev")

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
VERSIONS = BACKEND / "app" / "alembic" / "versions"
BACKUP = BACKEND / "app" / "alembic" / f"versions_server_autogen_backup_{datetime.now():%Y%m%d_%H%M%S}"
KEEP_REV = "wecomtoken01"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def git_untracked_versions() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", "backend/app/alembic/versions"],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    files: list[Path] = []
    for line in result.stdout.splitlines():
        if not line.startswith("?? "):
            continue
        path = (ROOT / line[3:].strip()).resolve()
        if path.is_file() and VERSIONS.resolve() in path.parents:
            files.append(path)
    return files


def alembic_output(*args: str) -> tuple[int, str]:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    return result.returncode, (result.stdout or "") + (result.stderr or "")


def heads(output: str) -> set[str]:
    return {
        match.group(1)
        for line in output.splitlines()
        if (match := re.match(r"^([0-9a-zA-Z_]+) \(head\)$", line.strip()))
    }


def db_versions() -> list[str]:
    import pymysql

    from app.config.setting import settings

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
            cur.execute("SELECT version_num FROM alembic_version")
            return [str(row[0]) for row in cur.fetchall()]
    finally:
        conn.close()


def delete_extra_versions(keep: str) -> None:
    import pymysql

    from app.config.setting import settings

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
            cur.execute("DELETE FROM alembic_version WHERE version_num <> %s", (keep,))
            if cur.rowcount == 0:
                cur.execute("INSERT INTO alembic_version (version_num) VALUES (%s)", (keep,))
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="清理服务器本地 autogen 迁移分支")
    parser.add_argument("--apply", action="store_true", help="执行；缺省只预演")
    args = parser.parse_args()

    files = git_untracked_versions()
    versions = db_versions()
    code, head_output = alembic_output("heads")

    print(f"项目根目录: {ROOT}")
    print(f"未跟踪迁移文件: {len(files)} 个")
    for path in files:
        print("  move:", path.relative_to(ROOT))
    print("alembic_version:", versions)
    print("alembic heads:", head_output.strip() or f"(exit {code})")

    if KEEP_REV not in versions:
        raise SystemExit(f"数据库 alembic_version 里没有 {KEEP_REV}，停止")

    if not args.apply:
        print("\n预演完成；确认无误后加 --apply。")
        return

    BACKUP.mkdir(parents=True, exist_ok=True)
    moved: list[tuple[Path, Path]] = []
    try:
        for path in files:
            destination = BACKUP / path.name
            if destination.exists():
                destination = BACKUP / f"{path.stem}_{datetime.now():%H%M%S}{path.suffix}"
            shutil.move(str(path), str(destination))
            moved.append((path, destination))

        code, head_output = alembic_output("heads")
        remaining = heads(head_output)
        if code != 0 or remaining != {KEEP_REV}:
            raise RuntimeError(
                f"移动后 heads 不是单一 {KEEP_REV}：exit={code} heads={sorted(remaining)}"
            )

        delete_extra_versions(KEEP_REV)
        print(f"已移动 {len(moved)} 个文件到 {BACKUP}")
        print("已清理 alembic_version，只保留", KEEP_REV)
        for args_ in ("current", "heads"):
            code, output = alembic_output(args_)
            print(f"alembic {args_} (exit={code}):")
            print(output.strip())
    except Exception:
        for source, destination in reversed(moved):
            if destination.exists() and not source.exists():
                shutil.move(str(destination), str(source))
        raise


if __name__ == "__main__":
    main()
