# 零售售后/退货退款同步（2026-10-27）

## 1. 本次新增

| 项 | 内容 |
| --- | --- |
| 表 | `retail_after_sale`、`retail_after_sale_item`（迁移 `b0f396df56ac`，基于 `retailshop01`） |
| 开放接口 | `POST /open/v1/retail/aftersales/sync`（免鉴权，淘系走奇门推送） |
| 管理端接口 | `GET /retail/aftersales/page`、`GET /retail/aftersales/{id}`、`POST /retail/aftersales/pull` |
| 定时任务 | 聚水潭售后 每 10 分钟增量 + 每日 00:00/07:00/12:00/18:00 补偿 7 天 |
| 脚本 | `scripts/sync_jushuitan_refunds.py`、`scripts/check_retail_data.py`（新增售后统计） |
| 页面 | 零售订单同步 → 新增「退款售后」页签（**不需要新菜单**） |

## 2. 服务器更新

在服务器项目根目录执行：

```bash
python deploy/retail-aftersale-20261027/update.py --apply --service fastapiadmin
```

脚本按顺序执行：

1. `git pull --ff-only origin master`
2. `python main.py upgrade --env prod`（建两张售后表）
3. `python scripts/check_retail_migration.py`（离线校验可升可降）
4. `python scripts/check_retail_data.py`（打印 `AFTER_SALES=...`）
5. `python scripts/sync_jushuitan_refunds.py --recent-days 7`（失败不阻断）
6. 重启后端

先预演，确认命令无误再加 `--apply`：

```bash
python deploy/retail-aftersale-20261027/update.py
```

## 3. 前端

服务器有 Node/pnpm 时：

```bash
python deploy/retail-aftersale-20261027/update.py --apply --service fastapiadmin \
  --build-frontend --frontend-target /usr/share/nginx/html
```

没有 Node 时，本机构建后把 `frontend/web/dist/*` 上传到 nginx 站点目录：

```bash
cd frontend/web
pnpm install
pnpm run build:prod
```

**「退款售后」是「零售订单同步」页面里的新页签，沿用原菜单与权限**：
查询用 `module_retail:order:query`，手动同步用 `module_retail:shop:sync`。
所以不需要执行 `seed_retail_menu.py`，也不需要给角色重新授权。

发布后确认新包已上线：

```bash
grep -l "retail/aftersales/page" /usr/share/nginx/html/js/*.js
```

## 4. 接口自测

免鉴权，直接推测试数据（虚构数据）：

```bash
curl -X POST "http://120.237.174.243:6479/open/v1/retail/aftersales/sync" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: as-test-20261027-001" \
  --data-binary @deploy/retail-aftersale-20261027/test_aftersale_sync.json
```

预期：

```json
{"code":0,"msg":"零售售后单同步完成","data":{"received":2,"created":2,"failed":0,"item_count":2,"periods":["2026-10"]}}
```

重复提交同一个 `X-Request-ID` 返回 `duplicate=true`；换 ID 再推同一份数据返回
`unchanged=2`（内容未变化不重复计数）。

页面查看：**开放接口 → 零售订单同步 → 退款售后**，期间选 `2026-10`。

## 5. 非淘系售后从聚水潭拉取

```bash
cd backend
python scripts/sync_jushuitan_refunds.py --recent-days 7
python scripts/sync_jushuitan_refunds.py --period 2026-10
python scripts/sync_jushuitan_refunds.py --period 2026-10 --dry-run
```

聚水潭售后接口（docType=9&docId=38）不返回淘系售后单，淘系必须走奇门推送
`/open/v1/retail/aftersales/sync`。

## 6. 回滚

```bash
bash deploy/retail-aftersale-20261027/ROLLBACK.sh
```

或手动：

```bash
cd backend
python main.py downgrade --env prod -1
git revert --no-edit <本次提交>
```

回滚只删两张售后表，不影响 `retail_order` / `retail_shop` 与已推送订单数据。
