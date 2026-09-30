<template>
  <div class="sys-dept-binding-page">
    <ElRow :gutter="12">
      <ElCol :span="6">
        <ElCard shadow="never" class="tree-card">
          <template #header>系统权限部门</template>
          <ElTree
            :data="deptTree"
            node-key="id"
            default-expand-all
            highlight-current
            :props="{ label: 'name', children: 'children' }"
            @node-click="handleSelectDept"
          />
        </ElCard>
      </ElCol>

      <ElCol :span="18">
        <ElCard shadow="never">
          <div class="toolbar">
            <ElSelect v-model="filters.source_type" placeholder="来源类型" clearable style="width: 160px">
              <ElOption v-for="item in sourceTypes" :key="item.value" :label="item.label" :value="item.value" />
            </ElSelect>
            <ElSelect v-model="filters.org_id" placeholder="业务组织" clearable style="width: 220px">
              <ElOption v-for="item in orgOptions" :key="item.value" :label="item.label" :value="item.value" />
            </ElSelect>
            <ElInput v-model="filters.keyword" placeholder="部门名称/编码" clearable style="width: 220px" />
            <ElButton @click="loadOptions">查询</ElButton>
            <ElButton type="primary" :disabled="!selectedSysDeptId || !selectedOptionIds.length" @click="bindSelected">
              绑定选中
            </ElButton>
          </div>

          <ElAlert v-if="!selectedSysDeptId" type="info" :closable="false" show-icon title="请先在左侧选择系统权限部门" />
          <template v-else>
            <ElDivider content-position="left">已绑定业务标准部门</ElDivider>
            <ElTable :data="bindings" border stripe max-height="300">
              <ElTableColumn prop="master_dept_code" label="业务部门编码" width="160" />
              <ElTableColumn prop="master_dept_name" label="业务部门名称" min-width="180" />
              <ElTableColumn prop="source_type" label="来源类型" width="110" />
              <ElTableColumn prop="source_org_code" label="来源组织" width="110" />
              <ElTableColumn prop="source_dept_code" label="来源部门编码" width="150" />
              <ElTableColumn label="操作" width="90">
                <template #default="{ row }">
                  <ElButton link type="danger" @click="unbindRow(row)">解绑</ElButton>
                </template>
              </ElTableColumn>
            </ElTable>

            <ElDivider content-position="left">可绑定业务标准部门</ElDivider>
            <ElTable
              :data="options"
              border
              stripe
              max-height="420"
              @selection-change="handleOptionSelection"
            >
              <ElTableColumn type="selection" width="48" />
              <ElTableColumn prop="org_code" label="组织编码" width="100" />
              <ElTableColumn prop="code" label="部门编码" width="160" />
              <ElTableColumn prop="name" label="部门名称" min-width="180" />
              <ElTableColumn prop="source_type" label="来源类型" width="110" />
              <ElTableColumn prop="source_org_code" label="来源组织" width="110" />
              <ElTableColumn prop="source_dept_code" label="来源部门编码" width="150" />
            </ElTable>
          </template>
        </ElCard>
      </ElCol>
    </ElRow>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import DeptAPI, { type DeptTable } from "@/api/module_system/dept";
import { ManualBindingAPI, type MappingItem } from "@/api/module_system_mapping";

const deptTree = ref<DeptTable[]>([]);
const selectedSysDeptId = ref<number | undefined>(undefined);
const bindings = ref<MappingItem[]>([]);
const options = ref<MappingItem[]>([]);
const selectedOptionIds = ref<number[]>([]);
const sourceTypes = ref<{ value: string; label: string }[]>([]);
const orgOptions = ref<{ value: number; label: string }[]>([]);
const filters = reactive<{ source_type?: string; org_id?: number; keyword?: string }>({
  source_type: undefined,
  org_id: undefined,
  keyword: undefined,
});

async function loadTree() {
  const res = await DeptAPI.listDept();
  deptTree.value = res.data?.data ?? [];
}

async function loadBaseOptions() {
  const [typeRes, orgRes] = await Promise.all([ManualBindingAPI.sourceTypes(), ManualBindingAPI.orgOptions()]);
  sourceTypes.value = typeRes.data?.data ?? [];
  orgOptions.value = orgRes.data?.data ?? [];
}

async function loadBindings() {
  if (!selectedSysDeptId.value) return;
  const res = await ManualBindingAPI.sysDeptBindings(selectedSysDeptId.value);
  bindings.value = res.data?.data ?? [];
}

async function loadOptions() {
  const params: Record<string, unknown> = {};
  if (filters.source_type) params.source_type = filters.source_type;
  if (filters.org_id) params.org_id = filters.org_id;
  if (filters.keyword) params.keyword = filters.keyword;
  const res = await ManualBindingAPI.sysDeptOptions(params);
  options.value = res.data?.data ?? [];
}

async function handleSelectDept(node: DeptTable) {
  selectedSysDeptId.value = node.id;
  await loadBindings();
}

function handleOptionSelection(rows: MappingItem[]) {
  selectedOptionIds.value = rows.map((row) => row.id!);
}

async function bindSelected() {
  await ManualBindingAPI.bindSysDept({ sys_dept_id: selectedSysDeptId.value, master_dept_ids: selectedOptionIds.value });
  ElMessage.success("绑定成功");
  selectedOptionIds.value = [];
  await loadBindings();
  await loadOptions();
}

async function unbindRow(row: MappingItem) {
  await ManualBindingAPI.unbindSysDept({ sys_dept_id: selectedSysDeptId.value, master_dept_ids: [row.master_dept_id] });
  ElMessage.success("解绑成功");
  await loadBindings();
  await loadOptions();
}

onMounted(async () => {
  await loadTree();
  await loadBaseOptions();
  await loadOptions();
});
</script>

<style scoped>
.sys-dept-binding-page {
  height: 100%;
  padding: 12px;
}
.tree-card {
  min-height: 720px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 12px;
}
</style>
