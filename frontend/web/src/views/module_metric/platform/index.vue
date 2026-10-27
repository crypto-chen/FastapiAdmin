<template>
  <div class="platform-analysis-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElSelect v-model="periodValue" placeholder="期间" clearable style="width: 130px" @change="handleQuery">
          <ElOption v-for="item in periodOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

        <ElSelect v-model="platform" placeholder="平台" clearable filterable style="width: 140px" @change="handleQuery">
          <ElOption v-for="item in platformOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

        <ElInputNumber
          v-model="shopId"
          :min="0"
          :controls="false"
          placeholder="店铺编号"
          style="width: 130px"
          @change="handleQuery"
        />

        <ElInput
          v-model="keyword"
          placeholder="平台/店铺（模糊）"
          clearable
          style="width: 190px"
          @keyup.enter="handleQuery"
        />

        <ElRadioGroup v-model="aggregateLevel" @change="handleQuery">
          <ElRadioButton label="detail">店铺明细</ElRadioButton>
          <ElRadioButton label="platform">平台小计</ElRadioButton>
          <ElRadioButton label="all">全部</ElRadioButton>
        </ElRadioGroup>

        <ElButton type="primary" :loading="loading" @click="handleQuery">查询</ElButton>
        <ElButton @click="detailVisible = true">字段说明</ElButton>
        <ElButton @click="openStats">平台排行</ElButton>
      </div>

      <div class="toolbar toolbar-second">
        <span class="picker-label">显示字段</span>
        <ElSelect
          v-model="visibleFields"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="9"
          filterable
          clearable
          placeholder="选择要显示的字段"
          style="width: 620px"
        >
          <ElOptionGroup v-for="group in columnGroups" :key="group.name" :label="group.name">
            <ElOption
              v-for="col in group.items"
              :key="col.field_code"
              :label="`${col.field_name}（${col.field_code}）`"
              :value="col.field_code"
            />
          </ElOptionGroup>
        </ElSelect>
        <ElButton link type="primary" @click="resetFields">恢复默认</ElButton>
      </div>

      <div class="summary">
        <span>期间 {{ page.period_value || "全部" }} · 税率 {{ page.tax_rate }}%</span>
        <span>平台 {{ summary.platform_count ?? "-" }} 个</span>
        <span>店铺 {{ summary.shop_count ?? "-" }} 个</span>
        <span>订单 {{ summary.order_count ?? 0 }} 张 / 已发货 {{ summary.shipped_order_count ?? 0 }} 张</span>
        <span>接单未税 {{ formatNumber(summary.intake_untaxed_sum) }}</span>
        <span>出货未税 {{ formatNumber(summary.shipment_untaxed_sum) }}</span>
        <span>退货退款 {{ formatNumber(summary.return_untaxed_sum) }}</span>
        <span>对外出货净额 {{ formatNumber(summary.net_shipment_sum) }}</span>
        <span>结算收入10% {{ formatNumber(summary.settlement_income_sum) }}</span>
        <span>总部分摊4% {{ formatNumber(summary.hq_allocation_sum) }}</span>
        <span>退货率 {{ formatPercent(summary.return_rate) }}</span>
      </div>

      <ElTable
        v-loading="loading"
        :data="rows"
        border
        stripe
        height="calc(100vh - 400px)"
        :row-class-name="rowClassName"
        @row-click="handleRowClick"
      >
        <ElTableColumn type="index" label="#" width="55" fixed />
        <ElTableColumn
          v-for="col in displayColumns"
          :key="col.field_code"
          :label="col.field_name"
          :prop="col.field_code"
          :min-width="columnWidth(col)"
          show-overflow-tooltip
          :fixed="col.field_code === 'PLT-01'"
        >
          <template #default="{ row }">
            <span :class="{ 'sensitive-cell': col.sensitive }">
              {{ formatCell(row[col.field_code], col) }}
            </span>
          </template>
        </ElTableColumn>
      </ElTable>

      <div class="pager">
        <ElPagination
          v-model:current-page="query.page_no"
          v-model:page-size="query.page_size"
          :total="page.total"
          :page-sizes="[20, 50, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="loadData"
          @size-change="handleQuery"
        />
      </div>
    </ElCard>

    <!-- 字段说明 -->
    <ElDrawer v-model="detailVisible" title="平台分析字段说明（PLT-xx）" size="820px">
      <ElTable :data="columns" border stripe max-height="calc(100vh - 160px)">
        <ElTableColumn prop="field_code" label="编码" width="100" />
        <ElTableColumn prop="field_name" label="名称" min-width="140" />
        <ElTableColumn prop="group" label="分组" width="80" />
        <ElTableColumn prop="source" label="取数来源" width="150" show-overflow-tooltip />
        <ElTableColumn label="可出性" width="110">
          <template #default="{ row }">
            <ElTag :type="statusTagType(row.status)" size="small">{{ row.status_label }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="note" label="口径/说明" min-width="280" show-overflow-tooltip />
      </ElTable>
    </ElDrawer>

    <!-- 平台排行 -->
    <ElDrawer v-model="statsVisible" title="平台排行（按对外出货净额）" size="560px">
      <ElDescriptions :column="2" border size="small">
        <ElDescriptionsItem label="期间">{{ stats.period_value || "全部" }}</ElDescriptionsItem>
        <ElDescriptionsItem label="平台数">{{ stats.platform_count ?? 0 }}</ElDescriptionsItem>
        <ElDescriptionsItem label="订单">{{ stats.order_count ?? 0 }} 张</ElDescriptionsItem>
        <ElDescriptionsItem label="店铺">{{ stats.shop_count ?? 0 }} 个</ElDescriptionsItem>
        <ElDescriptionsItem label="净额">{{ formatNumber(stats.net_shipment_sum) }}</ElDescriptionsItem>
        <ElDescriptionsItem label="结算收入10%">{{ formatNumber(stats.settlement_income_sum) }}</ElDescriptionsItem>
      </ElDescriptions>
      <div class="rank-list">
        <div v-for="(item, index) in stats.top_platforms || []" :key="item.platform" class="rank-item">
          <div class="rank-head">
            <span class="rank-index">{{ index + 1 }}</span>
            <span class="rank-name">{{ item.platform }}</span>
            <span class="rank-value">{{ formatNumber(item.net_shipment) }}</span>
          </div>
          <ElProgress
            :percentage="percentOfTop(item.net_shipment)"
            :stroke-width="10"
            :show-text="false"
            color="#409eff"
          />
          <div class="rank-sub">
            订单 {{ item.order_count }} 张 · 接单未税 {{ formatNumber(item.intake_untaxed) }} · 出货未税
            {{ formatNumber(item.shipment_untaxed) }} · 结算收入10% {{ formatNumber(item.settlement_income) }} ·
            总部分摊4% {{ formatNumber(item.hq_allocation) }} · 退货率 {{ formatPercent(item.return_rate) }}
          </div>
        </div>
        <ElEmpty v-if="!(stats.top_platforms || []).length" description="暂无数据" />
      </div>
    </ElDrawer>

    <!-- 单行全部字段 -->
    <ElDrawer v-model="rowVisible" :title="`${currentRowLabel} 全部字段`" size="640px">
      <ElDescriptions :column="1" border>
        <ElDescriptionsItem
          v-for="col in columns"
          :key="col.field_code"
          :label="`${col.field_name}（${col.field_code}）`"
        >
          {{ formatCell(rowDetail[col.field_code], col) }}
        </ElDescriptionsItem>
      </ElDescriptions>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { ElMessage } from "element-plus";
import {
  PlatformAnalysisAPI,
  type PlatformFieldItem,
  type PlatformPageResult,
  type PlatformRow,
  type PlatformStats,
} from "@/api/module_platform";

defineOptions({ name: "PlatformAnalysis" });

/** 目录拉不到时的兜底列 */
const FALLBACK_FIELDS = ["PLT-00", "PLT-01", "PLT-02", "PLT-08", "PLT-09", "PLT-11", "PLT-12", "PLT-13"];

const loading = ref(false);
const periodOptions = ref<string[]>([]);
const periodValue = ref<string | undefined>(undefined);
const platformOptions = ref<string[]>([]);
const platform = ref<string | undefined>(undefined);
const shopId = ref<number | undefined>(undefined);
const keyword = ref("");
const aggregateLevel = ref<"detail" | "platform" | "all">("detail");

const columns = ref<PlatformFieldItem[]>([]);
const visibleFields = ref<string[]>([]);
const rows = ref<PlatformRow[]>([]);
const query = reactive({ page_no: 1, page_size: 50 });
const page = reactive({ total: 0, period_value: null as string | null, tax_rate: 13 });
const summary = ref<PlatformStats>({});
const stats = ref<PlatformStats>({});

const detailVisible = ref(false);
const statsVisible = ref(false);
const rowVisible = ref(false);
const currentRowLabel = ref("");
const rowDetail = ref<PlatformRow>({} as PlatformRow);

const displayColumns = computed<PlatformFieldItem[]>(() =>
  columns.value.filter((col) => visibleFields.value.includes(col.field_code)),
);

const columnGroups = computed(() => {
  const groups: { name: string; items: PlatformFieldItem[] }[] = [];
  columns.value.forEach((col) => {
    let group = groups.find((item) => item.name === col.group);
    if (!group) {
      group = { name: col.group, items: [] };
      groups.push(group);
    }
    group.items.push(col);
  });
  return groups;
});

function columnWidth(col: PlatformFieldItem) {
  if (col.field_code === "PLT-01") return 110;
  if (col.field_code === "PLT-02") return 190;
  if (col.field_code === "PLT-08" || col.field_code === "PLT-09") return 140;
  return 120;
}

function formatNumber(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatPercent(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return `${(num * 100).toFixed(2)}%`;
}

function formatCell(value: unknown, col: PlatformFieldItem) {
  if (value === undefined || value === null || value === "") return "-";
  if (col.data_type === "number") return formatNumber(value);
  if (col.data_type === "percent") return formatPercent(value);
  return String(value);
}

function statusTagType(status?: string) {
  if (status === "ready") return "success";
  if (status === "pending_field" || status === "source_found") return "warning";
  if (status === "missing") return "danger";
  return "info";
}

function rowClassName({ row }: { row: PlatformRow }) {
  if (Number(row.is_aggregate) === 2) return "row-total";
  if (Number(row.is_aggregate) === 1) return "row-subtotal";
  return "";
}

function percentOfTop(value: number) {
  const max = Math.max(...(stats.value.top_platforms || []).map((item) => Number(item.net_shipment) || 0), 0);
  if (!max) return 0;
  return Math.max(1, Math.round((Number(value) / max) * 100));
}

function applyDefaultFields() {
  const ready = columns.value.filter((col) => col.status === "ready").map((col) => col.field_code);
  visibleFields.value = ready.length ? ready : columns.value.map((col) => col.field_code);
  if (!visibleFields.value.length) visibleFields.value = [...FALLBACK_FIELDS];
}

function resetFields() {
  applyDefaultFields();
}

async function loadMeta() {
  const [fieldRes, periodRes, platformRes] = await Promise.all([
    PlatformAnalysisAPI.fields(),
    PlatformAnalysisAPI.periods(),
    PlatformAnalysisAPI.platforms(),
  ]);
  columns.value = fieldRes.data?.data ?? [];
  periodOptions.value = periodRes.data?.data ?? [];
  platformOptions.value = platformRes.data?.data ?? [];
  if (!visibleFields.value.length) applyDefaultFields();
  if (!periodValue.value && periodOptions.value.length) periodValue.value = periodOptions.value[0];
}

async function loadData() {
  loading.value = true;
  try {
    const res = await PlatformAnalysisAPI.page({
      period_value: periodValue.value,
      platform: platform.value,
      shop_id: shopId.value ?? undefined,
      keyword: keyword.value || undefined,
      aggregate_level: aggregateLevel.value,
      page_no: query.page_no,
      page_size: query.page_size,
    });
    const data = res.data?.data as PlatformPageResult | undefined;
    rows.value = data?.items ?? [];
    page.total = data?.total ?? 0;
    page.period_value = data?.period_value ?? null;
    page.tax_rate = data?.tax_rate ?? 13;
    summary.value = data?.summary ?? {};
  } catch (error) {
    rows.value = [];
    ElMessage.error("查询平台分析失败");
    console.error(error);
  } finally {
    loading.value = false;
  }
}

function handleQuery() {
  query.page_no = 1;
  loadData();
}

async function openStats() {
  try {
    const res = await PlatformAnalysisAPI.stats(periodValue.value);
    stats.value = res.data?.data ?? {};
    statsVisible.value = true;
  } catch (error) {
    ElMessage.error("加载平台排行失败");
    console.error(error);
  }
}

function handleRowClick(row: PlatformRow) {
  const level = Number(row.is_aggregate);
  const suffix = level === 2 ? "（全表合计）" : level === 1 ? "（平台小计）" : "";
  currentRowLabel.value = `${row["PLT-01"] || "-"} / ${row["PLT-02"] || "-"}${suffix}`;
  rowDetail.value = row;
  rowVisible.value = true;
}

onMounted(async () => {
  try {
    await loadMeta();
    await loadData();
  } catch (error) {
    ElMessage.error("加载平台分析数据失败");
    console.error(error);
  }
});
</script>

<style lang="scss" scoped>
.platform-analysis-page {
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    align-items: center;
  }

  .toolbar-second {
    margin-top: 10px;
  }

  .picker-label {
    font-size: 13px;
    color: var(--el-text-color-secondary);
  }

  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    margin: 10px 0;
    font-size: 13px;
    color: var(--el-text-color-regular);
  }

  .pager {
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
  }

  .sensitive-cell {
    color: var(--el-color-danger);
  }

  :deep(.row-subtotal) {
    background: var(--el-fill-color-light);
    font-weight: 600;
  }

  :deep(.row-total) {
    background: var(--el-color-primary-light-9);
    font-weight: 700;
  }

  .rank-list {
    margin-top: 14px;
  }

  .rank-item {
    margin-bottom: 16px;
  }

  .rank-head {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
  }

  .rank-index {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: var(--el-color-primary-light-7);
    color: var(--el-color-primary);
    font-size: 12px;
  }

  .rank-name {
    flex: 1;
    font-weight: 600;
  }

  .rank-value {
    color: var(--el-color-primary);
    font-weight: 600;
  }

  .rank-sub {
    margin-top: 4px;
    font-size: 12px;
    color: var(--el-text-color-secondary);
  }
}
</style>
