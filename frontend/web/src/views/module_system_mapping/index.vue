<template>
  <div class="mapping-page">
    <ElTabs v-model="activeKey" @tab-change="handleTabChange">
      <ElTabPane v-for="resource in resources" :key="resource.key" :label="resource.label" :name="resource.key" />
    </ElTabs>

    <ElCard shadow="never">
      <div class="toolbar">
        <ElButton type="primary" @click="openCreate">新增映射</ElButton>
        <ElButton type="success" :loading="matching" @click="autoMatch">自动匹配</ElButton>
        <ElButton type="danger" :disabled="!selectedRows.length" @click="deleteSelected">删除</ElButton>
        <ElButton @click="loadData">刷新</ElButton>
      </div>

      <ElTable v-loading="loading" :data="rows" border stripe row-key="id" @selection-change="onSelectionChange">
        <ElTableColumn type="selection" width="48" />
        <ElTableColumn
          v-for="col in current.columns"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :min-width="col.width || 120"
          show-overflow-tooltip
        >
          <template #default="{ row }">{{ formatCell(row, col) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openEdit(row)">编辑</ElButton>
            <ElButton link type="danger" @click="removeRow(row)">删除</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <ElPagination
        v-model:current-page="page.page_no"
        v-model:page-size="page.page_size"
        :total="page.total"
        :page-sizes="[10, 20, 50]"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </ElCard>

    <ElDialog v-model="dialogVisible" :title="editingId ? '编辑映射' : '新增映射'" width="680px" destroy-on-close>
      <ElForm :model="form" label-width="130px">
        <ElFormItem v-for="field in current.fields" :key="field.prop" :label="field.label">
          <ElSelect v-if="field.type === 'select'" v-model="form[field.prop]" clearable>
            <ElOption v-for="option in field.options || []" :key="option.value" :label="option.label" :value="option.value" />
          </ElSelect>
          <ElInputNumber v-else-if="field.type === 'number'" v-model="form[field.prop]" style="width: 100%" />
          <ElInput
            v-else-if="field.type === 'json'"
            v-model="form[field.prop]"
            type="textarea"
            :rows="3"
          />
          <ElInput v-else v-model="form[field.prop]" clearable />
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
import { SystemMappingAPI, type MappingItem } from "@/api/module_system_mapping";

interface FieldConfig {
  prop: string;
  label: string;
  type?: "input" | "number" | "select" | "json";
  options?: { label: string; value: string | number }[];
  default?: unknown;
}

interface ColumnConfig {
  prop: string;
  label: string;
  width?: number;
  formatter?: (value: unknown) => string;
}

interface ResourceConfig {
  key: string;
  label: string;
  api: typeof SystemMappingAPI.org;
  columns: ColumnConfig[];
  fields: FieldConfig[];
}

const statusOptions = [
  { label: "有效", value: 0 },
  { label: "失效", value: 1 },
];
const matchModeOptions = [
  { label: "精确", value: "exact" },
  { label: "模糊", value: "fuzzy" },
  { label: "人工", value: "manual" },
];
const transformOptions = [
  { label: "直接", value: "direct" },
  { label: "码值映射", value: "code_map" },
  { label: "组织映射", value: "org_map" },
  { label: "部门映射", value: "dept_map" },
  { label: "人员映射", value: "person_map" },
  { label: "人员组织部门", value: "person_org_dept" },
  { label: "日期期间", value: "date_period" },
  { label: "币种", value: "currency" },
  { label: "公式", value: "formula" },
];

