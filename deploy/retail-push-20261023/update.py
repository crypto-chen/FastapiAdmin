"""零售数据推送接口 + 管理页面服务器更新脚本（conda Python，不使用 Docker）。

在服务器项目根目录执行：

    python deploy/retail-push-20261023/update.py --apply --service fastapiadmin

只预演命令（默认）：

    python deploy/retail-push-20261023/update.py

前端需要在服务器构建时：

    python deploy/retail-push-20261023/update.py --apply --service fastapiadmin \
      --build-frontend --frontend-target /usr/share/nginx/html
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


def log(message: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def run(
    cmd: list[str],
    cwd: Path,
    apply: bool,
    env_extra: dict[str, str] | None = None,
) -> None:
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


def build_frontend(apply: bool, target: str | None) -> None:
    pnpm = shutil.which("pnpm")
    npm = shutil.which("npm")
    if pnpm:
        run([pnpm, "install"], FRONTEND, apply)
        run([pnpm, "run", "build:prod"], FRONTEND, apply)
    elif npm:
        run([npm, "install"], FRONTEND, apply)
        run([npm, "run", "build"], FRONTEND, apply)
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
    parser = argparse.ArgumentParser(description="零售推送接口与管理页面服务器更新")
    parser.add_argument("--apply", action="store_true", help="执行；缺省只预演")
    parser.add_argument("--skip-pull", action="store_true", help="跳过 git pull")
    parser.add_argument("--env", default="prod", help="后端环境 dev/prod，默认 prod")
    parser.add_argument("--service", default=None, help="systemd 服务名，如 fastapiadmin")
    parser.add_argument("--build-frontend", action="store_true", help="在服务器构建前端")
    parser.add_argument("--frontend-target", default=None, help="nginx 站点目录，如 /usr/share/nginx/html")
    args = parser.parse_args()

    log(f"项目根目录：{ROOT}")
    log(f"模式：{'执行' if args.apply else '预演'}")

    if not args.skip_pull:
        run(["git", "pull", "--ff-only", "origin", "master"], ROOT, args.apply)

    backend_env = {"ENVIRONMENT": args.env}
    run([sys.executable, "main.py", "upgrade", "--env", args.env], BACKEND, args.apply, backend_env)
    run([sys.executable, "scripts/seed_retail_push_job.py"], BACKEND, args.apply, backend_env)
    run([sys.executable, "scripts/seed_retail_menu.py"], BACKEND, args.apply, backend_env)
    run([sys.executable, "scripts/check_retail_migration.py"], BACKEND, args.apply, backend_env)

    if args.build_frontend:
        build_frontend(args.apply, args.frontend_target)

    if args.service:
        run(["systemctl", "restart", args.service], ROOT, args.apply)
        run(["systemctl", "status", args.service, "--no-pager"], ROOT, args.apply)
    else:
        log("未指定 --service：请按现有方式重启后端（systemd/screen/nohup）")

    log("更新完成" if args.apply else "预演完成，确认后加 --apply")


if __name__ == "__main__":
    main()
