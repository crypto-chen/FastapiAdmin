# STF-13 业务员接单未税：收款日期口径

变更字段：`marketing_person_order_intake_untaxed`（STF-13）的 `measures.period_field` 由未设置改为 `collectiontime`。
归期从“订单创建月”改为“收款日期所在月”，订单明细按建单月回看 12 期、前看 1 期。

## 1. 服务器更新

在服务器项目目录拉取代码：

```bash
cd /path/to/FastapiAdmin
git pull origin master
```

进入 conda 环境后，在 `backend/` 目录执行：

```bash
cd backend
python scripts/deploy_stf13_collection_date.py --dry-run
```

确认输出包含：

```text
marketing_person_order_intake_untaxed (STF-13): period_field None -> collectiontime
```

执行更新与重算：

```bash
python scripts/deploy_stf13_collection_date.py --apply
```

脚本会自动：

1. 备份 `metric_def` 到 `backend/artifacts/stf13_collection_date_<时间>/metric_def_before.json`；
2. 更新 STF-13 的 `formula` / `measures` / `description`；
3. 重算库中已有期间（默认 2026-07 ~ 2026-10）；
4. 校验公司合计 = 业务员行合计。

更新代码后重启一次后端进程（使用你现有的 systemd / supervisor / 启动方式），让新引擎代码生效。

## 2. 校验

```bash
python scripts/deploy_stf13_collection_date.py --check
```

正常输出：

```json
{
  "periods": ["2026-07", "2026-08", "2026-09", "2026-10"],
  "totals": {
    "2026-07": 9051544.69,
    "2026-08": 7168875.32,
    "2026-09": 8015502.83,
    "2026-10": 3557131.31
  },
  "max_company_person_residual": 0.0,
  "period_field": "collectiontime",
  "errors": []
}
```

## 3. 日常指标重算

单期重算：

```bash
python scripts/recalc_metrics_batch.py --code marketing_person_order_intake_untaxed --period 2026-10
```

区间重算：

```bash
python scripts/recalc_metrics_batch.py --code marketing_person_order_intake_untaxed --period-from 2026-07 --period-to 2026-10
```

CRM 数据补录或修正后，先强制重拉批次再重算：

```bash
python scripts/recalc_metrics_batch.py --code marketing_person_order_intake_untaxed --period 2026-10 --refresh
```

需要连带重算下游指标时加 `--with-dependents`：

```bash
python scripts/recalc_metrics_batch.py --code marketing_person_order_intake_untaxed --period 2026-10 --with-dependents
```

## 4. 回滚

```bash
python scripts/deploy_stf13_collection_date.py --rollback
```

默认读取最近一次 `--apply` 的备份；也可显式指定：

```bash
python scripts/deploy_stf13_collection_date.py --rollback --backup backend/artifacts/stf13_collection_date_20261020_181612/metric_def_before.json
```
