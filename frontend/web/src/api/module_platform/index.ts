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
};
