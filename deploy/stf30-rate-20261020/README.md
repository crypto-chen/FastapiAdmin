# STF-30 结算收益折算比例部署（10% → 18%）

变更字段：`marketing_person_settlement_income`（STF-18）的 `measures.scale` 由 `0.1` 改为 `0.18`。
下游 `STF-26 / STF-27 / STF-28 / STF-30 / STF-37` 会按新口径重算。

## 1. 部署代码

```bash
cd /path/to/FastapiAdmin
git pull
# 按现有部署方式重启后端
```

## 2. 先看变更（不写库）

```bash
bash deploy/stf30-rate-20261020/deploy.sh --dry-run
```

输出中应看到：

```text
marketing_person_settlement_income (STF-18): scale 0.1 -> 0.18
```

## 3. 执行更新 + 重算 + 校验

```bash
bash deploy/stf30-rate-20261020/deploy.sh --apply
```

脚本会：

1. 备份当前 `metric_def` 到 `backend/artifacts/stf30_rate_<时间>/metric_def_before.json`；
2. 更新 STF-18/26/27/28/30 的定义；
3. 重算库中已有的 STF-30 期间（当前为 2024-10 ~ 2026-10，共 25 期）；
4. 逐业务员校验：
   - `STF-30 = STF-27 - STF-28 - STF-29`
   - `STF-18 = STF-17 × 18%`
   - `STF-37 = STF-30`

## 4. 校验当前结果（不改数据）

```bash
bash deploy/stf30-rate-20261020/deploy.sh --check
```

正常输出：

```json
{
  "periods": 25,
  "max_profit_residual": 1.4551915228366852e-11,
  "max_rate_error": 2.6160133226316162e-09,
  "max_ratio_error": 0.0
}
```

## 5. 回滚

```bash
bash deploy/stf30-rate-20261020/deploy.sh --rollback
```

默认读取最近一次备份；也可指定：

```bash
bash deploy/stf30-rate-20261020/deploy.sh --rollback --backup backend/artifacts/stf30_rate_20261020_174000/metric_def_before.json
```

## 参考结果（2026-09）

| 指标 | 10% | 18% |
|---|---:|---:|
| STF-18 营销结算收入 | 931,044.5478 | 1,675,880.1860 |
| STF-30 结算收益 | 84,872.5819 | 748,639.1570 |
