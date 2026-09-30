<template>
  <div class="metric-value-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElSelect
          v-model="metricId"
          placeholder="选择指标"
          style="width: 260px"
          filterable
          @change="handleQuery"
        >
          <ElOption
            v-for="item in metrics"
            :key="item.id"
            :label="`${item.name}（${item.code}）`"
            :value="item.id"
          />
        </ElSelect>
        <ElDatePicker
          v-model="periodValue"
          type="month"
          placeholder="期间"
          value-format="YYYY-MM"
          style="width: 150px"
          @change="handleQuery"
        />
        <ElSelect
          v-model="orgId"
          placeholder="组织"
          clearable
          filterable
          style="width: 220px"
          @change="handleQuery"
        >
          <ElOption v-for="opt in orgOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </ElSelect>
        <ElRadioGroup v-model="level" @change="handleQuery">
          <ElRadioButton value="org">组织合计</ElRadioButton>
          <ElRadioButton value="dept">数据明细</ElRadioButton>
          <ElRadioButton value="all">全部</ElRadioButton>
        </ElRadioGroup>
        <ElButton type="primary" :loading="loading" @click="handleQuery">查询</ElButton>
        <ElButton :loading="running" :disabled="!metricId" @click="handleRunCalc">重算</ElButton>
      </div>

      <ElAlert v-if="currentMetric" :closable="false" type="info" show-icon class="metric-tip">
        <template #title>
          口径：{{ currentMetric.description || currentMetric.code }}；期间类型 {{ currentMetric.period_type }}，
          默认显示最新计算版本。
        </template>
      </ElAlert>

      <div class="summary">
        组织合计（当前筛选）：<span class="summary-value">{{ formatAmount(orgLevelTotal) }}</span>
        <span class="summary-extra">共 {{ page.total }} 条结果</span>
      </div>

      <ElTable v-loading="loading" :data="rows" border stripe row-key="id" max-height="calc(100vh - 360px)">
        <ElTableColumn prop="period_value" label="期间" width="110" />
        <ElTableColumn prop="org_name" label="组织" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ row.org_name || row.org_code || "-" }}</template>
        </ElTableColumn>
        <ElTableColumn prop="dept_name" label="核算维度" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.dept_name || row.dept_code || "（组织合计）" }}</template>
        </ElTableColumn>
        <ElTableColumn prop="value" label="指标值" width="160" align="right">
          <template #default="{ row }">{{ formatAmount(row.value) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="calc_version" label="计算版本" width="100" align="center" />
        <ElTableColumn prop="calc_time" label="计算时间" width="190">
          <template #default="{ row }">{{ formatTime(row.calc_time) }}</template>
        </ElTableColumn>
      </ElTable>

      <ElPagination
        v-model:current-page="page.page_no"
        v-model:page-size="page.page_size"
        :total="page.total"
        :page-sizes="[20, 50, 100, 200]"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </ElCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import { MetricAPI, type MetricDefItem, type MetricValueItem } from "@/api/module_metric";
import { ManualBindingAPI } from "@/api/module_system_mapping";

defineOptions({ name: "MetricValue" });

const loading = ref(false);
const running = ref(false);
const metrics = ref<MetricDefItem[]>([]);
const metricId = ref<number | undefined>(undefined);
const orgOptions = ref<{ value: number; label: string }[]>([]);
const orgId = ref<number | undefined>(undefined);
const level = ref<"org" | "dept" | "all">("org");
const now = new Date();
const periodValue = ref<string>(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
const rows = ref<MetricValueItem[]>([]);
const page = reactive({ page_no: 1, page_size: 50, total: 0 });

const currentMetric = computed(() => metrics.value.find((item) => item.id === metricId.value));
const orgLevelTotal = computed(() =>
  rows.value.reduce((sum, row) => (row.dept_code ? sum : sum + Number(row.value || 0)), 0),
);

function formatAmount(value: unknown) {
  const num = Number(value ?? 0);
  if (Number.isNaN(num)) return "-";
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatTime(value?: string | null) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

async function loadMetrics() {
  const res = await MetricAPI.defPage({ page_no: 1, page_size: 100, status: 0 });
  metrics.value = res.data?.data?.items ?? [];
  if (!metricId.value && metrics.value.length) {
    metricId.value = metrics.value[0]?.id;
  }
}

async function loadData() {
  loading.value = true;
  try {
    const res = await MetricAPI.valuePage({
      page_no: page.page_no,
      page_size: page.page_size,
      metric_id: metricId.value,
      period_type: currentMetric.value?.period_type,
      period_value: periodValue.value || undefined,
      org_id: orgId.value,
      level: level.value,
    });
    const data = res.data?.data;
    rows.value = data?.items ?? [];
    page.total = data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

function handleQuery() {
  page.page_no = 1;
  loadData();
}

function handleSizeChange() {
  page.page_no = 1;
  loadData();
}

async function handleRunCalc() {
  if (!metricId.value) return ElMessage.warning("请先选择指标");
  running.value = true;
  ElMessage.info("正在重算：历史期间会先按该期间回补取数，可能需要几分钟，请勿关闭页面");
  try {
    const res = await MetricAPI.runCalc(metricId.value, {
      period_value: periodValue.value || undefined,
    });
    const data = res.data?.data;
    const backfilled = data?.backfilled_orgs?.length
      ? `，已按 ${data.period_value} 回补 ${data.backfilled_orgs.length} 个组织的取数`
      : "";
    ElMessage.success(
      `重算完成：${data?.period_value ?? ""} 合计 ${formatAmount(data?.total)}（组织 ${data?.org_count ?? 0} 个）${backfilled}`,
    );
    periodValue.value = data?.period_value ?? periodValue.value;
    await loadData();
  } finally {
    running.value = false;
  }
}

onMounted(async () => {
  const [orgRes] = await Promise.all([ManualBindingAPI.orgOptions(), loadMetrics()]);
  orgOptions.value = orgRes.data?.data ?? [];
  await loadData();
});
</script>

<style scoped>
.metric-value-page {
  height: 100%;
  padding: 12px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.metric-tip {
  margin-bottom: 12px;
}
.summary {
  margin-bottom: 12px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}
.summary-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--el-color-primary);
}
.summary-extra {
  margin-left: 12px;
  color: var(--el-text-color-secondary);
}
.pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
</style>
