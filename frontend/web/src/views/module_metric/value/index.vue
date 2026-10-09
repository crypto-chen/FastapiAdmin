<template>
  <div class="metric-value-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElRadioGroup v-model="viewMode">
          <ElRadioButton value="form">表单视图</ElRadioButton>
          <ElRadioButton value="detail">明细视图</ElRadioButton>
        </ElRadioGroup>

        <ElSelect
          v-model="metricIds"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="4"
          filterable
          clearable
          placeholder="选择指标（可多选）"
          style="width: 360px"
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
          style="width: 200px"
          @change="handleQuery"
        >
          <ElOption v-for="opt in orgOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </ElSelect>

        <ElRadioGroup v-model="level" @change="handleQuery">
          <ElRadioButton value="org">组织合计</ElRadioButton>
          <ElRadioButton value="dept">数据明细</ElRadioButton>
          <ElRadioButton value="person">业务员明细</ElRadioButton>
          <ElRadioButton value="all">全部</ElRadioButton>
        </ElRadioGroup>

        <ElButton type="primary" :loading="loading" @click="handleQuery">查询</ElButton>
        <ElButton :loading="running" @click="openRecalc">重算</ElButton>
      </div>

      <div class="summary">
        <span>共 {{ page.total }} 行 / {{ columns.length }} 个指标</span>
        <span class="summary-extra">鼠标移到指标名称上可查看口径</span>
      </div>

      <!-- 表单视图：一行一个组织/核算维度，一列一个指标，可一次对比多个指标 -->
      <ElTable
        v-if="viewMode === 'form'"
        v-loading="loading"
        :data="rows"
        border
        stripe
        row-key="row_key"
        max-height="calc(100vh - 400px)"
        show-summary
        :summary-method="formSummary"
      >
        <ElTableColumn prop="period_value" label="期间" width="100" fixed />
        <ElTableColumn label="组织" min-width="200" show-overflow-tooltip fixed>
          <template #default="{ row }">{{ row.org_name || row.org_code || "公司整体" }}</template>
        </ElTableColumn>
        <ElTableColumn label="核算维度" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.person_code ? "-" : row.dept_name || row.dept_code || "（组织合计）" }}
          </template>
        </ElTableColumn>
        <ElTableColumn v-if="hasPerson" label="业务员" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.person_name || row.person_code || "-" }}</template>
        </ElTableColumn>
        <ElTableColumn v-for="col in columns" :key="col.metric_id" min-width="170" align="right">
          <template #header>
            <MetricNameTip :name="col.name" :code="col.code" :description="col.description" />
          </template>
          <template #default="{ row }">{{ formatCell(row, col.metric_id) }}</template>
        </ElTableColumn>
      </ElTable>

      <!-- 明细视图：一行一个「指标 + 组织/维度」结果 -->
      <ElTable
        v-else
        v-loading="loading"
        :data="detailRows"
        border
        stripe
        max-height="calc(100vh - 400px)"
      >
        <ElTableColumn label="指标" min-width="200" fixed>
          <template #default="{ row }">
            <MetricNameTip :name="row.name" :code="row.code" :description="row.description" />
          </template>
        </ElTableColumn>
        <ElTableColumn prop="period_value" label="期间" width="100" />
        <ElTableColumn prop="org_text" label="组织" min-width="220" show-overflow-tooltip />
        <ElTableColumn prop="dept_text" label="核算维度" min-width="160" show-overflow-tooltip />
        <ElTableColumn v-if="hasPerson" prop="person_text" label="业务员" min-width="160" show-overflow-tooltip />
        <ElTableColumn label="指标值" width="170" align="right">
          <template #default="{ row }">{{ formatAmount(row.value) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="calc_version" label="计算版本" width="100" align="center" />
        <ElTableColumn label="计算时间" width="190">
          <template #default="{ row }">{{ formatTime(row.calc_time) }}</template>
        </ElTableColumn>
      </ElTable>

      <ElPagination
        v-model:current-page="page.page_no"
        v-model:page-size="page.page_size"
        :total="page.total"
        :page-sizes="[50, 100, 200, 500]"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </ElCard>

    <!-- 重算：勾选要重算的指标，支持「重算选中」与「重算全部」 -->
    <ElDialog v-model="recalcVisible" title="重算指标" width="680px" :close-on-click-modal="false">
      <div class="recalc-toolbar">
        <ElCheckbox v-model="recalcAll" :indeterminate="recalcIndeterminate">
          全选（{{ metrics.length }} 个启用指标）
        </ElCheckbox>
        <ElDatePicker
          v-model="recalcPeriod"
          type="month"
          placeholder="期间"
          value-format="YYYY-MM"
          style="width: 150px"
        />
      </div>
      <ElScrollbar height="320px">
        <ElCheckboxGroup v-model="recalcIds" class="recalc-list">
          <ElCheckbox v-for="item in metrics" :key="item.id" :value="item.id" class="recalc-item">
            <span>{{ item.name }}（{{ item.code }}）</span>
          </ElCheckbox>
        </ElCheckboxGroup>
      </ElScrollbar>
      <ElAlert :closable="false" type="info" show-icon class="recalc-tip">
        重算按依赖分层执行（组成指标先算），派生指标会自动带上其依赖指标；历史期间首次重算需按期间回补取数，可能耗时数分钟。
      </ElAlert>
      <template #footer>
        <ElButton @click="recalcVisible = false">取消</ElButton>
        <ElButton :loading="running" @click="handleRunAll">重算全部指标</ElButton>
        <ElButton type="primary" :loading="running" :disabled="!recalcIds.length" @click="handleRunSelected">
          重算选中（{{ recalcIds.length }}）
        </ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, defineComponent, h, onMounted, reactive, ref, type PropType } from "vue";
