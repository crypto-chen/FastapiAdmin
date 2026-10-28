import { request } from "@utils";

export interface PlatformFieldItem {
  field_code: string;
  field_name: string;
  data_type: string;
  group: string;
  sensitive: boolean;
  source?: string;
  note?: string;
  status?: string;
  status_label?: string;
  stored_in: string;
}

export interface PlatformRow {
  id: string;
  is_aggregate: number;
  aggregate_level: string;
  period_value: string;
  "PLT-00": string;
  "PLT-01": string;
  "PLT-02": string;
  "PLT-03": number | string;
  "PLT-04": number;
  "PLT-05": number;
  "PLT-06": number;
  "PLT-08": number;
  "PLT-09": number;
  "PLT-10": number;
  "PLT-11": number;
  "PLT-12": number;
  "PLT-13": number;
  "PLT-23": number;
  "PLT-37": number;
  "PLT-38": number;
  [key: string]: unknown;
}

export interface PlatformStats {
  period_value?: string | null;
  shop_count?: number;
  platform_count?: number;
  order_count?: number;
  shipped_order_count?: number;
  cancelled_order_count?: number;
  intake_untaxed_sum?: number | null;
  shipment_untaxed_sum?: number | null;
  return_untaxed_sum?: number | null;
  net_shipment_sum?: number | null;
  settlement_income_sum?: number | null;
  hq_allocation_sum?: number | null;
  avg_order_value?: number | null;
  return_rate?: number | null;
  top_platforms?: {
    platform: string;
    order_count: number;
    intake_untaxed: number;
    shipment_untaxed: number;
    net_shipment: number;
    settlement_income: number;
    hq_allocation: number;
    return_rate: number;
  }[];
}

export interface PlatformPageResult {
  items: PlatformRow[];
  columns: PlatformFieldItem[];
  total: number;
  page_no: number;
  page_size: number;
  has_next: boolean;
  period_value: string | null;
  tax_rate: number;
  summary: PlatformStats;
}

export interface PlatformQuery {
  period_value?: string;
  platform?: string;
  shop_id?: number;
  keyword?: string;
  aggregate_level?: "detail" | "platform" | "all";
  page_no?: number;
  page_size?: number;
}

export interface PlatformMetricConfig {
  id: number;
  field_code: string;
  field_name: string;
  group: string;
  data_type: string;
  unit?: string | null;
  sensitive: boolean;
  expression: string;
  readiness: string;
  status: string;
  status_label: string;
  enabled: boolean;
  note?: string | null;
  sort: number;
  status_num: number;
}

export interface PlatformMetricConfigList {
  items: PlatformMetricConfig[];
  base_variables: Record<string, string>;
  functions: string[];
}

export interface PlatformMetricPayload {
  code: string;
  name: string;
  group: string;
  data_type: string;
  unit?: string | null;
  sensitive: boolean;
  expression: string;
  readiness: string;
  note?: string | null;
  sort: number;
  status: number;
}

export const PlatformAnalysisAPI = {
  fields() {
    return request<ApiResponse<PlatformFieldItem[]>>({ url: "/platform/fields", method: "get" });
  },
  periods() {
    return request<ApiResponse<string[]>>({ url: "/platform/periods", method: "get" });
  },
  platforms() {
    return request<ApiResponse<string[]>>({ url: "/platform/platforms", method: "get" });
  },
  page(params: PlatformQuery) {
    return request<ApiResponse<PlatformPageResult>>({ url: "/platform/page", method: "get", params });
  },
  stats(periodValue?: string) {
    return request<ApiResponse<PlatformStats>>({
      url: "/platform/stats",
      method: "get",
      params: { period_value: periodValue },
    });
  },
  metricConfigs() {
    return request<ApiResponse<PlatformMetricConfigList>>({ url: "/platform/metrics", method: "get" });
  },
  createMetric(data: PlatformMetricPayload) {
    return request<ApiResponse<PlatformMetricConfig>>({ url: "/platform/metrics", method: "post", data });
  },
  updateMetric(id: number, data: PlatformMetricPayload) {
    return request<ApiResponse<PlatformMetricConfig>>({
      url: `/platform/metrics/${id}`,
      method: "put",
      data,
    });
  },
  deleteMetric(id: number) {
    return request<ApiResponse<null>>({ url: `/platform/metrics/${id}`, method: "delete" });
  },
  resetMetrics() {
    return request<ApiResponse<Record<string, number>>>({
      url: "/platform/metrics/reset",
      method: "post",
    });
  },
};
