import { request } from "@utils";

export interface OrderFieldItem {
  field_code: string;
  field_name: string;
  data_type: string;
  group: string;
  sensitive: boolean;
  excel_code?: string;
  stored_in: string;
}

export interface OrderRow {
  id: number;
  order_number: string;
  period_value: string;
  calc_version: number;
  data_quality_flag?: string | null;
  [key: string]: unknown;
}

export interface OrderPageResult {
  items: OrderRow[];
  columns: OrderFieldItem[];
  total: number;
  page_no: number;
  page_size: number;
  has_next: boolean;
  period_value: string | null;
  calc_version: number;
  summary: {
    order_count?: number;
    cost_missing_count?: number;
    mo_unlinked_count?: number;
    intake_untaxed_sum?: number;
  };
}

export interface OrderQuery {
  period_value?: string;
  calc_version?: number;
  order_number?: string;
  trade_type?: string;
  order_type?: string;
  customer_name?: string;
  salesman_code?: string;
  data_quality_flag?: string;
  keyword?: string;
  page_no?: number;
  page_size?: number;
}

export interface OrderBuildRunItem {
  id: number;
  period_value: string;
  calc_version: number;
  status: string;
  order_count: number;
  mo_linked_count: number;
  cost_missing_count: number;
  error?: string | null;
  finished_at?: string | null;
}

export const OrderAPI = {
  fields() {
    return request<ApiResponse<OrderFieldItem[]>>({ url: "/order/fields", method: "get" });
  },
  periods() {
    return request<ApiResponse<string[]>>({ url: "/order/periods", method: "get" });
  },
  page(params: OrderQuery) {
    return request<ApiResponse<OrderPageResult>>({ url: "/order/page", method: "get", params });
  },
  detail(orderNumber: string) {
    return request<ApiResponse<{ item: OrderRow; columns: OrderFieldItem[] }>>({
      url: `/order/detail/${encodeURIComponent(orderNumber)}`,
      method: "get",
    });
  },
  runs(periodValue?: string) {
    return request<ApiResponse<OrderBuildRunItem[]>>({
      url: "/order/runs",
      method: "get",
      params: { period_value: periodValue },
    });
  },
  rebuild(periodValue?: string) {
    return request<ApiResponse<Record<string, unknown>>>({
      url: "/order/rebuild",
      method: "post",
      data: { period_value: periodValue },
      timeout: 30 * 60 * 1000,
    });
  },
};
