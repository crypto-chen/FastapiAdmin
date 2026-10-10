-- ==========================================================================
-- 业务员指标 - 元数据 / 来源对象 / 同步任务 / 指标定义（幂等，可重复执行）
-- 生成时间：2026-10-10 10:28
-- 由 backend/scripts/export_person_metrics_sql.py 生成，请勿手工修改
-- 指标 29 个，来源对象 7 个，同步任务 7 个
-- 执行顺序：先 01_schema.sql，再本文件
-- 所有 INSERT 均按业务唯一键判重：连接按 name、来源系统/对象/指标按 code、同步任务按 name
-- ==========================================================================

SET NAMES utf8mb4;

-- 0) 确认目标库
SELECT DATABASE() AS current_db;

-- 1) CRM 连接（服务器已存在同名连接时跳过；指标沿用系统里已有的 CRM 连接）
INSERT INTO crm_connection
  (uuid, name, base_url, timeout, status, description, is_deleted, created_time, updated_time)
SELECT 'f91b02a5-7155-4b3b-b43b-c12b90a6a167', 'CRM 默认连接', 'http://crmapi.yonggubox.com', 30, 0, NULL, 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM crm_connection WHERE name = 'CRM 默认连接');

-- 2) 来源系统 CRM（按 code 幂等）
INSERT INTO meta_source_system
  (uuid, code, name, connector_type, connection_id, status, description, is_deleted, created_time, updated_time)
VALUES ('8ccec39e-7036-4bf6-8527-a3623ce5bf9b', 'crm', 'CRM', 'crm', (SELECT id FROM crm_connection WHERE name = 'CRM 默认连接' LIMIT 1), 0, 'CRM 订单/发货明细接口（业务员维度，无需鉴权）', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), connector_type = VALUES(connector_type),
  connection_id = VALUES(connection_id), status = VALUES(status), description = VALUES(description);

-- 3) 来源对象（业务员指标用到的 6 个 CRM 接口）

-- 来源对象 /hs/order/orderAnalyze?type=1
INSERT INTO meta_source_object
  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)
VALUES ('34dac713-e66c-41b3-a91a-cacb4134ba9e', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), '/hs/order/orderAnalyze?type=1', 'CRM 订单明细（内贸）', 'api', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, NULL, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),
  request_template = VALUES(request_template), status = VALUES(status);

-- 来源对象 /hs/order/orderAnalyze?type=2
INSERT INTO meta_source_object
  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)
VALUES ('49f25490-0b1c-406c-ade4-378474c97bf2', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), '/hs/order/orderAnalyze?type=2', 'CRM 订单明细（外贸）', 'api', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, NULL, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),
  request_template = VALUES(request_template), status = VALUES(status);

-- 来源对象 /hs/order/orderShipments?type=1
INSERT INTO meta_source_object
  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)
VALUES ('0baf369d-5588-4bd7-b9df-32a81abec861', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), '/hs/order/orderShipments?type=1', 'CRM 发货明细（内贸）', 'api', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, NULL, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),
  request_template = VALUES(request_template), status = VALUES(status);

-- 来源对象 /hs/order/orderShipments?type=2
INSERT INTO meta_source_object
  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)
VALUES ('d2345f68-260f-41db-a598-032b8aabfb09', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), '/hs/order/orderShipments?type=2', 'CRM 发货明细（外贸）', 'api', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, NULL, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),
  request_template = VALUES(request_template), status = VALUES(status);

-- 来源对象 /hs/customer/getCusotmerList
INSERT INTO meta_source_object
  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)
VALUES ('6e22bd33-5f4f-47fa-9a11-f059d7bde2eb', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), '/hs/customer/getCusotmerList', 'CRM 客户列表（业务员客户数）', 'api', '{}', NULL, NULL, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),
  request_template = VALUES(request_template), status = VALUES(status);

-- 来源对象 /hs/quote/getQuoteList
INSERT INTO meta_source_object
  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)
VALUES ('d9871b27-14de-472b-985c-10da0b6752da', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), '/hs/quote/getQuoteList', 'CRM 报价单明细（业务员报价）', 'api', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, NULL, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),
  request_template = VALUES(request_template), status = VALUES(status);

-- 来源对象 /hs/getReturnOrderDetail
INSERT INTO meta_source_object
  (uuid, system_id, code, name, query_type, request_template, variables, watermark_field, status, is_deleted, created_time, updated_time)
VALUES ('9047209b-ea6a-45d7-8c2e-e112cfb29117', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), '/hs/getReturnOrderDetail', 'CRM 退款订单明细（业务员退货退款）', 'api', '{"dateRange":["{{ now.replace(day=1).strftime(''%Y-%m-%d'') }}","{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime(''%Y-%m-%d'') }}"]}', NULL, NULL, 0, 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), query_type = VALUES(query_type),
  request_template = VALUES(request_template), status = VALUES(status);

-- 4) 同步任务（cron 与 seed 脚本一致：明细每天 02:00，客户列表每周一 02:00）

-- 同步任务 CRM业务员指标-CRM 订单明细（内贸）（cron 0 0 2 * * ?）
INSERT INTO meta_sync_job
  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,
   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)
SELECT '0b242e65-199d-48ef-9e30-49c5a72b60fa', 'CRM业务员指标-CRM 订单明细（内贸）', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), (SELECT o.id FROM meta_source_object o WHERE o.code = '/hs/order/orderAnalyze?type=1' LIMIT 1), NULL, NULL, '0 0 2 * * ?', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, 'full', NULL, 0, 'CRM 接口 /hs/order/orderAnalyze?type=1，按 month 取整月明细（未分页，单月约 1.3k 行）', 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = 'CRM业务员指标-CRM 订单明细（内贸）');

