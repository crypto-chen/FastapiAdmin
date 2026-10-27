# 平台渠道分析指标开放接口（2026-10-27）

## 1. 本次新增

| 项 | 内容 |
| --- | --- |
| 表字段 | `open_client.allow_platform_analysis`（迁移 `retailplatform01`，默认 0=不开放） |
| 开放接口 | `GET /open/v1/retail/platform/analysis`（开放令牌 + 应用开关） |
| 管理端 | 「系统管理 → 开放接口应用」表单新增「平台渠道分析」开关与列表列 |
| 脚本 | `scripts/check_platform_analysis_access.py`（列出应用与开关状态） |
| 文档 | `docs/平台渠道分析指标开放接口对接说明.md`（发给第三方） |

返回指标：PLT-08 接单未税、PLT-09 货物出货未税、PLT-11 退货退款、
PLT-12 对外出货净额、PLT-13 营销结算收入 10%、PLT-37 退货率。

## 2. 服务器更新

```bash
python deploy/platform-analysis-api-20261027/update.py --apply --service fastapiadmin
```

脚本按顺序执行：

1. `git pull --ff-only origin master`
2. `python main.py upgrade --env prod`（给 `open_client` 加开关字段）
3. `python scripts/check_retail_migration.py`（离线校验可升可降）
4. `python scripts/check_platform_analysis_access.py`（打印各应用是否已开通）
5. 重启后端

预演（10 秒，不执行）：

```bash
python deploy/platform-analysis-api-20261027/update.py
```

## 3. 前端（开关所在页面）

```bash
python deploy/platform-analysis-api-20261027/update.py --apply --service fastapiadmin \
  --build-frontend --frontend-target /usr/share/nginx/html
```

没有 Node 时本机构建后上传 `frontend/web/dist/*`。

## 4. 开通步骤（管理员）

1. 「系统管理 → 开放接口应用」编辑目标应用（如 `apipost_test`）；
2. 打开「平台渠道分析」开关，保存；
3. 让对方用原 `app_id` / `app_secret` 换令牌后调用，无需重置密钥。

命令行确认：

```bash
cd backend
python scripts/check_platform_analysis_access.py
```

## 5. 自测

```bash
python deploy/platform-analysis-api-20261027/test_platform_analysis.py \
  --app-id apipost_test --app-secret <secret> --period 2026-10
```

预期：先打印「换令牌成功」，再打印 `TOTAL:` 与明细；未开开关时返回
`{"code":40102,...}` 并提示去开开关。

## 6. 回滚

```bash
bash deploy/platform-analysis-api-20261027/ROLLBACK.sh
```

回滚只删除 `open_client.allow_platform_analysis` 字段，接口随即对所有应用返回 403；
不影响零售订单/售后/指标数据。
