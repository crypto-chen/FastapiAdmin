<template>
  <div class="customer-analysis-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElSelect v-model="periodValue" placeholder="期间" clearable style="width: 130px" @change="handleQuery">
          <ElOption v-for="item in periodOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

        <ElInput
          v-model="keyword"
          placeholder="客户编码/名称（模糊）"
          clearable
          style="width: 200px"
          @keyup.enter="handleQuery"
        />

        <ElInput
          v-model="salesmanCode"
          placeholder="业务员编码"
          clearable
          style="width: 150px"
          @keyup.enter="handleQuery"
        />

        <ElSelect v-model="orderType" placeholder="订单类型" clearable style="width: 130px" @change="handleQuery">
          <ElOption label="批量" value="批量" />
          <ElOption label="打样" value="打样" />
          <ElOption label="零售" value="零售" />
        </ElSelect>

        <ElSelect v-model="productLine" placeholder="产品线大类" clearable style="width: 140px" @change="handleQuery">
          <ElOption v-for="item in productLineOptions" :key="item" :label="item" :value="item" />
        </ElSelect>

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
          style="width: 560px"
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
        <span>期间 {{ page.period_value || "-" }} · 版本 v{{ page.calc_version || "-" }}</span>
        <span>客户数（主档时点）{{ page.summary.customer_count ?? "-" }}</span>
        <span>订单 {{ page.summary.order_count ?? 0 }} 单</span>
        <span>接单未税合计 {{ formatNumber(page.summary.intake_untaxed_sum) }}</span>
        <span>对外出货净额 {{ formatNumber(page.summary.net_shipment_sum) }}</span>
        <span class="summary-extra">点行可看该客户的全部字段</span>
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
          :fixed="col.field_code === 'CUS-01'"
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
    <ElDrawer v-model="detailVisible" title="客户分析字段说明（CUS-xx）" size="680px">
      <ElTable :data="columns" border stripe max-height="calc(100vh - 160px)">
        <ElTableColumn prop="field_code" label="编码" width="100" />
        <ElTableColumn prop="field_name" label="名称" min-width="130" />
        <ElTableColumn prop="group" label="分组" width="80" />
        <ElTableColumn prop="source" label="底稿来源" width="110" />
        <ElTableColumn prop="data_type" label="类型" width="80" />
        <ElTableColumn label="敏感" width="70">
          <template #default="{ row }">{{ row.sensitive ? "是" : "-" }}</template>
        </ElTableColumn>
        <ElTableColumn prop="note" label="口径/说明" min-width="200" show-overflow-tooltip />
      </ElTable>
    </ElDrawer>

    <!-- 单客户全部字段 -->
    <ElDrawer v-model="rowVisible" :title="`客户 ${currentCustomer} 全部字段`" size="620px">
      <ElDescriptions :column="1" border>
        <ElDescriptionsItem v-for="col in columns" :key="col.field_code" :label="`${col.field_name}（${col.field_code}）`">
          {{ formatCell(rowDetail[col.field_code], col) }}
        </ElDescriptionsItem>
      </ElDescriptions>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { CustomerAPI, type CustomerFieldItem, type CustomerPageResult, type CustomerRow } from "@/api/module_customer";
import { ElMessage, ElMessageBox } from "element-plus";

defineOptions({ name: "CustomerAnalysis" });

/** 目录拉不到时兜底 */
const FALLBACK_FIELDS = ["CUS-01", "CUS-02", "CUS-08", "CUS-12", "CUS-16", "CUS-28"];

const loading = ref(false);
const running = ref(false);
const periodOptions = ref<string[]>([]);
const periodValue = ref<string | undefined>(undefined);
const keyword = ref("");
const salesmanCode = ref("");
const orderType = ref<string | undefined>(undefined);
const productLine = ref<string | undefined>(undefined);

const columns = ref<CustomerFieldItem[]>([]);
const visibleFields = ref<string[]>([]);
const rows = ref<CustomerRow[]>([]);
const query = reactive({ page_no: 1, page_size: 50 });
const page = reactive({
  total: 0,
  period_value: null as string | null,
  calc_version: 0,
  summary: {
    customer_count: undefined,
    order_count: 0,
    intake_untaxed_sum: 0,
    net_shipment_sum: 0,
  } as NonNullable<CustomerPageResult["summary"]>,
});

