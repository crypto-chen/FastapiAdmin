"""一次性同步 2026-10-27 全部改动到服务器（conda Python，不使用 Docker）。

覆盖当天所有提交（售后同步、13% 去税、已发货出货、退货退款口径、净额/结算收入、
平台渠道分析开放接口、启动编码修复、指标中心平台分析页面）。

在服务器项目根目录执行：

    python deploy/sync-all-20261027/update.py --apply --service fastapiadmin

带前端构建：

    python deploy/sync-all-20261027/update.py --apply --service fastapiadmin \
      --build-frontend --frontend-target /usr/share/nginx/html

只预演（默认，不执行任何命令）：

    python deploy/sync-all-20261027/update.py

脚本是幂等的：重复执行不会重复建菜单/任务。
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
FRONTEND = ROOT / "frontend" / "web"
LOG_PATH = Path(__file__).resolve().parent / "update_run.log"


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
    # Windows GBK 控制台：子进程输出里的替换字符/emoji 直接 print 会抛 UnicodeEncodeError
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


def build_frontend(apply: bool, target: str | None) -> None:
    pnpm = shutil.which("pnpm")
    npm = shutil.which("npm")
    if pnpm:
        run([pnpm, "install"], FRONTEND, apply, title="前端依赖")
        run([pnpm, "run", "build:prod"], FRONTEND, apply, title="前端构建")
    elif npm:
        run([npm, "install"], FRONTEND, apply, title="前端依赖")
        run([npm, "run", "build"], FRONTEND, apply, title="前端构建")
    else:
        log("未找到 pnpm/npm：请在本机构建 frontend/web 后把 dist 上传到 nginx 站点目录")
        return
    if not target:
        log("未指定 --frontend-target：构建产物在 frontend/web/dist，请按现有 nginx 目录发布")
        return
    if apply:
        target_path = Path(target)
        target_path.mkdir(parents=True, exist_ok=True)
        for item in (FRONTEND / "dist").iterdir():
            destination = target_path / item.name
            if item.is_dir():
                shutil.copytree(item, destination, dirs_exist_ok=True)
            else:
                shutil.copy2(item, destination)
        log(f"前端 dist 已发布到 {target_path}")
    else:
        log(f"[预演] 将 frontend/web/dist/* 发布到 {target}")


def main() -> None:
    parser = argparse.ArgumentParser(description="2026-10-27 全部改动一次性上线")
    parser.add_argument("--apply", action="store_true", help="执行；缺省只预演")
    parser.add_argument("--skip-pull", action="store_true", help="跳过 git pull")
    parser.add_argument("--env", default="prod", help="后端环境 dev/prod，默认 prod")
    parser.add_argument("--service", default=None, help="systemd 服务名，如 fastapiadmin")
    parser.add_argument("--build-frontend", action="store_true", help="在服务器构建前端")
    parser.add_argument("--frontend-target", default=None, help="nginx 站点目录")
    parser.add_argument("--skip-seeds", action="store_true", help="跳过菜单/任务初始化")
    parser.add_argument("--backfill-begin", default=None, help="平台指标补算起始期间 YYYY-MM")
    parser.add_argument("--backfill-end", default=None, help="平台指标补算结束期间 YYYY-MM")
    args = parser.parse_args()

    log(f"项目根目录：{ROOT}")
    log(f"模式：{'执行' if args.apply else '预演'}")

    # 1) 拉代码（当天 9 个提交）
    if not args.skip_pull:
        run(
            ["git", "pull", "--ff-only", "origin", "master"],
            ROOT,
            args.apply,
            title="拉取代码",
        )
        run(["git", "log", "--oneline", "-9"], ROOT, args.apply, required=False, title="本次提交")

    backend_env = {"ENVIRONMENT": args.env}

    # 2) 应用迁移：b0f396df56ac（售后两表）+ retailplatform01（开放应用开关）
    run(
        [python_bin(), "main.py", "upgrade", "--env", args.env],
        BACKEND,
        args.apply,
        backend_env,
        title="数据库迁移",
    )
    run(
        [python_bin(), "scripts/check_retail_migration.py"],
        BACKEND,
        args.apply,
        backend_env,
        title="迁移离线校验（可升可降）",
    )

    if not args.skip_seeds:
        # 3) 零售推送回放任务（指标联动用，幂等）
        run(
            [python_bin(), "scripts/seed_retail_push_job.py"],
            BACKEND,
            args.apply,
            backend_env,
            required=False,
            title="零售推送回放任务",
        )
        # 4) 菜单：零售订单同步 / 指标中心-平台分析
        run(
            [python_bin(), "scripts/seed_retail_menu.py"],
            BACKEND,
            args.apply,
            backend_env,
            title="菜单：零售订单同步",
        )
        run(
            [python_bin(), "scripts/seed_platform_menu.py"],
            BACKEND,
            args.apply,
            backend_env,
            title="菜单：指标中心-平台分析",
        )
        # 5) 平台指标定义（指标配置化，新增指标不用改代码）
        run(
            [python_bin(), "scripts/seed_platform_metrics.py"],
            BACKEND,
            args.apply,
            backend_env,
            title="平台指标定义",
        )

    # 5) 自检：数据量 / 开放应用开关
    run(
        [python_bin(), "scripts/check_retail_data.py"],
        BACKEND,
        args.apply,
        backend_env,
        required=False,
        title="零售数据自检",
    )
    run(
        [python_bin(), "scripts/check_platform_analysis_access.py"],
        BACKEND,
        args.apply,
        backend_env,
        required=False,
        title="开放应用-平台渠道分析开关",
    )

    # 6) 可选：平台指标历史补算（快照表 platform_metric_snapshot）
    if args.backfill_begin and args.backfill_end:
        run(
            [
                python_bin(),
                "scripts/build_platform_snapshots.py",
                "--begin",
                args.backfill_begin,
                "--end",
                args.backfill_end,
            ],
            BACKEND,
            args.apply,
            backend_env,
            required=False,
            title=f"平台指标补算 {args.backfill_begin} ~ {args.backfill_end}",
        )

    if args.build_frontend:
        build_frontend(args.apply, args.frontend_target)

    if args.service and os.name == "nt":
        log(
            f"Windows 本机不支持 systemctl，已跳过重启（--service {args.service}）。"
            "本机请用 python main.py run --env=dev 启动后端。"
        )
    elif args.service:
        run(["systemctl", "restart", args.service], ROOT, args.apply, title="重启后端")
        run(
            ["systemctl", "status", args.service, "--no-pager"],
            ROOT,
            args.apply,
            required=False,
            title="服务状态",
        )
    else:
        log("未指定 --service：请按现有方式重启后端（systemd/screen/nohup）")

    log("更新完成" if args.apply else "预演完成，确认后加 --apply")
    log("重启后定时任务自动注册：订单/售后 每10分钟增量，店铺与7天补偿 每日 00/07/12/18 点")


if __name__ == "__main__":
    main()
