<template>
  <div class="metadata-page">
    <ElTabs v-model="activeKey" @tab-change="handleTabChange">
      <ElTabPane v-for="resource in orderedResources" :key="resource.key" :label="resource.label" :name="resource.key" />
    </ElTabs>

    <ElCard shadow="never">
      <div class="toolbar">
        <ElButton type="primary" @click="openCreate">新增</ElButton>
        <ElButton type="danger" :disabled="!selectedRows.length" @click="deleteSelected">删除</ElButton>
        <ElButton @click="loadData">刷新</ElButton>
      </div>

      <ElTable
        v-loading="loading"
        :data="rows"
        border
        stripe
        row-key="id"
        @selection-change="onSelectionChange"
      >
        <ElTableColumn type="selection" width="48" />
        <ElTableColumn
          v-for="col in current.columns"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :min-width="col.width || 120"
          show-overflow-tooltip
        >
          <template #default="{ row }">
            <span>{{ formatCell(row, col) }}</span>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <ElButton v-if="current.key === 'syncJob'" link type="success" @click="runJob(row)">执行</ElButton>
            <ElButton link type="primary" @click="openEdit(row)">编辑</ElButton>
            <ElButton link type="danger" @click="removeRow(row)">删除</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <ElPagination
        v-model:current-page="page.page_no"
        v-model:page-size="page.page_size"
        :total="page.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </ElCard>

    <ElDialog v-model="dialogVisible" :title="dialogTitle" width="680px" destroy-on-close>
      <ElForm ref="formRef" :model="form" label-width="110px">
        <ElFormItem v-for="field in current.fields" :key="field.prop" :label="field.label">
          <div v-if="field.type === 'variables'" class="variable-editor">
            <div v-for="(item, index) in form[field.prop]" :key="index" class="variable-row">
              <ElInput v-model="item.name" placeholder="变量名" style="width: 150px" />
              <ElSelect v-model="item.value_type" style="width: 120px">
                <ElOption
                  v-for="option in variableTypeOptions"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </ElSelect>
              <ElInput v-model="item.value" placeholder="变量值或表达式" />
              <ElInput v-model="item.description" placeholder="说明" style="width: 150px" />
              <ElButton link type="danger" @click="removeVariable(field.prop, index)">删除</ElButton>
            </div>
            <ElButton size="small" @click="addVariable(field.prop)">添加变量</ElButton>
          </div>
          <ElSelect
            v-else-if="field.type === 'select'"
            v-model="form[field.prop]"
            :placeholder="`请选择${field.label}`"
            clearable
          >
            <ElOption
              v-for="option in field.options || []"
              :key="option.value"
              :label="option.label"
              :value="option.value"
            />
          </ElSelect>
          <ElSwitch v-else-if="field.type === 'switch'" v-model="form[field.prop]" />
          <ElInputNumber
            v-else-if="field.type === 'number'"
            v-model="form[field.prop]"
            controls-position="right"
            style="width: 100%"
          />
          <ElInput
            v-else-if="field.type === 'json'"
            v-model="form[field.prop]"
            type="textarea"
            :rows="3"
            :placeholder="`请输入${field.label}(JSON)`"
          />
          <ElInput v-else v-model="form[field.prop]" :placeholder="`请输入${field.label}`" clearable />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="submitting" @click="submitForm">保存</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { MetadataAPI, type MetaItem } from "@/api/module_metadata";

type FieldType = "input" | "number" | "select" | "switch" | "json" | "variables";

interface FieldConfig {
  prop: string;
  label: string;
  type?: FieldType;
  options?: { label: string; value: string | number }[];
  default?: unknown;
}

interface ColumnConfig {
  prop: string;
  label: string;
  width?: number;
  formatter?: (value: unknown, row: MetaItem) => string;
}

interface ResourceConfig {
  key: string;
  label: string;
  api: typeof MetadataAPI.sourceSystem;
  columns: ColumnConfig[];
  fields: FieldConfig[];
}

const statusOptions = [
  { label: "启用", value: 0 },
  { label: "停用", value: 1 },
];