-- 同步任务 CRM业务员指标-CRM 订单明细（外贸）（cron 0 0 2 * * ?）
INSERT INTO meta_sync_job
  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,
   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)
SELECT 'b7a52302-915b-402e-90ef-539504d4fbd3', 'CRM业务员指标-CRM 订单明细（外贸）', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), (SELECT o.id FROM meta_source_object o WHERE o.code = '/hs/order/orderAnalyze?type=2' LIMIT 1), NULL, NULL, '0 0 2 * * ?', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, 'full', NULL, 0, 'CRM 接口 /hs/order/orderAnalyze?type=2，按 month 取整月明细（未分页，单月约 1.3k 行）', 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = 'CRM业务员指标-CRM 订单明细（外贸）');

-- 同步任务 CRM业务员指标-CRM 发货明细（内贸）（cron 0 0 2 * * ?）
INSERT INTO meta_sync_job
  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,
   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)
SELECT '354a850c-4247-4fb0-8606-d77ba56c32e7', 'CRM业务员指标-CRM 发货明细（内贸）', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), (SELECT o.id FROM meta_source_object o WHERE o.code = '/hs/order/orderShipments?type=1' LIMIT 1), NULL, NULL, '0 0 2 * * ?', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, 'full', NULL, 0, 'CRM 接口 /hs/order/orderShipments?type=1，按 month 取整月明细（未分页，单月约 1.3k 行）', 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = 'CRM业务员指标-CRM 发货明细（内贸）');

-- 同步任务 CRM业务员指标-CRM 发货明细（外贸）（cron 0 0 2 * * ?）
INSERT INTO meta_sync_job
  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,
   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)
SELECT 'e53f9812-207d-4c6e-a3ef-042d7acc0a34', 'CRM业务员指标-CRM 发货明细（外贸）', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), (SELECT o.id FROM meta_source_object o WHERE o.code = '/hs/order/orderShipments?type=2' LIMIT 1), NULL, NULL, '0 0 2 * * ?', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, 'full', NULL, 0, 'CRM 接口 /hs/order/orderShipments?type=2，按 month 取整月明细（未分页，单月约 1.3k 行）', 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = 'CRM业务员指标-CRM 发货明细（外贸）');

-- 同步任务 CRM业务员指标-CRM 客户列表（业务员客户数）（cron 0 0 2 ? * MON）
INSERT INTO meta_sync_job
  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,
   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)
SELECT '1832017a-fb48-47bd-9fab-a16bd6d5af04', 'CRM业务员指标-CRM 客户列表（业务员客户数）', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), (SELECT o.id FROM meta_source_object o WHERE o.code = '/hs/customer/getCusotmerList' LIMIT 1), NULL, NULL, '0 0 2 ? * MON', '{}', NULL, 'full', NULL, 0, 'CRM 接口 /hs/customer/getCusotmerList，按 month 取整月明细（未分页，单月约 1.3k 行）', 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = 'CRM业务员指标-CRM 客户列表（业务员客户数）');

-- 同步任务 CRM业务员指标-CRM 报价单明细（业务员报价）（cron 0 0 2 * * ?）
INSERT INTO meta_sync_job
  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,
   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)
SELECT '682fb51e-107d-46cf-8b6d-c3a098ab3f5e', 'CRM业务员指标-CRM 报价单明细（业务员报价）', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), (SELECT o.id FROM meta_source_object o WHERE o.code = '/hs/quote/getQuoteList' LIMIT 1), NULL, NULL, '0 0 2 * * ?', '{"month":"{{ now.strftime(''%Y-%m'') }}"}', NULL, 'full', NULL, 0, 'CRM 接口 /hs/quote/getQuoteList，按 month 取整月明细（未分页，单月约 1.3k 行）', 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = 'CRM业务员指标-CRM 报价单明细（业务员报价）');

-- 同步任务 CRM业务员指标-CRM 退款订单明细（业务员退货退款）（cron 0 0 2 * * ?）
INSERT INTO meta_sync_job
  (uuid, name, source_system_id, source_object_id, standard_entity_id, org_code, cron_expr,
   request_params, variables, sync_mode, watermark_field, status, description, is_deleted, created_time, updated_time)
SELECT '7f2e14e1-d17b-4ab6-bc7d-67f419441710', 'CRM业务员指标-CRM 退款订单明细（业务员退货退款）', (SELECT id FROM meta_source_system WHERE code = 'crm' LIMIT 1), (SELECT o.id FROM meta_source_object o WHERE o.code = '/hs/getReturnOrderDetail' LIMIT 1), NULL, NULL, '0 0 2 * * ?', '{"dateRange":["{{ now.replace(day=1).strftime(''%Y-%m-%d'') }}","{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)).strftime(''%Y-%m-%d'') }}"]}', NULL, 'full', NULL, 0, 'CRM 接口 /hs/getReturnOrderDetail，按 month 取整月明细（未分页，单月约 1.3k 行）', 0, NOW(), NOW()
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM meta_sync_job WHERE name = 'CRM业务员指标-CRM 退款订单明细（业务员退货退款）');

-- 5) 指标定义（16 个业务员指标，含 Excel 科目编码与取数配置）

