<template>
  <div class="manual-binding-page">
    <ElTabs v-model="activeKey">
      <ElTabPane label="组织绑定" name="org" />
      <ElTabPane label="部门绑定" name="dept" />
      <ElTabPane label="人员绑定" name="person" />
      <ElTabPane label="人员任岗绑定" name="personOrg" />
    </ElTabs>

    <ElCard shadow="never">
      <div class="toolbar">
        <ElSelect v-model="sourceType" placeholder="来源类型" clearable style="width: 200px" @change="loadCurrent">
          <ElOption v-for="opt in sourceTypes" :key="opt.value" :label="opt.label" :value="opt.value" />
        </ElSelect>
        <ElButton type="primary" :loading="loading" @click="loadCurrent">刷新</ElButton>
        <ElButton :loading="syncingOrg" @click="syncCrmOrg">同步CRM架构</ElButton>
        <ElButton :loading="syncingPerson" @click="syncCrmPerson">同步CRM人员</ElButton>
      </div>

      <ElTable v-loading="loading" :data="rows" border stripe row-key="id" max-height="calc(100vh - 300px)">
        <ElTableColumn
          v-for="col in currentColumns"
          :key="col.prop"
          :prop="col.prop"
          :label="col.label"
          :min-width="col.width || 120"
          show-overflow-tooltip
        />
        <ElTableColumn label="绑定目标" min-width="280">
          <template #default="{ row }">
            <div v-if="activeKey === 'org'" class="bind-cell">
              <ElSelect v-model="orgTargets[row.id]" placeholder="选择内部组织" clearable filterable>
                <ElOption v-for="opt in orgOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </ElSelect>
              <ElButton type="primary" size="small" @click="bindOrgRow(row)">绑定</ElButton>
            </div>
            <div v-else-if="activeKey === 'dept'" class="bind-cell">
              <ElSelect
                v-model="deptTargets[row.id]"
                placeholder="选择内部部门"
                clearable
                filterable
                :disabled="!row.master_org_id"
              >
                <ElOption
                  v-for="opt in deptOptionsByOrg(row.master_org_id)"
                  :key="opt.id"
                  :label="`${opt.code} - ${opt.name}`"
                  :value="opt.id"
                />
              </ElSelect>
              <ElButton type="primary" size="small" :disabled="!row.master_org_id" @click="bindDeptRow(row)">绑定</ElButton>
            </div>
            <div v-else-if="activeKey === 'person'" class="bind-cell">
              <ElSelect v-model="personTargets[row.id]" placeholder="选择内部人员" clearable filterable>
                <ElOption v-for="opt in personOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </ElSelect>
              <ElButton type="primary" size="small" @click="bindPersonRow(row)">绑定</ElButton>
            </div>
            <div v-else class="bind-person-org">
              <ElSelect v-model="personOrgForms[row.id].master_person_id" placeholder="内部人员" clearable filterable>
                <ElOption v-for="opt in personOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </ElSelect>
              <ElSelect v-model="personOrgForms[row.id].master_org_id" placeholder="内部组织" clearable filterable>
                <ElOption v-for="opt in orgOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
              </ElSelect>
              <ElSelect
                v-model="personOrgForms[row.id].master_dept_id"
                placeholder="内部部门"
                clearable
                filterable
              >
                <ElOption
                  v-for="opt in deptOptionsByOrg(personOrgForms[row.id].master_org_id)"
                  :key="opt.id"
                  :label="`${opt.code} - ${opt.name}`"
                  :value="opt.id"
                />
              </ElSelect>
              <ElSwitch v-model="personOrgForms[row.id].is_primary" active-text="主岗" />
              <ElButton type="primary" size="small" @click="bindPersonOrgRow(row)">绑定</ElButton>
            </div>
          </template>
        </ElTableColumn>
      </ElTable>
    </ElCard>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { ManualBindingAPI, type MappingItem } from "@/api/module_system_mapping";

