import { request } from "@utils";

export interface CustomerFieldItem {
  field_code: string;
  field_name: string;
  data_type: string;
  group: string;
  sensitive: boolean;
  excel_code?: string;
  source?: string;
  note?: string;
  stored_in: string;
}

export interface CustomerRow {
  id: number;
  period_value: string;
  calc_version: number;
  is_aggregate: boolean;
  customer_code?: string | null;
  customer_name?: string | null;
  salesman_code?: string | null;
  order_count: number;
  data_quality_flag?: string | null;
  [key: string]: unknown;
}

export interface CustomerPageResult {
  items: CustomerRow[];
  columns: CustomerFieldItem[];
  total: number;
  page_no: number;
  page_size: number;
  has_next: boolean;
  period_value: string | null;
  calc_version: number;
  summary: {
    customer_count?: number;
    order_count?: number;
    intake_untaxed_sum?: number;
    net_shipment_sum?: number;
  };
}

export interface CustomerQuery {
  period_value?: string;
  calc_version?: number;
  customer_code?: string;
  customer_name?: string;
  salesman_code?: string;
  order_type?: string;
  product_line?: string;
  trade_type?: string;
  include_aggregate?: boolean;
  keyword?: string;
  page_no?: number;
  page_size?: number;
}

export interface CustomerBuildRunItem {
  id: number;
  period_value: string;
  calc_version: number;
  status: string;
  customer_count: number;
  order_count: number;
  intake_untaxed_sum?: number | null;
  net_shipment_sum?: number | null;
  master_customer_count: number;
  warnings?: string[] | null;
  error?: string | null;
  finished_at?: string | null;
}

export const CustomerAPI = {
  fields() {
    return request<ApiResponse<CustomerFieldItem[]>>({ url: "/customer/fields", method: "get" });
  },
  periods() {
    return request<ApiResponse<string[]>>({ url: "/customer/periods", method: "get" });
  },
  page(params: CustomerQuery) {
    return request<ApiResponse<CustomerPageResult>>({ url: "/customer/page", method: "get", params });
  },
  detail(customerCode: string) {
    return request<ApiResponse<{ item: CustomerRow; columns: CustomerFieldItem[] }>>({
      url: `/customer/detail/${encodeURIComponent(customerCode)}`,
      method: "get",
    });
  },
  runs(periodValue?: string) {
    return request<ApiResponse<CustomerBuildRunItem[]>>({
      url: "/customer/runs",
      method: "get",
      params: { period_value: periodValue },
    });
  },
  rebuild(periodValue?: string) {
    return request<ApiResponse<Record<string, unknown>>>({
      url: "/customer/rebuild",
      method: "post",
      data: { period_value: periodValue },
      timeout: 30 * 60 * 1000,
    });
  },
};
