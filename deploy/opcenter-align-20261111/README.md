# 运营中心指标对齐新口径 + 部门编码过滤（2026-11-11）

## 变更

1. 部门过滤由名称改为编码：`BM000008 / BM000021 / BM000023`
   （ERP 中 BM000008 现名为「品类与流量部」，历史名「在线营销部」；按名称过滤会漏计）。
2. 17 项指标按最新口径表调整关键字：
   - 办公费：+ `FLB辅/劳保`
   - 国内快递费：只留 `内贸快递`（去掉售后运输费）
   - 售后费用：`售后返工费 + 售后运输费`（去掉售后其它费用/赔偿费，售后运输费不再按期间切换）
   - 平台费：去掉 `专用平台费用`
   - 水电费：只留 `电费`
   - 维修费：只留 `维修费`

## 变更文件

| 文件 | 说明 |
| --- | --- |
| `backend/app/modules/metric/engine.py` | `extract_account_balance` 新增 `department_codes`（维度编码首段精确匹配） |
| `backend/scripts/seed_opcenter_metrics.py` | 部门编码 + 新口径关键字 |
| `backend/tests/test_opcenter_dept_filter.py` | 编码过滤、改名不影响、17 项定义断言 |

## 服务器 dev 一键更新（推荐）

项目根目录执行，默认 `--env dev`，先预演再执行：

```bash
python deploy/opcenter-align-20261111/update.py
python deploy/opcenter-align-20261111/update.py --apply --env dev --service fastapiadmin
```

脚本顺序：

1. `git fetch origin master` + `git merge --ff-only origin/master`
2. `python scripts/seed_opcenter_metrics.py`
3. `python scripts/seed_opcenter_menu.py`
4. `python scripts/recalc_metrics_batch.py --code-file scripts/metric_groups/opcenter_cost.txt`
5. `systemctl restart fastapiadmin`（可选，Windows 自动跳过）

重算默认覆盖库里已有同步批次的全部期间；只补某段：

```bash
python deploy/opcenter-align-20261111/update.py --apply --period-from 2026-09 --period-to 2026-11
```

跳过步骤：`--skip-pull` / `--skip-recalc`；重启：`--service fastapiadmin`。

## 手工命令（backend 目录）

```bash
python scripts/seed_opcenter_metrics.py
python scripts/seed_opcenter_menu.py
python scripts/recalc_metrics_batch.py --code-file scripts/metric_groups/opcenter_cost.txt
```

重算（指标页「重算」或接口批量重算）：

```bash
python -c "import asyncio; from app.modules.metric.batch import run_metric_batch; asyncio.run(run_metric_batch(period_value='2026-10', codes=[f'OPC-COST-{i:02d}' for i in range(1,18)]))"
```

## 校验

```bash
python -m pytest tests/test_opcenter_dept_filter.py -q
```

## 回滚

```bash
bash deploy/opcenter-align-20261111/ROLLBACK.sh
```

回滚后再执行 `python scripts/seed_opcenter_metrics.py`（脚本已恢复为旧口径）并重算，即可恢复旧定义与数值。
