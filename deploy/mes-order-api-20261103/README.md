# MES 订单信息开放接口（2026-11-03）

## 改了什么

新增 MES 专用只读接口：

```
GET /open/v1/mes/orders
```

返回字段：CRM 订单号、客户名称、负责工程、产品系列、产品型号、产品尺寸、数量、贸易类型、接单日期。

查询条件：CRM 订单号、客户名称、负责工程、产品系列、产品型号、产品尺寸、贸易类型。

## 代码位置

| 文件 | 作用 |
| --- | --- |
| `backend/app/modules/mes/open_controller.py` | 路由与权限校验 |
| `backend/app/modules/mes/service.py` | 订单宽表查询、最新版本、过滤 |
| `backend/app/modules/mes/schema.py` | 参数与返回结构 |
| `backend/app/api/open/v1/routers.py` | 注册 `/open/v1/mes/orders` |
| `backend/app/modules/order/fields.py` | 新增负责工程字段定义 |
| `backend/app/modules/order/build.py` | 新构建订单自动写入负责工程 |
| `backend/scripts/backfill_order_engineer.py` | 历史订单负责工程回填 |
| `backend/scripts/seed_mes_open_client.py` | 创建 MES 接入应用 |
| `docs/MES订单信息开放接口对接说明.md` | 第三方对接文档 |

## 服务器执行（conda，不用 Docker）

### 1. 更新代码

```bash
git pull
```

### 2. 回填历史负责工程

```bash
cd backend
python scripts/backfill_order_engineer.py
python scripts/backfill_order_engineer.py --apply
```

预演输出 `待写入 N 行`，确认后执行 `--apply`。新订单由每日构建自动写入，不需要每天回填。

### 3. 创建 MES 应用

```bash
python scripts/seed_mes_open_client.py \
  --app-id mes \
  --name "MES 系统" \
  --ip-whitelist <MES出口IP> \
  --rate-limit 600
```

保存输出的 `app_secret`（只显示一次）。

### 4. 重启后端

按服务器现有方式重启后端进程。

### 5. 验证

```bash
curl "http://120.237.174.243:6479/open/v1/mes/orders?page_no=1&page_size=1" \
  -H "Authorization: Bearer <access_token>"
```

预期：HTTP 200、`code=0`、`data.items` 有数据、`engineer_name` 有值。

## 回滚

1. 回滚代码到上一版本并重启；
2. MES 停止调用；
3. `extra.engineer_code` / `extra.engineer_name` 为新增 JSON 字段，保留不影响旧功能；
4. 无删表、删数据、无数据库结构变更。

## 说明

- 只返回内贸/外贸正常订单，排除零售单（`LS` 开头）和作废单（`status=522`）；
- 每期只返回最新计算版本；
- 复用开放接口 `allow_order_detail` 权限，MES 应用需开启该权限；
- 历史数据回填是一次性操作，接口本身不修改 CRM。
