"""指标口径版本上线更新（conda Python，不使用 Docker）。

服务器项目根目录执行：

    python deploy/metric-rule-version-20261113/update.py
    python deploy/metric-rule-version-20261113/update.py --apply --service fastapiadmin

默认只预演，不执行任何命令。`--apply` 才会拉代码、跑迁移、跑校验、重启服务。

本版本新增：
- metric_def_version：指标定义按生效期保存快照；
- metric_period_version：每月钉住历史口径与当前生效口径；
- metric_run.rule_mode：重算记录 historical / current；
- 指标重算接口与前端支持选择历史规则或当前规则。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
WEB = ROOT / "frontend" / "web"
LOG_PATH = Path(__file__).resolve().parent / "update_run.log"
MIGRATION_HEAD = "metricrule01"

VERIFY_CODE = r"""
import asyncio
from sqlalchemy import inspect
from app.core.database import async_engine

async def main():
    async with async_engine.connect() as conn:
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        cols = await conn.run_sync(
            lambda c: {item["name"] for item in inspect(c).get_columns("metric_run")}
        )
        ok = {"metric_def_version", "metric_period_version"} <= tables and "rule_mode" in cols
        print("SCHEMA_OK" if ok else "SCHEMA_FAIL")

asyncio.run(main())
"""


def python_bin() -> str:
    """优先项目 venv（本机），否则当前解释器（服务器 conda）。"""
    for candidate in (
        BACKEND / ".venv" / "Scripts" / "python.exe",
        BACKEND / ".venv" / "bin" / "python",
    ):
        if candidate.exists():
            return str(candidate)
    return sys.executable


def log(message: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(line.encode(encoding, "replace").decode(encoding, "replace"))
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(
    cmd: list[str],
    cwd: Path,
    apply: bool,
    *,
    env_extra: dict[str, str] | None = None,
    required: bool = True,
    title: str | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str] | None:
    if title:
        log(f"== {title} ==")
    log("$ " + " ".join(str(item) for item in cmd))
    if not apply:
        return None
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=bool(capture),
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if capture and result.stdout:
        log(result.stdout.strip())
    if capture and result.stderr:
        log(result.stderr.strip())
    if result.returncode != 0:
        message = f"命令失败（退出码 {result.returncode}）：{' '.join(cmd)}"
        if required:
            raise SystemExit(message)
        log("WARN " + message)
    return result


def git_text(args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} 失败：{result.stderr.strip()}")
    return result.stdout.strip()


def preflight(apply: bool, pull: bool, branch: str) -> None:
    current = git_text(["branch", "--show-current"])
    log(f"当前分支：{current or '(detached)'}；目标分支：{branch}")
    if current and current != branch:
        raise SystemExit(f"当前分支是 {current}，请先切到 {branch}")
    if pull:
        dirty = git_text(["status", "--porcelain", "--untracked-files=no"])
        if dirty:
            log("检测到未提交的已跟踪改动：")
            log(dirty)
            if apply:
                raise SystemExit("服务器工作区不干净，先提交/还原再更新")


def sync_code(apply: bool, branch: str) -> None:
    run(["git", "fetch", "origin", branch], ROOT, apply, title="拉取代码")
    run(["git", "merge", "--ff-only", f"origin/{branch}"], ROOT, apply, title="快进合并")


def migrate(apply: bool, env_name: str | None) -> None:
    env_extra = {"ENVIRONMENT": env_name} if env_name else None
    run(
        [python_bin(), "-m", "alembic", "upgrade", "heads"],
        BACKEND,
        apply,
        env_extra=env_extra,
        title="执行数据库迁移",
    )
    result = run(
        [python_bin(), "-c", VERIFY_CODE],
        BACKEND,
        apply,
        env_extra=env_extra,
        title="校验新表与字段",
        capture=True,
    )
    if apply and result is not None and "SCHEMA_OK" not in (result.stdout or ""):
        raise SystemExit("迁移后校验失败：缺少 metric_def_version / metric_period_version / rule_mode")


def build_frontend(apply: bool) -> None:
    if not (WEB / "node_modules").exists():
        raise SystemExit(f"前端依赖不存在：{WEB / 'node_modules'}，先执行 pnpm install")
    run(["pnpm", "build:prod"], WEB, apply, title="构建前端")


def verify(apply: bool, env_name: str | None) -> None:
    env_extra = {"ENVIRONMENT": env_name} if env_name else None
    run(
        [python_bin(), "-m", "pytest", "tests/test_metric_rule_version.py", "-q"],
        BACKEND,
        apply,
        env_extra=env_extra,
        title="校验口径版本逻辑",
    )


def restart(apply: bool, service: str | None) -> None:
    if not service:
        log("未指定 --service，跳过服务重启；新增调度任务需自行重启后端")
        return
    if os.name == "nt":
        log("Windows 本机跳过 systemctl restart")
        return
    run(["systemctl", "restart", service], ROOT, apply, title=f"重启服务 {service}")


def main() -> None:
    parser = argparse.ArgumentParser(description="指标口径版本服务器更新")
    parser.add_argument("--apply", action="store_true", help="实际执行；默认只预演")
    parser.add_argument("--branch", default="master", help="目标分支，默认 master")
    parser.add_argument("--env", default=None, help="ENVIRONMENT，如 dev / prod；缺省沿用服务器配置")
    parser.add_argument("--service", default=None, help="systemd 服务名，如 fastapiadmin")
    parser.add_argument("--skip-pull", action="store_true", help="跳过 git fetch/merge")
    parser.add_argument("--skip-tests", action="store_true", help="跳过 pytest 校验")
    parser.add_argument("--build-frontend", action="store_true", help="在服务器执行 pnpm build:prod")
    args = parser.parse_args()

    log("=" * 60)
    log("指标口径版本更新开始" + ("" if args.apply else "（预演）"))
    preflight(args.apply, not args.skip_pull, args.branch)
    if not args.skip_pull:
        sync_code(args.apply, args.branch)
    migrate(args.apply, args.env)
    if args.build_frontend:
        build_frontend(args.apply)
    else:
        log("前端源码有改动；服务器页面需更新时，加 --build-frontend 或上传 frontend/web/dist")
    if not args.skip_tests:
        verify(args.apply, args.env)
    restart(args.apply, args.service)
    log(f"完成；迁移版本 {MIGRATION_HEAD}")
    if not args.apply:
        log("以上为预演。确认无误后追加 --apply 再执行。")


if __name__ == "__main__":
    main()
