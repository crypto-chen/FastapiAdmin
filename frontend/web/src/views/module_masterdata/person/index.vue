<!-- 系统标准人员：内部标准人员（master_person）维护页，对齐 module_system_mapping 写法 -->
<template>
  <div class="standard-person-page">
    <ElCard shadow="never">
      <div class="toolbar">
        <ElInput
          v-model="query.name"
          placeholder="人员姓名"
          clearable
          style="width: 160px"
          @keyup.enter="handleSearch"
        />
        <ElInput
          v-model="query.code"
          placeholder="人员编码"
          clearable
          style="width: 160px"
          @keyup.enter="handleSearch"
        />
        <ElSelect v-model="query.org_id" placeholder="所属组织" clearable filterable style="width: 220px">
          <ElOption v-for="opt in orgOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
        </ElSelect>
        <ElSelect v-model="query.status" placeholder="状态" clearable style="width: 120px">
          <ElOption label="启用" :value="0" />
          <ElOption label="停用" :value="1" />
        </ElSelect>
        <ElButton type="primary" :loading="loading" @click="handleSearch">查询</ElButton>
        <ElButton @click="resetQuery">重置</ElButton>
      </div>

      <div class="toolbar">
        <ElButton type="primary" @click="openCreate">新增人员</ElButton>
        <ElButton type="danger" :disabled="!selectedRows.length" @click="removeSelected">批量删除</ElButton>
        <ElButton @click="loadData">刷新</ElButton>
        <span class="total-hint">共 {{ page.total }} 人</span>
      </div>

      <ElTable v-loading="loading" :data="rows" border stripe row-key="id" @selection-change="onSelectionChange">
        <ElTableColumn type="selection" width="48" />
        <ElTableColumn prop="code" label="人员编码" width="140" show-overflow-tooltip />
        <ElTableColumn prop="name" label="人员姓名" width="140" show-overflow-tooltip />
        <ElTableColumn label="所属组织" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.org_name || "—" }}</template>
        </ElTableColumn>
        <ElTableColumn label="手机号" width="140">
          <template #default="{ row }">{{ row.mobile || "—" }}</template>
        </ElTableColumn>
        <ElTableColumn label="邮箱" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">{{ row.email || "—" }}</template>
        </ElTableColumn>
        <ElTableColumn label="状态" width="90">
          <template #default="{ row }">
            <ElTag :type="row.status === 0 ? 'success' : 'info'">{{ row.status === 0 ? "启用" : "停用" }}</ElTag>
          </template>
        </ElTableColumn>
        <ElTableColumn label="备注" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.description || "—" }}</template>
        </ElTableColumn>
        <ElTableColumn label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <ElButton link type="primary" @click="openEdit(row as MasterPersonItem)">编辑</ElButton>
            <ElButton link type="danger" @click="removeRow(row as MasterPersonItem)">删除</ElButton>
          </template>
        </ElTableColumn>
      </ElTable>

      <ElPagination
        v-model:current-page="page.page_no"
        v-model:page-size="page.page_size"
        :total="page.total"
        :page-sizes="[10, 20, 50, 100]"
        layout="total, sizes, prev, pager, next, jumper"
        class="pagination"
        @current-change="loadData"
        @size-change="handleSizeChange"
      />
    </ElCard>

    <ElDialog
      v-model="dialogVisible"
      :title="editingId ? '编辑标准人员' : '新增标准人员'"
      width="560px"
      destroy-on-close
    >
      <ElForm ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <ElFormItem label="人员编码" prop="code">
          <ElInput v-model="form.code" clearable placeholder="如 YG20002 / 001" />
        </ElFormItem>
        <ElFormItem label="人员姓名" prop="name">
          <ElInput v-model="form.name" clearable />
        </ElFormItem>
        <ElFormItem label="所属组织" prop="org_id">
          <ElSelect v-model="form.org_id" placeholder="请选择所属组织" clearable filterable style="width: 100%">
            <ElOption v-for="opt in orgOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </ElSelect>
        </ElFormItem>
        <ElFormItem label="手机号" prop="mobile">
          <ElInput v-model="form.mobile" clearable />
        </ElFormItem>
        <ElFormItem label="邮箱" prop="email">
          <ElInput v-model="form.email" clearable />
        </ElFormItem>
        <ElFormItem label="状态" prop="status">
          <ElRadioGroup v-model="form.status">
            <ElRadio :value="0">启用</ElRadio>
            <ElRadio :value="1">停用</ElRadio>
          </ElRadioGroup>
        </ElFormItem>
        <ElFormItem label="备注" prop="description">
          <ElInput v-model="form.description" type="textarea" :rows="3" />
        </ElFormItem>
      </ElForm>
      <template #footer>
        <ElButton @click="dialogVisible = false">取消</ElButton>
        <ElButton type="primary" :loading="submitting" @click="submitForm">保存</ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox, type FormInstance, type FormRules } from "element-plus";
