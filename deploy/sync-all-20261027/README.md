# 2026-10-27 全部改动一次性上线（服务器）

昨天之后没更新过服务器，用这一条命令把当天 **9 个提交**一次同步完。

## 1. 一条命令

```bash
python deploy/sync-all-20261027/update.py --apply --service fastapiadmin \
  --build-frontend --frontend-target /usr/share/nginx/html
```

服务器没有 Node 时，去掉 `--build-frontend`，在本机构建后上传 `frontend/web/dist/*`。

先预演（10 秒，不执行）：

```bash
python deploy/sync-all-20261027/update.py
```

## 2. 脚本会做什么（顺序）

| 步骤 | 命令 | 作用 |
|---|---|---|
| 1 | `git pull --ff-only origin master` | 拉到 `f04a4a77`（含当天 9 个提交） |
| 2 | `python main.py upgrade --env prod` | 应用 2 个迁移：`b0f396df56ac`（售后两表）、`retailplatform01`（开放应用开关） |
| 3 | `python scripts/check_retail_migration.py` | 离线校验迁移可升可降 |
| 4 | `python scripts/seed_retail_push_job.py` | 创建/复用「零售数据-外部推送」任务（指标回放用，幂等） |
| 5 | `python scripts/seed_retail_menu.py` | 注册菜单「开放接口 → 零售订单同步」（幂等） |
| 6 | `python scripts/seed_platform_menu.py` | 注册菜单「指标中心 → 平台分析」（幂等） |
| 7 | `check_retail_data.py` / `check_platform_analysis_access.py` | 打印数据量与应用开关状态 |
| 8 | `systemctl restart fastapiadmin` | 重启，定时任务随之注册 |

## 3. 这次创建的「平台指标」是什么形态

平台分析指标（PLT-08/09/10/11/12/13/37）**不落宽表、不建 metric_def**，
而是实时从 `retail_order` + `retail_after_sale` + `retail_shop` 汇总：

- 管理端看：**指标中心 → 平台分析**（`/metric/platform`）；
- 第三方读：`GET /open/v1/retail/platform/analysis`（需在开放应用里打开「平台渠道分析」开关）。

所以「创建平台指标」= 执行上面的菜单 seed + 迁移，**没有额外的指标定义要建**。
如果之后要求这些数值出现在「指标结果」页并按月留版本，再单独做 metric_def 落值（另行开发）。

## 4. 同步任务要不要建

不用建表、不用配置。后端启动时由 `app/__init__.py` 的 lifespan 自动注册：

| 任务 ID | 频率 | 说明 |
|---|---|---|
| `retail_order_sync:jushuitan:10m` | 每 10 分钟 | 拉非淘系订单（回看 30 分钟） |
| `retail_aftersale_sync:jushuitan:10m` | 每 10 分钟 | 拉非淘系售后（回看 30 分钟） |
| `retail_order_sync:jushuitan:daily` | 每天 00/07/12/18 点 | 订单 7 天补偿 |
| `retail_aftersale_sync:jushuitan:daily` | 每天 00/07/12/18 点 | 售后 7 天补偿 |
| `retail_shop_sync:jushuitan:daily` | 每天 00/07/12/18 点 | 店铺/平台名称 |

**重启即可**，`--service fastapiadmin` 会自动重启。

## 5. 上线后 3 步验收（每步 1 分钟）

1. 迁移与数据
```bash
cd backend
python scripts/check_retail_data.py
```
期望包含：`AFTER_SALES=...`、`MENU=id:... permission:module_retail:order:query`、`PUSH_JOB=id:...`。

2. 菜单
```bash
python scripts/seed_platform_menu.py     # 幂等，可重复执行
```
期望：`平台分析菜单 id=...，权限 module_metric:platform:query`。刷新后台 → 指标中心 → 平台分析。

3. 接口
```bash
curl -X POST "http://120.237.174.243:6479/open/v1/retail/aftersales/sync" \
  -H "Content-Type: application/json" \
  --data-binary @deploy/retail-aftersale-20261027/test_aftersale_sync.json
```
期望 `code=0`、`created/unchanged` 合计 2。

## 6. 两个必须人工确认的开关

1. **聚水潭售后接口权限**：开放平台给应用申请 `/open/refund/single/query`。
   未申请时日志只提示一次「聚水潭售后同步跳过（code=190）」，
   售后表为空、`AFTER_SALES=0`；订单同步不受影响。
2. **第三方读平台指标**：管理端「系统管理 → 开放接口应用」编辑目标应用，打开
   「平台渠道分析」开关（否则 `/open/v1/retail/platform/analysis` 返回 403/40102）。

## 7. 回滚

```bash
git log --oneline -9          # 确认要回退的提交
git revert --no-edit <commit> # 或整段回退
python main.py upgrade --env prod   # 若已降级迁移
```

各子改动的单独回滚脚本仍在对应目录：
`deploy/retail-aftersale-20261027/ROLLBACK.sh`、`deploy/platform-analysis-api-20261027/ROLLBACK.sh`、
`deploy/platform-metric-page-20261027/ROLLBACK.sh`。
