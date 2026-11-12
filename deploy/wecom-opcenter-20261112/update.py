"""企业微信打卡同步 + 运营中心工时指标上线（conda Python，不使用 Docker）。

本次上线内容：
- 新增企微通讯录/打卡同步模块与两张迁移；
- 新增运营中心主表工时指标 TM-01（正常工作时间）/ TM-02（加班时间）；
- 重算 2026-09、2026-10、2026-11 三个期间。

服务器项目根目录执行（默认 dev 环境，默认只预演）：

    python deploy/wecom-opcenter-20261112/update.py
    python deploy/wecom-opcenter-20261112/update.py --apply \
        --env dev --service fastapiadmin

如果服务器还没有企微连接，先设置 Token 服务地址（含密钥，不要提交到 Git）：

    export WECOM_TOKEN_URL='http://crm.yonggubox.com/qywechat/yg_technology_app/getAccessTokens/key/...'
    python deploy/wecom-opcenter-20261112/update.py --apply --env dev

已存在企微连接时不需要设置；脚本会跳过连接写入。
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
DEFAULT_PERIODS = ["2026-09", "2026-10", "2026-11"]


def python_bin() -> str:
    """优先项目自带 venv；服务器 conda 环境则使用当前解释器。"""
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
        raise SystemExit(f"命令失败（退出码 {result.returncode}）：{' '.join(cmd)}")


def sync_code(apply: bool) -> None:
    """fetch + 快进；服务器有本地提交/分叉时直接报错，不覆盖。"""
    run(["git", "fetch", "origin", "master"], ROOT, apply, title="拉取代码")
    run(
        ["git", "merge", "--ff-only", "origin/master"],
        ROOT,
        apply,
        title="快进到 origin/master",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="企微打卡 + 运营中心工时指标上线")
    parser.add_argument("--apply", action="store_true", help="执行；缺省只预演")
    parser.add_argument("--env", default="dev", help="后端环境，默认 dev")
    parser.add_argument("--skip-pull", action="store_true", help="跳过 git fetch/merge")
    parser.add_argument("--skip-token", action="store_true", help="跳过企微连接写入")
    parser.add_argument("--skip-recalc", action="store_true", help="跳过指标重算")
    parser.add_argument(
        "--token-url",
        default=None,
        help="Token 服务 URL；也可用 WECOM_TOKEN_URL",
    )
    parser.add_argument(
        "--service",
        default=None,
        help="systemd 服务名，如 fastapiadmin",
    )
    parser.add_argument(
        "--period",
        action="append",
        default=None,
        help="重算期间，可重复；默认 2026-09/2026-10/2026-11",
    )
    args = parser.parse_args()

    log(f"项目根目录：{ROOT}")
    log(f"模式：{'执行' if args.apply else '预演'}，环境：{args.env}")
    backend_env = {"ENVIRONMENT": args.env}

    if not args.skip_pull:
        sync_code(args.apply)

    run(
        [python_bin(), "main.py", "upgrade", "--env", args.env],
        BACKEND,
        args.apply,
        backend_env,
        title="应用数据库迁移",
    )

    token_url = (args.token_url or os.environ.get("WECOM_TOKEN_URL") or "").strip()
    if args.skip_token:
        log("跳过企微连接写入（--skip-token）")
    elif token_url:
        token_env = {**backend_env, "WECOM_TOKEN_URL": token_url}
        run(
            [python_bin(), "scripts/seed_wecom_token_connection.py"],
            BACKEND,
            args.apply,
            token_env,
            title="写入/更新企微连接（Token 模式）",
        )
    else:
        log(
            "未提供 --token-url/WECOM_TOKEN_URL，跳过连接写入；"
            "将沿用数据库中已有的企微连接"
        )

    run(
        [python_bin(), "scripts/seed_opcenter_worktime_metrics.py"],
        BACKEND,
        args.apply,
        backend_env,
        title="写入 TM-01/TM-02 指标定义",
    )

    if not args.skip_recalc:
        periods = args.period or DEFAULT_PERIODS
        cmd = [
            python_bin(),
            "scripts/recalc_metrics_batch.py",
            "--code-file",
            "scripts/metric_groups/opcenter_worktime.txt",
        ]
        for period in periods:
            cmd.extend(["--period", period])
        run(cmd, BACKEND, args.apply, backend_env, title="重算 TM-01/TM-02")

    if args.service and shutil.which("systemctl"):
        run(["systemctl", "restart", args.service], ROOT, args.apply, title="重启服务")
    elif args.service:
        log("未找到 systemctl（Windows 环境），跳过自动重启")
    else:
        log("未指定 --service，跳过重启；请按现有方式重启后端进程")

    log("完成")


if __name__ == "__main__":
    main()

