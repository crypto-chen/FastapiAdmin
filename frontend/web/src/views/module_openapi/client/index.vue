<template>
  <div class="openapi-client-page">
    <ElCard shadow="never">
      <ElAlert type="info" show-icon :closable="false" class="api-tip">
        <template #title>
          外部系统对接：先 <b>POST /open/v1/auth/token</b> 用应用密钥换令牌，再 <b>POST /open/v1/metrics/query</b> 批量取数。
          默认只返回「组织合计」，需要部门/客户明细请在下方应用上单独开启。
        </template>
      </ElAlert>

      <div class="toolbar">
        <ElInput
          v-model="search.app_id"
          placeholder="应用标识"
          clearable
          style="width: 180px"
          @keyup.enter="handleQuery"
        />
        <ElInput
          v-model="search.name"
          placeholder="应用名称"
          clearable
          style="width: 180px"
          @keyup.enter="handleQuery"
        />
        <ElSelect v-model="search.status" placeholder="状态" clearable style="width: 120px">
          <ElOption label="启用" :value="0" />
          <ElOption label="停用" :value="1" />
        </ElSelect>
        <ElButton type="primary" :loading="loading" @click="handleQuery">查询</ElButton>
        <ElButton @click="handleReset">重置</ElButton>
        <ElButton v-hasPerm="'module_openapi:client:create'" type="primary" plain @click="openCreate">
          新增应用
        </ElButton>
      </div>

      <ElTable v-loading="loading" :data="rows" border stripe row-key="id">
        <ElTableColumn prop="app_id" label="应用标识" min-width="160" show-overflow-tooltip />
        <ElTableColumn prop="name" label="应用名称" min-width="160" show-overflow-tooltip />
        <ElTableColumn prop="status" label="状态" width="90" align="center">
          <template #default="{ row }">
            <ElTag :type="row.status === 0 ? 'success' : 'info'" size="small">
              {{ row.status === 0 ? "启用" : "停用" }}
            </ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="组织范围" min-width="140" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.org_scope?.length ? row.org_scope.join("、") : "全部组织" }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="核算维度" width="110" align="center">
          <template #default="{ row }">
            {{ row.allow_dept_detail ? "含明细" : "仅合计" }}
          </template>
        </ElTableColumn>
        <ElTableColumn label="限流(次/分)" width="110" align="center">
          <template #default="{ row }">{{ row.rate_limit }}</template>
        </ElTableColumn>
        <ElTableColumn label="令牌有效期" width="110" align="center">
          <template #default="{ row }">{{ Math.round(row.token_ttl_seconds / 60) }} 分钟</template>
        </ElTableColumn>
        <ElTableColumn prop="ip_whitelist" label="IP 白名单" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.ip_whitelist || "不限制" }}</template>
        </ElTableColumn>
        <ElTableColumn prop="contact" label="联系人" width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.contact || "-" }}</template>
        </ElTableColumn>
        <ElTableColumn label="创建时间" width="170">
          <template #default="{ row }">{{ formatTime(row.created_time) }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="220" fixed="right">
          <template #default="{ row }">
            <ElButton
              v-hasPerm="'module_openapi:client:update'"
              link
              type="primary"
              @click="openEdit(row as OpenClientItem)"
            >
              编辑
            </ElButton>
            <ElButton
              v-hasPerm="'module_openapi:client:update'"
              link
              type="warning"
              @click="handleResetSecret(row as OpenClientItem)"
            >
              重置密钥
            </ElButton>
            <ElButton
              v-hasPerm="'module_openapi:client:delete'"
              link
              type="danger"
              @click="handleDelete(row as OpenClientItem)"
            >
              删除
            </ElButton>
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

    <ElDialog v-model="formVisible" :title="formTitle" width="640px" destroy-on-close>
      <ElForm ref="formRef" :model="form" :rules="rules" label-width="120px">
        <ElFormItem label="应用标识" prop="app_id">
          <ElInput v-model="form.app_id" :disabled="isEdit" placeholder="英文/数字，如 bi_report" />
        </ElFormItem>
        <ElFormItem label="应用名称" prop="name">
          <ElInput v-model="form.name" placeholder="如 BI 报表平台" />
        </ElFormItem>
        <ElFormItem label="状态">
          <ElRadioGroup v-model="form.status">
            <ElRadio :value="0">启用</ElRadio>
            <ElRadio :value="1">停用</ElRadio>
          </ElRadioGroup>
        </ElFormItem>
        <ElFormItem label="限流(次/分)">
          <ElInputNumber v-model="form.rate_limit" :min="1" :max="100000" :step="60" />
        </ElFormItem>
        <ElFormItem label="令牌有效期">
          <ElInputNumber v-model="form.token_ttl_seconds" :min="300" :max="604800" :step="300" />
          <span class="form-tip">秒（默认 7200 秒 = 2 小时）</span>
        </ElFormItem>
        <ElFormItem label="组织范围">
          <ElSelect v-model="form.org_scope" multiple filterable clearable placeholder="留空 = 全部组织" style="width: 100%">
            <ElOption v-for="item in orgOptions" :key="item.value" :label="item.label" :value="item.value" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="核算维度明细">
          <ElSwitch v-model="form.allow_dept_detail" />
          <span class="form-tip">关闭时只返回组织合计；开启后对方可查部门/客户明细</span>
        </ElFormItem>
        <ElFormItem label="允许触发重算">
          <ElSwitch v-model="form.allow_run_calc" />
          <span class="form-tip">开启后对方可调重算接口（耗时较长，谨慎开放）</span>
        </ElFormItem>
        <ElFormItem label="IP 白名单">
          <ElInput v-model="form.ip_whitelist" placeholder="192.168.1.10,10.0.0.*（留空不限制）" />
        </ElFormItem>
        <ElFormItem label="凭证到期时间">
          <ElDatePicker
            v-model="form.expire_time"
            type="datetime"
            placeholder="留空 = 长期有效"
            value-format="YYYY-MM-DDTHH:mm:ss"
            style="width: 100%"
          />
        </ElFormItem>
        <ElFormItem label="联系人">
          <ElInput v-model="form.contact" placeholder="对接方联系人" />
        </ElFormItem>
        <ElFormItem label="用途备注">
          <ElInput v-model="form.description" type="textarea" :rows="2" placeholder="如：经营看板取数" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="formVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="submitting" @click="submitForm">确定</ElButton>
      </template>
    </ElDialog>

    <ElDialog v-model="secretVisible" title="应用密钥（仅显示一次）" width="560px" :close-on-click-modal="false">
      <ElAlert type="warning" show-icon :closable="false" class="secret-tip">
        <template #title>密钥关闭后无法再次查看，请立即复制并交给对接方；重置密钥会使旧密钥与已签发令牌立即失效。</template>
      </ElAlert>
      <ElDescriptions :column="1" border>
        <ElDescriptionsItem label="应用标识">{{ secretInfo.app_id }}</ElDescriptionsItem>
        <ElDescriptionsItem label="应用密钥">
          <div class="secret-row">
            <span class="secret-value">{{ secretInfo.app_secret }}</span>
            <ElButton link type="primary" @click="copySecret">复制</ElButton>
          </div>
        </ElDescriptionsItem>
      </ElDescriptions>
      <template #footer>
        <ElButton type="primary" @click="secretVisible = false">我已保存</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import {
  OpenApiClientAPI,
  type OpenClientItem,
  type OptionItem,
} from "@/api/module_openapi";

