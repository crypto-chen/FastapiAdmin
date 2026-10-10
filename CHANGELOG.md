# 更新日志

记录 FastapiAdmin 的显著变更。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### 重构
- **2026-09-06** 全线 README 校正（根 / backend / web / 小程序 / 文档工程）
- **2026-09-06** 定时任务与存储路由重构：`app/api/v1/routers.py` 表驱动挂载，新增存储域控制器
- **2026-09-06** 后端模块结构调整：业务模块从 `api/v1` 下沉至 `app/modules/`；调度器优雅停机逻辑合并至 `SchedulerUtil.shutdown()`；健康检查路由调整
- **2026-09-03** 存储与工作流模块重构，调整目录结构与初始化逻辑

### 新增
- **2026-10-09** 新增《业务员指标开放接口对接说明》生成脚本 `backend/scripts/gen_person_metric_api_doc.py`（读 `metric_def` 分类「营销中心-业务员」+ `metric_value` 真实结果，输出 `docs/业务员指标开放接口对接说明.md`：接入三步、16 个指标清单与口径、请求参数、真实长表/宽表/合计样例、字段说明、口径注意事项、错误码），业务员指标变动后重跑即可刷新
- **2026-10-09** 新增服务器上线配套：`backend/scripts/backfill_person_metrics.py`（按期间回补业务员指标的取数与重算，已存在批次自动跳过，支持 `--refresh` / `--code`）与 `docs/业务员指标上线部署说明.md`（备份 → 传代码 → 重建启动 → 建指标任务 → 回补历史 → 开对接权限 → 校验 → 出文档，含回滚与常见问题）
- **2026-10-09** 新增业务员指标的 SQL 导出脚本 `backend/scripts/export_person_metrics_sql.py`：生成 `deploy/person-metrics/01_schema.sql`（表结构、按 information_schema 判重，MySQL 8 无 ADD COLUMN IF NOT EXISTS 的替代写法）、`02_defs.sql`（CRM 连接/来源系统/6 个来源对象/6 个同步任务/16 个指标定义，全部按业务唯一键幂等）、`03_values.sql`（可选结果快照，含按期间的 DELETE 守卫）；三个文件均已在本地库验证可重复执行
- **2026-10-09** 营销中心**业务员分析指标**（按年月 × 业务员）：新增引擎取数类型 `crm_person_amount`（订单明细按 `create_id` 分组）与 `crm_shipment_person_amount`（发货明细 × 订单未税单价，订单明细 12 期回看），指标结果写入 `metric_value`（新增 `person_code` / `person_name`，`dept_code` 存业务员编码）；首批 3 个指标 `marketing_person_order_intake_untaxed`(STF-13 接单未税)、`marketing_person_goods_shipment_untaxed`(STF-14 货物出货未税)、`marketing_person_design_service_income`(STF-15 设计服务收入)，来源 CRM `/hs/order/orderAnalyze`、`/hs/order/orderShipments`，初始化脚本 `backend/scripts/seed_crm_person_metrics.py`
- **2026-10-09** 业务员指标扩充到 6 个：新增 `crm_order_push_person` 取数类型（按 **ERP 下推时间** 落在当期过滤，`stat=amount` 出下推金额、`stat=period_days` 出下推周期；平均周期按「Σ天数 ÷ Σ订单数」在业务员与公司两层加权，不把各人平均值相加），`crm_shipment_person_amount` 增加 `value_mode`（`amount` 金额 / `qty` 数量）；新增 `marketing_person_goods_shipment_qty`(STF-68 出货数量)、`marketing_person_order_push_untaxed`(STF-23 下推金额)、`marketing_person_order_push_period`(STF-24 下推周期)
- **2026-10-09** 业务员指标扩充到 10 个：取数执行器支持 `row_filters` 行过滤（按 `order_type` / `is_new` 等字段拆分口径）；新增 `marketing_person_sample_order_intake_untaxed`(STF-38 打样接单业绩)、`marketing_person_batch_order_intake_untaxed`(STF-39 批量接单业绩)、`marketing_person_new_customer_intake_untaxed`(STF-40 新客户业绩)、`marketing_person_old_customer_intake_untaxed`(STF-41 老客户业绩)
- **2026-10-09** 业务员指标扩充到 11 个：`crm_person_amount` 增加 `value_mode`（`amount` 金额 / `count_orders` 订单数 / `count_customers` 客户去重数），客户数按业务员去重、公司合计取全部业务员客户并集（同一客户被多人跟过只算一次）；新增 `marketing_person_old_customer_order_count`(STF-48 本月下单老客户数量，`is_new=2` 客户去重)；开放接口 `total_only=true` + `level=person` 改为取公司合计层（避免把平均值/去重计数按业务员行相加）
- **2026-10-09** 业务员指标扩充到 13 个：新增 CRM 客户列表数据源 `/hs/customer/getCusotmerList`（每周一 02:00 同步全量快照，计算时按期间自动回补）与取数类型 `metric_ratio_person`（分子/分母都是业务员维度指标，**按业务员分别相除**，公司合计 = Σ分子 ÷ Σ分母）；新增 `marketing_person_total_customer_count`(STF-47 总客户数量，按客户表 `principal_id` 归属、未分配业务员不计入)、`marketing_person_repurchase_rate`(STF-49 复购率 = STF-48 ÷ STF-47)
- **2026-10-09** 业务员指标扩充到 16 个：新增 CRM 报价单明细数据源 `/hs/quote/getQuoteList`（按 `month` 取已审核报价单，接口额外返回 `create_id`）与取数类型 `crm_quote_person`（`stat` = `count` 报价次数 / `success_rate` 报价成功率 / `gross_profit_rate` 报价毛利率，比率均按业务员分别相除、公司合计按 Σ分子 ÷ Σ分母）；新增 `marketing_person_quote_count`、`marketing_person_quote_success_rate`、`marketing_person_quote_gross_profit_rate`
- **2026-10-09** 业务员指标扩充到 18 个：新增 `marketing_person_order_count`（业务员接单量 = 当期有效订单条数，客单价分母）与 `marketing_person_order_price`（STF-50 客单价 = 接单未税 ÷ 接单量，走 `metric_ratio_person` 按业务员分别相除）
- **2026-10-09** 业务员指标扩充到 19 个：`crm_order_push_person` 增加 `period_filter`（=false 表示不看时间、只按行过滤，用于存量类指标）；新增 `marketing_person_unship_order_inventory`（STF-25 库存 = 业务员名下未出货订单（`chuhuo != 1`）的有效订单未税金额，24 期回看；订单明细无成本字段，暂以未税金额作库存金额口径）
- **2026-10-09** 业务员指标扩充到 20 个：新增 `marketing_person_return_refund_untaxed`（STF-16 退货退款，负数入账）；数据源为 CRM《退款订单明细》`/hs/getReturnOrderDetail`（按 `status=522` + 订单创建月过滤，内贸 `account` / 外贸 `receivable_CNY`，按退款单 `create_id` 分组），同步任务 job 75 已启用——该路由曾一度 404 未发布，发布后实测 2026-09 明细 4 条合计 5,658.99，与公司口径 `/hs/getReturnOrder` 完全一致；元数据同步与指标引擎兼容 `{"data": {"data": [...]}}` 双层响应结构
- **2026-10-09** 业务员指标扩充到 21 个：新增取数类型 `metric_sum_person`（若干业务员维度指标**按业务员分别相加**，公司合计 = Σ各业务员，缺项按 0）与指标 `marketing_person_external_shipment_net_untaxed`（STF-17 对外出货净额 = STF-14 货物出货未税 + STF-15 设计服务收入 + STF-16 退货退款（负数））；2026-09 = 9,256,683.87，业务员逐人校验 56/56 一致
- **2026-10-09** 业务员指标扩充到 22 个：`metric_sum_person` 增加 `scale` 折算（先按业务员相加再乘系数）；新增 `marketing_person_settlement_income`（STF-18 营销结算收入10% = 对外出货净额 × 10%，按业务员分别折算；2026-09 = 925,668.39，业务员逐人校验 0 差异）
- **2026-10-09** 业务员指标扩充到 23 个：新增取数类型 `metric_alloc_person`（业务员基数 ÷ 分摊基数总额 × 待分摊费用池，`base_metric_codes` 留空则用 Σ业务员基数，即按占比全额分摊）与指标 `marketing_person_variable_expense_allocation`（STF-26 变动费用分摊 = STF-18 ÷ ORD-01 × CM-01；2026-09 = 27,421.31；**口径已确认保持以 ORD-01 为分母**，分摊合计小于费用池属预期）
- **2026-10-10** 业务员指标扩充到 24 个：新增 `marketing_person_fixed_expense_allocation`（STF-28 固定费用分摊 = STF-18 ÷ ORD-01 × CM-04 固定费用合计；2026-09 = 17,866.54，口径与 STF-26 一致、业务员逐人校验 0 差异）
- **2026-10-09** 开放接口支持**业务员维度**：`POST /open/v1/metrics/query` 新增 `level=person` 与 `person_codes` / `person_ids` 过滤，返回行补 `person_id`（业务员主ID，内部标准人员）/ `person_code` / `person_name`（宽表同名列），接入应用新增权限开关 `open_client.allow_person_detail`
- **2026-10-09** 指标结果页新增「业务员明细」视图：层级筛选增加 `person`（对应后端 `level=person`），表格在含业务员行时自动多显示一列「业务员」，合计行按「有组织合计行则用它、否则累加业务员行」取值（`frontend/web/src/views/module_metric/value/index.vue`）
- **2026-10-09** CRM 人员同步改为两个**手动任务**（不注册定时任务）：「同步 CRM 人员架构」（来源组织+部门）与「同步 CRM 人员」（来源人员）。入口三处共用 `backend/app/modules/crm/personnel_sync.py`：人工绑定页两个按钮、接口 `POST /system-mapping/sync/crm-org` 与 `/sync/crm-person`（权限 `module_mapping:sync:org|person`）、脚本 `python scripts/sync_crm_personnel.py --target {org|person|all}`
- **2026-10-09** 「系统映射管理」新增「系统标准人员」菜单与页面：维护内部标准人员 `master_person`（查询/新增/编辑/单条与批量删除），前端页面 `frontend/web/src/views/module_masterdata/person/index.vue` + 接口封装 `frontend/web/src/api/module_masterdata/index.ts`，菜单与按钮权限由 `backend/scripts/seed_system_mapping_menu.py` 初始化
- **2026-10-09** 同步 CRM 组织架构与人员主数据：新增解析模块 `backend/app/modules/crm/org_person.py` 与同步脚本 `backend/scripts/sync_crm_personnel.py`（`GET /hs/base/getDepartment` + `GET /hs/base/getPersonnel` → `source_org` / `source_dept` / `source_person`，来源类型 `crm`，脚本幂等、支持 `--dry-run`），并补解析规则单测 `backend/tests/test_crm_personnel_sync.py`
- **2026-08-19** 存储模块（文件浏览 / 传输 / 工作流）、内部聊天与工作流功能增强

