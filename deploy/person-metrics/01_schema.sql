-- ==========================================================================
-- 业务员指标 - 表结构变更（可在数据库客户端直接执行，重复执行安全）
-- 生成时间：2026-10-10 14:01
-- 由 backend/scripts/export_person_metrics_sql.py 生成，请勿手工修改
-- 对应 alembic 迁移：203324073db9（metric_value 业务员列）、d81f6c2a7e35 / cd6a5655eba2（open_client 权限）
-- 推荐先用后端自带迁移：docker compose exec backend python main.py upgrade --env=prod
-- 若走本脚本，请在本文件执行完后按文末提示把 alembic_version 对齐
-- ==========================================================================

SET NAMES utf8mb4;

-- metric_value.person_code
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'metric_value' AND COLUMN_NAME = 'person_code') = 0,
  'ALTER TABLE metric_value ADD COLUMN person_code VARCHAR(64) NULL COMMENT ''业务员编码(来源原始，未映射也保留)''',
  'SELECT ''跳过：metric_value.person_code 已存在'' AS note');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- metric_value.person_name
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'metric_value' AND COLUMN_NAME = 'person_name') = 0,
  'ALTER TABLE metric_value ADD COLUMN person_name VARCHAR(255) NULL COMMENT ''业务员姓名(来源原始)''',
  'SELECT ''跳过：metric_value.person_name 已存在'' AS note');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- metric_value 索引 ix_metric_value_person_code
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.STATISTICS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'metric_value' AND INDEX_NAME = 'ix_metric_value_person_code') = 0,
  'CREATE INDEX ix_metric_value_person_code ON metric_value (person_code)',
  'SELECT ''跳过：索引 ix_metric_value_person_code 已存在'' AS note');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- open_client.allow_person_detail
SET @ddl := IF((SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'open_client' AND COLUMN_NAME = 'allow_person_detail') = 0,
  'ALTER TABLE open_client ADD COLUMN allow_person_detail TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''是否允许查询业务员明细(默认不开放)''',
  'SELECT ''跳过：open_client.allow_person_detail 已存在'' AS note');
PREPARE stmt FROM @ddl; EXECUTE stmt; DEALLOCATE PREPARE stmt;

-- --------------------------------------------------------------------------
-- 执行完上面语句后，让 alembic 版本与库状态一致（避免下次启动再重复加列）
-- 选项 1（推荐）：改用后端迁移命令，本文件只作为检查参考：
--     docker compose exec backend python main.py upgrade --env=prod
-- 选项 2：手工对齐（仅当你确认服务器 alembic 已包含 b7c1d9e4f2a0 之前的全部迁移）：
--     SELECT version_num FROM alembic_version;
--     UPDATE alembic_version SET version_num = 'cd6a5655eba2';

-- 客户端执行结果核对：应分别返回 person_code / person_name / allow_person_detail
SELECT TABLE_NAME, COLUMN_NAME FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = DATABASE()
  AND ((TABLE_NAME = 'metric_value' AND COLUMN_NAME IN ('person_code','person_name'))
    OR (TABLE_NAME = 'open_client' AND COLUMN_NAME = 'allow_person_detail'));