const resources: ResourceConfig[] = [
  {
    key: "org",
    label: "组织映射",
    api: SystemMappingAPI.org,
    columns: [
      { prop: "source_type", label: "来源类型", width: 110 },
      { prop: "source_org_code", label: "来源组织编码", width: 140 },
      { prop: "source_org_name", label: "来源组织名称", width: 180 },
      { prop: "master_org_code", label: "标准组织编码", width: 140 },
      { prop: "master_org_name", label: "标准组织名称", width: 180 },
      { prop: "match_mode", label: "匹配方式", width: 100 },
      { prop: "confidence", label: "置信度", width: 90 },
    ],
    fields: [
      { prop: "source_org_id", label: "来源组织ID", type: "number" },
      { prop: "master_org_id", label: "标准组织ID", type: "number" },
      { prop: "match_mode", label: "匹配方式", type: "select", options: matchModeOptions, default: "manual" },
      { prop: "confidence", label: "置信度", type: "number", default: 100 },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
  {
    key: "person",
    label: "人员映射",
    api: SystemMappingAPI.person,
    columns: [
      { prop: "source_type", label: "来源类型", width: 110 },
      { prop: "source_person_code", label: "来源人员编码", width: 140 },
      { prop: "source_person_name", label: "来源人员姓名", width: 160 },
      { prop: "master_person_code", label: "标准人员编码", width: 140 },
      { prop: "master_person_name", label: "标准人员姓名", width: 160 },
      { prop: "match_mode", label: "匹配方式", width: 100 },
      { prop: "confidence", label: "置信度", width: 90 },
    ],
    fields: [
      { prop: "source_person_id", label: "来源人员ID", type: "number" },
      { prop: "master_person_id", label: "标准人员ID", type: "number" },
      { prop: "match_mode", label: "匹配方式", type: "select", options: matchModeOptions, default: "manual" },
      { prop: "confidence", label: "置信度", type: "number", default: 100 },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
  {
    key: "dept",
    label: "部门映射",
    api: SystemMappingAPI.dept,
    columns: [
      { prop: "source_type", label: "来源类型", width: 110 },
      { prop: "source_org_code", label: "来源组织", width: 100 },
      { prop: "source_dept_code", label: "来源部门编码", width: 140 },
      { prop: "source_dept_name", label: "来源部门名称", width: 160 },
      { prop: "master_org_code", label: "标准组织", width: 100 },
      { prop: "master_dept_code", label: "标准部门编码", width: 140 },
      { prop: "master_dept_name", label: "标准部门名称", width: 160 },
      { prop: "match_mode", label: "匹配方式", width: 100 },
    ],
    fields: [
      { prop: "source_dept_id", label: "来源部门ID", type: "number" },
      { prop: "master_dept_id", label: "标准部门ID", type: "number" },
      { prop: "match_mode", label: "匹配方式", type: "select", options: matchModeOptions, default: "manual" },
      { prop: "confidence", label: "置信度", type: "number", default: 100 },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
  {
    key: "field",
    label: "字段映射",
    api: SystemMappingAPI.field,
    columns: [
      { prop: "source_field_key", label: "来源字段", width: 140 },
      { prop: "source_field_name", label: "来源字段名称", width: 160 },
      { prop: "standard_field_code", label: "标准字段", width: 140 },
      { prop: "standard_field_name", label: "标准字段名称", width: 160 },
      { prop: "transform_type", label: "加工类型", width: 120 },
      { prop: "order", label: "顺序", width: 70 },
    ],
    fields: [
      { prop: "source_object_id", label: "来源对象ID", type: "number" },
      { prop: "source_field_id", label: "来源字段ID", type: "number" },
      { prop: "standard_field_id", label: "标准字段ID", type: "number" },
      { prop: "transform_type", label: "加工类型", type: "select", options: transformOptions, default: "direct" },
      { prop: "transform_config", label: "加工配置", type: "json" },
      { prop: "order", label: "执行顺序", type: "number", default: 0 },
      { prop: "status", label: "状态", type: "select", options: statusOptions, default: 0 },
    ],
  },
];

const activeKey = ref(resources[0]!.key);
const rows = ref<MappingItem[]>([]);
const loading = ref(false);
const submitting = ref(false);
const matching = ref(false);
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const selectedRows = ref<MappingItem[]>([]);
const form = reactive<Record<string, any>>({});
const page = reactive({ page_no: 1, page_size: 10, total: 0 });

const current = computed(() => resources.find((item) => item.key === activeKey.value) ?? resources[0]!);

function formatCell(row: MappingItem, col: ColumnConfig) {
  const value = row[col.prop];
  if (col.formatter) return col.formatter(value);
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

async function loadData() {
  loading.value = true;
  try {
    const res = await current.value.api.page({ page_no: page.page_no, page_size: page.page_size });
    rows.value = res.data?.data?.items ?? [];
    page.total = res.data?.data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

function resetForm(row?: MappingItem) {
  Object.keys(form).forEach((key) => delete form[key]);
  current.value.fields.forEach((field) => {
    let value = row?.[field.prop] ?? field.default ?? undefined;
    if (field.type === "json" && value !== undefined && value !== null && typeof value !== "string") {
      value = JSON.stringify(value, null, 2);
    }
    form[field.prop] = value;
  });
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: MappingItem) {
  editingId.value = row.id ?? null;
  resetForm(row);
  dialogVisible.value = true;
}

async function submitForm() {
  const payload = { ...form };
  for (const field of current.value.fields) {
    if (field.type === "json" && typeof payload[field.prop] === "string" && payload[field.prop]) {
      try {
        payload[field.prop] = JSON.parse(payload[field.prop]);
      } catch {
        ElMessage.warning(`${field.label} 不是有效 JSON`);
        return;
      }
    }
  }
  submitting.value = true;
  try {
    if (editingId.value) {
      await current.value.api.update(editingId.value, payload);
      ElMessage.success("修改成功");
    } else {
      await current.value.api.create(payload);
      ElMessage.success("新增成功");
    }
    dialogVisible.value = false;
    await loadData();
  } finally {
    submitting.value = false;
  }
}

async function removeRow(row: MappingItem) {
  await ElMessageBox.confirm("确认删除该映射？", "提示", { type: "warning" });
  await current.value.api.remove([row.id!]);
  ElMessage.success("删除成功");
  await loadData();
}

async function deleteSelected() {
  await ElMessageBox.confirm(`确认删除选中的 ${selectedRows.value.length} 条映射？`, "提示", { type: "warning" });
  await current.value.api.remove(selectedRows.value.map((row) => row.id!));
  ElMessage.success("删除成功");
  await loadData();
}

async function autoMatch() {
  matching.value = true;
  try {
    const res = await current.value.api.autoMatch({});
    const result = res.data?.data ?? {};
    ElMessage.success(`自动匹配完成：新增 ${result.created ?? 0}，跳过 ${result.skipped ?? 0}`);
    await loadData();
  } finally {
    matching.value = false;
  }
}

function onSelectionChange(values: MappingItem[]) {
  selectedRows.value = values;
}

function handleSizeChange() {
  page.page_no = 1;
  loadData();
}

function handleTabChange() {
  page.page_no = 1;
  selectedRows.value = [];
  loadData();
}

onMounted(loadData);
</script>

<style scoped>
.mapping-page {
  height: 100%;
  padding: 12px;
}
.toolbar {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
