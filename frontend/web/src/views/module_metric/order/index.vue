<template>
  <div class="order-full-chain-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElSelect v-model="periodValue" placeholder="期间" clearable style="width: 130px" @change="handleQuery">
          <ElOption v-for="item in periodOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

        <ElInput
          v-model="orderNumber"
          placeholder="订单号（模糊）"
          clearable
          style="width: 190px"
          @keyup.enter="handleQuery"
        />

        <ElSelect v-model="tradeType" placeholder="贸易类型" clearable style="width: 130px" @change="handleQuery">
          <ElOption label="内贸" value="domestic" />
          <ElOption label="外贸" value="export" />
        </ElSelect>

        <ElSelect v-model="qualityFlag" placeholder="数据质量" clearable style="width: 150px" @change="handleQuery">
          <ElOption label="全部正常" value="ok" />
          <ElOption label="成本缺失" value="cost_missing" />
          <ElOption label="未关联生产订单" value="mo_unlinked" />
        </ElSelect>

        <ElInput v-model="customerName" placeholder="客户（模糊）" clearable style="width: 170px" @keyup.enter="handleQuery" />

        <ElButton type="primary" :loading="loading" @click="handleQuery">查询</ElButton>
        <ElButton :loading="running" @click="handleRebuild">按期间构建</ElButton>
        <ElButton @click="detailVisible = true">字段说明</ElButton>
      </div>

      <div class="toolbar toolbar-second">
        <span class="picker-label">显示字段</span>
        <ElSelect
          v-model="visibleFields"
          multiple
          collapse-tags
          collapse-tags-tooltip
          :max-collapse-tags="6"
          filterable
          clearable
          placeholder="选择要显示的字段"
          style="width: 520px"
        >
          <ElOptionGroup v-for="group in columnGroups" :key="group.name" :label="group.name">
            <ElOption
              v-for="col in group.items"
              :key="col.field_code"
            :label="col.excel_code ? `${col.field_name}（${col.excel_code}）` : `${col.field_name}（${col.field_code}）`"
              :value="col.field_code"
            />
          </ElOptionGroup>
        </ElSelect>
        <ElButton link type="primary" @click="resetFields">恢复默认</ElButton>
      </div>

      <div class="summary">
        <span>期间 {{ page.period_value || "-" }} · 版本 v{{ page.calc_version || "-" }}</span>
        <span>订单 {{ page.summary.order_count ?? 0 }} 张</span>
        <span>成本缺失 {{ page.summary.cost_missing_count ?? 0 }}</span>
        <span>未关联生产订单 {{ page.summary.mo_unlinked_count ?? 0 }}</span>
        <span>接单未税合计 {{ formatNumber(page.summary.intake_untaxed_sum) }}</span>
        <span class="summary-extra">点行可看该订单的全部字段</span>
      </div>

      <ElTable
        v-loading="loading"
        :data="rows"
        border
        stripe
        height="calc(100vh - 380px)"
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
          :fixed="col.field_code === 'order_number'"
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
    <ElDrawer v-model="detailVisible" title="订单全链路字段说明" size="620px">
      <ElTable :data="columns" border stripe max-height="calc(100vh - 160px)">
        <ElTableColumn prop="excel_code" label="指标编码" width="100" />
        <ElTableColumn prop="field_code" label="字段编码" min-width="170" />
        <ElTableColumn prop="field_name" label="名称" min-width="130" />
        <ElTableColumn prop="group" label="分组" width="90" />
        <ElTableColumn prop="data_type" label="类型" width="90" />
        <ElTableColumn label="落库" width="90">
          <template #default="{ row }">{{ row.stored_in === "core" ? "物理列" : "extra" }}</template>
        </ElTableColumn>
        <ElTableColumn label="敏感" width="80">
          <template #default="{ row }">{{ row.sensitive ? "是" : "-" }}</template>
        </ElTableColumn>
      </ElTable>
    </ElDrawer>

    <!-- 单订单全部字段 -->
    <ElDrawer v-model="rowVisible" :title="`订单 ${currentOrder} 全部字段`" size="560px">
      <ElDescriptions :column="1" border>
        <ElDescriptionsItem v-for="col in displayColumns" :key="col.field_code" :label="col.field_name">
          {{ formatCell(rowDetail[col.field_code], col) }}
        </ElDescriptionsItem>
      </ElDescriptions>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { OrderAPI, type OrderFieldItem, type OrderPageResult, type OrderRow } from "@/api/module_order";
import { ElMessage, ElMessageBox } from "element-plus";

defineOptions({ name: "OrderFullChain" });

/** 目录拉不到时兜底（正常情况下按 ORD 编码动态取） */
const FALLBACK_FIELDS = ["order_number", "customer_name", "salesman_name", "intake_untaxed"];

const loading = ref(false);
const running = ref(false);
const periodOptions = ref<string[]>([]);
const periodValue = ref<string | undefined>(undefined);
const orderNumber = ref("");
const tradeType = ref<string | undefined>(undefined);
const qualityFlag = ref<string | undefined>(undefined);
const customerName = ref("");

