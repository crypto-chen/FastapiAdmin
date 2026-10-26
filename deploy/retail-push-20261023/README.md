# 零售数据推送接口 + 管理页面更新（2026-10-23）

## 1. 服务器更新

在服务器项目根目录执行：

```bash
python deploy/retail-push-20261023/update.py --apply --service fastapiadmin
```

脚本按顺序执行：

1. `git pull --ff-only origin master`
2. `python main.py upgrade --env prod`
3. `python scripts/seed_retail_push_job.py`
4. `python scripts/seed_retail_menu.py`
5. `python scripts/check_retail_migration.py`
6. 重启 `fastapiadmin`（如指定 `--service`）

先预演：

```bash
python deploy/retail-push-20261023/update.py
```

## 2. 前端

服务器有 Node/pnpm 时：

```bash
python deploy/retail-push-20261023/update.py --apply --service fastapiadmin \
  --build-frontend --frontend-target /usr/share/nginx/html
```

如果由 FastAPI 直接托管前端，把 `--frontend-target` 换成 `backend/dist`。

服务器没有 Node 时，本机构建后上传 `frontend/web/dist` 到现有 nginx 站点目录：

```bash
cd frontend/web
pnpm install
pnpm run build:prod
```

更新后重新登录后台，左侧菜单：**开放接口 → 零售订单同步**。

## 3. 同步测试

接口不需要 token：

```bash
python deploy/retail-push-20261023/test_sync.py
```

也可以直接 curl：

```bash
curl -L -X POST "http://120.237.174.243:6479/open/v1/retail/orders/sync" \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: retail-test-20261023-001" \
  --data-binary @deploy/retail-push-20261023/test_retail_sync.json
```

预期：

```json
{"code":0,"data":{"received":2,"created":2,"failed":0,"periods":["2026-10"]}}
```

重复提交同一 `X-Request-ID` 会返回 `duplicate=true`。

测试数据为虚构订单（店铺/买家/地址均为测试值），可在页面筛选期间 `2026-10` 查看。

## 4. 页面不显示「零售订单同步」排查

前端打包只更新页面文件，**菜单由后端数据库注册**。按顺序检查：

```bash
cd backend
ENVIRONMENT=prod python scripts/check_retail_data.py
ENVIRONMENT=prod python scripts/check_retail_menu.py
ENVIRONMENT=prod python scripts/seed_retail_menu.py
```

- 输出应包含 `零售订单菜单 id=...`；没有输出或报父菜单错误，先执行 `ENVIRONMENT=prod python scripts/seed_openapi_menu.py`。
- 菜单只绑定 `SUPER_ADMIN` / `ADMIN`；用其他角色登录时需要到「系统管理 → 角色 → 菜单权限」勾选。
- 注册菜单后**退出重新登录**（菜单在前端登录时加载并缓存）。
- 确认发布目录是正在使用的 nginx 站点目录，且新 `dist` 里包含页面：

```bash
grep -R "retail/orders/page" /usr/share/nginx/html/assets | head
```

没有结果说明发布目录仍是旧 `dist`；重新构建并复制 `frontend/web/dist/*`。

## 5. 非淘系订单从聚水潭拉取

淘系走奇门，非淘系走聚水潭「订单查询」`/open/orders/single/query`：

```bash
cd backend
python scripts/sync_jushuitan_orders.py --name "聚水潭默认连接" --period 2026-10
```

先只取数验证：

```bash
python scripts/sync_jushuitan_orders.py --name "聚水潭默认连接" --period 2026-10 --dry-run
```

建议每日拉取最近 7 天，更新 `WaitConfirm → Delivering/Sent` 状态：

```bash
python scripts/sync_jushuitan_orders.py --name "聚水潭默认连接" \
  --begin "2026-10-19 00:00:00" --end "2026-10-26 23:59:59" --date-type 0
```

后端启动后会自动注册：**每 10 分钟拉最近 30 分钟**，以及 **每天 02:10 拉最近 7 天**。
只需重启后端，不需要额外配置 Windows 任务计划。
