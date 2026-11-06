# 营销费用口径更新（2026-11-06）

本次只改后端指标口径，**没有数据库迁移、没有前端改动**。  
服务器是 conda 直跑环境，按下面 5 步执行；所有 Python 命令都在 `backend/` 目录下运行。

## 0. 需要上传的文件

必需（少一个都会导致口径不生效）：

```text
backend/app/modules/metric/engine.py
backend/scripts/seed_marketing_metrics.py
```

建议同时上传：

```text
backend/scripts/metric_groups/expense_caliber.txt
docs/核算指标系统设计.md
```

上传示例（在本地项目根目录执行）：

```bash
scp backend/app/modules/metric/engine.py <user>@<server>:/path/to/FastapiAdmin/backend/app/modules/metric/
scp backend/scripts/seed_marketing_metrics.py <user>@<server>:/path/to/FastapiAdmin/backend/scripts/
scp backend/scripts/metric_groups/expense_caliber.txt <user>@<server>:/path/to/FastapiAdmin/backend/scripts/metric_groups/
```

如果服务器是从 Git 拉代码，提交并推送后执行：

```bash
cd /path/to/FastapiAdmin
git pull origin master
```

## 1. 备份数据库（建议）

```bash
mysqldump -h<DB_HOST> -u<DB_USER> -p'<DB_PASSWORD>' \
  --single-transaction --databases fastapiadmin \
  > ~/fastapiadmin_backup_$(date +%Y%m%d_%H%M).sql
```

## 2. 更新指标定义（幂等，可重复执行）

```bash
cd /path/to/FastapiAdmin/backend
export ENVIRONMENT=dev           # 你的服务器使用 dev
python scripts/seed_marketing_metrics.py
```

期望输出包含：

```text
指标定义已就绪: id=... code=marketing_software_expense name=营销中心软件费用
```

## 3. 重启后端（必须在重算前）

上传的 `engine.py` 只有重启后才生效；先重启，再跑重算，避免旧进程/调度器用旧口径写入结果。

```bash
# systemd
systemctl restart fastapiadmin

# 或 supervisor
supervisorctl restart fastapiadmin
```

## 4. 重算（先算 2026-10，再算 2026-11）

```bash
cd /path/to/FastapiAdmin/backend
export ENVIRONMENT=dev           # 与上一步一致
python scripts/recalc_metrics_batch.py \
  --code marketing_software_expense \
  --code marketing_platform_expense \
  --code marketing_domestic_express_expense \
  --code marketing_after_sales_expense \
  --code marketing_total_expense \
  --with-dependents \
  --period 2026-10 \
  --period 2026-11
```

说明：

- `--with-dependents` 会连带重算费用合计、变动费用、边际贡献等下游指标。
- 2026-10 的「售后运输费」只在该期间从国内快递费调到售后费用；其他月份仍按原口径。
- 如果服务器没有 2026-11 的同步批次，脚本会实时回补金蝶取数，耗时会比 10 月长。

可选：回填历史期间（只建议在服务器已有这些期间同步批次时执行；缺批次会实时回补金蝶）：

```bash
python scripts/recalc_metrics_batch.py \
  --code marketing_software_expense \
  --code marketing_platform_expense \
  --code marketing_total_expense \
  --with-dependents \
  --period-from 2025-08 --period-to 2026-10
```

## 5. 核对

打开「指标中心 → 营销业务指标 → 指标结果」，选择 **2026-10**，确认：

- `营销中心软件费用` 已出现在「营销中心-主表」分类；
- `营销中心平台费` 包含「平台固定费（年费/月租）」；
- `营销中心国内快递费` 不再包含「售后运输费」；
- `营销中心售后费用` 包含「售后运输费」。

本地验证值（服务器以实际批次为准）：

```text
2026-10 软件费用      0.00
2026-10 平台费        4,701.26（其中平台固定费 1,886.79）
2026-10 国内快递费    0.00
2026-10 售后费用      867.00
2026-10 费用合计      142,161.339
```

## 回滚

优先用第 1 步的数据库备份恢复。  
如果需要按指标回滚，把本地 `backend/artifacts/marketing_expense_20261106/` 整个目录上传到服务器同一路径，再执行：

```bash
bash backend/artifacts/marketing_expense_20261106/ROLLBACK.sh /path/to/FastapiAdmin
```

数据库回滚先预演，确认后再加 `--apply`：

```bash
cd /path/to/FastapiAdmin/backend
export ENVIRONMENT=dev
python artifacts/marketing_expense_20261106/ROLLBACK_DB.py
python artifacts/marketing_expense_20261106/ROLLBACK_DB.py --apply
```

注意：`ROLLBACK_DB.py` 会删除基线快照之后新增的 `metric_value` 行，并恢复 4 个原有指标定义、删除新指标；执行前务必确认基线快照仍适用。
