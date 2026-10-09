import { request } from "@utils";

export interface OpenApiPageQuery {
  page_no?: number;
  page_size?: number;
  [key: string]: unknown;
}

export interface OpenApiPageResult<T = Record<string, unknown>> {
  items: T[];
  total: number;
  page_no: number;
  page_size: number;
  has_next?: boolean;
}

export interface OpenClientItem {
  id: number;
  app_id: string;
  name: string;
  status: number;
  ip_whitelist?: string | null;
  token_ttl_seconds: number;
  rate_limit: number;
  allow_dept_detail: boolean;
  allow_person_detail: boolean;
  allow_run_calc: boolean;
  org_scope?: string[] | null;
  expire_time?: string | null;
  contact?: string | null;
  description?: string | null;
  created_time?: string | null;
}

export interface OpenClientSecretResult extends OpenClientItem {
  /** 仅在创建/重置密钥时返回一次 */
  app_secret: string;
}

export interface OpenApiLogItem {
  id: number;
  client_id?: number | null;
  app_id?: string | null;
  path: string;
  method: string;
  params?: Record<string, unknown> | null;
  response_code: number;
  http_status: number;
  cost_ms: number;
  client_ip?: string | null;
  description?: string | null;
  created_time?: string | null;
}

export interface OptionItem {
  value: string;
  label: string;
}

export const OpenApiClientAPI = {
  page(params: OpenApiPageQuery) {
    return request<ApiResponse<OpenApiPageResult<OpenClientItem>>>({
      url: "/openapi/client/page",
      method: "get",
      params,
    });
  },
  create(body: Record<string, unknown>) {
    return request<ApiResponse<OpenClientSecretResult>>({
      url: "/openapi/client/create",
      method: "post",
      data: body,
    });
  },
  update(id: number, body: Record<string, unknown>) {
    return request<ApiResponse<OpenClientItem>>({
      url: `/openapi/client/update/${id}`,
      method: "put",
      data: body,
    });
  },
  remove(ids: number[]) {
    return request<ApiResponse>({ url: "/openapi/client/delete", method: "delete", data: ids });
  },
  resetSecret(id: number) {
    return request<ApiResponse<OpenClientSecretResult>>({
      url: `/openapi/client/reset-secret/${id}`,
      method: "post",
    });
  },
  orgOptions() {
    return request<ApiResponse<OptionItem[]>>({ url: "/openapi/client/org-options", method: "get" });
  },
};

export const OpenApiLogAPI = {
  page(params: OpenApiPageQuery) {
    return request<ApiResponse<OpenApiPageResult<OpenApiLogItem>>>({
      url: "/openapi/log/page",
      method: "get",
      params,
    });
  },
};
