<template>
  <div class="retail-sync-page">
    <ElCard shadow="never">
      <ElTabs v-model="activeTab" @tab-change="handleTabChange">
        <ElTabPane label="零售订单" name="orders">
          <div class="toolbar">
            <ElSelect v-model="orderSearch.period_value" placeholder="期间" clearable style="width: 120px">
              <ElOption v-for="item in periods" :key="item" :label="item" :value="item" />
            </ElSelect>
            <ElInputNumber
              v-model="orderSearch.shop_id"
              :min="0"
              :controls="false"
              placeholder="店铺ID"
              style="width: 120px"
            />
            <ElInput
              v-model="orderSearch.shop_name"
              placeholder="店铺名称"
              clearable
              style="width: 150px"
              @keyup.enter="queryOrders"
            />
            <ElInput
              v-model="orderSearch.so_id"
              placeholder="线上/内部单号"
              clearable
              style="width: 170px"
              @keyup.enter="queryOrders"
            />
            <ElInput
              v-model="orderSearch.status"
              placeholder="订单状态"
              clearable
              style="width: 130px"
              @keyup.enter="queryOrders"
            />
            <ElInput
              v-model="orderSearch.keyword"
              placeholder="单号/买家/备注"
              clearable
              style="width: 170px"
              @keyup.enter="queryOrders"
            />
            <ElButton type="primary" :loading="orderLoading" @click="queryOrders">查询</ElButton>
            <ElButton @click="resetOrderSearch">重置</ElButton>
          </div>

          <div class="summary">
            <span>订单 {{ orderPage.summary.order_count }} 张</span>
            <span>买家实付合计 {{ formatMoney(orderPage.summary.buyer_paid_amount_sum) }}</span>
            <span>明细行合计 {{ orderPage.summary.item_count_sum }}</span>
            <span class="summary-extra">点「明细」查看 SKU 与金额</span>
          </div>

          <ElTable v-loading="orderLoading" :data="orders" border stripe height="calc(100vh - 360px)">
            <ElTableColumn prop="period_value" label="期间" width="90" fixed />
            <ElTableColumn label="店铺" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.shop_name || "-" }}<span class="muted"> / {{ row.shop_id }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="so_id" label="线上单号" min-width="180" show-overflow-tooltip />
            <ElTableColumn prop="o_id" label="内部单号" width="110" show-overflow-tooltip />
            <ElTableColumn label="状态" width="110" align="center">
              <template #default="{ row }">
                <ElTag :type="orderStatusType(row.status)" size="small">{{ row.status || "-" }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="buyer_nick" label="买家" width="110" show-overflow-tooltip>
              <template #default="{ row }">{{ row.buyer_nick || "-" }}</template>
            </ElTableColumn>
            <ElTableColumn label="买家实付" width="110" align="right">
              <template #default="{ row }">{{ formatMoney(row.buyer_paid_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="item_count" label="明细" width="70" align="center" />
            <ElTableColumn label="上游修改" width="165">
              <template #default="{ row }">{{ formatTime(row.modified_time) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="last_batch_id" label="最近批次" min-width="190" show-overflow-tooltip />
            <ElTableColumn label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <ElButton link type="primary" @click="openOrder(row as RetailOrderRow)">明细</ElButton>
              </template>
            </ElTableColumn>
          </ElTable>

          <div class="pager">
            <ElPagination
              v-model:current-page="orderPage.page_no"
              v-model:page-size="orderPage.page_size"
              :total="orderPage.total"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="loadOrders"
              @size-change="queryOrders"
            />
          </div>
        </ElTabPane>

        <ElTabPane label="推送批次" name="batches">
          <div class="toolbar">
            <ElInput
              v-model="batchSearch.request_id"
              placeholder="请求ID"
              clearable
              style="width: 200px"
              @keyup.enter="queryBatches"
            />
            <ElInput
              v-model="batchSearch.source"
              placeholder="来源"
              clearable
              style="width: 120px"
              @keyup.enter="queryBatches"
            />
            <ElSelect v-model="batchSearch.status" placeholder="状态" clearable style="width: 130px">
              <ElOption label="成功" value="success" />
              <ElOption label="部分成功" value="partial" />
              <ElOption label="失败" value="failed" />
              <ElOption label="处理中" value="running" />
            </ElSelect>
            <ElButton type="primary" :loading="batchLoading" @click="queryBatches">查询</ElButton>
            <ElButton @click="resetBatchSearch">重置</ElButton>
          </div>

          <ElTable v-loading="batchLoading" :data="batches" border stripe height="calc(100vh - 300px)">
            <ElTableColumn label="推送时间" width="165">
              <template #default="{ row }">{{ formatTime(row.created_time) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="request_id" label="请求ID" min-width="190" show-overflow-tooltip />
            <ElTableColumn prop="source" label="来源" width="90" />
            <ElTableColumn label="状态" width="100" align="center">
              <template #default="{ row }">
                <ElTag :type="batchStatusType(row.status)" size="small">{{ batchStatusText(row.status) }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="received_count" label="收到" width="70" align="center" />
            <ElTableColumn prop="created_count" label="新增" width="70" align="center" />
            <ElTableColumn prop="updated_count" label="更新" width="70" align="center" />
            <ElTableColumn prop="stale_count" label="跳过" width="70" align="center" />
            <ElTableColumn prop="failed_count" label="失败" width="70" align="center" />
            <ElTableColumn prop="item_count" label="明细" width="70" align="center" />
            <ElTableColumn label="期间" width="110">
              <template #default="{ row }">{{ row.periods?.join("、") || "-" }}</template>
            </ElTableColumn>
            <ElTableColumn label="下一页" width="80" align="center">
              <template #default="{ row }">{{ row.has_next ? "是" : "否" }}</template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <ElButton link type="primary" @click="openBatch(row as RetailBatchRow)">详情</ElButton>
              </template>
            </ElTableColumn>
          </ElTable>

          <div class="pager">
            <ElPagination
              v-model:current-page="batchPage.page_no"
              v-model:page-size="batchPage.page_size"
              :total="batchPage.total"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="loadBatches"
              @size-change="queryBatches"
            />
          </div>
        </ElTabPane>
      </ElTabs>
    </ElCard>

    <ElDrawer v-model="orderVisible" title="零售订单明细" size="760px">
      <template v-if="orderDetail">
        <ElDescriptions :column="2" border>
          <ElDescriptionsItem label="期间">{{ orderDetail.order.period_value }}</ElDescriptionsItem>
          <ElDescriptionsItem label="状态">{{ orderDetail.order.status || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="店铺">
            {{ orderDetail.order.shop_name || "-" }} / {{ orderDetail.order.shop_id }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="线上单号">{{ orderDetail.order.so_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="内部单号">{{ orderDetail.order.o_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="买家">{{ orderDetail.order.buyer_nick || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="买家实付">{{ formatMoney(orderDetail.order.buyer_paid_amount) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="应付金额">{{ formatMoney(orderDetail.order.pay_amount) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="支付时间">{{ formatTime(orderDetail.order.pay_date) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="上游修改">{{ formatTime(orderDetail.order.modified_time) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="收货地址" :span="2">
            {{ [orderDetail.order.receiver_state, orderDetail.order.receiver_city, orderDetail.order.receiver_district, orderDetail.order.receiver_town].filter(Boolean).join(" / ") || "-" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="备注" :span="2">{{ orderDetail.order.remark || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="最近批次" :span="2">{{ orderDetail.order.last_batch_id || "-" }}</ElDescriptionsItem>
        </ElDescriptions>

        <ElTable :data="orderDetail.items" border stripe class="detail-table">
          <ElTableColumn prop="sku_id" label="SKU" min-width="130" show-overflow-tooltip />
          <ElTableColumn prop="name" label="商品名称" min-width="220" show-overflow-tooltip />
          <ElTableColumn prop="properties_value" label="规格" min-width="150" show-overflow-tooltip />
          <ElTableColumn label="数量" width="75" align="right">
            <template #default="{ row }">{{ row.qty ?? "-" }}</template>
          </ElTableColumn>
          <ElTableColumn label="单价" width="90" align="right">
            <template #default="{ row }">{{ formatMoney(row.price) }}</template>
          </ElTableColumn>
          <ElTableColumn label="买家实付" width="100" align="right">
            <template #default="{ row }">{{ formatMoney(row.buyer_paid_amount) }}</template>
          </ElTableColumn>
          <ElTableColumn label="卖家实收" width="100" align="right">
            <template #default="{ row }">{{ formatMoney(row.seller_income_amount) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="item_status" label="明细状态" width="100">
            <template #default="{ row }">{{ row.item_status || "-" }}</template>
          </ElTableColumn>
        </ElTable>
      </template>
    </ElDrawer>

    <ElDrawer v-model="batchVisible" title="推送批次详情" size="680px">
      <template v-if="batchDetail">
        <ElDescriptions :column="2" border>
          <ElDescriptionsItem label="请求ID">{{ batchDetail.request_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="来源">{{ batchDetail.source }}</ElDescriptionsItem>
          <ElDescriptionsItem label="状态">{{ batchStatusText(batchDetail.status) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="期间">{{ batchDetail.periods?.join("、") || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="收到">{{ batchDetail.received_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="新增 / 更新">{{ batchDetail.created_count }} / {{ batchDetail.updated_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="跳过 / 失败">{{ batchDetail.stale_count }} / {{ batchDetail.failed_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="明细行">{{ batchDetail.item_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="推送时间" :span="2">{{ formatTime(batchDetail.created_time) }}</ElDescriptionsItem>
        </ElDescriptions>
        <div class="json-block">
          <div class="json-title">请求参数</div>
          <pre>{{ prettyJson(batchDetail.params) }}</pre>
        </div>
        <div v-if="batchDetail.errors?.length" class="json-block">
          <div class="json-title">错误</div>
          <pre>{{ prettyJson(batchDetail.errors) }}</pre>
        </div>
        <div class="json-block">
          <div class="json-title">处理结果</div>
          <pre>{{ prettyJson(batchDetail.result) }}</pre>
        </div>
      </template>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  RetailAPI,
  type RetailBatchDetail,
  type RetailBatchRow,
  type RetailOrderDetail,
  type RetailOrderRow,
} from "@/api/module_retail";

defineOptions({ name: "RetailOrderSync" });

const activeTab = ref("orders");
const periods = ref<string[]>([]);
const orderLoading = ref(false);
const batchLoading = ref(false);
const orders = ref<RetailOrderRow[]>([]);
const batches = ref<RetailBatchRow[]>([]);

const orderSearch = reactive<{
  period_value?: string;
  shop_id?: number;
  shop_name?: string;
  so_id?: string;
  status?: string;
  keyword?: string;
}>({});
const batchSearch = reactive<{ request_id?: string; source?: string; status?: string }>({});

const orderPage = reactive({
  page_no: 1,
  page_size: 20,
  total: 0,
  summary: { order_count: 0, buyer_paid_amount_sum: 0, item_count_sum: 0 },
});
const batchPage = reactive({ page_no: 1, page_size: 20, total: 0 });

const orderVisible = ref(false);
const orderDetail = ref<RetailOrderDetail | null>(null);
const batchVisible = ref(false);
const batchDetail = ref<RetailBatchDetail | null>(null);

function formatTime(value?: string | null) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

function formatMoney(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function orderStatusType(status?: string | null) {
  if (!status) return "info";
  if (["Cancelled", "Delete", "Refunded"].includes(status)) return "danger";
  if (["WaitConfirm", "WaitPay"].includes(status)) return "warning";
  return "success";
}

function batchStatusType(status: string) {
  if (status === "failed") return "danger";
  if (status === "partial" || status === "running") return "warning";
  return "success";
}

function batchStatusText(status: string) {
  const labels: Record<string, string> = {
    success: "成功",
    partial: "部分成功",
    failed: "失败",
    running: "处理中",
  };
  return labels[status] ?? status;
}

function prettyJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

async function loadPeriods() {
  try {
    const res = await RetailAPI.periods();
    periods.value = res.data?.data ?? [];
  } catch {
    periods.value = [];
  }
}

async function loadOrders() {
  orderLoading.value = true;
  try {
    const res = await RetailAPI.orders({
      period_value: orderSearch.period_value,
      shop_id: orderSearch.shop_id ?? undefined,
      shop_name: orderSearch.shop_name || undefined,
      so_id: orderSearch.so_id || undefined,
      status: orderSearch.status || undefined,
      keyword: orderSearch.keyword || undefined,
      page_no: orderPage.page_no,
      page_size: orderPage.page_size,
    });
    const data = res.data?.data;
    orders.value = data?.items ?? [];
    orderPage.total = data?.total ?? 0;
    orderPage.summary = data?.summary ?? { order_count: 0, buyer_paid_amount_sum: 0, item_count_sum: 0 };
  } catch (error) {
    orders.value = [];
    ElMessage.error("查询零售订单失败");
    console.error(error);
  } finally {
    orderLoading.value = false;
  }
}

async function loadBatches() {
  batchLoading.value = true;
  try {
    const res = await RetailAPI.batches({
      request_id: batchSearch.request_id || undefined,
      source: batchSearch.source || undefined,
      status: batchSearch.status || undefined,
      page_no: batchPage.page_no,
      page_size: batchPage.page_size,
    });
    const data = res.data?.data;
    batches.value = data?.items ?? [];
    batchPage.total = data?.total ?? 0;
  } catch (error) {
    batches.value = [];
    ElMessage.error("查询推送批次失败");
    console.error(error);
  } finally {
    batchLoading.value = false;
  }
}

function queryOrders() {
  orderPage.page_no = 1;
  loadOrders();
}

function resetOrderSearch() {
  Object.assign(orderSearch, {
    period_value: undefined,
    shop_id: undefined,
    shop_name: "",
    so_id: "",
    status: "",
    keyword: "",
  });
  queryOrders();
}

function queryBatches() {
  batchPage.page_no = 1;
  loadBatches();
}

function resetBatchSearch() {
  Object.assign(batchSearch, { request_id: "", source: "", status: undefined });
  queryBatches();
}

async function openOrder(row: RetailOrderRow) {
  try {
    const res = await RetailAPI.orderDetail(row.id);
    orderDetail.value = res.data?.data ?? null;
    orderVisible.value = true;
  } catch (error) {
    ElMessage.error("加载订单明细失败");
    console.error(error);
  }
}

async function openBatch(row: RetailBatchRow) {
  try {
    const res = await RetailAPI.batchDetail(row.id);
    batchDetail.value = res.data?.data ?? null;
    batchVisible.value = true;
  } catch (error) {
    ElMessage.error("加载批次详情失败");
    console.error(error);
  }
}

function handleTabChange(name: string | number) {
  if (name === "batches" && !batches.value.length) {
    loadBatches();
  }
}

onMounted(async () => {
  await loadPeriods();
  await loadOrders();
});
</script>

<style lang="scss" scoped>
.retail-sync-page {
  height: 100%;
  padding: 12px;

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 12px;
  }

  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    margin-bottom: 10px;
    font-size: 13px;
    color: var(--el-text-color-regular);
  }

  .summary-extra,
  .muted {
    color: var(--el-text-color-secondary);
  }

  .pager {
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
  }

  .detail-table {
    margin-top: 14px;
  }

  .json-block {
    margin-top: 14px;
  }

  .json-title {
    margin-bottom: 6px;
    font-size: 13px;
    font-weight: 600;
  }

  pre {
    max-height: 260px;
    padding: 10px;
    margin: 0;
    overflow: auto;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
    background: var(--el-fill-color-lighter);
    border-radius: 4px;
  }
}
</style>