const columns = ref<OrderFieldItem[]>([]);
const visibleFields = ref<string[]>([]);
const rows = ref<OrderRow[]>([]);
const query = reactive({ page_no: 1, page_size: 50 });
const page = reactive({
  total: 0,
  period_value: null as string | null,
  calc_version: 0,
  summary: {
    order_count: 0,
    cost_missing_count: 0,
    mo_unlinked_count: 0,
    intake_untaxed_sum: 0,
  } as NonNullable<OrderPageResult["summary"]>,
});

const detailVisible = ref(false);
const rowVisible = ref(false);
const currentOrder = ref("");
const rowDetail = ref<OrderRow>({} as OrderRow);

const columnMap = computed(() => {
  const map: Record<string, OrderFieldItem> = {};
  columns.value.forEach((item) => (map[item.field_code] = item));
  return map;
});

/** 按注册表顺序过滤出可见列，保证新加字段不改变既有列序。 */
const displayColumns = computed<OrderFieldItem[]>(() =>
  columns.value.filter((col) => visibleFields.value.includes(col.field_code)),
);

const columnGroups = computed(() => {
  const groups: { name: string; items: OrderFieldItem[] }[] = [];
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

function columnWidth(col: OrderFieldItem) {
  if (col.field_code === "order_number") return 160;
  if (col.data_type === "string" && (col.group === "基础" || col.group === "质量")) return 150;
  if (col.data_type === "number") return 130;
  return 130;
}

function formatNumber(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCell(value: unknown, col: OrderFieldItem) {
  if (value === undefined || value === null || value === "") return "-";
  if (col.data_type === "number") return formatNumber(value);
  if (col.field_code === "trade_type") return value === "domestic" ? "内贸" : value === "export" ? "外贸" : String(value);
  return String(value).replace("T", " ").slice(0, 19);
}

/** 默认展示全部带 ORD 编码的字段（与财务底稿口径一致）；档案里没有编码的辅助字段不默认展示。 */
function applyDefaultFields() {
  const codes = columns.value.filter((col) => col.excel_code).map((col) => col.field_code);
  visibleFields.value = codes.length ? codes : [...FALLBACK_FIELDS];
}

function resetFields() {
  applyDefaultFields();
}

async function loadMeta() {
  const [fieldRes, periodRes] = await Promise.all([OrderAPI.fields(), OrderAPI.periods()]);
  columns.value = fieldRes.data?.data ?? [];
  periodOptions.value = periodRes.data?.data ?? [];
  if (!visibleFields.value.length) {
    applyDefaultFields();
  }
  if (!periodValue.value && periodOptions.value.length) {
    periodValue.value = periodOptions.value[0];
  }
}

async function loadData() {
  loading.value = true;
  try {
    const res = await OrderAPI.page({
      period_value: periodValue.value,
      order_number: orderNumber.value || undefined,
      trade_type: tradeType.value,
      data_quality_flag: qualityFlag.value,
      customer_name: customerName.value || undefined,
      page_no: query.page_no,
      page_size: query.page_size,
    });
    const data = res.data?.data;
    rows.value = data?.items ?? [];
    page.total = data?.total ?? 0;
    page.period_value = data?.period_value ?? null;
    page.calc_version = data?.calc_version ?? 0;
    page.summary = data?.summary ?? {
      order_count: 0,
      cost_missing_count: 0,
      mo_unlinked_count: 0,
      intake_untaxed_sum: 0,
    };
  } catch (error) {
    // 这里吞掉异常：loadData 会被模板事件直接调用，抛出会成为「组件事件处理器未处理错误」
    rows.value = [];
    ElMessage.error("查询订单全链路失败");
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
      `将按期间 ${periodValue.value || "最新期间"} 重新构建订单全链路（生成新版本，不覆盖历史）`,
      "确认构建",
      { type: "warning" },
    );
  } catch {
    // 用户取消：Element Plus 的 confirm 以 'cancel' reject，这里吞掉，避免抛到组件事件处理器上
    return;
  }
  running.value = true;
  try {
    const res = await OrderAPI.rebuild(periodValue.value);
    const data = res.data?.data as Record<string, number> | undefined;
    ElMessage.success(
      `构建完成：订单 ${data?.order_count ?? 0} 张，版本 v${data?.calc_version ?? "-"}`,
    );
    await loadMeta();
    await loadData();
  } catch (error) {
    ElMessage.error("构建失败，请查看后端日志");
    console.error(error);
  } finally {
    running.value = false;
  }
}

function handleRowClick(row: OrderRow) {
  currentOrder.value = String(row.order_number);
  rowDetail.value = row;
  rowVisible.value = true;
}

onMounted(async () => {
  try {
    await loadMeta();
    await loadData();
  } catch (error) {
    ElMessage.error("加载订单全链路数据失败");
    console.error(error);
  }
});
</script>

<style lang="scss" scoped>
.order-full-chain-page {
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
}
</style>