-- 指标 - marketing_person_order_count
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('8696a1e9-94a2-4f32-800a-717d53313ad2', 'marketing_person_order_count', '营销中心业务员接单量', '营销中心-业务员', NULL, 'month', 0, '接单量（单）= 当期有效订单条数（status=384，剔除作废），内贸 + 外贸订单明细按订单创建月 createtime 落当期，按业务员（下单人 create_id）分组；不按订单类型/是否出货过滤，也不看金额。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"单","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"value_mode":"count_orders","person_field":"create_id","status_allow":["384"],"status_field":"status"}', NULL, 1, 0, '接单量（单）= 当期有效订单条数（status=384，剔除作废），内贸 + 外贸订单明细按订单创建月 createtime 落当期，按业务员（下单人 create_id）分组；不按订单类型/是否出货过滤，也不看金额。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-10 marketing_person_quote_count
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('8b8f7cb9-429b-456c-b1e8-cd359072cf67', 'marketing_person_quote_count', '营销中心业务员报价次数', '营销中心-业务员', 'STF-10', 'month', 0, '报价次数（次）= 当期已审核报价单（quote_bills.status=''E''）条数，按报价日期 date 落在当期，按业务员（报价单 create_id）分组。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_quote_person","stat":"count","unit":"次","group_by":"person","components":[{"label":"报价单","source_object_code":"/hs/quote/getQuoteList"}],"person_field":"create_id"}', NULL, 1, 0, '报价次数（次）= 当期已审核报价单（quote_bills.status=''E''）条数，按报价日期 date 落在当期，按业务员（报价单 create_id）分组。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-11 marketing_person_quote_success_rate
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('ac96ddfd-63e5-4cf8-aff4-b683a8130396', 'marketing_person_quote_success_rate', '营销中心业务员报价成功率', '营销中心-业务员', 'STF-11', 'month', 0, '报价成功率（%）= 已转订单的报价单数 ÷ 报价次数 × 100%，按业务员分别计算（接口 transformation=1 表示该报价单已关联有效内贸/外贸订单，status=384）；公司合计 = Σ已转单数 ÷ Σ报价次数 × 100；报价次数为 0 的业务员不输出行。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_quote_person","stat":"success_rate","unit":"%","group_by":"person","components":[{"label":"报价单","source_object_code":"/hs/quote/getQuoteList"}],"person_field":"create_id","transformation_allow":["1"],"transformation_field":"transformation"}', NULL, 1, 0, '报价成功率（%）= 已转订单的报价单数 ÷ 报价次数 × 100%，按业务员分别计算（接口 transformation=1 表示该报价单已关联有效内贸/外贸订单，status=384）；公司合计 = Σ已转单数 ÷ Σ报价次数 × 100；报价次数为 0 的业务员不输出行。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-12 marketing_person_quote_gross_profit_rate
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('bd666288-0815-4d70-9ae5-62b6de349027', 'marketing_person_quote_gross_profit_rate', '营销中心业务员报价毛利率', '营销中心-业务员', 'STF-12', 'month', 0, '报价毛利率（%）=（报价未税 −（材料成本 + 加工费））÷ 报价未税 × 100%，按业务员分别计算（公司合计 = Σ(未税 − 料工费) ÷ Σ未税 × 100）；接口字段 not_tax_all_quote_amount = 报价未税总价、material_labor_cost = 料工费；**注意**：当前接口的 material_labor_cost = materialCost × qty（含附件费、**不含** processCost 加工费），待 CRM 侧改成 (materialCost + processCost) × qty 后本指标自动按新口径取数，无需改本系统。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_quote_person","stat":"gross_profit_rate","unit":"%","group_by":"person","components":[{"label":"报价单","source_object_code":"/hs/quote/getQuoteList"}],"cost_field":"material_labor_cost","amount_field":"not_tax_all_quote_amount","person_field":"create_id"}', NULL, 1, 0, '报价毛利率（%）=（报价未税 −（材料成本 + 加工费））÷ 报价未税 × 100%，按业务员分别计算（公司合计 = Σ(未税 − 料工费) ÷ Σ未税 × 100）；接口字段 not_tax_all_quote_amount = 报价未税总价、material_labor_cost = 料工费；**注意**：当前接口的 material_labor_cost = materialCost × qty（含附件费、**不含** processCost 加工费），待 CRM 侧改成 (materialCost + processCost) × qty 后本指标自动按新口径取数，无需改本系统。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-13 marketing_person_order_intake_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('a9e50e29-19a0-4056-9253-f8e46bc49469', 'marketing_person_order_intake_untaxed', '营销中心业务员接单未税', '营销中心-业务员', 'STF-13', 'month', 0, '接单未税（元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，只统计有效订单 status=384（剔除作废 522），按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"元","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"person_field":"create_id","status_allow":["384"],"status_field":"status"}', NULL, 1, 0, '接单未税（元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，只统计有效订单 status=384（剔除作废 522），按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-14 marketing_person_goods_shipment_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('9bce28a7-7044-48b4-be75-8acb7a2e0352', 'marketing_person_goods_shipment_untaxed', '营销中心业务员货物出货未税', '营销中心-业务员', 'STF-14', 'month', 0, '货物出货未税（元）= Σ(发货数量 send_qty × 该订单未税单价)，未税单价 = 订单未税金额 ÷ 订单数量（内贸 remove_taxes_freight、外贸 receivable_CNY，status=384）；发货月按发货单审核月 check_date，业务员取所属订单的下单人 create_id；订单明细按 12 期回看，覆盖发货月之前创建的订单。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_shipment_person_amount","unit":"元","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"status_allow":["384"],"status_field":"status","order_source_object_code":"/hs/order/orderAnalyze?type=1","shipment_source_object_code":"/hs/order/orderShipments?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"receivable_CNY"}],"status_allow":["384"],"status_field":"status","order_source_object_code":"/hs/order/orderAnalyze?type=2","shipment_source_object_code":"/hs/order/orderShipments?type=2"}],"person_field":"create_id","lookback_periods":12,"backfill_lookback":true}', NULL, 1, 0, '货物出货未税（元）= Σ(发货数量 send_qty × 该订单未税单价)，未税单价 = 订单未税金额 ÷ 订单数量（内贸 remove_taxes_freight、外贸 receivable_CNY，status=384）；发货月按发货单审核月 check_date，业务员取所属订单的下单人 create_id；订单明细按 12 期回看，覆盖发货月之前创建的订单。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-15 marketing_person_design_service_income
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('e3d84700-85d1-4578-93e8-1438da29cd4d', 'marketing_person_design_service_income', '营销中心业务员设计服务收入', '营销中心-业务员', 'STF-15', 'month', 0, '设计服务收入（元）= Σ(内贸 design_remove_taxes_freight + 外贸 design_cost)，只统计有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组；当月无设计服务收入的业务员不输出行（按 0 处理）。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"元","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"design_remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"design_cost"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"person_field":"create_id","status_allow":["384"],"status_field":"status"}', NULL, 1, 0, '设计服务收入（元）= Σ(内贸 design_remove_taxes_freight + 外贸 design_cost)，只统计有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组；当月无设计服务收入的业务员不输出行（按 0 处理）。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-16 marketing_person_return_refund_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('a6a7cc0d-0914-43f1-bc3e-4ded022c9d8c', 'marketing_person_return_refund_untaxed', '营销中心业务员退货退款', '营销中心-业务员', 'STF-16', 'month', 0, '退货退款（元，**负数口径**）= Σ退款订单金额，按业务员（退款单 create_id）分组；数据源为 CRM《退款订单明细》`/hs/getReturnOrderDetail`（已按退款状态 status=522 + 订单创建月 createtime 过滤）；内贸取 account（= receivable − taxes，去税）、外贸取 receivable_CNY（人民币应收）；实测 2026-09 明细 4 条合计 5,658.99，与公司口径 /hs/getReturnOrder 完全一致。与公司口径「营销中心退货/退款（负数）」一致按负数入账，便于对外出货净额 = 出货未税 + 设计服务收入 + 退货退款（负数）。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"元","group_by":"person","components":[{"label":"退款订单明细","amount_terms":[{"sign":-1,"field":"account"},{"sign":-1,"field":"receivable_CNY"}],"source_object_code":"/hs/getReturnOrderDetail"}],"person_field":"create_id","status_allow":[],"status_field":null}', NULL, 1, 0, '退货退款（元，**负数口径**）= Σ退款订单金额，按业务员（退款单 create_id）分组；数据源为 CRM《退款订单明细》`/hs/getReturnOrderDetail`（已按退款状态 status=522 + 订单创建月 createtime 过滤）；内贸取 account（= receivable − taxes，去税）、外贸取 receivable_CNY（人民币应收）；实测 2026-09 明细 4 条合计 5,658.99，与公司口径 /hs/getReturnOrder 完全一致。与公司口径「营销中心退货/退款（负数）」一致按负数入账，便于对外出货净额 = 出货未税 + 设计服务收入 + 退货退款（负数）。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-17 marketing_person_external_shipment_net_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('3a86f3ed-87cf-4ebc-b6b6-2aa2fca099c5', 'marketing_person_external_shipment_net_untaxed', '营销中心业务员对外出货净额', '营销中心-业务员', 'STF-17', 'month', 0, '对外出货净额（元）= 货物出货未税（STF-14）+ 设计服务收入（STF-15）+ 退货退款（STF-16，负数），**按业务员分别相加**（kind=metric_sum_person，逐个业务员取三个组成指标的当期结果相加）；公司合计 = Σ各业务员；某个业务员当月没有某个组成指标的行时按 0 计入；三项口径同源（都按业务员维度算好后相加），与公司口径「营销中心对外出货未税销售额（净额）」一致。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_sum_person","unit":"元","component_metric_codes":["marketing_person_goods_shipment_untaxed","marketing_person_design_service_income","marketing_person_return_refund_untaxed"]}', NULL, 1, 0, '对外出货净额（元）= 货物出货未税（STF-14）+ 设计服务收入（STF-15）+ 退货退款（STF-16，负数），**按业务员分别相加**（kind=metric_sum_person，逐个业务员取三个组成指标的当期结果相加）；公司合计 = Σ各业务员；某个业务员当月没有某个组成指标的行时按 0 计入；三项口径同源（都按业务员维度算好后相加），与公司口径「营销中心对外出货未税销售额（净额）」一致。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-18 marketing_person_settlement_income
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('e3e32923-bb5b-40d1-9b67-0fa6a326a7a5', 'marketing_person_settlement_income', '营销中心业务员营销结算收入10%', '营销中心-业务员', 'STF-18', 'month', 0, '营销结算收入10%（元）= 对外出货净额（STF-17）× 10%，**按业务员分别折算**（kind=metric_sum_person + scale=0.1，逐个业务员取当期净额乘 10%）；公司合计 = Σ各业务员；与公司口径「营销中心总收益（营销结算收入）」= 对外出货未税净额 × 10% 一致。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_sum_person","unit":"元","scale":0.1,"component_metric_codes":["marketing_person_external_shipment_net_untaxed"]}', NULL, 1, 0, '营销结算收入10%（元）= 对外出货净额（STF-17）× 10%，**按业务员分别折算**（kind=metric_sum_person + scale=0.1，逐个业务员取当期净额乘 10%）；公司合计 = Σ各业务员；与公司口径「营销中心总收益（营销结算收入）」= 对外出货未税净额 × 10% 一致。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-23 marketing_person_order_push_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('9dbd3682-a978-4a03-8239-7ef4a7482d07', 'marketing_person_order_push_untaxed', '营销中心业务员下推金额', '营销中心-业务员', 'STF-23', 'month', 0, '下推金额（元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取已下推订单（erp_push_status=1）且 **下推时间 erp_push_date 落在当期**，只统计有效订单 status=384，按业务员（下单人 create_id）分组；订单明细按 12 期回看（下推月通常晚于建单月）。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_order_push_person","stat":"amount","unit":"元","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"person_field":"create_id","status_allow":["384"],"status_field":"status","push_date_field":"erp_push_date","lookback_periods":12,"backfill_lookback":true,"cycle_start_field":"createtime","push_status_allow":["1"],"push_status_field":"erp_push_status"}', NULL, 1, 0, '下推金额（元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取已下推订单（erp_push_status=1）且 **下推时间 erp_push_date 落在当期**，只统计有效订单 status=384，按业务员（下单人 create_id）分组；订单明细按 12 期回看（下推月通常晚于建单月）。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-24 marketing_person_order_push_period
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('2458699f-86cb-4f66-93f2-f2d965a2e8d2', 'marketing_person_order_push_period', '营销中心业务员下推周期', '营销中心-业务员', 'STF-24', 'month', 0, '下推周期（天）= Σ(下推时间 erp_push_date − 建单时间 createtime) ÷ 下推订单数，按业务员分别计算（订单数加权，不是各订单周期的简单平均）：取已下推订单（erp_push_status=1）且下推时间落在当期、订单有效 status=384；公司合计同样按「天数和 ÷ 订单数和」加权。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_order_push_person","stat":"period_days","unit":"天","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"person_field":"create_id","status_allow":["384"],"status_field":"status","push_date_field":"erp_push_date","lookback_periods":12,"backfill_lookback":true,"cycle_start_field":"createtime","push_status_allow":["1"],"push_status_field":"erp_push_status"}', NULL, 1, 0, '下推周期（天）= Σ(下推时间 erp_push_date − 建单时间 createtime) ÷ 下推订单数，按业务员分别计算（订单数加权，不是各订单周期的简单平均）：取已下推订单（erp_push_status=1）且下推时间落在当期、订单有效 status=384；公司合计同样按「天数和 ÷ 订单数和」加权。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-25 marketing_person_unship_order_inventory
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('16c949b3-2868-4bbf-8c80-00a57dcbe62e', 'marketing_person_unship_order_inventory', '营销中心业务员库存（未出货订单）', '营销中心-业务员', 'STF-25', 'month', 0, '库存（元）= 业务员名下**未出货订单**（orderAnalyze 的 chuhuo ≠ 1）的有效订单（status=384）未税金额合计（内贸 remove_taxes_freight + 外贸 receivable_CNY），按业务员（下单人 create_id）分组；订单明细按 24 期回看（未出货订单可能很久以前建单），同一订单只在其建单月的批次里出现，不会重复计算。**注意**：订单明细表没有成本字段（material_cost/process_cost 实测全为 0/NULL），因此暂以**未税金额**作为订单库存金额口径；与公司口径「营销中心外部订单库存（未税）」（来源 /hs/getNoChuHuo，不限建单月）存在差异，业务员版受 24 期回看窗口限制、偏低。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_order_push_person","stat":"amount","unit":"元","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"row_filters":[{"op":"not_equals","field":"chuhuo","value":"1"}],"person_field":"create_id","status_allow":["384"],"status_field":"status","period_filter":false,"lookback_periods":24,"backfill_lookback":true,"push_status_allow":[]}', NULL, 1, 0, '库存（元）= 业务员名下**未出货订单**（orderAnalyze 的 chuhuo ≠ 1）的有效订单（status=384）未税金额合计（内贸 remove_taxes_freight + 外贸 receivable_CNY），按业务员（下单人 create_id）分组；订单明细按 24 期回看（未出货订单可能很久以前建单），同一订单只在其建单月的批次里出现，不会重复计算。**注意**：订单明细表没有成本字段（material_cost/process_cost 实测全为 0/NULL），因此暂以**未税金额**作为订单库存金额口径；与公司口径「营销中心外部订单库存（未税）」（来源 /hs/getNoChuHuo，不限建单月）存在差异，业务员版受 24 期回看窗口限制、偏低。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-26 marketing_person_variable_expense_allocation
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('1337fd89-509f-413d-8cca-10e53cf4fb5f', 'marketing_person_variable_expense_allocation', '营销中心业务员变动费用分摊', '营销中心-业务员', 'STF-26', 'month', 0, '变动费用分摊（元）= 业务员收入（STF-18 营销结算收入10%）÷ 总收入（ORD-01 营销中心接单金额·未税）× 变动费用合计（CM-01），按业务员分别计算（kind=metric_alloc_person）；分母与费用池都取公司口径指标的当期合计行；**口径已确认（业务确认保持 ORD-01 作分母）**：各业务员分摊额合计小于 CM-01 变动费用合计属预期，差额部分不参与业务员分摊；如需改成「按各业务员收入占比分摊（合计=费用池）」，把 base_metric_codes 置空即可（改用 Σ业务员基数作分母）。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_alloc_person","unit":"元","base_metric_codes":["marketing_order_intake_untaxed"],"pool_metric_codes":["marketing_variable_expense_total"],"share_metric_codes":["marketing_person_settlement_income"]}', NULL, 1, 0, '变动费用分摊（元）= 业务员收入（STF-18 营销结算收入10%）÷ 总收入（ORD-01 营销中心接单金额·未税）× 变动费用合计（CM-01），按业务员分别计算（kind=metric_alloc_person）；分母与费用池都取公司口径指标的当期合计行；**口径已确认（业务确认保持 ORD-01 作分母）**：各业务员分摊额合计小于 CM-01 变动费用合计属预期，差额部分不参与业务员分摊；如需改成「按各业务员收入占比分摊（合计=费用池）」，把 base_metric_codes 置空即可（改用 Σ业务员基数作分母）。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-27 marketing_person_contribution_margin
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('6ee6f7ec-4739-4107-89df-e4d4ed56d854', 'marketing_person_contribution_margin', '营销中心业务员边际贡献', '营销中心-业务员', 'STF-27', 'month', 0, '边际贡献（元）= 营销结算收入10%（STF-18）− 变动费用分摊（STF-26），按业务员分别相减（kind=metric_diff_person，加项 − 减项，缺失项按 0）；公司合计 = Σ各业务员；与公司口径「营销中心边际贡献」= 总收益（营销结算收入）− 变动费用合计 同思路。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_diff_person","unit":"元","addend_metric_codes":["marketing_person_settlement_income"],"subtrahend_metric_codes":["marketing_person_variable_expense_allocation"]}', NULL, 1, 0, '边际贡献（元）= 营销结算收入10%（STF-18）− 变动费用分摊（STF-26），按业务员分别相减（kind=metric_diff_person，加项 − 减项，缺失项按 0）；公司合计 = Σ各业务员；与公司口径「营销中心边际贡献」= 总收益（营销结算收入）− 变动费用合计 同思路。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-28 marketing_person_fixed_expense_allocation
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('f51f1985-e321-4f7b-bcb8-d9f4da88be0f', 'marketing_person_fixed_expense_allocation', '营销中心业务员固定费用分摊', '营销中心-业务员', 'STF-28', 'month', 0, '固定费用分摊（元）= 业务员收入（STF-18 营销结算收入10%）÷ 总收入（ORD-01 营销中心接单金额·未税）× 固定费用合计（CM-04），按业务员分别计算（kind=metric_alloc_person）；分母与费用池都取公司口径指标的当期合计行，口径与 STF-26 变动费用分摊保持一致（**已确认以 ORD-01 作分母**：各业务员分摊额合计小于固定费用合计属预期，差额不参与业务员分摊）。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_alloc_person","unit":"元","base_metric_codes":["marketing_order_intake_untaxed"],"pool_metric_codes":["marketing_fixed_expense_total"],"share_metric_codes":["marketing_person_settlement_income"]}', NULL, 1, 0, '固定费用分摊（元）= 业务员收入（STF-18 营销结算收入10%）÷ 总收入（ORD-01 营销中心接单金额·未税）× 固定费用合计（CM-04），按业务员分别计算（kind=metric_alloc_person）；分母与费用池都取公司口径指标的当期合计行，口径与 STF-26 变动费用分摊保持一致（**已确认以 ORD-01 作分母**：各业务员分摊额合计小于固定费用合计属预期，差额不参与业务员分摊）。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-29 marketing_person_hq_allocation
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('f2778837-6edc-4a9e-bc26-a7600326c76a', 'marketing_person_hq_allocation', '营销中心业务员总部分摊', '营销中心-业务员', 'STF-29', 'month', 0, '总部分摊（元）= 对外出货净额（STF-17）× 8%，**按业务员分别折算**（kind=metric_sum_person + scale=0.08，逐个业务员取当期净额乘 8%）；公司合计 = Σ各业务员。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_sum_person","unit":"元","scale":0.08,"component_metric_codes":["marketing_person_external_shipment_net_untaxed"]}', NULL, 1, 0, '总部分摊（元）= 对外出货净额（STF-17）× 8%，**按业务员分别折算**（kind=metric_sum_person + scale=0.08，逐个业务员取当期净额乘 8%）；公司合计 = Σ各业务员。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-30 marketing_person_settlement_profit
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('2c7db5f8-9f1c-46ab-b6fb-5cc5becad348', 'marketing_person_settlement_profit', '营销中心业务员结算收益', '营销中心-业务员', 'STF-30', 'month', 0, '结算收益（元）= 边际贡献（STF-27）− 固定费用分摊（STF-28）− 总部分摊（STF-29），按业务员分别相减（kind=metric_diff_person，加项 1 个、减项 2 个，缺失项按 0）；公司合计 = Σ各业务员。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_diff_person","unit":"元","addend_metric_codes":["marketing_person_contribution_margin"],"subtrahend_metric_codes":["marketing_person_fixed_expense_allocation","marketing_person_hq_allocation"]}', NULL, 1, 0, '结算收益（元）= 边际贡献（STF-27）− 固定费用分摊（STF-28）− 总部分摊（STF-29），按业务员分别相减（kind=metric_diff_person，加项 1 个、减项 2 个，缺失项按 0）；公司合计 = Σ各业务员。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-36 marketing_person_sales_per_capita
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('f21e998b-a80f-4948-b38b-f796d288cdac', 'marketing_person_sales_per_capita', '营销中心业务员人均销售额', '营销中心-业务员', 'STF-36', 'month', 0, '人均销售额（元）= 对外出货净额（STF-17），按业务员分别取值（kind=metric_sum_person，单一组成指标；业务员维度下即为该业务员的当期销售额）。如需按人数折算（如「净额合计 ÷ 业务员人数」或「÷ 在职营销人员数」），增配 scale 或再引入人数类指标即可，口径请与业务确认。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_sum_person","unit":"元","component_metric_codes":["marketing_person_external_shipment_net_untaxed"]}', NULL, 1, 0, '人均销售额（元）= 对外出货净额（STF-17），按业务员分别取值（kind=metric_sum_person，单一组成指标；业务员维度下即为该业务员的当期销售额）。如需按人数折算（如「净额合计 ÷ 业务员人数」或「÷ 在职营销人员数」），增配 scale 或再引入人数类指标即可，口径请与业务确认。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-37 marketing_person_profit_per_capita
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('d449db59-93fd-4d5a-a67b-eed4cc966957', 'marketing_person_profit_per_capita', '营销中心业务员人均利润贡献', '营销中心-业务员', 'STF-37', 'month', 0, '人均利润贡献（元）= 结算收益（STF-30），按业务员分别取值（kind=metric_sum_person，单一组成指标；业务员维度下即为该业务员的当期结算收益）。如需按人数折算（如「结算收益合计 ÷ 业务员人数」），增配 scale 或再引入人数类指标即可。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_sum_person","unit":"元","component_metric_codes":["marketing_person_settlement_profit"]}', NULL, 1, 0, '人均利润贡献（元）= 结算收益（STF-30），按业务员分别取值（kind=metric_sum_person，单一组成指标；业务员维度下即为该业务员的当期结算收益）。如需按人数折算（如「结算收益合计 ÷ 业务员人数」），增配 scale 或再引入人数类指标即可。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-38 marketing_person_sample_order_intake_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('80938cb3-fecf-4625-9a6c-8797cc5fa216', 'marketing_person_sample_order_intake_untaxed', '营销中心业务员打样接单业绩（未税）', '营销中心-业务员', 'STF-38', 'month', 0, '打样接单业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取订单类型 order_type=2（打样）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"元","group_by":"person","components":[{"label":"内贸","row_filters":[{"op":"equals","field":"order_type","value":"2"}],"amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","row_filters":[{"op":"equals","field":"order_type","value":"2"}],"amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"row_filters":[{"op":"equals","field":"order_type","value":"2"}],"person_field":"create_id","status_allow":["384"],"status_field":"status"}', NULL, 1, 0, '打样接单业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取订单类型 order_type=2（打样）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-39 marketing_person_batch_order_intake_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('9e3d4c90-8f6f-4de9-91ef-01c619a96368', 'marketing_person_batch_order_intake_untaxed', '营销中心业务员批量接单业绩（未税）', '营销中心-业务员', 'STF-39', 'month', 0, '批量接单业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取订单类型 order_type=1（批量）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"元","group_by":"person","components":[{"label":"内贸","row_filters":[{"op":"equals","field":"order_type","value":"1"}],"amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","row_filters":[{"op":"equals","field":"order_type","value":"1"}],"amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"row_filters":[{"op":"equals","field":"order_type","value":"1"}],"person_field":"create_id","status_allow":["384"],"status_field":"status"}', NULL, 1, 0, '批量接单业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取订单类型 order_type=1（批量）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-40 marketing_person_new_customer_intake_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('1670d7bb-2ced-4cae-a029-1f64307d2429', 'marketing_person_new_customer_intake_untaxed', '营销中心业务员新客户业绩（未税）', '营销中心-业务员', 'STF-40', 'month', 0, '新客户业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取客户标识 is_new=1（新客户）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"元","group_by":"person","components":[{"label":"内贸","row_filters":[{"op":"equals","field":"is_new","value":"1"}],"amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","row_filters":[{"op":"equals","field":"is_new","value":"1"}],"amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"row_filters":[{"op":"equals","field":"is_new","value":"1"}],"person_field":"create_id","status_allow":["384"],"status_field":"status"}', NULL, 1, 0, '新客户业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取客户标识 is_new=1（新客户）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-41 marketing_person_old_customer_intake_untaxed
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('61931507-0222-4fef-b5ee-1b76700c3e00', 'marketing_person_old_customer_intake_untaxed', '营销中心业务员老客户业绩（未税）', '营销中心-业务员', 'STF-41', 'month', 0, '老客户业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取客户标识 is_new=2（老客户）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"元","group_by":"person","components":[{"label":"内贸","row_filters":[{"op":"equals","field":"is_new","value":"2"}],"amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","row_filters":[{"op":"equals","field":"is_new","value":"2"}],"amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"row_filters":[{"op":"equals","field":"is_new","value":"2"}],"person_field":"create_id","status_allow":["384"],"status_field":"status"}', NULL, 1, 0, '老客户业绩（未税，元）= Σ(内贸 remove_taxes_freight + 外贸 receivable_CNY)，取客户标识 is_new=2（老客户）、有效订单 status=384，按订单创建月 createtime 落到当期，按业务员（下单人 create_id）分组。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-47 marketing_person_total_customer_count
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('090f8d2e-7e17-49c6-a25a-b8388cfcf84d', 'marketing_person_total_customer_count', '营销中心业务员总客户数量', '营销中心-业务员', 'STF-47', 'month', 0, '总客户数量（家）= 客户表中**所属业务员（principal_id）**为本业务员的客户数量；来源 CRM 客户列表接口（未分页全量，当前快照），未分配业务员（principal_id 为空）的客户不计入；该指标是时点快照口径，历史期间取重算时点最新的客户列表批次。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"家","group_by":"person","components":[{"label":"客户列表","source_object_code":"/hs/customer/getCusotmerList"}],"value_mode":"count_customers","person_field":"principal_id","status_allow":[],"status_field":null,"customer_field":"id","exclude_empty_person":true}', NULL, 1, 0, '总客户数量（家）= 客户表中**所属业务员（principal_id）**为本业务员的客户数量；来源 CRM 客户列表接口（未分页全量，当前快照），未分配业务员（principal_id 为空）的客户不计入；该指标是时点快照口径，历史期间取重算时点最新的客户列表批次。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-48 marketing_person_old_customer_order_count
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('9df25b1a-0baf-4b53-9299-bd1ffe611e61', 'marketing_person_old_customer_order_count', '营销中心业务员本月下单老客户数量', '营销中心-业务员', 'STF-48', 'month', 0, '本月下单老客户数量（家）= 当期订单中 **is_new=2（老客户）** 的客户去重数，按订单创建月 createtime 落当期，只统计有效订单 status=384，按业务员（下单人 create_id）分组；同一客户当月多单只算一次、跨内贸外贸也只算一次；公司合计取全部业务员的客户并集。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_person_amount","unit":"家","group_by":"person","components":[{"label":"内贸","row_filters":[{"op":"equals","field":"is_new","value":"2"}],"amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"source_object_code":"/hs/order/orderAnalyze?type=1"},{"label":"外贸","row_filters":[{"op":"equals","field":"is_new","value":"2"}],"amount_terms":[{"sign":1,"field":"receivable_CNY"}],"source_object_code":"/hs/order/orderAnalyze?type=2"}],"value_mode":"count_customers","row_filters":[{"op":"equals","field":"is_new","value":"2"}],"person_field":"create_id","status_allow":["384"],"status_field":"status","customer_field":"customer"}', NULL, 1, 0, '本月下单老客户数量（家）= 当期订单中 **is_new=2（老客户）** 的客户去重数，按订单创建月 createtime 落当期，只统计有效订单 status=384，按业务员（下单人 create_id）分组；同一客户当月多单只算一次、跨内贸外贸也只算一次；公司合计取全部业务员的客户并集。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-49 marketing_person_repurchase_rate
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('30496544-74ec-4308-b212-1186a8dc2a17', 'marketing_person_repurchase_rate', '营销中心业务员复购率', '营销中心-业务员', 'STF-49', 'month', 0, '复购率（%）= 本月下单老客户数量 ÷ 总客户数量 × 100%，**按业务员分别计算**（分子为「营销中心业务员本月下单老客户数量」STF-48，分母为「营销中心业务员总客户数量」STF-47，同为当月、同一业务员）；分母为 0 的业务员不输出行；公司合计 = Σ分子 ÷ Σ分母 × 100。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_ratio_person","unit":"%","ratio_scale":100,"numerator_metric_codes":["marketing_person_old_customer_order_count"],"denominator_metric_codes":["marketing_person_total_customer_count"]}', NULL, 1, 0, '复购率（%）= 本月下单老客户数量 ÷ 总客户数量 × 100%，**按业务员分别计算**（分子为「营销中心业务员本月下单老客户数量」STF-48，分母为「营销中心业务员总客户数量」STF-47，同为当月、同一业务员）；分母为 0 的业务员不输出行；公司合计 = Σ分子 ÷ Σ分母 × 100。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-50 marketing_person_order_price
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('fbb2be7a-6c99-4569-8d2f-07b4c7af41cc', 'marketing_person_order_price', '营销中心业务员客单价', '营销中心-业务员', 'STF-50', 'month', 0, '客单价（元/单）= 接单未税（STF-13）÷ 接单量（当期有效订单条数），**按业务员分别相除**；分子取「营销中心业务员接单未税」，分母取「营销中心业务员接单量」，同为当月、同一业务员；公司合计 = Σ接单未税 ÷ Σ接单量；接单量为 0 的业务员不输出行。', '{"org":false,"dept":true,"person":true}', '{"kind":"metric_ratio_person","unit":"元/单","ratio_scale":1,"numerator_metric_codes":["marketing_person_order_intake_untaxed"],"denominator_metric_codes":["marketing_person_order_count"]}', NULL, 1, 0, '客单价（元/单）= 接单未税（STF-13）÷ 接单量（当期有效订单条数），**按业务员分别相除**；分子取「营销中心业务员接单未税」，分母取「营销中心业务员接单量」，同为当月、同一业务员；公司合计 = Σ接单未税 ÷ Σ接单量；接单量为 0 的业务员不输出行。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 指标 STF-68 marketing_person_goods_shipment_qty
INSERT INTO metric_def
  (uuid, code, name, category, excel_code, period_type, sensitivity, formula, dimensions, measures,
   source_entity_id, version, status, description, is_deleted, created_time, updated_time)
VALUES ('1b8d5459-c32b-4e37-84b5-3a24f45dc56f', 'marketing_person_goods_shipment_qty', '营销中心业务员出货数量', '营销中心-业务员', 'STF-68', 'month', 0, '出货数量 = Σ发货数量 send_qty，发货月按发货单审核月 check_date，业务员取所属订单的下单人 create_id；订单明细按 12 期回看以取得业务员归属。', '{"org":false,"dept":true,"person":true}', '{"kind":"crm_shipment_person_amount","unit":"个","group_by":"person","components":[{"label":"内贸","amount_terms":[{"sign":1,"field":"remove_taxes_freight"}],"status_allow":["384"],"status_field":"status","order_source_object_code":"/hs/order/orderAnalyze?type=1","shipment_source_object_code":"/hs/order/orderShipments?type=1"},{"label":"外贸","amount_terms":[{"sign":1,"field":"receivable_CNY"}],"status_allow":["384"],"status_field":"status","order_source_object_code":"/hs/order/orderAnalyze?type=2","shipment_source_object_code":"/hs/order/orderShipments?type=2"}],"value_mode":"qty","person_field":"create_id","lookback_periods":12,"backfill_lookback":true}', NULL, 1, 0, '出货数量 = Σ发货数量 send_qty，发货月按发货单审核月 check_date，业务员取所属订单的下单人 create_id；订单明细按 12 期回看以取得业务员归属。 数据来源：CRM《订单分析接口文档》《订单发货分析接口文档》（/hs/order/orderAnalyze / /hs/order/orderShipments，GET、无需鉴权，month 为整月）；业务员映射链为 create_id → source_person(raw_json.id) → 工号 → master_person。月指标，每日 02:30 重算当月，每次计算保留 calc_version 版本。', 0, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), category = VALUES(category), excel_code = VALUES(excel_code),
  period_type = VALUES(period_type), sensitivity = VALUES(sensitivity), formula = VALUES(formula),
  dimensions = VALUES(dimensions), measures = VALUES(measures), status = VALUES(status),
  description = VALUES(description), version = VALUES(version);

-- 6) 给对接方开「业务员明细」权限（把 app_id 换成实际值后取消注释执行）
-- UPDATE open_client SET allow_person_detail = 1 WHERE app_id = '<对接方app_id>';

-- 7) 执行结果核对（指标应 16 行、同步任务应 6 行）
SELECT COUNT(*) AS person_metric_count FROM metric_def WHERE category = '营销中心-业务员';
SELECT id, name, cron_expr, status FROM meta_sync_job WHERE name LIKE 'CRM业务员指标%';
SELECT code, name, excel_code FROM metric_def WHERE category = '营销中心-业务员' ORDER BY excel_code;
