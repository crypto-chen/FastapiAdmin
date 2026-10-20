# PUSH-01-a / PUSH-01-b 取数接口调整

## 变更

- `/hs/push/getPush` 改用 `dateRange`（下推时间整月）+ `type`
- `type=1`：本月创建本月下推，对应 PUSH-01-a
- `type=2`：非本月创建但本月下推，对应 PUSH-01-b
- `dateRange` 写成 `YYYY-MM-01 00:00:00` ~ `YYYY-MM-末 23:59:59`
- 来源对象 code 从 `?scope=same_month` / `?scope=prior_month` 原地迁移到 `?type=1` / `?type=2`

## 服务器更新

在项目根目录拉取代码后，进入 `backend`：

```bash
git pull origin master
cd backend
python scripts/seed_crm_push_metrics.py
python scripts/recalc_metrics_batch.py --code marketing_order_push_same_month --code marketing_order_push_prior_month --refresh --period-from 2025-08 --period-to 2026-10 --with-dependents
```

然后按现有方式重启后端服务。

## 校验

```bash
python scripts/crm_check.py --period 2026-09
```

关注三行：

```text
本月接单本月下推（未税） = 7,469,553.97
前期接单本月下推（未税） = 1,806,596.18
下推金额合计（未税） = 9,276,150.15
```

## 回滚

```bash
bash deploy/push-type-20261020/ROLLBACK.sh
```

数据库定义回滚需重新执行旧版 seed 脚本；变更前定义备份在
`backend/artifacts/push_type_20261020/before.json`（本地产物，不随 git 提交）。