const activeKey = ref("org");
const loading = ref(false);
const syncingOrg = ref(false);
const syncingPerson = ref(false);
const rows = ref<MappingItem[]>([]);
const orgOptions = ref<{ value: number; label: string }[]>([]);
const personOptions = ref<{ value: number; label: string }[]>([]);
const allDeptOptions = ref<Record<string, unknown>[]>([]);
const sourceTypes = ref<{ value: string; label: string }[]>([]);
const sourceType = ref<string | undefined>(undefined);
const orgTargets = reactive<Record<number, number | undefined>>({});
const deptTargets = reactive<Record<number, number | undefined>>({});
const personTargets = reactive<Record<number, number | undefined>>({});
const personOrgForms = reactive<Record<number, Record<string, any>>>({});

const currentColumns = computed(() => {
  if (activeKey.value === "org") {
    return [
      { prop: "source_type", label: "来源类型", width: 110 },
      { prop: "source_code", label: "来源组织编码", width: 140 },
      { prop: "source_name", label: "来源组织名称", width: 220 },
      { prop: "source_parent_code", label: "来源上级编码", width: 140 },
    ];
  }
  if (activeKey.value === "dept") {
    return [
      { prop: "source_type", label: "来源类型", width: 110 },
      { prop: "source_org_code", label: "来源组织", width: 110 },
      { prop: "source_code", label: "来源部门编码", width: 160 },
      { prop: "source_name", label: "来源部门名称", width: 200 },
      { prop: "source_parent_code", label: "来源上级编码", width: 140 },
    ];
  }
  if (activeKey.value === "person") {
    return [
      { prop: "source_type", label: "来源类型", width: 110 },
      { prop: "source_code", label: "来源人员编码", width: 150 },
      { prop: "source_name", label: "来源人员姓名", width: 150 },
      { prop: "mobile", label: "手机号", width: 140 },
      { prop: "email", label: "邮箱", width: 180 },
    ];
  }
  return [
    { prop: "source_type", label: "来源类型", width: 110 },
    { prop: "source_code", label: "来源人员编码", width: 150 },
    { prop: "source_name", label: "来源人员姓名", width: 150 },
    { prop: "source_org_code", label: "来源组织", width: 110 },
  ];
});

function deptOptionsByOrg(orgId?: number) {
  if (!orgId) return allDeptOptions.value.filter((item) => !item.org_id);
  return allDeptOptions.value.filter((item) => Number(item.org_id) === Number(orgId));
}

async function loadOptions() {
  const [orgRes, personRes, deptRes, typeRes] = await Promise.all([
    ManualBindingAPI.orgOptions(),
    ManualBindingAPI.personOptions(),
    ManualBindingAPI.deptOptions(),
    ManualBindingAPI.sourceTypes(),
  ]);
  orgOptions.value = orgRes.data?.data ?? [];
  personOptions.value = personRes.data?.data ?? [];
  allDeptOptions.value = deptRes.data?.data ?? [];
  sourceTypes.value = typeRes.data?.data ?? [];
}

async function loadCurrent() {
  loading.value = true;
  try {
    if (activeKey.value === "org") {
      const res = await ManualBindingAPI.unmappedOrg({ source_type: sourceType.value });
      rows.value = res.data?.data ?? [];
    } else if (activeKey.value === "dept") {
      const res = await ManualBindingAPI.unmappedDept({ source_type: sourceType.value });
      rows.value = res.data?.data ?? [];
    } else if (activeKey.value === "person") {
      const res = await ManualBindingAPI.unmappedPerson({ source_type: sourceType.value });
      rows.value = res.data?.data ?? [];
    } else {
      const res = await ManualBindingAPI.sourcePersons({ page_no: 1, page_size: 500, source_type: sourceType.value });
      rows.value = res.data?.data?.items ?? [];
      rows.value.forEach((row) => {
        if (!personOrgForms[row.id!]) {
          personOrgForms[row.id!] = { master_person_id: undefined, master_org_id: undefined, master_dept_id: undefined, is_primary: false, status: 0 };
        }
      });
    }
  } finally {
    loading.value = false;
  }
}

