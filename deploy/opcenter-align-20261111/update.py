"""运营中心主表指标上线（conda Python，不使用 Docker）。

改动：
- 指标中心新增「运营中心指标 → 运营中心主表指标」菜单；
- 新增 17 个指标 OPC-COST-01 ~ 17；
- 取数：科目余额表 6601，核算维度部门按编码 BM000008 / BM000021 / BM000023 过滤；
- 费用项目关键字按 2026-11-11 新口径表。

服务器项目根目录执行：

    python deploy/opcenter-align-20261111/update.py --apply --env dev

只预演（默认，不执行任何命令）：

    python deploy/opcenter-align-20261111/update.py

可重复执行：指标定义/菜单均为幂等 upsert，重算按最新版本覆盖。
重算默认覆盖库里已有同步批次的全部期间；也可用 --period-from/--period-to 限定。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
LOG_PATH = Path(__file__).resolve().parent / "update_run.log"
CODE_FILE = "scripts/metric_groups/opcenter_cost.txt"


def python_bin() -> str:
    """优先用项目自带 venv（本机），否则用当前解释器（服务器 conda）。"""
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
    env_extra: dict[str, str] | None = None,
    required: bool = True,
    title: str | None = None,
) -> None:
    if title:
        log(f"== {title} ==")
    log("$ " + " ".join(str(item) for item in cmd))
    if not apply:
        return
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if result.stdout.strip():
        log(result.stdout.strip())
    if result.stderr.strip():
        log(result.stderr.strip())
    if result.returncode != 0:
        message = f"命令失败（退出码 {result.returncode}）：{' '.join(cmd)}"
        if required:
            raise SystemExit(message)
        log("WARN " + message)


def env_works(env_name: str) -> bool:
    """探测某个 ENVIRONMENT 能否加载到数据库密码（服务器可能只有 .env.dev）。"""
    code = (
        "from app.config.setting import settings;"
        "print('OK' if settings.DATABASE_PASSWORD else 'EMPTY')"
    )
    env = os.environ.copy()
    env["ENVIRONMENT"] = env_name
    result = subprocess.run(
        [python_bin(), "-c", code],
        cwd=BACKEND,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return result.returncode == 0 and bool(lines) and lines[-1] == "OK"


def sync_code(apply: bool) -> None:
    """fetch + 快进；分叉时直接报错，不覆盖服务器本地提交。"""
    run(["git", "fetch", "origin", "master"], ROOT, apply, title="拉取代码")
    run(["git", "merge", "--ff-only", "origin/master"], ROOT, apply, title="快进到 origin/master")


def main() -> None:
    parser = argparse.ArgumentParser(description="运营中心主表指标上线")
    parser.add_argument("--apply", action="store_true", help="执行；缺省只预演")
    parser.add_argument("--skip-pull", action="store_true", help="跳过 git pull")
    parser.add_argument("--skip-recalc", action="store_true", help="跳过指标重算")
    parser.add_argument("--env", default="dev", help="后端环境 dev/prod，默认 dev")
    parser.add_argument("--service", default=None, help="systemd 服务名，如 fastapiadmin")
    parser.add_argument("--period-from", default=None, help="重算起始期间，如 2026-01")
    parser.add_argument("--period-to", default=None, help="重算结束期间，如 2026-11")
    args = parser.parse_args()

    log(f"项目根目录：{ROOT}")
    log(f"模式：{'执行' if args.apply else '预演'}")

    if not args.skip_pull:
        sync_code(args.apply)

    # 优先用户指定的环境；探测不到时不强制 ENVIRONMENT，子进程沿用当前环境变量。
    candidates = list(dict.fromkeys([args.env, "dev", "prod"]))
    chosen_env = next((name for name in candidates if env_works(name)), None)
    if chosen_env:
        log(f"数据库环境：{chosen_env}")
        backend_env = {"ENVIRONMENT": chosen_env}
    else:
        log("未探测到可用的 ENVIRONMENT 配置，子进程沿用当前环境变量")
        backend_env = {}

    run(
        [python_bin(), "scripts/seed_opcenter_metrics.py"],
        BACKEND,
        args.apply,
        backend_env,
        title="写入 17 个指标定义（按部门编码）",
    )
    run(
        [python_bin(), "scripts/seed_opcenter_menu.py"],
        BACKEND,
        args.apply,
        backend_env,
        title="写入指标中心菜单与权限",
    )

    if not args.skip_recalc:
        cmd = [python_bin(), "scripts/recalc_metrics_batch.py", "--code-file", CODE_FILE]
        if args.period_from:
            cmd.extend(["--period-from", args.period_from])
        if args.period_to:
            cmd.extend(["--period-to", args.period_to])
        run(cmd, BACKEND, args.apply, backend_env, title="重算运营中心指标")

    if args.service and shutil.which("systemctl"):
        run(["systemctl", "restart", args.service], ROOT, args.apply, title="重启服务")
    elif args.service:
        log("未找到 systemctl（Windows 环境），跳过自动重启；请手动重启后端进程")
    else:
        log("未指定 --service，跳过重启；服务器请按现有方式重启后端进程")

    log("完成")


if __name__ == "__main__":
    main()