import { ElMessage, ElTooltip } from "element-plus";
import { MetricAPI, type MetricDefItem, type MetricMatrixColumn, type MetricMatrixRow } from "@/api/module_metric";
import { ManualBindingAPI } from "@/api/module_system_mapping";

defineOptions({ name: "MetricValue" });

/** 指标名称 + 口径悬浮提示：鼠标移到指标名上展示口径。 */
const MetricNameTip = defineComponent({
  name: "MetricNameTip",
  props: {
    name: { type: String, required: true },
    code: { type: String as PropType<string | null>, default: null },
    description: { type: String as PropType<string | null>, default: null },
  },
  setup(props) {
    return () =>
      h(
        ElTooltip,
        { placement: "top", effect: "dark", "show-after": 120, popperClass: "metric-tip-popper" },
        {
          content: () =>
            h("div", { class: "metric-tip" }, [
              h(
                "div",
                { class: "metric-tip-title" },
                props.code ? `${props.name}（${props.code}）` : props.name,
              ),
              h("div", { class: "metric-tip-body" }, props.description?.trim() || "暂无口径说明"),
            ]),
          default: () => h("span", { class: "metric-name" }, props.name),
        },
      );
  },
});

const loading = ref(false);
const running = ref(false);
const metrics = ref<MetricDefItem[]>([]);
const metricIds = ref<number[]>([]);
const viewMode = ref<"form" | "detail">("form");
const orgOptions = ref<{ value: number; label: string }[]>([]);
const orgId = ref<number | undefined>(undefined);
const level = ref<"org" | "dept" | "person" | "all">("org");
const now = new Date();
const periodValue = ref<string>(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`);
const columns = ref<MetricMatrixColumn[]>([]);
const rows = ref<MetricMatrixRow[]>([]);
const page = reactive({ page_no: 1, page_size: 200, total: 0 });

const recalcVisible = ref(false);
const recalcIds = ref<number[]>([]);
const recalcPeriod = ref<string>(periodValue.value);

const recalcAll = computed({
  get: () => metrics.value.length > 0 && recalcIds.value.length === metrics.value.length,
  set: (value: boolean) => {
    recalcIds.value = value ? metrics.value.map((item) => item.id) : [];
  },
});
const recalcIndeterminate = computed(() => recalcIds.value.length > 0 && !recalcAll.value);

interface DetailRow {
  key: string;
  name: string;
  code: string;
  description?: string | null;
  period_value: string;
  org_text: string;
  dept_text: string;
  person_text: string;
  value?: number;
  calc_version?: number;
  calc_time?: string | null;
}

/** 明细视图：把表单行摊平成「一行一个指标值」。 */
const detailRows = computed<DetailRow[]>(() =>
  rows.value.flatMap((row) =>
    columns.value.flatMap((col) => {
      const value = row.values[String(col.metric_id)];
      if (value === undefined || value === null) return [];
      const item: DetailRow = {
        key: `${row.row_key}:${col.metric_id}`,
        name: col.name,
        code: col.code,
        description: col.description,
        period_value: row.period_value,
        org_text: row.org_name || row.org_code || "公司整体",
        dept_text: row.person_code ? "-" : row.dept_name || row.dept_code || "（组织合计）",
        person_text: row.person_name || row.person_code || "",
        value,
        calc_version: row.calc_versions[String(col.metric_id)],
        calc_time: row.calc_times[String(col.metric_id)],
      };
      return [item];
    }),
  ),
);

function formatAmount(value: unknown) {
  if (value === undefined || value === null) return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCell(row: Record<string, any>, metricId: number) {
  return formatAmount((row.values ?? {})[String(metricId)]);
}

/** 当前结果里是否含业务员行（含则表格多显示一列「业务员」）。 */
const hasPerson = computed(() => rows.value.some((row) => Boolean(row.person_code)));

function formatTime(value?: string | null) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

/** 表单合计行：只累加组织合计行，避免与核算维度明细重复计入。 */
function formSummary({ columns: tableColumns, data }: { columns: unknown[]; data: MetricMatrixRow[] }) {
  // 前置列：期间 + 组织 + 核算维度（+ 业务员，仅在含业务员行时出现）
  const leadCount = hasPerson.value ? 4 : 3;
  // 有组织合计行时用它（避免与明细重复计入）；按业务员取数时没有合计行，直接累加业务员行
  const totalBase = data.some((row) => !row.dept_code && !row.person_code)
    ? data.filter((row) => !row.dept_code && !row.person_code)
    : data.filter((row) => Boolean(row.person_code));
  return tableColumns.map((_, index) => {
    if (index === 0) return level.value === "person" ? "合计（业务员行累加）" : "合计（组织）";
    if (index < leadCount) return "";
    const metricId = columns.value[index - leadCount]?.metric_id;
    if (!metricId) return "";
    const total = totalBase.reduce((sum, row) => {
      const value = row.values[String(metricId)];
      return value === undefined || value === null ? sum : sum + Number(value);
    }, 0);
    return formatAmount(total);
  });
}

async function loadMetrics() {
  // 指标定义接口单页上限 100，启用指标可能超过一页，这里翻页取全（最多 500 个）
  const all: MetricDefItem[] = [];
  for (let pageNo = 1; pageNo <= 5; pageNo++) {
    const res = await MetricAPI.defPage({ page_no: pageNo, page_size: 100, status: 0 });
    const items = res.data?.data?.items ?? [];
    all.push(...items);
    if (items.length < 100) break;
  }
  metrics.value = all;
  if (!metricIds.value.length && metrics.value.length) {
    // 默认带上前若干指标，打开即能看到多指标对比
    metricIds.value = metrics.value.slice(0, 10).map((item) => item.id);
  }
}

async function loadData() {
  if (!metricIds.value.length) {
    columns.value = [];
    rows.value = [];
    page.total = 0;
    return;
  }
  loading.value = true;
  try {
    const res = await MetricAPI.matrix({
      metric_ids: metricIds.value.join(","),
      period_value: periodValue.value || undefined,
      org_id: orgId.value,
      level: level.value,
      page_no: page.page_no,
      page_size: page.page_size,
    });
    const data = res.data?.data;
    columns.value = data?.columns ?? [];
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

function openRecalc() {
  recalcPeriod.value = periodValue.value;
  recalcIds.value = metricIds.value.length ? [...metricIds.value] : metrics.value.map((item) => item.id);
  recalcVisible.value = true;
}

async function handleRunAll() {
  await runBatch(undefined, recalcPeriod.value);
}

async function handleRunSelected() {
  if (!recalcIds.value.length) {
    ElMessage.warning("请先勾选要重算的指标");
    return;
  }
  await runBatch([...recalcIds.value], recalcPeriod.value);
}

async function runBatch(ids: number[] | undefined, period: string) {
  running.value = true;
  ElMessage.info(
    ids?.length ? `正在重算 ${ids.length} 个指标，请勿关闭页面` : "正在重算全部启用指标，请勿关闭页面",
  );
  try {
    const res = await MetricAPI.runBatch({
      metric_ids: ids,
      period_value: period || undefined,
    });
    const data = res.data?.data;
    const failed = data?.failed ?? [];
    if (failed.length) {
      ElMessage.warning(
        `重算结束：成功 ${data?.success ?? 0}/${data?.metric_count ?? 0}，失败 ${failed.length} 个：${failed
          .slice(0, 3)
          .join("；")}`,
      );
    } else {
      ElMessage.success(
        `重算完成：成功 ${data?.success ?? 0}/${data?.metric_count ?? 0} 个指标，耗时 ${data?.elapsed_seconds ?? 0}s`,
      );
    }
    if (data?.period) {
      periodValue.value = data.period;
      recalcPeriod.value = data.period;
    }
    recalcVisible.value = false;
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
.summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 14px;
  color: var(--el-text-color-regular);
}
.summary-extra {
  color: var(--el-text-color-secondary);
}
.pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
.metric-name {
  border-bottom: 1px dashed var(--el-text-color-secondary);
  cursor: help;
}
.recalc-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.recalc-list {
  display: flex;
  flex-direction: column;
}
.recalc-item {
  height: 30px;
}
.recalc-tip {
  margin-top: 8px;
}
</style>

<style>
.metric-tip-popper {
  max-width: 420px;
}
.metric-tip-popper .metric-tip-title {
  margin-bottom: 4px;
  font-weight: 600;
}
.metric-tip-popper .metric-tip-body {
  line-height: 1.5;
  white-space: pre-wrap;
}
</style>
