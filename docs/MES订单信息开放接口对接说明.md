# MES 订单信息开放接口对接说明

> 版本：v1.0  
> 日期：2026-11-03  
> 接口用途：MES 只读拉取 CRM 内外贸订单信息  
> 服务地址：`http://120.237.174.243:6479`  
> 接口前缀：`/open/v1`

---

## 1. 对接方案概览

MES 通过独立开放接口读取 CRM 内外贸订单，不直接连接 CRM，也不访问核算系统管理端。

```
MES ──GET /open/v1/mes/orders──> 核算指标系统 ──读取──> 订单全链路宽表
                                      │
                                      └──数据来源：CRM orderAnalyze（内贸/外贸）
```

### 1.1 提供的数据

| 中文名 | 接口字段 | 说明 |
| --- | --- | --- |
| CRM 订单号 | `crm_order_no` | CRM `orderAnalyze.number` |
| 客户名称 | `customer_name` | CRM 客户主档名称 |
| 负责工程 | `engineer_name` | CRM `principal_engineering` 对应人员姓名 |
| 产品系列 | `product_series` | CRM 产品系列字典名称 |
| 产品型号 | `product_model` | CRM 产品型号字典名称（如 `H27A`） |
| 产品尺寸 | `product_size` | CRM 订单行 `size` |
| 数量 | `quantity` | CRM 订单行 `qty` |
| 贸易类型 | `trade_type` | `domestic` 内贸 / `export` 外贸（附加字段） |
| 接单日期 | `order_date` | CRM 接单日期（附加字段） |

### 1.2 数据范围

- 只返回 **内贸 + 外贸正常订单**；
- 排除零售订单（订单号 `LS` 开头、订单类型 3）；
- 排除 CRM 作废订单（`status=522`）；
- 同一订单只返回最新计算版本，不返回历史版本；
- 默认返回全部历史期间，按接单期间倒序、订单号倒序。

### 1.3 数据更新频率

- CRM 订单明细与订单宽表每天重建 **4 次**：`00:00 / 07:00 / 12:00 / 18:00`（Asia/Shanghai）；
- 每个轮次先同步 CRM，再重建最近 3 个期间；
- 新订单/变更通常在 **下一个轮次完成后** 可查，最长等待约 6 小时；
- 历史订单只有在 CRM 回补或重算后才会变化。

---

## 2. 接入步骤

### 第 1 步：申请应用凭证

向核算系统管理员提供：

1. 系统名称：`MES`
2. 调用方出口 IP（用于 IP 白名单）
3. 预计调用频率
4. 联系人

管理员创建应用后，会得到：

```
app_id     = mes
app_secret = 一次性明文密钥
```

> `app_secret` 只在创建/重置时显示一次，请放入 MES 的配置中心或密钥管理，不要写进代码仓库。

管理员可用以下命令创建（在 `backend/` 目录、conda 环境执行）：

```bash
python scripts/seed_mes_open_client.py --app-id mes --name "MES 系统" --ip-whitelist <MES出口IP>
```

如需限制只能看内贸或外贸：

```bash
python scripts/seed_mes_open_client.py --app-id mes --trade-type domestic
python scripts/seed_mes_open_client.py --app-id mes --trade-type export
```

### 第 2 步：换取访问令牌

```http
POST /open/v1/auth/token
Content-Type: application/json

{
  "app_id": "mes",
  "app_secret": "<密钥>"
}
```

成功响应：

```json
{
  "code": 0,
  "msg": "获取令牌成功",
  "data": {
    "access_token": "eyJhbGciOi...",
    "token_type": "Bearer",
    "expires_in": 7200
  },
  "status_code": 200,
  "success": true
}
```

后续业务接口统一带请求头：

```http
Authorization: Bearer <access_token>
```

建议：

- 令牌默认有效期 2 小时；
- 在过期前 5 分钟主动续期；
- 收到 `401` 时重新换令牌并重试一次；
- 不要每次请求都换令牌。

### 第 3 步：调用订单接口

```http
GET /open/v1/mes/orders
```

最小调用：

```bash
curl "http://120.237.174.243:6479/open/v1/mes/orders?page_no=1&page_size=200" \
  -H "Authorization: Bearer <access_token>"
```

---

## 3. 接口详情

### 3.1 请求地址

```
GET http://120.237.174.243:6479/open/v1/mes/orders
```

### 3.2 查询参数

所有参数可选，多个条件按 **AND** 组合；字符串条件均为模糊匹配（包含即可）。

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `crm_order_no` | string | 否 | - | CRM 订单号，模糊匹配 |
| `customer_name` | string | 否 | - | 客户名称，模糊匹配 |
| `engineer_name` | string | 否 | - | 负责工程姓名，模糊匹配 |
| `product_series` | string | 否 | - | 产品系列，模糊匹配 |
| `product_model` | string | 否 | - | 产品型号，模糊匹配 |
| `product_size` | string | 否 | - | 产品尺寸，模糊匹配 |
| `trade_type` | string | 否 | 全部 | `domestic` 内贸 / `export` 外贸 |
| `page_no` | int | 否 | 1 | 页码，从 1 开始 |
| `page_size` | int | 否 | 200 | 每页条数，最大 1000 |

