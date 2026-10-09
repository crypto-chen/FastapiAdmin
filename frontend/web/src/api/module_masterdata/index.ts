import { request } from "@utils";

/** 内部标准人员（master_person） */
export interface MasterPersonItem {
  id?: number;
  code: string;
  name: string;
  org_id?: number | null;
  org_name?: string | null;
  mobile?: string | null;
  email?: string | null;
  status: number;
  description?: string | null;
  created_time?: string;
  updated_time?: string;
}

export interface MasterPersonQuery {
  page_no?: number;
  page_size?: number;
  name?: string;
  code?: string;
  org_id?: number;
  status?: number;
  [key: string]: unknown;
}

export interface MasterPersonPageResult {
  items: MasterPersonItem[];
  total: number;
  page_no: number;
  page_size: number;
  has_next?: boolean;
}

export const MasterDataAPI = {
  person: {
    /** 分页查询内部标准人员 */
    page(params: MasterPersonQuery) {
      return request<ApiResponse<MasterPersonPageResult>>({
        url: "/masterdata/person/page",
        method: "get",
        params,
      });
    },
    /** 内部标准人员详情 */
    detail(id: number) {
      return request<ApiResponse<MasterPersonItem>>({
        url: `/masterdata/person/detail/${id}`,
        method: "get",
      });
    },
    /** 新增内部标准人员 */
    create(body: Partial<MasterPersonItem>) {
      return request<ApiResponse<MasterPersonItem>>({
        url: "/masterdata/person/create",
        method: "post",
        data: body,
      });
    },
    /** 修改内部标准人员 */
    update(id: number, body: Partial<MasterPersonItem>) {
      return request<ApiResponse<MasterPersonItem>>({
        url: `/masterdata/person/update/${id}`,
        method: "put",
        data: body,
      });
    },
    /** 删除内部标准人员（批量） */
    remove(ids: number[]) {
      return request<ApiResponse>({
        url: "/masterdata/person/delete",
        method: "delete",
        data: ids,
      });
    },
  },
};