const detailVisible = ref(false);
const rowVisible = ref(false);
const currentCustomer = ref("");
const rowDetail = ref<CustomerRow>({} as CustomerRow);

/** 产品线大类取选项：从当前页数据里出现的取值去重（口径落地前先用动态值） */
const productLineOptions = computed(() => {
  const set = new Set<string>();
  rows.value.forEach((row) => {
    String(row["CUS-09"] ?? "")
      .split("/")
      .filter(Boolean)
      .forEach((item) => set.add(item.trim()));
  });
  return [...set].sort();
});

/** 按注册表顺序过滤出可见列，保证新加字段不改变既有列序。 */
const displayColumns = computed<CustomerFieldItem[]>(() =>
  columns.value.filter((col) => visibleFields.value.includes(col.field_code)),
);

const columnGroups = computed(() => {
  const groups: { name: string; items: CustomerFieldItem[] }[] = [];
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

function columnWidth(col: CustomerFieldItem) {
  if (col.field_code === "CUS-01") return 150;
  if (col.field_code === "CUS-02") return 200;
  if (col.field_code === "CUS-09" || col.field_code === "CUS-10" || col.field_code === "CUS-11") return 160;
  if (col.data_type === "number") return 130;
  return 130;
}

function formatNumber(value: unknown) {
  if (value === undefined || value === null || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return "-";
  return num.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatCell(value: unknown, col: CustomerFieldItem) {
  if (value === undefined || value === null || value === "") return "-";
  if (col.data_type === "number") return formatNumber(value);
  return String(value);
}

/** 默认展示全部 CUS 编码字段（与财务底稿口径一致） */
function applyDefaultFields() {
  const codes = columns.value.map((col) => col.field_code);
  visibleFields.value = codes.length ? codes : [...FALLBACK_FIELDS];
}

function resetFields() {
  applyDefaultFields();
}

async function loadMeta() {
  const [fieldRes, periodRes] = await Promise.all([CustomerAPI.fields(), CustomerAPI.periods()]);
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
    const res = await CustomerAPI.page({
      period_value: periodValue.value,
      keyword: keyword.value || undefined,
      salesman_code: salesmanCode.value || undefined,
      order_type: orderType.value,
      product_line: productLine.value,
      page_no: query.page_no,
      page_size: query.page_size,
    });
    const data = res.data?.data;
    rows.value = data?.items ?? [];
    page.total = data?.total ?? 0;
    page.period_value = data?.period_value ?? null;
    page.calc_version = data?.calc_version ?? 0;
    page.summary = data?.summary ?? {
      customer_count: undefined,
      order_count: 0,
      intake_untaxed_sum: 0,
      net_shipment_sum: 0,
    };
  } catch (error) {
    // loadData 会被模板事件直接调用，抛出会成为「组件事件处理器未处理错误」
    rows.value = [];
    ElMessage.error("查询客户分析失败");
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
      `将按期间 ${periodValue.value || "最新期间"} 重新构建客户分析（生成新版本，不覆盖历史）`,
      "确认构建",
      { type: "warning" },
    );
  } catch {
    // 用户取消：Element Plus 的 confirm 以 'cancel' reject，这里吞掉
    return;
  }
  running.value = true;
  try {
    const res = await CustomerAPI.rebuild(periodValue.value);
    const data = res.data?.data as Record<string, number> | undefined;
    ElMessage.success(
      `构建完成：客户 ${data?.customer_count ?? 0} 个，版本 v${data?.calc_version ?? "-"}`,
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

function handleRowClick(row: CustomerRow) {
  currentCustomer.value = String(row.customer_name ?? row.customer_code ?? "");
  rowDetail.value = row;
  rowVisible.value = true;
}

onMounted(async () => {
  try {
    await loadMeta();
    await loadData();
  } catch (error) {
    ElMessage.error("加载客户分析数据失败");
    console.error(error);
  }
});
</script>

<style lang="scss" scoped>
.customer-analysis-page {
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