### 优化
- **2026-10-09** 修复「元数据配置 → 指标定义」列表整体报错：`MetricDefOutSchema` 沿用了创建校验的 `description` 500 字上限，而库中该列是 Text、初始化脚本会直写长篇口径说明（`seed_crm_person_metrics.py` 实测 508 字），输出校验失败让整页分页 500，前端表现为「组件渲染异常」。输出不再校验长度，写入上限同步放宽到 4000 字（`backend/app/modules/metric/schema.py`），并补回归用例 `test_page_tolerates_description_over_create_limit`
- **2026-10-09** 修复 CRM 客户端路径查询串被丢弃：`CrmClient.call` 传入 `params` 时 httpx 会整体替换 URL 上的查询串，导致 `/hs/order/orderAnalyze?type=2` 退化为默认内贸（外贸数据被静默写成内贸）；现在先把路径查询串并入 `params`，`/hs/push/getPush?type=2` 这类按参数拆分的来源对象同样受益
- **2026-10-09** 元数据同步与指标引擎支持 CRM 明细数组：`extract_payload_rows` / `_payload_rows` 兼容 `data` 为数组的响应（订单 / 发货明细），同步日志行数按数组长度登记
- **2026-08-16** Auth IP 归属地处理优化，缓存与展示调整
- **2026-08-13** 前端统一使用设计令牌替换硬编码颜色值
- **2026-08-11** 小程序统一 `wd-text` 组件，优化页面配置

## [3.0.0] - 2026-08-10

### 新增
- 项目初始基础结构与配置
- 控制台启动状态显示数据库类型
