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
        <ElButton type="warning" plain @click="openConfig">指标配置</ElButton>
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
        <ElButton link type="primary" @click="selectReadyFields">只看现用可出</ElButton>
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
        <span>客单价 {{ formatNumber(summary.avg_order_value) }}</span>
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

    <!-- 指标配置：新增指标不用改代码 -->
    <ElDrawer v-model="configVisible" title="平台指标配置" size="960px">
      <div class="config-toolbar">
        <ElButton type="primary" @click="openMetricForm()">新增指标</ElButton>
        <ElButton @click="handleResetMetrics">恢复默认指标</ElButton>
        <span class="picker-label">新增/修改后刷新列表即可看到新列，无需发版</span>
      </div>

      <ElTable v-loading="configLoading" :data="configs" border stripe max-height="calc(100vh - 320px)">
        <ElTableColumn prop="field_code" label="编码" width="100" />
        <ElTableColumn prop="field_name" label="名称" min-width="140" />
        <ElTableColumn prop="group" label="分组" width="80" />
        <ElTableColumn prop="data_type" label="类型" width="90" />
        <ElTableColumn prop="expression" label="表达式" min-width="240" show-overflow-tooltip />
        <ElTableColumn prop="sort" label="排序" width="80" align="center" />
        <ElTableColumn label="可出性" width="100" align="center">
          <template #default="{ row }">
            <ElTag :type="statusTagType(row.status)" size="small">{{ row.status_label }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="90" align="center">
          <template #default="{ row }">
            <ElTag :type="row.status_num === 0 ? 'success' : 'info'" size="small">
              {{ row.status_num === 0 ? "启用" : "停用" }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openMetricForm(row as PlatformMetricConfig)">编辑</ElButton>
            <ElButton link type="danger" @click="handleDeleteMetric(row as PlatformMetricConfig)">删除</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <div class="config-tip">
        <div><b>可用基础变量：</b>{{ baseVariableText }}</div>
        <div><b>可用函数：</b>{{ functionText }}</div>
        <div>表达式示例：<code>PLT-12 * settlement_rate</code>、<code>abs(PLT-11) / choose(PLT-12 &gt; 0, PLT-12, PLT-09)</code></div>
      </div>
    </ElDrawer>

    <ElDialog v-model="metricFormVisible" :title="metricForm.id ? '编辑指标' : '新增指标'" width="620px">
      <ElForm :model="metricForm" label-width="90px">
        <ElFormItem label="编码" required>
          <ElInput v-model="metricForm.code" :disabled="!!metricForm.id" placeholder="PLT-39" />
        </ElFormItem>
        <ElFormItem label="名称" required>
          <ElInput v-model="metricForm.name" placeholder="如：取消率" />
        </ElFormItem>
        <ElFormItem label="分组">
          <ElSelect v-model="metricForm.group" style="width: 100%">
            <ElOption label="维度" value="维度" />
            <ElOption label="数量" value="数量" />
            <ElOption label="金额" value="金额" />
            <ElOption label="比率" value="比率" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="数据类型">
          <ElSelect v-model="metricForm.data_type" style="width: 100%">
            <ElOption label="数值 number" value="number" />
            <ElOption label="百分比 percent" value="percent" />
            <ElOption label="文本 string" value="string" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="可出性">
          <ElSelect v-model="metricForm.readiness" style="width: 100%">
            <ElOption label="现用可出（表达式必填）" value="ready" />
            <ElOption label="待确认（口径未定）" value="pending" />
            <ElOption label="待做（缺录入/接口）" value="todo" />
            <ElOption label="缺数据源" value="missing" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="表达式" required>
          <ElInput
            v-model="metricForm.expression"
            type="textarea"
            :rows="3"
            placeholder="PLT-08 / max(PLT-04 - PLT-06, 1)"
          />
        </ElFormItem>
        <ElFormItem label="单位">
          <ElInput v-model="metricForm.unit" placeholder="元 / 单 / 元/单" />
        </ElFormItem>
        <ElFormItem label="口径说明">
          <ElInput v-model="metricForm.note" type="textarea" :rows="2" />
        </ElFormItem>
        <ElFormItem label="排序">
          <ElInputNumber v-model="metricForm.sort" :min="0" :max="9999" />
        </ElFormItem>
        <ElFormItem label="状态">
          <ElSwitch v-model="metricForm.enabled" active-text="启用" inactive-text="停用" />
        </ElFormItem>
        <ElFormItem label="敏感字段">
          <ElSwitch v-model="metricForm.sensitive" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="metricFormVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="metricSaving" @click="submitMetric">保存</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { ElMessage, ElMessageBox } from "element-plus";
import {
  PlatformAnalysisAPI,
  type PlatformFieldItem,
  type PlatformMetricConfig,
  type PlatformMetricPayload,
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

const configVisible = ref(false);
const configLoading = ref(false);
const configs = ref<PlatformMetricConfig[]>([]);
const baseVariables = ref<Record<string, string>>({});
const functions = ref<string[]>([]);
const metricFormVisible = ref(false);
const metricSaving = ref(false);
const metricForm = reactive<{
  id?: number;
  code: string;
  name: string;
  group: string;
  data_type: string;
  unit?: string;
  expression: string;
  note?: string;
  sort: number;
  enabled: boolean;
  sensitive: boolean;
  readiness: string;
}>({
  code: "",
  name: "",
  group: "金额",
  data_type: "number",
  unit: "",
  expression: "",
  note: "",
  sort: 200,
  enabled: true,
  sensitive: false,
  readiness: "ready",
});

const baseVariableText = computed(() =>
  Object.entries(baseVariables.value)
    .map(([key, desc]) => `${key}（${desc}）`)
    .join("；"),
);
const functionText = computed(() => functions.value.join("、"));

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

function selectReadyFields() {
  applyDefaultFields();
  ElMessage.success("已切换为「现用可出」字段");
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

async function loadConfigs() {
  configLoading.value = true;
  try {
    const res = await PlatformAnalysisAPI.metricConfigs();
    const data = res.data?.data;
    configs.value = data?.items ?? [];
    baseVariables.value = data?.base_variables ?? {};
    functions.value = data?.functions ?? [];
  } catch (error) {
    configs.value = [];
    ElMessage.error("加载平台指标配置失败");
    console.error(error);
  } finally {
    configLoading.value = false;
  }
}

function openConfig() {
  configVisible.value = true;
  loadConfigs();
}

function openMetricForm(row?: PlatformMetricConfig) {
  Object.assign(metricForm, {
    id: row?.id,
    code: row?.field_code ?? "",
    name: row?.field_name ?? "",
    group: row?.group ?? "金额",
    data_type: row?.data_type ?? "number",
    unit: row?.unit ?? "",
    expression: row?.expression ?? "",
    note: row?.note ?? "",
    sort: row?.sort ?? 200,
    enabled: (row?.status_num ?? 0) === 0,
    sensitive: row?.sensitive ?? false,
    readiness: (row?.status as string) || "ready",
  });
  metricFormVisible.value = true;
}

function buildMetricPayload(): PlatformMetricPayload {
  return {
    code: metricForm.code.trim().toUpperCase(),
    name: metricForm.name.trim(),
    group: metricForm.group,
    data_type: metricForm.data_type,
    unit: metricForm.unit || null,
    sensitive: metricForm.sensitive,
    expression: metricForm.expression.trim(),
    readiness: metricForm.readiness,
    note: metricForm.note || null,
    sort: metricForm.sort,
    status: metricForm.enabled ? 0 : 1,
  };
}

async function submitMetric() {
  if (!metricForm.code.trim() || !metricForm.name.trim() || !metricForm.expression.trim()) {
    ElMessage.warning("编码、名称、表达式必填");
    return;
  }
  metricSaving.value = true;
  try {
    const payload = buildMetricPayload();
    if (metricForm.id) {
      await PlatformAnalysisAPI.updateMetric(metricForm.id, payload);
    } else {
      await PlatformAnalysisAPI.createMetric(payload);
    }
    ElMessage.success("保存成功，刷新列表即可看到新列");
    metricFormVisible.value = false;
    await loadConfigs();
    await loadMeta();
    await loadData();
  } catch (error) {
    ElMessage.error("保存失败，请检查表达式与编码是否重复");
    console.error(error);
  } finally {
    metricSaving.value = false;
  }
}

async function handleDeleteMetric(row: PlatformMetricConfig) {
  try {
    await ElMessageBox.confirm(`删除指标 ${row.field_code} ${row.field_name}？`, "确认删除", {
      type: "warning",
    });
  } catch {
    return;
  }
  try {
    await PlatformAnalysisAPI.deleteMetric(row.id);
    ElMessage.success("已删除");
    await loadConfigs();
    await loadMeta();
    await loadData();
  } catch (error) {
    ElMessage.error("删除失败");
    console.error(error);
  }
}

async function handleResetMetrics() {
  try {
    await ElMessageBox.confirm("恢复默认平台指标（只补齐/更新默认项，不删除自定义指标）？", "确认", {
      type: "warning",
    });
  } catch {
    return;
  }
  try {
    const res = await PlatformAnalysisAPI.resetMetrics();
    const data = res.data?.data ?? {};
    ElMessage.success(`已恢复：新增 ${data.created ?? 0}，更新 ${data.updated ?? 0}`);
    await loadConfigs();
    await loadMeta();
    await loadData();
  } catch (error) {
    ElMessage.error("恢复失败");
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

  .config-toolbar {
    display: flex;
    gap: 10px;
    align-items: center;
    margin-bottom: 10px;
  }

  .config-tip {
    margin-top: 12px;
    font-size: 12px;
    line-height: 1.8;
    color: var(--el-text-color-secondary);

    code {
      padding: 0 4px;
      background: var(--el-fill-color-light);
      border-radius: 3px;
    }
  }
}
</style>