defineOptions({ name: "OpenApiClient" });

const loading = ref(false);
const submitting = ref(false);
const rows = ref<OpenClientItem[]>([]);
const orgOptions = ref<OptionItem[]>([]);
const page = reactive({ page_no: 1, page_size: 20, total: 0 });
const search = reactive<{ app_id?: string; name?: string; status?: number }>({});

const formVisible = ref(false);
const isEdit = ref(false);
const formRef = ref<FormInstance>();
const currentId = ref<number | undefined>(undefined);
const form = reactive({
  app_id: "",
  name: "",
  status: 0,
  rate_limit: 600,
  token_ttl_seconds: 7200,
  org_scope: [] as string[],
  allow_dept_detail: false,
  allow_run_calc: false,
  ip_whitelist: "",
  expire_time: "" as string | null,
  contact: "",
  description: "",
});

const rules: FormRules = {
  app_id: [{ required: true, message: "请输入应用标识", trigger: "blur" }],
  name: [{ required: true, message: "请输入应用名称", trigger: "blur" }],
};

const formTitle = computed(() => (isEdit.value ? "编辑接入应用" : "新增接入应用"));

const secretVisible = ref(false);
const secretInfo = reactive({ app_id: "", app_secret: "" });

function formatTime(value?: string | null) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

