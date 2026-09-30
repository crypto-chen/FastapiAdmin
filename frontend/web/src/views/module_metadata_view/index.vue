<template>
  <div class="metadata-view-page">
    <ElTabs v-model="activeKey" @tab-change="handleTabChange">
      <ElTabPane v-for="resource in resources" :key="resource.key" :label="resource.label" :name="resource.key" />
    </ElTabs>

    <ElCard shadow="never">
      <div class="toolbar">
        <ElSelect
          v-if="current.key === 'syncRun'"
          v-model="jobId"
          placeholder="选择同步任务"
          clearable
          style="width: 280px"
          @change="loadData"
        >
          <ElOption v-for="job in jobs" :key="job.id" :label="job.name" :value="job.id" />
        </ElSelect>
        <ElButton @click="loadData">刷新</ElButton>
      </div>

      <ElTable v-loading="loading" :data="rows" border stripe>
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
        <ElTableColumn v-if="current.key === 'syncRun'" label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openRunDetail(row)">查看</ElButton>
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

    <ElDialog v-model="detailVisible" title="同步返回数据" width="900px">
      <pre class="json-preview">{{ detailJson }}</pre>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { MetadataAPI, type MetaItem } from "@/api/module_metadata";

interface ColumnConfig {
  prop: string;
  label: string;
  width?: number;
  formatter?: (value: unknown) => string;
}

interface ResourceConfig {
  key: string;
  label: string;
  page: (params: any) => Promise<any>;
  columns: ColumnConfig[];
}

const statusText = (value: unknown) => (Number(value) === 0 ? "启用" : "停用");

const resources: ResourceConfig[] = [
  {
    key: "sourceObject",
    label: "来源对象",
    page: MetadataAPI.sourceObject.page,
    columns: [
      { prop: "system_code", label: "系统编码", width: 110 },
      { prop: "code", label: "对象编码", width: 180 },
      { prop: "name", label: "对象名称", width: 180 },
      { prop: "query_type", label: "查询类型", width: 120 },
      { prop: "status", label: "状态", width: 80, formatter: statusText },
    ],
  },
  {
    key: "sourceField",
    label: "来源字段",
    page: MetadataAPI.sourceField.page,
    columns: [
      { prop: "object_code", label: "对象编码", width: 170 },
      { prop: "field_key", label: "字段Key", width: 170 },
      { prop: "field_name", label: "字段名称", width: 180 },
      { prop: "data_type", label: "数据类型", width: 100 },
      { prop: "status", label: "状态", width: 80, formatter: statusText },
    ],
  },
  {
    key: "standardEntity",
    label: "标准实体",
    page: MetadataAPI.standardEntity.page,
    columns: [
      { prop: "code", label: "实体编码", width: 160 },
      { prop: "name", label: "实体名称", width: 180 },
      { prop: "table_name", label: "物理表", width: 160 },
      { prop: "status", label: "状态", width: 80, formatter: statusText },
    ],
  },
  {
    key: "standardField",
    label: "标准字段",
    page: MetadataAPI.standardField.page,
    columns: [
      { prop: "entity_code", label: "实体编码", width: 160 },
      { prop: "field_code", label: "字段编码", width: 160 },
      { prop: "field_name", label: "字段名称", width: 180 },
      { prop: "data_type", label: "数据类型", width: 100 },
      { prop: "status", label: "状态", width: 80, formatter: statusText },
    ],
  },
  {
    key: "fieldMapping",
    label: "字段映射",
    page: MetadataAPI.fieldMapping.page,
    columns: [
      { prop: "source_field_key", label: "来源字段", width: 160 },
      { prop: "source_field_name", label: "来源字段名称", width: 180 },
      { prop: "standard_field_code", label: "标准字段", width: 160 },
      { prop: "transform_type", label: "加工类型", width: 120 },
      { prop: "order", label: "顺序", width: 70 },
      { prop: "status", label: "状态", width: 80, formatter: statusText },
    ],
  },
  {
    key: "syncJob",
    label: "同步任务",
    page: MetadataAPI.syncJob.page,
    columns: [
      { prop: "name", label: "任务名称", width: 200 },
      { prop: "system_code", label: "系统编码", width: 110 },
      { prop: "object_code", label: "对象编码", width: 180 },
      { prop: "org_code", label: "组织编码", width: 100 },
      { prop: "cron_expr", label: "Cron表达式", width: 160 },
      { prop: "status", label: "状态", width: 80, formatter: statusText },
    ],
  },
  {
    key: "syncRun",
    label: "同步日志",
    page: MetadataAPI.syncJob.runPage,
    columns: [
      { prop: "batch_id", label: "批次ID", width: 200 },
      { prop: "status", label: "状态", width: 100 },
      { prop: "row_count", label: "行数", width: 100 },
      { prop: "started_at", label: "开始时间", width: 180 },
      { prop: "finished_at", label: "结束时间", width: 180 },
      { prop: "error", label: "错误信息", width: 240 },
    ],
  },
];

const activeKey = ref(resources[0]!.key);
const rows = ref<MetaItem[]>([]);
const jobs = ref<MetaItem[]>([]);
const jobId = ref<number | undefined>(undefined);
const loading = ref(false);
const detailVisible = ref(false);
const detailJson = ref("");
const page = reactive({ page_no: 1, page_size: 10, total: 0 });

const current = computed(() => resources.find((item) => item.key === activeKey.value) ?? resources[0]!);

function formatCell(row: MetaItem, col: ColumnConfig) {
  const value = row[col.prop];
  if (col.formatter) return col.formatter(value);
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

async function loadJobs() {
  const res = await MetadataAPI.syncJob.page({ page_no: 1, page_size: 100 });
  jobs.value = res.data?.data?.items ?? [];
}

async function loadData() {
  loading.value = true;
  try {
    const params: Record<string, unknown> = { page_no: page.page_no, page_size: page.page_size };
    if (current.value.key === "syncRun" && jobId.value) params.job_id = jobId.value;
    const res = await current.value.page(params);
    rows.value = res.data?.data?.items ?? [];
    page.total = res.data?.data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

async function openRunDetail(row: MetaItem) {
  const res = await MetadataAPI.syncJob.runDetail(row.id!);
  detailJson.value = JSON.stringify(res.data?.data?.rows_json ?? {}, null, 2);
  detailVisible.value = true;
}

function handleSizeChange() {
  page.page_no = 1;
  loadData();
}

function handleTabChange() {
  page.page_no = 1;
  loadData();
}

onMounted(async () => {
  await loadJobs();
  await loadData();
});
</script>

<style scoped>
.metadata-view-page {
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
.json-preview {
  max-height: 70vh;
  overflow: auto;
  padding: 12px;
  background: var(--el-fill-color-light);
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
}
</style>
