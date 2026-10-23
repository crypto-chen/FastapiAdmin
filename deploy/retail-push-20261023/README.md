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
curl -X POST "http://120.237.174.243:6479/open/v1/retail/orders/sync" \
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
