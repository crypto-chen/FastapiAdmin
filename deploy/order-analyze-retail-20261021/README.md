# CRM orderAnalyze type=3（零售订单范围）上线说明

## 变更

CRM `/hs/order/orderAnalyze` 新增 `type=3`：

- 返回 `LS` 开头的零售订单，单月约 1,600 行；
- 行内 `type`：1=内贸零售、2=外贸零售；
- 零售金额字段为 `remove_taxes_freight`（外贸零售行 `receivable_CNY` 为空）；
- 作废单 `status=522` 需剔除。

本系统把零售订单并入订单全链路宽表，并按 `order_type=3（零售）` 标识：

- 贸易类型仍按行内 `type` 落 `domestic/export`；
- 订单类型固定 `3`，`extra.order_type` = `零售`；
- `intake_untaxed` 取 `remove_taxes_freight`。

## 影响指标

| 指标组 | 影响 |
| --- | --- |
| 订单全链路 ORD-00 ~ ORD-68 | 新增零售订单；接单、数量、客户/业务员/订单类型维度、成本毛利等按零售补全 |
| 客户分析 CUS-xx | 零售客户进入客户宽表，客户数、接单、净额、毛利分摊随之变化 |
| 产品线分析 PRD-xx | 零售订单按型号/产品线进入宽表；无型号的零售单落“未命中型号” |
| 业务员 STF-13/15/23/24/25/38~41/47~50 等 | 接单、订单数、新老客户、未出货库存等新增零售口径；出货类仍取原发货接口 |
| 公司 ORD-01-a/b/c | 不重新取数：仍取 CRM 金额接口，零售已由 `getRetailAmount` 覆盖，避免重复计入 |

发货接口 `/hs/order/orderShipments?type=3` 当前返回 0 行，`getShipmentsDetail` 也不含零售订单；
零售出货继续取聚水潭 `retail_outbound_untaxed_amount`，业务员出货指标不新增零售分支。

## 服务器更新

在服务器项目根目录拉取代码后，直接执行 Python 一键脚本（Windows / Linux 通用）：

```bash
python deploy/order-analyze-retail-20261021/deploy.py --apply
```

指定服务名时：

```bash
python deploy/order-analyze-retail-20261021/deploy.py --apply --service fastapiadmin
```

不带 `--apply` 只预演命令。脚本日志写入 `deploy/order-analyze-retail-20261021/deploy_run.log`。

等价的手工步骤（进入 `backend`）：

```bash
git pull origin master
cd backend
python scripts/seed_crm_person_metrics.py
python scripts/seed_order_module.py
python scripts/run_meta_sync.py --name "CRM业务员指标-CRM 订单明细（零售）" --period 2023-11,2023-12,2024-01,2024-02,2024-03,2024-04,2024-05,2024-06,2024-07,2024-08,2024-09,2024-10,2024-11,2024-12,2025-01,2025-02,2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10
python scripts/run_order_build.py --period 2024-10,2024-11,2024-12,2025-01,2025-02,2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10
python scripts/run_customer_build.py --period 2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10
python scripts/run_product_build.py --period 2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10
python scripts/recalc_metrics_batch.py --code-file scripts/metric_groups/order_retail.txt --with-dependents --period-from 2025-07 --period-to 2026-10
```

最后重启后端进程（conda 环境）：

```bash
# 按现有方式重启，例如 systemd：
systemctl restart fastapiadmin
# 或前台/screen/nohup 方式启动：
python main.py run --env=prod
```

## 校验

```bash
python scripts/run_meta_sync.py --name "CRM业务员指标-CRM 订单明细（零售）" --period 2026-09 --show-latest
python scripts/verify_ord01_formula.py --period 2026-09
```

期望 2026-09 订单全链路：零售订单 1,570 张、零售接单未税 838,216.39（含外贸零售 67,202.68）。

## 回滚

```bash
bash deploy/order-analyze-retail-20261021/ROLLBACK.sh
```

回滚脚本会恢复代码、删除本次新增的 type=3 同步批次与宽表新版本，并恢复本次变更前的指标定义。
