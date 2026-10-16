<template>
  <div class="product-line-analysis-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElSelect v-model="periodValue" placeholder="期间" clearable style="width: 130px" @change="handleQuery">
          <ElOption v-for="item in periodOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

        <ElSelect v-model="productLine" placeholder="产品线大类" clearable filterable style="width: 170px" @change="handleQuery">
          <ElOption v-for="item in productLineOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

        <ElInput
          v-model="keyword"
          placeholder="产品线/SKU（模糊）"
          clearable
          style="width: 190px"
          @keyup.enter="handleQuery"
        />

        <ElSelect v-model="orderType" placeholder="订单类型" clearable style="width: 120px" @change="handleQuery">
          <ElOption label="批量" value="批量" />
          <ElOption label="打样" value="打样" />
          <ElOption label="零售" value="零售" />
          <ElOption label="备货" value="备货" />
        </ElSelect>

        <ElSelect v-model="platform" placeholder="平台" clearable filterable style="width: 130px" @change="handleQuery">
          <ElOption v-for="item in platformOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

        <ElRadioGroup v-model="aggregateLevel" @change="handleQuery">
          <ElRadioButton label="detail">产品线 × SKU</ElRadioButton>
          <ElRadioButton label="line">产品线小计</ElRadioButton>
          <ElRadioButton label="all">全部</ElRadioButton>
        </ElRadioGroup>

        <ElButton type="primary" :loading="loading" @click="handleQuery">查询</ElButton>
        <ElButton :loading="running" @click="handleRebuild">按期间构建</ElButton>
        <ElButton @click="detailVisible = true">字段说明</ElButton>
        <ElButton @click="statsVisible = true">产品线排行</ElButton>
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
              :label="`${col.field_name}（${col.field_code}）${col.status_label && col.status_label !== '现用可出' ? ' · ' + col.status_label : ''}`"
              :value="col.field_code"
            />
          </ElOptionGroup>
        </ElSelect>
        <ElButton link type="primary" @click="resetFields">恢复默认</ElButton>
        <ElButton link type="primary" @click="selectReadyFields">只看现用可出</ElButton>
      </div>

      <div class="summary">
        <span>期间 {{ page.period_value || "-" }} · 版本 v{{ page.calc_version || "-" }}</span>
        <span>产品线 {{ summary.line_count ?? "-" }} 个</span>
        <span>SKU {{ summary.sku_count ?? "-" }} 个</span>
        <span>订单 {{ summary.order_count ?? 0 }} 行</span>
        <span>接单未税 {{ formatNumber(summary.intake_untaxed_sum) }}</span>
        <span>出货未税 {{ formatNumber(summary.ship_untaxed_sum) }}</span>
        <span>对外出货净额 {{ formatNumber(summary.net_shipment_sum) }}</span>
        <span>结算收入10% {{ formatNumber(summary.settlement_income_sum) }}</span>
        <span class="summary-extra">点行可看该行全部字段</span>
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
          :fixed="col.field_code === 'PRD-01'"
        >
          <template #default="{ row }">
            <span :class="{ 'sensitive-cell': col.sensitive }">{{ formatCell(row[col.field_code], col) }}</span>
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
    <ElDrawer v-model="detailVisible" title="产品线分析字段说明（PRD-xx）" size="820px">
      <ElTable :data="columns" border stripe max-height="calc(100vh - 160px)">
        <ElTableColumn prop="field_code" label="编码" width="100" />
        <ElTableColumn prop="field_name" label="名称" min-width="130" />
        <ElTableColumn prop="group" label="分组" width="80" />
        <ElTableColumn prop="source" label="底稿来源" width="100" />
        <ElTableColumn label="可出性" width="110">
          <template #default="{ row }">
            <ElTag :type="statusTagType(row.status)" size="small">{{ row.status_label }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="note" label="口径/说明" min-width="260" show-overflow-tooltip />
      </ElTable>
    </ElDrawer>

    <!-- 产品线排行 -->
    <ElDrawer v-model="statsVisible" title="产品线排行（按对外出货净额）" size="560px">
      <ElDescriptions :column="2" border size="small">
        <ElDescriptionsItem label="期间">{{ summary.period_value || "-" }}</ElDescriptionsItem>
        <ElDescriptionsItem label="版本">v{{ summary.calc_version || "-" }}</ElDescriptionsItem>
        <ElDescriptionsItem label="订单">{{ summary.order_count ?? 0 }} 行</ElDescriptionsItem>
        <ElDescriptionsItem label="SKU">{{ summary.sku_count ?? 0 }} 个</ElDescriptionsItem>
      </ElDescriptions>
      <div class="rank-list">
        <div v-for="(item, index) in summary.top_lines || []" :key="item.product_line" class="rank-item">
          <div class="rank-head">
            <span class="rank-index">{{ index + 1 }}</span>
            <span class="rank-name">{{ item.product_line }}</span>
            <span class="rank-value">{{ formatNumber(item.net_shipment) }}</span>
          </div>
          <ElProgress
            :percentage="percentOfTop(item.net_shipment)"
            :stroke-width="10"
            :show-text="false"
            color="#409eff"
          />
          <div class="rank-sub">
            订单 {{ item.order_count }} 行 · 接单未税 {{ formatNumber(item.intake_untaxed) }} · 出货未税
            {{ formatNumber(item.ship_untaxed) }} · 结算收入10% {{ formatNumber(item.settlement_income) }}
          </div>
        </div>
        <ElEmpty v-if="!(summary.top_lines || []).length" description="暂无数据" />
      </div>
    </ElDrawer>

    <!-- 单行全部字段 -->
    <ElDrawer v-model="rowVisible" :title="`${currentRowLabel} 全部字段`" size="640px">
      <ElDescriptions :column="1" border>
        <ElDescriptionsItem v-for="col in columns" :key="col.field_code" :label="`${col.field_name}（${col.field_code}）`">
          {{ formatCell(rowDetail[col.field_code], col) }}
        </ElDescriptionsItem>
      </ElDescriptions>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import {
  ProductLineAPI,
  type ProductLineFieldItem,
  type ProductLinePageResult,
  type ProductLineRow,
  type ProductLineStats,
} from "@/api/module_product";
import { ElMessage, ElMessageBox } from "element-plus";

defineOptions({ name: "ProductLineAnalysis" });

/** 目录拉不到时兜底 */
const FALLBACK_FIELDS = ["PRD-01", "PRD-02", "PRD-22", "PRD-23", "PRD-26", "PRD-27", "PRD-X01"];

const loading = ref(false);
const running = ref(false);
const periodOptions = ref<string[]>([]);
const periodValue = ref<string | undefined>(undefined);
const productLineOptions = ref<string[]>([]);
const productLine = ref<string | undefined>(undefined);
const platform = ref<string | undefined>(undefined);
const keyword = ref("");
const orderType = ref<string | undefined>(undefined);
const aggregateLevel = ref<"detail" | "line" | "all">("detail");

const columns = ref<ProductLineFieldItem[]>([]);
const visibleFields = ref<string[]>([]);
const rows = ref<ProductLineRow[]>([]);
const query = reactive({ page_no: 1, page_size: 50 });
const page = reactive({
  total: 0,
  period_value: null as string | null,
  calc_version: 0,
});
const summary = ref<ProductLineStats>({});

const detailVisible = ref(false);
const statsVisible = ref(false);
const rowVisible = ref(false);
const currentRowLabel = ref("");
const rowDetail = ref<ProductLineRow>({} as ProductLineRow);

/** 平台选项：从当前页数据里出现的取值去重（多值拼接串按 `/` 拆） */
const platformOptions = computed(() => {
  const set = new Set<string>();
  rows.value.forEach((row) => {
    String(row["PRD-20"] ?? "")
      .split("/")
      .filter(Boolean)
      .forEach((item) => set.add(item.trim()));
  });
  return [...set].sort();
});

/** 按注册表顺序过滤出可见列，保证新加字段不改变既有列序 */
const displayColumns = computed<ProductLineFieldItem[]>(() =>
  columns.value.filter((col) => visibleFields.value.includes(col.field_code)),
);

const columnGroups = computed(() => {
  const groups: { name: string; items: ProductLineFieldItem[] }[] = [];
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

function columnWidth(col: ProductLineFieldItem) {
  if (col.field_code === "PRD-01") return 150;
  if (col.field_code === "PRD-02") return 150;
  if (col.field_code === "PRD-21") return 240;
  if (col.field_code === "PRD-18") return 200;
  return 130;
}

function formatNumber(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCell(value: unknown, col: ProductLineFieldItem) {
  if (value === undefined || value === null || value === "") return "-";
  if (col.data_type === "number") return formatNumber(value);
  return String(value);
}

function statusTagType(status?: string) {
  if (status === "ready") return "success";
  if (status === "pending_field" || status === "source_found") return "warning";
  if (status === "missing") return "danger";
  return "info";
}

function rowClassName({ row }: { row: ProductLineRow }) {
  if (Number(row.is_aggregate) === 2) return "row-total";
  if (Number(row.is_aggregate) === 1) return "row-subtotal";
  return "";
}

function percentOfTop(value: number) {
  const max = Math.max(...(summary.value.top_lines || []).map((item) => Number(item.net_shipment) || 0), 0);
  if (!max) return 0;
  return Math.max(1, Math.round((Number(value) / max) * 100));
}

/** 默认展示「现用可出」的字段（PRD 口径里本期真能出数的那些） */
function applyDefaultFields() {
  const ready = columns.value.filter((col) => col.status === "ready").map((col) => col.field_code);
  visibleFields.value = ready.length ? ready : columns.value.map((col) => col.field_code);
  if (!visibleFields.value.length) visibleFields.value = [...FALLBACK_FIELDS];
}

function resetFields() {
  applyDefaultFields();
}

function selectReadyFields() {
  applyDefaultFields();
  ElMessage.success("已切换为「现用可出」字段");
}

async function loadMeta() {
  const [fieldRes, periodRes] = await Promise.all([ProductLineAPI.fields(), ProductLineAPI.periods()]);
  columns.value = fieldRes.data?.data ?? [];
  periodOptions.value = periodRes.data?.data ?? [];
  if (!visibleFields.value.length) {
    applyDefaultFields();
  }
  if (!periodValue.value && periodOptions.value.length) {
    periodValue.value = periodOptions.value[0];
  }
}

async function loadProductLines() {
  try {
    const res = await ProductLineAPI.productLines(periodValue.value);
    productLineOptions.value = res.data?.data ?? [];
  } catch {
    productLineOptions.value = [];
  }
}

async function loadData() {
  loading.value = true;
  try {
    const res = await ProductLineAPI.page({
      period_value: periodValue.value,
      product_line: productLine.value,
      keyword: keyword.value || undefined,
      order_type: orderType.value,
      platform: platform.value,
      aggregate_level: aggregateLevel.value,
      page_no: query.page_no,
      page_size: query.page_size,
    });
    const data = res.data?.data as ProductLinePageResult | undefined;
    rows.value = data?.items ?? [];
    page.total = data?.total ?? 0;
    page.period_value = data?.period_value ?? null;
    page.calc_version = data?.calc_version ?? 0;
    summary.value = data?.summary ?? {};
  } catch (error) {
    // loadData 会被模板事件直接调用，抛出会成为「组件事件处理器未处理错误」
    rows.value = [];
    ElMessage.error("查询产品线分析失败");
    console.error(error);
  } finally {
    loading.value = false;
  }
}

function handleQuery() {
  query.page_no = 1;
  loadData();
}

async function handleRebuild() {
  try {
    await ElMessageBox.confirm(
      `将按期间 ${periodValue.value || "最新期间"} 重新构建产品线分析（生成新版本，不覆盖历史）`,
      "确认构建",
      { type: "warning" },
    );
  } catch {
    // 用户取消：Element Plus 的 confirm 以 'cancel' reject，这里吞掉
    return;
  }
  running.value = true;
  try {
    const res = await ProductLineAPI.rebuild(periodValue.value);
    const data = res.data?.data as Record<string, number> | undefined;
    ElMessage.success(
      `构建完成：产品线 ${data?.line_count ?? 0} 个、SKU ${data?.sku_count ?? 0} 个，版本 v${data?.calc_version ?? "-"}`,
    );
    await loadMeta();
    await loadProductLines();
    await loadData();
  } catch (error) {
    ElMessage.error("构建失败，请查看后端日志");
    console.error(error);
  } finally {
    running.value = false;
  }
}

function handleRowClick(row: ProductLineRow) {
  const level = Number(row.is_aggregate);
  const suffix = level === 2 ? "（全表合计）" : level === 1 ? "（产品线小计）" : "";
  currentRowLabel.value = `${row.product_line_code || "-"} / ${row.sku || "全部 SKU"}${suffix}`;
  rowDetail.value = row;
  rowVisible.value = true;
}

onMounted(async () => {
  try {
    await loadMeta();
    await loadProductLines();
    await loadData();
  } catch (error) {
    ElMessage.error("加载产品线分析数据失败");
    console.error(error);
  }
});
</script>

<style lang="scss" scoped>
.product-line-analysis-page {
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

  .summary-extra {
    color: var(--el-text-color-secondary);
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