/** 手动任务：同步 CRM 人员架构（组织 + 部门），无定时执行 */
async function syncCrmOrg() {
  await ElMessageBox.confirm(
    "将拉取 CRM 组织架构并写入来源组织/来源部门（按来源编码更新，不影响已绑定关系），是否继续？",
    "同步 CRM 人员架构",
    { type: "info", confirmButtonText: "开始同步", cancelButtonText: "取消" }
  );
  syncingOrg.value = true;
  try {
    const res = await ManualBindingAPI.syncCrmOrg();
    const r = (res.data?.data ?? {}) as Record<string, number>;
    ElMessage.success(
      `同步完成：来源组织 新增 ${r.orgs_created ?? 0} / 更新 ${r.orgs_updated ?? 0}，` +
        `来源部门 新增 ${r.depts_created ?? 0} / 更新 ${r.depts_updated ?? 0}（共 ${r.dept_total ?? 0}）`
    );
    await loadOptions();
    await loadCurrent();
  } finally {
    syncingOrg.value = false;
  }
}

/** 手动任务：同步 CRM 人员，无定时执行 */
async function syncCrmPerson() {
  await ElMessageBox.confirm(
    "将拉取 CRM 人员明细并写入来源人员表（按来源编码更新，不影响已绑定关系），是否继续？",
    "同步 CRM 人员",
    { type: "info", confirmButtonText: "开始同步", cancelButtonText: "取消" }
  );
  syncingPerson.value = true;
  try {
    const res = await ManualBindingAPI.syncCrmPerson();
    const r = (res.data?.data ?? {}) as Record<string, number>;
    ElMessage.success(
      `同步完成：来源人员 新增 ${r.persons_created ?? 0} / 更新 ${r.persons_updated ?? 0}，` +
        `共 ${r.person_total ?? 0} 人（在职 ${r.person_active ?? 0}）`
    );
    await loadOptions();
    await loadCurrent();
  } finally {
    syncingPerson.value = false;
  }
}

async function bindOrgRow(row: MappingItem) {
  if (!orgTargets[row.id!]) return ElMessage.warning("请选择内部组织");
  await ManualBindingAPI.bindOrg({ source_org_id: row.id, master_org_id: orgTargets[row.id!] });
  ElMessage.success("组织绑定成功");
  await loadCurrent();
}

async function bindDeptRow(row: MappingItem) {
  if (!deptTargets[row.id!]) return ElMessage.warning("请选择内部部门");
  await ManualBindingAPI.bindDept({ source_dept_id: row.id, master_dept_id: deptTargets[row.id!] });
  ElMessage.success("部门绑定成功");
  await loadCurrent();
}

async function bindPersonRow(row: MappingItem) {
  if (!personTargets[row.id!]) return ElMessage.warning("请选择内部人员");
  await ManualBindingAPI.bindPerson({ source_person_id: row.id, master_person_id: personTargets[row.id!] });
  ElMessage.success("人员绑定成功");
  await loadCurrent();
}

async function bindPersonOrgRow(row: MappingItem) {
  const form = personOrgForms[row.id!];
  if (!form?.master_person_id || !form?.master_org_id) return ElMessage.warning("请选择内部人员和组织");
  await ManualBindingAPI.bindPersonOrg({
    source_person_id: row.id,
    master_person_id: form.master_person_id,
    master_org_id: form.master_org_id,
    master_dept_id: form.master_dept_id,
    is_primary: form.is_primary,
    status: form.status ?? 0,
  });
  ElMessage.success("任岗绑定成功");
  await loadCurrent();
}

onMounted(async () => {
  await loadOptions();
  await loadCurrent();
});
</script>

<style scoped>
.manual-binding-page {
  height: 100%;
  padding: 12px;
}
.toolbar {
  margin-bottom: 12px;
}
.bind-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bind-person-org {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}
.bind-person-org .el-select {
  width: 160px;
}
</style>