示例：

```
GET /open/v1/mes/orders?engineer_name=黎胜华&trade_type=export&page_no=1&page_size=100
GET /open/v1/mes/orders?crm_order_no=DY202610-00005
GET /open/v1/mes/orders?customer_name=SubDude&product_model=K22C
```

### 3.3 成功响应

```json
{
  "code": 0,
  "msg": "查询 MES 订单成功",
  "data": {
    "total": 34892,
    "page_no": 1,
    "page_size": 200,
    "has_more": true,
    "schema_version": "2026-11-03",
    "items": [
      {
        "crm_order_no": "PL202610-02941",
        "customer_name": "埃尔利德（广东）智能科技有限公司",
        "engineer_name": "胡嘉怡",
        "product_series": "H系列",
        "product_model": "H30A",
        "product_size": "147-41-100",
        "quantity": 100.0,
        "trade_type": "domestic",
        "order_date": "2026-10-31"
      }
    ]
  },
  "status_code": 200,
  "success": true
}
```

> 上述 `total` 为当前库示例值，实际以响应为准。

### 3.4 返回字段

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `total` | int | 否 | 满足条件的总条数 |
| `page_no` | int | 否 | 当前页码 |
| `page_size` | int | 否 | 每页条数 |
| `has_more` | bool | 否 | 是否还有下一页 |
| `schema_version` | string | 否 | 字段版本，变更时更新 |
| `items[].crm_order_no` | string | 否 | CRM 订单号 |
| `items[].customer_name` | string | 是 | 客户名称 |
| `items[].engineer_name` | string | 是 | 负责工程姓名 |
| `items[].product_series` | string | 是 | 产品系列 |
| `items[].product_model` | string | 是 | 产品型号 |
| `items[].product_size` | string | 是 | 产品尺寸 |
| `items[].quantity` | number | 是 | 数量 |
| `items[].trade_type` | string | 是 | `domestic` / `export` |
| `items[].order_date` | date | 是 | 接单日期 `YYYY-MM-DD` |

### 3.5 分页建议

- 首次全量同步：`page_size=1000`，从 `page_no=1` 递增，直到 `has_more=false`；
- 日常增量：按订单号或客户名称查询，不建议每次全量拉取；
- 全量约 3.5 万条，按 1000/页约 35 次请求；
- 单次请求超时建议 30 秒。

---

## 4. 字段来源与口径

| 接口字段 | CRM 来源 | 处理说明 |
| --- | --- | --- |
| `crm_order_no` | `orderAnalyze.number` | 原样返回 |
| `customer_name` | `orderAnalyze.customer` → `getCusotmerList.name` | 客户主档优先，订单自带名称兜底 |
| `engineer_name` | `orderAnalyze.principal_engineering` → CRM 人员姓名 | 与业务员 `create_id` 使用同一套人员索引 |
| `product_series` | `orderAnalyze.product_series` → 产品系列字典 | 返回字典名称，不返回编码 |
| `product_model` | `orderAnalyze.product_model` → 产品型号字典 | 返回型号名称（如 `H27A`） |
| `product_size` | `orderAnalyze.size` | 原样返回 |
| `quantity` | `orderAnalyze.qty` | 数值型 |
| `trade_type` | `orderAnalyze` 来源类型 | `domestic` / `export` |
| `order_date` | `orderAnalyze.createtime` | 接单日期 |

### 4.1 空值说明

- CRM 本身没有维护时，字段返回 `null`；
- 负责工程为空时，先确认该订单 CRM 是否填写 `principal_engineering`；
- 产品型号为空时，确认 CRM 型号字典是否匹配；
- 接口不会用业务员、客户负责人等字段替代负责工程。

---

## 5. 鉴权与错误处理

### 5.1 业务状态码

判断成功请用 `code == 0` 或 `success == true`，不要用 `code == 200`。

| HTTP | `code` | 含义 | MES 处理 |
| --- | --- | --- | --- |
| 200 | 0 | 成功 | 正常解析 |
| 400 | - | 参数格式错误 | 修正参数，不要重试 |
| 401 | 40100 | 未带令牌 / 令牌无效 / 过期 | 重新换令牌后重试一次 |
| 403 | 40101 | 应用停用、IP 不在白名单、无订单权限 | 联系管理员 |
| 403 | 40102 | 指标权限不足 | 与 MES 无关 |
| 429 | 40103 | 调用频率超限 | 按提示等待后重试 |

