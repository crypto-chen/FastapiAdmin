# 客户编码匹配改造（2026-10-31）

## 改了什么

CRM 定制客户与零售客户分属两张表，`id` 会重复；两个接口已改为返回唯一编码：

- `hs/order/orderAnalyze` 新增 `customer_code`（零售单为 `LS...`，旧批次回退 `customer_number`）；
- `hs/customer/getCusotmerList` 新增 `is_retail`（0=定制，1=零售），客户编码 `number` 唯一。

本系统把所有客户匹配从「客户 ID」改为「客户编码」：

| 位置 | 改动 |
| --- | --- |
| 订单全链路 `order/build.py` | 客户主档按 `number` 建索引；订单优先用 `customer_code` 匹配，ID 仅在旧批次且唯一时兜底；`extra.customer_is_retail` 落零售标识 |
| 客户分析 `customer/build.py` | 主档/分桶按客户编码；零售客户生成独立 CUS 行；`extra.is_retail` 输出 |
| STF-48 本月下单老客户数 | 按 `customer_code` 去重（回退 customer_number / customer） |
| STF-47 总客户数 | 按 `number` 去重，**含零售客户** |
| STF-49 复购率 | 随 STF-47/48 自动重算 |

## 服务器执行（conda，不用 Docker）

```bash
cd /path/to/FastapiAdmin
python deploy/customer-code-20261031/update.py            # 预演
python deploy/customer-code-20261031/update.py --apply --service fastapiadmin
```

脚本顺序：

1. `git fetch origin master` + 快进；本地提交与远端分叉且工作区干净时自动 `git reset --hard origin/master`
2. `python scripts/seed_crm_person_metrics.py`
3. 重新同步客户档案 + 订单明细（内贸/外贸/零售）2025-07 ~ 2026-10
4. `python scripts/run_order_build.py --period ...`
5. `python scripts/run_customer_build.py --period ...`
6. `python scripts/recalc_metrics_batch.py --code ... --with-dependents --period-from 2025-07 --period-to 2026-10`
7. `python scripts/check_customer_code_mapping.py --period 2026-10`
8. `systemctl restart fastapiadmin`（Windows 无 systemctl 时自动跳过，需手动重启后端进程）

脚本会先探测 `prod` / `dev` 两个环境，选第一个能读到 `DATABASE_PASSWORD` 的 `.env`；
服务器只配了 `.env.dev` 时自动使用 dev，也可显式传 `--env dev`。

跳过某一步：`--skip-sync` / `--skip-build` / `--skip-pull`。

## 手工命令（等价）

```bash
cd backend
python scripts/seed_crm_person_metrics.py
python scripts/run_meta_sync.py --name "CRM业务员指标-CRM 客户列表（业务员客户数）" --period 2026-10
python scripts/run_meta_sync.py --name "CRM业务员指标-CRM 订单明细（内贸）" --period 2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10
python scripts/run_meta_sync.py --name "CRM业务员指标-CRM 订单明细（外贸）" --period 2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10
python scripts/run_meta_sync.py --name "CRM业务员指标-CRM 订单明细（零售）" --period 2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10
python scripts/run_order_build.py --period 2025-07,...,2026-10
python scripts/run_customer_build.py --period 2025-07,...,2026-10
python scripts/recalc_metrics_batch.py --code marketing_person_new_customer_intake_untaxed --code marketing_person_old_customer_intake_untaxed --code marketing_person_old_customer_order_count --code marketing_person_total_customer_count --with-dependents --period-from 2025-07 --period-to 2026-10
python scripts/check_customer_code_mapping.py --period 2026-10
```

## 回滚

代码回滚到上一提交后，用旧代码重跑同样的同步/构建/重算命令即可覆盖结果版本：

```bash
git revert --no-commit HEAD && git commit -m "revert: 客户编码匹配"
cd backend
python scripts/seed_crm_person_metrics.py
python scripts/run_order_build.py --period 2025-07,...,2026-10
python scripts/run_customer_build.py --period 2025-07,...,2026-10
python scripts/recalc_metrics_batch.py --code marketing_person_new_customer_intake_untaxed --code marketing_person_old_customer_intake_untaxed --code marketing_person_old_customer_order_count --code marketing_person_total_customer_count --with-dependents --period-from 2025-07 --period-to 2026-10
```
