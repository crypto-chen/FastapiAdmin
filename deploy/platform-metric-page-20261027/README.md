# 指标中心 → 平台分析（2026-10-27）

## 1. 本次新增

| 项 | 内容 |
| --- | --- |
| 菜单 | **指标中心 → 平台分析**（`/metric/platform`，权限 `module_metric:platform:query`） |
| 后端 | `app/modules/platform/*`：`/api/v1/platform/{fields,periods,platforms,page,stats}` |
| 前端 | `src/views/module_metric/platform/index.vue`（与产品线分析同版式） |
| 取数 | 实时汇总 `retail_order` + `retail_after_sale` + `retail_shop`，**不新建宽表** |

页面能力（与产品线分析一致）：

- 期间 / 平台 / 店铺编号 / 关键字筛选；
- 聚合层级：店铺明细 / 平台小计 / 全部（含总计行）；
- 显示字段多选（按 PLT-xx 编码，分组：维度/数量/金额/比率）；
- 汇总条：平台数、店铺数、订单/已发货、接单未税、出货未税、退货退款、净额、结算收入10%、退货率；
- 点行看全部字段；「字段说明」抽屉列口径；「平台排行」按净额排序。

指标口径：PLT-08 接单未税、PLT-09 货物出货未税（已发货订单）、PLT-11 退货退款
（取消单 + 发货后售后）、PLT-12 对外出货净额、PLT-13 营销结算收入 10%、PLT-37 退货率；
金额统一 ÷1.13（`RETAIL_TAX_RATE`），结算比例 `RETAIL_SETTLEMENT_RATE`。

## 2. 服务器更新

```bash
python deploy/platform-metric-page-20261027/update.py --apply --service fastapiadmin
```

脚本：`git pull` → `main.py upgrade`（本次无新迁移）→ `scripts/seed_platform_menu.py` → 重启。

预演（10 秒）：

```bash
python deploy/platform-metric-page-20261027/update.py
```

## 3. 前端

```bash
python deploy/platform-metric-page-20261027/update.py --apply --service fastapiadmin \
  --build-frontend --frontend-target /usr/share/nginx/html
```

没有 Node 时本机构建后上传 `frontend/web/dist/*`。发布后确认：

```bash
grep -l "platform/fields" /usr/share/nginx/html/js/*.js
```

## 4. 查看

登录后台 → **指标中心 → 平台分析**。首次进入自动选最新期间；
菜单只绑定 `SUPER_ADMIN` / `ADMIN`，其他角色需在「系统管理 → 角色 → 菜单权限」勾选。

## 5. 回滚

```bash
bash deploy/platform-metric-page-20261027/ROLLBACK.sh
```

只删菜单与角色绑定（代码保留）；加 `--with-code` 再回退代码。无数据库结构变更。
