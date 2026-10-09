import { request } from "@utils";

export interface MappingPageQuery {
  page_no?: number;
  page_size?: number;
  [key: string]: unknown;
}

export interface MappingPageResult<T = Record<string, unknown>> {
  items: T[];
  total: number;
  page_no: number;
  page_size: number;
  has_next?: boolean;
}

export type MappingItem = Record<string, unknown> & { id?: number };

function mappingCrudApi(path: string) {
  return {
    page(params: MappingPageQuery) {
      return request<ApiResponse<MappingPageResult<MappingItem>>>({ url: `${path}/page`, method: "get", params });
    },
    create(body: Record<string, unknown>) {
      return request<ApiResponse<MappingItem>>({ url: `${path}/create`, method: "post", data: body });
    },
    update(id: number, body: Record<string, unknown>) {
      return request<ApiResponse<MappingItem>>({ url: `${path}/update/${id}`, method: "put", data: body });
    },
    remove(ids: number[]) {
      return request<ApiResponse>({ url: `${path}/delete`, method: "delete", data: ids });
    },
    autoMatch(body: Record<string, unknown> = {}) {
      return request<ApiResponse<Record<string, number>>>({ url: `${path}/auto-match`, method: "post", data: body });
    },
  };
}

export const SystemMappingAPI = {
  org: mappingCrudApi("/masterdata/mapping/org"),
  person: mappingCrudApi("/masterdata/mapping/person"),
  dept: mappingCrudApi("/system-mapping/dept"),
  field: {
    ...mappingCrudApi("/metadata/field-mapping"),
    autoMatch(body: Record<string, unknown> = {}) {
      return request<ApiResponse<Record<string, number>>>({
        url: "/system-mapping/field/auto-match",
        method: "post",
        data: body,
      });
    },
  },
};

export const ManualBindingAPI = {
  unmappedOrg(params: Record<string, unknown> = {}) {
    return request<ApiResponse<MappingItem[]>>({ url: "/system-mapping/unmapped/org", method: "get", params });
  },
  unmappedDept(params: Record<string, unknown> = {}) {
    return request<ApiResponse<MappingItem[]>>({ url: "/system-mapping/unmapped/dept", method: "get", params });
  },
  unmappedPerson(params: Record<string, unknown> = {}) {
    return request<ApiResponse<MappingItem[]>>({ url: "/system-mapping/unmapped/person", method: "get", params });
  },
  orgOptions() {
    return request<ApiResponse<{ value: number; label: string }[]>>({ url: "/system-mapping/options/org", method: "get" });
  },
  deptOptions(orgId?: number) {
    return request<ApiResponse<Record<string, unknown>[]>>({
      url: "/system-mapping/options/dept",
      method: "get",
      params: orgId ? { org_id: orgId } : {},
    });
  },
  personOptions() {
    return request<ApiResponse<{ value: number; label: string }[]>>({ url: "/system-mapping/options/person", method: "get" });
  },
  sourcePersons(params: MappingPageQuery) {
    return request<ApiResponse<MappingPageResult<MappingItem>>>({ url: "/masterdata/source/person/page", method: "get", params });
  },
  sourceTypes() {
    return request<ApiResponse<{ value: string; label: string }[]>>({ url: "/system-mapping/source-types", method: "get" });
  },
  /** 手动任务：同步 CRM 人员架构（来源组织 + 来源部门），无定时执行 */
  syncCrmOrg() {
    return request<ApiResponse<Record<string, number>>>({ url: "/system-mapping/sync/crm-org", method: "post" });
  },
  /** 手动任务：同步 CRM 人员（来源人员），无定时执行 */
  syncCrmPerson() {
    return request<ApiResponse<Record<string, number>>>({ url: "/system-mapping/sync/crm-person", method: "post" });
  },
  bindOrg(body: Record<string, unknown>) {
    return request<ApiResponse>({ url: "/system-mapping/bind/org", method: "post", data: body });
  },
  bindDept(body: Record<string, unknown>) {
    return request<ApiResponse>({ url: "/system-mapping/bind/dept", method: "post", data: body });
  },
  bindPerson(body: Record<string, unknown>) {
    return request<ApiResponse>({ url: "/system-mapping/bind/person", method: "post", data: body });
  },
  bindPersonOrg(body: Record<string, unknown>) {
    return request<ApiResponse>({ url: "/system-mapping/bind/person-org", method: "post", data: body });
  },
  sysDeptBindings(sysDeptId: number) {
    return request<ApiResponse<MappingItem[]>>({
      url: "/system-mapping/sys-dept/bindings",
      method: "get",
      params: { sys_dept_id: sysDeptId },
    });
  },
  sysDeptOptions(params: Record<string, unknown> = {}) {
    return request<ApiResponse<MappingItem[]>>({ url: "/system-mapping/sys-dept/options", method: "get", params });
  },
  bindSysDept(body: Record<string, unknown>) {
    return request<ApiResponse>({ url: "/system-mapping/sys-dept/bind", method: "post", data: body });
  },
  unbindSysDept(body: Record<string, unknown>) {
    return request<ApiResponse>({ url: "/system-mapping/sys-dept/unbind", method: "post", data: body });
  },
};
