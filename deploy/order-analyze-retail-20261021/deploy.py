"""CRM orderAnalyze type=3（零售）一键更新脚本（纯 Python，Windows/Linux 通用）。

在项目根目录执行：
    python deploy/order-analyze-retail-20261021/deploy.py
    python deploy/order-analyze-retail-20261021/deploy.py --apply
    python deploy/order-analyze-retail-20261021/deploy.py --apply --service fastapiadmin

默认只预演；加 --apply 才真正执行。
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
LOG_FILE = Path(__file__).resolve().parent / "deploy_run.log"

SYNC_PERIODS = ",".join(
    [f"2023-{m:02d}" for m in (11, 12)]
    + [f"2024-{m:02d}" for m in range(1, 13)]
    + [f"2025-{m:02d}" for m in range(1, 13)]
    + [f"2026-{m:02d}" for m in range(1, 11)]
)
BUILD_PERIODS = ",".join(
    [f"2024-{m:02d}" for m in (10, 11, 12)]
    + [f"2025-{m:02d}" for m in range(1, 13)]
    + [f"2026-{m:02d}" for m in range(1, 11)]
)
RETAIL_PERIODS = ",".join(
    [f"2025-{m:02d}" for m in range(7, 13)]
    + [f"2026-{m:02d}" for m in range(1, 11)]
)

STEPS: list[tuple[str, list[str]]] = [
    ("[1/8] 指标/来源对象定义", ["scripts/seed_crm_person_metrics.py"]),
    ("[2/8] 订单全链路元数据", ["scripts/seed_order_module.py"]),
    (
        "[3/8] 同步零售订单 type=3",
        [
            "scripts/run_meta_sync.py",
            "--name",
            "CRM业务员指标-CRM 订单明细（零售）",
            "--period",
            SYNC_PERIODS,
        ],
    ),
    ("[4/8] 重建订单全链路", ["scripts/run_order_build.py", "--period", BUILD_PERIODS]),
    ("[5/8] 重建客户分析", ["scripts/run_customer_build.py", "--period", RETAIL_PERIODS]),
    ("[6/8] 重建产品线分析", ["scripts/run_product_build.py", "--period", RETAIL_PERIODS]),
    (
        "[7/8] 重算业务员指标及下游",
        [
            "scripts/recalc_metrics_batch.py",
            "--code-file",
            "scripts/metric_groups/order_retail.txt",
            "--with-dependents",
            "--period-from",
            "2025-07",
            "--period-to",
            "2026-10",
        ],
    ),
    (
        "[8/8] 校验零售同步批次",
        [
            "scripts/run_meta_sync.py",
            "--name",
            "CRM业务员指标-CRM 订单明细（零售）",
            "--period",
            "2026-09",
            "--show-latest",
        ],
    ),
]


def log(message: str = "") -> None:
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def run_step(label: str, args: list[str], python: str, env_name: str, apply: bool) -> None:
    command = [python, *args]
    log(f"\n{label}")
    log("  > " + " ".join(command))
    if not apply:
        return

    env = os.environ.copy()
    env["ENVIRONMENT"] = env_name
    env["PYTHONIOENCODING"] = "utf-8"
    process = subprocess.Popen(
        command,
        cwd=str(BACKEND),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        line = line.rstrip()
        print(line, flush=True)
        with LOG_FILE.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    code = process.wait()
    if code != 0:
        log(
            "\n提示：若出现 MySQL 1045 / Access denied，请检查 "
            f"backend/env/.env.{env_name} 是否存在且 DATABASE_PASSWORD 已填写；"
            "也可以直接设置 DATABASE_PASSWORD 环境变量后重跑。"
        )
        raise SystemExit(f"步骤失败：{label}，退出码 {code}")


def restart_service(service: str) -> None:
    log(f"\n重启服务：{service}")
    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            f"Restart-Service -Name '{service}' -Force; Get-Service -Name '{service}' | Format-Table Name,Status,StartType",
        ]
    else:
        command = ["systemctl", "restart", service]
    subprocess.run(command, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="CRM orderAnalyze type=3（零售）一键更新")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只预演）")
    parser.add_argument("--service", default="", help="服务名；Windows 用 Restart-Service，Linux 用 systemctl")
    parser.add_argument(
        "--env",
        default=os.getenv("ENVIRONMENT", "dev"),
        help="后端环境名，默认取 ENVIRONMENT，未设置时用 dev；生产库请传 --env prod",
    )
    parser.add_argument("--python", default=sys.executable, help="Python 解释器，默认当前解释器")
    args = parser.parse_args()

    if not BACKEND.is_dir():
        raise SystemExit(f"找不到 backend 目录：{BACKEND}")

    LOG_FILE.write_text(
        f"orderAnalyze type=3 部署开始 {datetime.now():%Y-%m-%d %H:%M:%S}\n",
        encoding="utf-8",
    )
    log(f"项目根目录：{ROOT}")
    log(f"后端目录：{BACKEND}")
    log(f"Python：{args.python}")
    log(f"环境：{args.env}")
    log(f"模式：{'执行' if args.apply else '预演'}")
    log(f"日志：{LOG_FILE}")

    for label, step_args in STEPS:
        run_step(label, step_args, args.python, args.env, args.apply)

    if not args.apply:
        log("\n预演完成，未执行任何命令。确认后加 --apply。")
        return

    if args.service:
        restart_service(args.service)
    else:
        log("\n未指定 --service：请按现有方式重启后端进程。")
    log("\n服务器更新完成。")


if __name__ == "__main__":
    main()