async function loadData() {
  loading.value = true;
  try {
    const res = await OpenApiClientAPI.page({
      page_no: page.page_no,
      page_size: page.page_size,
      app_id: search.app_id || undefined,
      name: search.name || undefined,
      status: search.status,
    });
    const data = res.data?.data;
    rows.value = data?.items ?? [];
    page.total = data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

async function loadOrgOptions() {
  const res = await OpenApiClientAPI.orgOptions();
  orgOptions.value = res.data?.data ?? [];
}

function handleQuery() {
  page.page_no = 1;
  loadData();
}

function handleReset() {
  search.app_id = undefined;
  search.name = undefined;
  search.status = undefined;
  handleQuery();
}

function handleSizeChange() {
  page.page_no = 1;
  loadData();
}

function resetForm() {
  Object.assign(form, {
    app_id: "",
    name: "",
    status: 0,
    rate_limit: 600,
    token_ttl_seconds: 7200,
    org_scope: [],
    allow_dept_detail: false,
    allow_run_calc: false,
    ip_whitelist: "",
    expire_time: "",
    contact: "",
    description: "",
  });
}

function openCreate() {
  isEdit.value = false;
  currentId.value = undefined;
  resetForm();
  formVisible.value = true;
}

function openEdit(row: OpenClientItem) {
  isEdit.value = true;
  currentId.value = row.id;
  Object.assign(form, {
    app_id: row.app_id,
    name: row.name,
    status: row.status,
    rate_limit: row.rate_limit,
    token_ttl_seconds: row.token_ttl_seconds,
    org_scope: row.org_scope ?? [],
    allow_dept_detail: row.allow_dept_detail,
    allow_run_calc: row.allow_run_calc,
    ip_whitelist: row.ip_whitelist ?? "",
    expire_time: row.expire_time ? row.expire_time.replace(" ", "T").slice(0, 19) : "",
    contact: row.contact ?? "",
    description: row.description ?? "",
  });
  formVisible.value = true;
}

function buildPayload() {
  return {
    name: form.name,
    status: form.status,
    rate_limit: form.rate_limit,
    token_ttl_seconds: form.token_ttl_seconds,
    org_scope: form.org_scope.length ? [...form.org_scope] : null,
    allow_dept_detail: form.allow_dept_detail,
    allow_run_calc: form.allow_run_calc,
    ip_whitelist: form.ip_whitelist || null,
    expire_time: form.expire_time || null,
    contact: form.contact || null,
    description: form.description || null,
  };
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    if (isEdit.value && currentId.value) {
      await OpenApiClientAPI.update(currentId.value, buildPayload());
      ElMessage.success("修改成功");
    } else {
      const res = await OpenApiClientAPI.create({ app_id: form.app_id, ...buildPayload() });
      const data = res.data?.data;
      if (data) {
        secretInfo.app_id = data.app_id;
        secretInfo.app_secret = data.app_secret;
        secretVisible.value = true;
      }
      ElMessage.success("创建成功");
    }
    formVisible.value = false;
    await loadData();
  } finally {
    submitting.value = false;
  }
}

async function handleResetSecret(row: OpenClientItem) {
  await ElMessageBox.confirm(
    `重置后「${row.name}」的旧密钥与已签发令牌会立即失效，对接方需重新换令牌。是否继续？`,
    "重置密钥",
    { type: "warning" },
  );
  const res = await OpenApiClientAPI.resetSecret(row.id);
  const data = res.data?.data;
  if (data) {
    secretInfo.app_id = data.app_id;
    secretInfo.app_secret = data.app_secret;
    secretVisible.value = true;
  }
  await loadData();
}

async function handleDelete(row: OpenClientItem) {
  await ElMessageBox.confirm(`删除后「${row.name}」将无法再调用接口，是否继续？`, "删除应用", { type: "warning" });
  await OpenApiClientAPI.remove([row.id]);
  ElMessage.success("删除成功");
  await loadData();
}

async function copySecret() {
  try {
    await navigator.clipboard.writeText(secretInfo.app_secret);
    ElMessage.success("密钥已复制");
  } catch {
    ElMessage.warning("浏览器拒绝访问剪贴板，请手动选中复制");
  }
}

onMounted(async () => {
  await loadOrgOptions();
  await loadData();
});
</script>

<style scoped>
.openapi-client-page {
  height: 100%;
  padding: 12px;
}
.api-tip {
  margin-bottom: 12px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.form-tip {
  margin-left: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
.pagination {
  margin-top: 12px;
  justify-content: flex-end;
}
.secret-tip {
  margin-bottom: 12px;
}
.secret-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.secret-value {
  font-family: var(--el-font-family-mono, monospace);
  word-break: break-all;
}
</style>