const variableTypeOptions = [
  { label: "字符串", value: "string" },
  { label: "整数", value: "integer" },
  { label: "小数", value: "decimal" },
  { label: "布尔", value: "boolean" },
  { label: "日期", value: "date" },
  { label: "JSON", value: "json" },
  { label: "表达式", value: "expression" },
];

const resources: ResourceConfig[] = [
  {
    key: "sourceSystem",
    label: "来源系统",
    api: MetadataAPI.sourceSystem,
    columns: [
      { prop: "code", label: "系统编码", width: 120 },
      { prop: "name", label: "系统名称", width: 140 },
      { prop: "connector_type", label: "连接器类型", width: 120 },
      { prop: "connection_id", label: "连接ID", width: 90 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "code", label: "系统编码" },
      { prop: "name", label: "系统名称" },
      { prop: "connector_type", label: "连接器类型" },
      { prop: "connection_id", label: "连接配置ID", type: "number" },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
      { prop: "description", label: "备注" },
    ],
  },
  {
    key: "sourceObject",
    label: "来源对象",
    api: MetadataAPI.sourceObject,
    columns: [
      { prop: "system_code", label: "系统编码", width: 120 },
      { prop: "code", label: "对象编码", width: 160 },
      { prop: "name", label: "对象名称", width: 160 },
      { prop: "query_type", label: "查询类型", width: 110 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "system_id", label: "来源系统ID", type: "number" },
      { prop: "code", label: "对象编码/表单Id" },
      { prop: "name", label: "对象名称" },
      { prop: "query_type", label: "查询类型", default: "bill_query" },
      { prop: "request_template", label: "请求模板", type: "json" },
      { prop: "variables", label: "变量定义", type: "variables" },
      { prop: "watermark_field", label: "水位字段" },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
  {
    key: "sourceField",
    label: "来源字段",
    api: MetadataAPI.sourceField,
    columns: [
      { prop: "object_code", label: "对象编码", width: 150 },
      { prop: "field_key", label: "字段Key", width: 150 },
      { prop: "field_name", label: "字段名称", width: 150 },
      { prop: "data_type", label: "数据类型", width: 100 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "object_id", label: "来源对象ID", type: "number" },
      { prop: "field_key", label: "字段Key" },
      { prop: "field_name", label: "字段名称" },
      { prop: "data_type", label: "数据类型", default: "string" },
      { prop: "is_primary_key", label: "主键", type: "switch", default: false },
      { prop: "is_watermark", label: "增量水位", type: "switch", default: false },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
  {
    key: "standardEntity",
    label: "标准实体",
    api: MetadataAPI.standardEntity,
    columns: [
      { prop: "code", label: "实体编码", width: 160 },
      { prop: "name", label: "实体名称", width: 160 },
      { prop: "table_name", label: "物理表", width: 140 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "code", label: "标准实体编码" },
      { prop: "name", label: "标准实体名称" },
      { prop: "table_name", label: "目标物理表" },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
      { prop: "description", label: "备注" },
    ],
  },
  {
    key: "standardField",
    label: "标准字段",
    api: MetadataAPI.standardField,
    columns: [
      { prop: "entity_code", label: "实体编码", width: 150 },
      { prop: "field_code", label: "字段编码", width: 150 },
      { prop: "field_name", label: "字段名称", width: 150 },
      { prop: "data_type", label: "数据类型", width: 100 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "entity_id", label: "标准实体ID", type: "number" },
      { prop: "field_code", label: "标准字段编码" },
      { prop: "field_name", label: "标准字段名称" },
      { prop: "data_type", label: "数据类型", default: "string" },
      { prop: "is_dimension", label: "是否维度", type: "switch", default: false },
      { prop: "is_measure", label: "是否度量", type: "switch", default: false },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
  {
    key: "fieldMapping",
    label: "字段映射",
    api: MetadataAPI.fieldMapping,
    columns: [
      { prop: "source_field_key", label: "来源字段", width: 140 },
      { prop: "standard_field_code", label: "标准字段", width: 140 },
      { prop: "transform_type", label: "加工类型", width: 120 },
      { prop: "order", label: "执行顺序", width: 90 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "source_object_id", label: "来源对象ID", type: "number" },
      { prop: "source_field_id", label: "来源字段ID", type: "number" },
      { prop: "standard_field_id", label: "标准字段ID", type: "number" },
      { prop: "transform_type", label: "加工类型", default: "direct" },
      { prop: "transform_config", label: "加工配置", type: "json" },
      { prop: "order", label: "执行顺序", type: "number", default: 0 },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
  {
    key: "metricDef",
    label: "指标定义",
    api: MetadataAPI.metricDef,
    columns: [
      { prop: "code", label: "指标编码", width: 140 },
      { prop: "excel_code", label: "Excel科目编码", width: 130 },
      { prop: "name", label: "指标名称", width: 160 },
      { prop: "category", label: "指标分类", width: 130 },
      { prop: "period_type", label: "期间类型", width: 100 },
      { prop: "sensitivity", label: "敏感级别", width: 90 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "code", label: "指标编码" },
      { prop: "excel_code", label: "Excel科目编码" },
      { prop: "name", label: "指标名称" },
      { prop: "category", label: "指标分类", default: "营销中心-主表" },
      { prop: "period_type", label: "期间类型", default: "month" },
      { prop: "sensitivity", label: "敏感级别", type: "number", default: 0 },
      { prop: "formula", label: "计算公式", type: "json" },
      { prop: "dimensions", label: "维度配置", type: "json" },
      { prop: "measures", label: "度量配置", type: "json" },
      { prop: "source_entity_id", label: "来源标准实体ID", type: "number" },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
      { prop: "description", label: "备注" },
    ],
  },
  {
    key: "syncJob",
    label: "同步任务",
    api: MetadataAPI.syncJob,
    columns: [
      { prop: "name", label: "任务名称", width: 180 },
      { prop: "system_code", label: "系统编码", width: 100 },
      { prop: "object_code", label: "对象编码", width: 180 },
      { prop: "org_code", label: "组织编码", width: 100 },
      { prop: "cron_expr", label: "Cron表达式", width: 160 },
      { prop: "status", label: "状态", width: 80, formatter: (v) => (Number(v) === 0 ? "启用" : "停用") },
    ],
    fields: [
      { prop: "name", label: "任务名称" },
      { prop: "source_system_id", label: "来源系统ID", type: "number" },
      { prop: "source_object_id", label: "来源对象ID", type: "number" },
      { prop: "standard_entity_id", label: "标准实体ID", type: "number" },
      { prop: "org_code", label: "组织编码" },
      { prop: "cron_expr", label: "Cron表达式", default: "0 0 2 * * ?" },
      { prop: "request_params", label: "请求参数", type: "json" },
      { prop: "variables", label: "变量定义", type: "variables" },
      { prop: "sync_mode", label: "同步模式", default: "full" },
      { prop: "watermark_field", label: "水位字段" },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
      { prop: "description", label: "备注" },
    ],
  },
];

const activeKey = ref(resources[0]!.key);
const rows = ref<MetaItem[]>([]);
const loading = ref(false);
const submitting = ref(false);
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const selectedRows = ref<MetaItem[]>([]);
const form = reactive<Record<string, any>>({});

const page = reactive({
  page_no: 1,
  page_size: 10,
  total: 0,
});

const current = computed(() => resources.find((item) => item.key === activeKey.value) ?? resources[0]!);
const dialogTitle = computed(() => (editingId.value ? "编辑" : "新增"));

const orderedResources = computed(() => {
  const syncJob = resources.find((item) => item.key === "syncJob");
  const rest = resources.filter((item) => item.key !== "syncJob");
  const sourceIndex = rest.findIndex((item) => item.key === "sourceObject");
  if (!syncJob) return resources;
  const insertIndex = sourceIndex >= 0 ? sourceIndex : 1;
  return [...rest.slice(0, insertIndex), syncJob, ...rest.slice(insertIndex)];
});

function formatCell(row: MetaItem, col: ColumnConfig) {
  const value = row[col.prop];
  if (col.formatter) return col.formatter(value, row);
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

async function loadData() {
  loading.value = true;
  try {
    const res = await current.value.api.page({ page_no: page.page_no, page_size: page.page_size });
    const data = res.data?.data;
    rows.value = data?.items ?? [];
    page.total = data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

function resetForm(defaults?: MetaItem) {
  Object.keys(form).forEach((key) => delete form[key]);
  current.value.fields.forEach((field) => {
    if (field.type === "variables") {
      const source = defaults?.[field.prop];
      form[field.prop] = Array.isArray(source) ? source.map((item) => ({ ...(item as Record<string, unknown>) })) : [];
      return;
    }
    let value = defaults?.[field.prop] ?? field.default ?? (field.type === "switch" ? false : undefined);
    if (field.type === "json" && value !== undefined && value !== null && typeof value !== "string") {
      value = JSON.stringify(value, null, 2);
    }
    form[field.prop] = value;
  });
}

function addVariable(prop: string) {
  if (!Array.isArray(form[prop])) form[prop] = [];
  form[prop].push({ name: "", value_type: "expression", value: "", description: "" });
}

function removeVariable(prop: string, index: number) {
  if (Array.isArray(form[prop])) form[prop].splice(index, 1);
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: MetaItem) {
  editingId.value = row.id ?? null;
  resetForm(row);
  if (current.value.key === "sourceObject" || current.value.key === "fieldMapping") {
    // 文本域 JSON 保持字符串，避免绑定对象
  }
  dialogVisible.value = true;
}

async function submitForm() {
  const payload = { ...form };
  for (const field of current.value.fields) {
    const key = field.prop;
    if (field.type === "json" && typeof payload[key] === "string" && payload[key]) {
      try {
        payload[key] = JSON.parse(payload[key] as string);
      } catch {
        ElMessage.warning(`${field.label} 不是有效 JSON`);
        throw new Error("invalid json");
      }
    }
    if (field.type === "variables" && Array.isArray(payload[key])) {
      payload[key] = payload[key].map((item: Record<string, any>) => {
        if (item.value_type === "json" && typeof item.value === "string" && item.value) {
          try {
            return { ...item, value: JSON.parse(item.value) };
          } catch {
            ElMessage.warning(`${item.name || "变量"} 的 JSON 值格式错误`);
            throw new Error("invalid variable json");
          }
        }
        return item;
      });
    }
  }
  submitting.value = true;
  try {
    if (editingId.value) {
      await current.value.api.update(editingId.value, payload);
      ElMessage.success("修改成功");
    } else {
      await current.value.api.create(payload);
      ElMessage.success("创建成功");
    }
    dialogVisible.value = false;
    await loadData();
  } catch (error) {
    if ((error as Error).message !== "invalid json" && (error as Error).message !== "invalid variable json") ElMessage.error("操作失败");
  } finally {
    submitting.value = false;
  }
}

function removeRow(row: MetaItem) {
  ElMessageBox.confirm("确认删除该数据？", "提示", { type: "warning" }).then(async () => {
    await current.value.api.remove([row.id!]);
    ElMessage.success("删除成功");
    await loadData();
  });
}

function deleteSelected() {
  ElMessageBox.confirm(`确认删除选中的 ${selectedRows.value.length} 条数据？`, "提示", { type: "warning" }).then(async () => {
    await current.value.api.remove(selectedRows.value.map((row) => row.id!));
    ElMessage.success("删除成功");
    await loadData();
  });
}

async function runJob(row: MetaItem) {
  await ElMessageBox.confirm("确认立即执行该同步任务？", "提示", { type: "warning" });
  await MetadataAPI.syncJob.runNow(row.id!);
  ElMessage.success("执行请求已提交");
}

function onSelectionChange(rowsValue: MetaItem[]) {
  selectedRows.value = rowsValue;
}

function handleSizeChange() {
  page.page_no = 1;
  loadData();
}

function handleTabChange() {
  page.page_no = 1;
  page.page_size = 10;
  selectedRows.value = [];
  loadData();
}

onMounted(() => {
  loadData();
});
</script>

<style scoped>
.metadata-page {
  height: 100%;
  padding: 12px;
}
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.variable-editor {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.variable-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
