"""客户编码匹配改造上线（conda Python，不使用 Docker）。

改动：
- 订单 `customer_code`（旧批次回退 customer_number）→ 客户档案 `number` 匹配；
- 客户档案 `is_retail`（0 定制 / 1 零售）区分两套客户表，ID 重复不再误配；
- STF-47 总客户数量包含零售客户，STF-48 按客户编码去重；
- 重跑订单全链路、客户分析，并重算 STF-40/41/47/48 及下游 STF-49。

服务器项目根目录执行：

    python deploy/customer-code-20261031/update.py --apply --service fastapiadmin

只预演（默认，不执行任何命令）：

    python deploy/customer-code-20261031/update.py

可重复执行：同步/构建都会生成新版本，指标按最新版本覆盖。
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

PERIODS = ",".join(
    [f"2025-{m:02d}" for m in range(7, 13)]
    + [f"2026-{m:02d}" for m in range(1, 11)]
)

CUSTOMER_JOB = "CRM业务员指标-CRM 客户列表（业务员客户数）"
ORDER_JOBS = (
    "CRM业务员指标-CRM 订单明细（内贸）",
    "CRM业务员指标-CRM 订单明细（外贸）",
    "CRM业务员指标-CRM 订单明细（零售）",
)
METRIC_CODES = (
    "marketing_person_new_customer_intake_untaxed",
    "marketing_person_old_customer_intake_untaxed",
    "marketing_person_old_customer_order_count",
    "marketing_person_total_customer_count",
)


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
    """fetch + 快进；若服务器曾拉过被改写的提交导致分叉，工作区干净时自动 reset 到 origin/master。"""
    run(["git", "fetch", "origin", "master"], ROOT, apply, title="拉取代码")
    if not apply:
        return
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", "origin/master"],
        cwd=ROOT,
        capture_output=True,
    )
    if ancestor.returncode == 0:
        run(["git", "merge", "--ff-only", "origin/master"], ROOT, apply)
        return
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if (status.stdout or "").strip():
        raise SystemExit("本地有未提交的已跟踪修改，无法自动对齐 origin/master，请先处理")
    log("检测到本地提交与 origin/master 分叉，工作区干净 → git reset --hard origin/master")
    run(["git", "reset", "--hard", "origin/master"], ROOT, apply)


def main() -> None:
    parser = argparse.ArgumentParser(description="客户编码匹配改造上线")
    parser.add_argument("--apply", action="store_true", help="执行；缺省只预演")
    parser.add_argument("--skip-pull", action="store_true", help="跳过 git pull")
    parser.add_argument("--skip-sync", action="store_true", help="跳过 CRM 重新同步")
    parser.add_argument("--skip-build", action="store_true", help="跳过宽表重建")
    parser.add_argument("--env", default="prod", help="后端环境 dev/prod，默认 prod")
    parser.add_argument("--service", default=None, help="systemd 服务名，如 fastapiadmin")
    args = parser.parse_args()

    log(f"项目根目录：{ROOT}")
    log(f"模式：{'执行' if args.apply else '预演'}")
    log(f"期间：{PERIODS}")

    if not args.skip_pull:
        sync_code(args.apply)

    # 服务器可能没有 .env.prod（或密码为空）：按 prod → dev 探测，选第一个能读到密码的环境。
    # 都探测不到时不强制 ENVIRONMENT，子进程沿用服务器当前环境变量。
    chosen_env = next(
        (name for name in dict.fromkeys([args.env, "prod", "dev"]) if env_works(name)),
        None,
    )
    if chosen_env:
        log(f"数据库环境：{chosen_env}")
        backend_env = {"ENVIRONMENT": chosen_env}
    else:
        log("未探测到可用的 ENVIRONMENT 配置，子进程沿用当前环境变量")
        backend_env = {}

    run(
        [python_bin(), "scripts/seed_crm_person_metrics.py"],
        BACKEND,
        args.apply,
        backend_env,
        title="指标定义（客户编码匹配 + 零售客户计入 STF-47）",
    )

    if not args.skip_sync:
        run(
            [python_bin(), "scripts/run_meta_sync.py", "--name", CUSTOMER_JOB, "--period", "2026-10"],
            BACKEND,
            args.apply,
            backend_env,
            title="同步客户档案（含 is_retail）",
        )
        for job in ORDER_JOBS:
            run(
                [python_bin(), "scripts/run_meta_sync.py", "--name", job, "--period", PERIODS],
                BACKEND,
                args.apply,
                backend_env,
                title=f"同步订单明细：{job}",
            )

    if not args.skip_build:
        run(
            [python_bin(), "scripts/run_order_build.py", "--period", PERIODS],
            BACKEND,
            args.apply,
            backend_env,
            title="重建订单全链路",
        )
        run(
            [python_bin(), "scripts/run_customer_build.py", "--period", PERIODS],
            BACKEND,
            args.apply,
            backend_env,
            title="重建客户分析",
        )

    cmd = [
        python_bin(),
        "scripts/recalc_metrics_batch.py",
        "--with-dependents",
        "--period-from",
        "2025-07",
        "--period-to",
        "2026-10",
    ]
    for code in METRIC_CODES:
        cmd.extend(["--code", code])
    run(cmd, BACKEND, args.apply, backend_env, title="重算客户类指标（含下游）")

    run(
        [python_bin(), "scripts/check_customer_code_mapping.py", "--period", "2026-10"],
        BACKEND,
        args.apply,
        backend_env,
        required=False,
        title="校验",
    )

    if args.service and shutil.which("systemctl"):
        run(["systemctl", "restart", args.service], ROOT, args.apply, title="重启服务")
    elif args.service:
        log("未找到 systemctl（Windows 环境），跳过自动重启；请手动重启后端进程")
    else:
        log("未指定 --service，跳过重启；服务器请按现有方式重启后端进程")

    log("完成")


if __name__ == "__main__":
    main()