### 5.2 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `401` 缺少 Authorization | 未带令牌 | 加 `Authorization: Bearer <token>` |
| `401` 令牌已过期 | 超过 2 小时 | 重新换令牌 |
| `403` IP 不在白名单 | MES 出口 IP 变化 | 把新出口 IP 加入白名单 |
| `403` 应用未开通订单查询权限 | 创建时未开 `allow_order_detail` | 管理员在开放应用里开启 |
| `429` | 超过每分钟配额 | 降低频率或申请提高配额 |
| 查不到刚下的订单 | 尚未到下一个同步轮次 | 等下一轮（00/07/12/18 点后）再查，或联系管理员手动同步 |
| `engineer_name` 为空 | 历史数据未回填或 CRM 未填 | 管理员执行回填脚本 |
| `400 Invalid host header` | 反向代理/应用未放行该 IP 或域名 | 把 `120.237.174.243` 加入 `ALLOWED_HOSTS` |

---

## 6. 调用示例

### 6.1 Python

```python
import httpx

BASE = "http://120.237.174.243:6479"
APP_ID = "mes"
APP_SECRET = "<密钥>"

with httpx.Client(timeout=30) as client:
    token_resp = client.post(
        f"{BASE}/open/v1/auth/token",
        json={"app_id": APP_ID, "app_secret": APP_SECRET},
    )
    token_resp.raise_for_status()
    token = token_resp.json()["data"]["access_token"]

    headers = {"Authorization": f"Bearer {token}"}
    page_no = 1
    while True:
        resp = client.get(
            f"{BASE}/open/v1/mes/orders",
            headers=headers,
            params={"page_no": page_no, "page_size": 1000},
        )
        resp.raise_for_status()
        body = resp.json()
        data = body["data"]
        for item in data["items"]:
            print(item["crm_order_no"], item["customer_name"], item["engineer_name"])
        if not data["has_more"]:
            break
        page_no += 1
```

### 6.2 C#

```csharp
using System.Net.Http.Headers;
using System.Net.Http.Json;

var baseUrl = "http://120.237.174.243:6479";
using var http = new HttpClient { Timeout = TimeSpan.FromSeconds(30) };

var tokenResp = await http.PostAsJsonAsync($"{baseUrl}/open/v1/auth/token", new {
    app_id = "mes",
    app_secret = "<密钥>"
});
tokenResp.EnsureSuccessStatusCode();
var tokenJson = await tokenResp.Content.ReadFromJsonAsync<TokenResponse>();

http.DefaultRequestHeaders.Authorization =
    new AuthenticationHeaderValue("Bearer", tokenJson.data.access_token);

var resp = await http.GetAsync(
    $"{baseUrl}/open/v1/mes/orders?page_no=1&page_size=1000");
resp.EnsureSuccessStatusCode();
var body = await resp.Content.ReadFromJsonAsync<OrderResponse>();
```

---

## 7. 服务器上线步骤（conda 环境）

> 以下命令均在项目 `backend/` 目录执行，不使用 Docker。

### 7.1 更新代码并重启

```bash
git pull
```

重启后端进程（按服务器现有方式，如系统服务或进程管理器）。

### 7.2 回填历史负责工程

首次上线执行一次；预演确认数量后再写库：

```bash
python scripts/backfill_order_engineer.py
python scripts/backfill_order_engineer.py --apply
```

预期输出示例：

```
完成：写入 34925 行，工程姓名缺失 0 行
```

> 新构建的订单会自动写入负责工程，无需每天执行回填。

### 7.3 创建 MES 接入应用

```bash
python scripts/seed_mes_open_client.py \
  --app-id mes \
  --name "MES 系统" \
  --ip-whitelist <MES出口IP> \
  --rate-limit 600
```

保存输出的 `app_secret`，只显示一次。

### 7.4 验证

```bash
curl "http://120.237.174.243:6479/open/v1/mes/orders?page_no=1&page_size=1" \
  -H "Authorization: Bearer <access_token>"
```

确认：

- HTTP 200；
- `code=0`；
- `data.items` 有数据；
- `engineer_name` 不为空（抽查有负责工程的订单）。

---

## 8. 安全与运维建议

1. **必须配置 IP 白名单**：只允许 MES 服务器出口 IP；
2. 生产环境建议通过 HTTPS/专线访问，避免明文传输密钥；
3. `app_secret` 放配置中心，定期轮换；
4. MES 侧只读，不要复用管理端账号；
5. 接口不返回金额、成本、毛利等敏感字段；
6. 调用日志可在核算系统管理端「开放接口-调用日志」查看；
7. 如出口 IP 变化，先更新白名单再切换流量。

---

## 9. 回滚方案

本接口为新增路由，不改动现有订单表和数据库结构：

1. 回滚代码到上一版本并重启；
2. MES 停止调用；
3. `extra.engineer_code` / `extra.engineer_name` 是新增 JSON 字段，保留不影响旧功能；
4. 如需完全清理回填字段，可按期间重新构建订单宽表覆盖最新版本；
5. 回滚不涉及删表、删数据。

---

## 10. 接口清单

| 方法 | 路径 | 用途 | 鉴权 |
| --- | --- | --- | --- |
| POST | `/open/v1/auth/token` | 应用凭证换令牌 | 否 |
| GET | `/open/v1/mes/orders` | MES 查询内外贸订单 | Bearer Token |