import { MasterDataAPI, type MasterPersonItem } from "@/api/module_masterdata";
import { ManualBindingAPI } from "@/api/module_system_mapping";

const rows = ref<MasterPersonItem[]>([]);
const loading = ref(false);
const submitting = ref(false);
const dialogVisible = ref(false);
const editingId = ref<number | null>(null);
const selectedRows = ref<MasterPersonItem[]>([]);
const formRef = ref<FormInstance>();
const orgOptions = ref<{ value: number; label: string }[]>([]);

const page = reactive({ page_no: 1, page_size: 10, total: 0 });
const query = reactive<{ name?: string; code?: string; org_id?: number; status?: number }>({
  name: undefined,
  code: undefined,
  org_id: undefined,
  status: undefined,
});

const emptyForm = (): MasterPersonItem => ({
  code: "",
  name: "",
  org_id: null,
  mobile: "",
  email: "",
  status: 0,
  description: "",
});
const form = reactive<MasterPersonItem>(emptyForm());

const formRules: FormRules = {
  code: [{ required: true, message: "请输入人员编码", trigger: "blur" }],
  name: [{ required: true, message: "请输入人员姓名", trigger: "blur" }],
};

async function loadOrgOptions() {
  const res = await ManualBindingAPI.orgOptions();
  orgOptions.value = res.data?.data ?? [];
}

async function loadData() {
  loading.value = true;
  try {
    const res = await MasterDataAPI.person.page({
      page_no: page.page_no,
      page_size: page.page_size,
      name: query.name || undefined,
      code: query.code || undefined,
      org_id: query.org_id || undefined,
      status: query.status ?? undefined,
    });
    rows.value = res.data?.data?.items ?? [];
    page.total = res.data?.data?.total ?? 0;
  } finally {
    loading.value = false;
  }
}

function handleSearch() {
  page.page_no = 1;
  loadData();
}

function resetQuery() {
  query.name = undefined;
  query.code = undefined;
  query.org_id = undefined;
  query.status = undefined;
  handleSearch();
}

function handleSizeChange() {
  page.page_no = 1;
  loadData();
}

function resetForm(row?: MasterPersonItem) {
  Object.assign(form, emptyForm(), row ? { ...row } : {});
  formRef.value?.clearValidate();
}

function openCreate() {
  editingId.value = null;
  resetForm();
  dialogVisible.value = true;
}

function openEdit(row: MasterPersonItem) {
  editingId.value = row.id ?? null;
  resetForm(row);
  dialogVisible.value = true;
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false);
  if (!valid) return;

  const payload = {
    code: form.code?.trim(),
    name: form.name?.trim(),
    org_id: form.org_id || null,
    mobile: form.mobile || null,
    email: form.email || null,
    status: form.status,
    description: form.description || null,
  };
  submitting.value = true;
  try {
    if (editingId.value) {
      await MasterDataAPI.person.update(editingId.value, payload);
      ElMessage.success("修改成功");
    } else {
      await MasterDataAPI.person.create(payload);
      ElMessage.success("新增成功");
    }
    dialogVisible.value = false;
    await loadData();
  } finally {
    submitting.value = false;
  }
}

async function removeRow(row: MasterPersonItem) {
  await ElMessageBox.confirm(`确认删除标准人员「${row.name}」？`, "提示", { type: "warning" });
  await MasterDataAPI.person.remove([row.id!]);
  ElMessage.success("删除成功");
  await loadData();
}

async function removeSelected() {
  await ElMessageBox.confirm(`确认删除选中的 ${selectedRows.value.length} 名人员？`, "提示", { type: "warning" });
  await MasterDataAPI.person.remove(selectedRows.value.map((row) => row.id!));
  ElMessage.success("删除成功");
  selectedRows.value = [];
  await loadData();
}

function onSelectionChange(values: MasterPersonItem[]) {
  selectedRows.value = values;
}

onMounted(async () => {
  await Promise.all([loadOrgOptions(), loadData()]);
});
</script>

<style scoped lang="scss">
.standard-person-page {
  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
  }

  .total-hint {
    margin-left: auto;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }

  .pagination {
    margin-top: 12px;
    justify-content: flex-end;
  }
}
</style>
