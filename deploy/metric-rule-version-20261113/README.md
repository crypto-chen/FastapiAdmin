# 指标口径版本更新（2026-11-13）

## 变更

1. 新增 `metric_def_version`：指标口径按生效期保存快照，修改指标不再覆盖旧公式。
2. 新增 `metric_period_version`：每个期间钉住 `pinned_def_version` 与 `active_def_version`。
3. 新增 `metric_run.rule_mode`：重算记录 `historical` / `current`。
4. 重算接口与指标结果页支持选择：
   - `historical`（默认）：按该月钉住的历史口径重算；
   - `current`：按指标当前最新口径重算，并把该期间生效口径切到最新。

## 服务器更新

先在项目根目录预演：

```bash
python deploy/metric-rule-version-20261113/update.py
```

确认后执行：

```bash
python deploy/metric-rule-version-20261113/update.py --apply --service fastapiadmin
```

脚本顺序：

1. 检查分支与工作区；
2. `git fetch origin master` + `git merge --ff-only origin/master`；
3. `python -m alembic upgrade heads`；
4. 校验 `metric_def_version` / `metric_period_version` / `metric_run.rule_mode`；
5. `pytest tests/test_metric_rule_version.py`；
6. `systemctl restart fastapiadmin`（可选）。

## 前端

前端源码有改动。服务器页面需要更新时，二选一：

- 服务器有 Node/pnpm：加 `--build-frontend`；
- 本地构建 `frontend/web` 后，把 `dist/` 上传到服务器对应目录。

## 常用参数

```bash
# 只跑迁移，不拉代码
python deploy/metric-rule-version-20261113/update.py --apply --skip-pull --service fastapiadmin

# 跳过 pytest
python deploy/metric-rule-version-20261113/update.py --apply --skip-tests --service fastapiadmin

# 指定环境
python deploy/metric-rule-version-20261113/update.py --apply --env dev --service fastapiadmin
```

## 回滚

先备份数据库。回滚分两步：

1. 代码切回上一个提交；
2. 在 `backend` 目录执行：

```bash
python -m alembic downgrade wecomtoken01
```

`downgrade` 会删除 `metric_def_version`、`metric_period_version` 和 `metric_run.rule_mode`；
如果已经产生多口径重算结果，先导出 `metric_value` 再回滚。

## 服务器本地噪声迁移

如果服务器上存在未跟踪的自动迁移（如 `2026_11_13_1107_29bf6c113584.py`），先
`python -m alembic stamp metricrule01`，再把本地迁移文件移到 `backend/alembic_local_backup/`。
该迁移先建后删外键，净效果是外键丢失；补回：

```bash
cd backend
python ..\deploy\metric-rule-version-20261113\repair_fk.py --env prod
```

`--env` 必须与后端启动参数一致（`python main.py run --env=prod` 就用 prod），否则会连到另一个数据库。
