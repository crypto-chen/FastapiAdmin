<template>
  <div class="openapi-log-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElInput
          v-model="search.app_id"
          placeholder="应用标识"
          clearable
          style="width: 170px"
          @keyup.enter="handleQuery"
        />
        <ElInput
          v-model="search.path"
          placeholder="请求路径"
          clearable
          style="width: 220px"
          @keyup.enter="handleQuery"
        />
        <ElSelect v-model="search.method" placeholder="方法" clearable style="width: 110px">
          <ElOption v-for="item in ['GET', 'POST', 'PUT', 'DELETE']" :key="item" :label="item" :value="item" />
        </ElSelect>
        <ElSelect v-model="search.http_status" placeholder="HTTP 状态" clearable style="width: 130px">
          <ElOption label="200 成功" :value="200" />
          <ElOption label="400 参数错误" :value="400" />
          <ElOption label="401 未认证" :value="401" />
          <ElOption label="403 无权限" :value="403" />
          <ElOption label="429 限流" :value="429" />
          <ElOption label="500 服务异常" :value="500" />
        </ElSelect>
        <ElDatePicker
          v-model="createdTime"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          value-format="YYYY-MM-DD HH:mm:ss"
          style="width: 340px"
        />
        <ElButton type="primary" :loading="loading" @click="handleQuery">查询</ElButton>
        <ElButton @click="handleReset">重置</ElButton>
      </div>

      <ElTable v-loading="loading" :data="rows" border stripe row-key="id">
        <ElTableColumn prop="created_time" label="调用时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_time) }}</template>
        </ElTableColumn>
        <ElTableColumn prop="app_id" label="应用标识" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">{{ row.app_id || "-" }}</template>
        </ElTableColumn>
        <ElTableColumn prop="method" label="方法" width="80" align="center" />
        <ElTableColumn prop="path" label="请求路径" min-width="200" show-overflow-tooltip />
        <ElTableColumn label="HTTP" width="90" align="center">
          <template #default="{ row }">
            <ElTag :type="statusTagType(row.http_status)" size="small">{{ row.http_status }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn prop="response_code" label="业务码" width="90" align="center" />
        <ElTableColumn label="耗时" width="100" align="right">
          <template #default="{ row }">{{ row.cost_ms }} ms</template>
        </ElTableColumn>
        <ElTableColumn prop="client_ip" label="调用方 IP" min-width="130" show-overflow-tooltip>
          <template #default="{ row }">{{ row.client_ip || "-" }}</template>
        </ElTableColumn>
        <ElTableColumn prop="description" label="接口说明" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || "-" }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openDetail(row as OpenApiLogItem)">参数</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <ElPagination
        v-model:current-page="page.page_no"
        v-model:page-size="page.page_size"
        :total="page.total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </ElCard>

    <ElDialog v-model="detailVisible" title="请求参数" width="620px" destroy-on-close>
      <pre class="params-json">{{ detailText }}</pre>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { OpenApiLogAPI, type OpenApiLogItem } from "@/api/module_openapi";

defineOptions({ name: "OpenApiLog" });

const loading = ref(false);
const rows = ref<OpenApiLogItem[]>([]);
const page = reactive({ page_no: 1, page_size: 20, total: 0 });
const createdTime = ref<string[] | undefined>(undefined);
const search = reactive<{ app_id?: string; path?: string; method?: string; http_status?: number }>({});
const detailVisible = ref(false);
const detail = ref<OpenApiLogItem | null>(null);

const detailText = computed(() => JSON.stringify(detail.value?.params ?? {}, null, 2));

function formatTime(value?: string | null) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

function statusTagType(status: number) {
  if (status >= 500) return "danger";
  if (status >= 400) return "warning";
  return "success";
}

async function loadData() {
  loading.value = true;
  try {
    const res = await OpenApiLogAPI.page({
      page_no: page.page_no,
      page_size: page.page_size,
      app_id: search.app_id || undefined,
      path: search.path || undefined,
      method: search.method || undefined,
      http_status: search.http_status,
      created_time: createdTime.value?.length === 2 ? createdTime.value : undefined,
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

function handleReset() {
  search.app_id = undefined;
  search.path = undefined;
  search.method = undefined;
  search.http_status = undefined;
  createdTime.value = undefined;
  handleQuery();
}

function handleSizeChange() {
  page.page_no = 1;
  loadData();
}

function openDetail(row: OpenApiLogItem) {
  detail.value = row;
  detailVisible.value = true;
}

onMounted(loadData);
</script>

<style scoped>
.openapi-log-page {
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
.pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
.params-json {
  max-height: 420px;
  margin: 0;
  overflow: auto;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
