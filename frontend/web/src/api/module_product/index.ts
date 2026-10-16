import { request } from "@utils";

export interface ProductLineFieldItem {
  field_code: string;
  field_name: string;
  data_type: string;
  group: string;
  sensitive: boolean;
  excel_code?: string;
  source?: string;
  note?: string;
  status?: string;
  status_label?: string;
  stored_in: string;
}

export interface ProductLineRow {
  id: number;
  period_value: string;
  calc_version: number;
  is_aggregate: number;
  product_line_code?: string | null;
  product_line_name?: string | null;
  sku?: string | null;
  order_count: number;
  intake_untaxed?: number | null;
  ship_untaxed?: number | null;
  net_shipment?: number | null;
  gross_profit?: number | null;
  contribution_margin?: number | null;
  data_quality_flag?: string | null;
  [key: string]: unknown;
}

export interface ProductLineStats {
  period_value?: string;
  calc_version?: number;
  line_count?: number;
  sku_count?: number;
  order_count?: number;
  intake_untaxed_sum?: number | null;
  ship_untaxed_sum?: number | null;
  net_shipment_sum?: number | null;
  settlement_income_sum?: number | null;
  hq_allocation_sum?: number | null;
  top_lines?: {
    product_line: string;
    order_count: number;
    intake_untaxed: number;
    ship_untaxed: number;
    net_shipment: number;
    settlement_income: number;
    hq_allocation: number;
  }[];
}

export interface ProductLinePageResult {
  items: ProductLineRow[];
  columns: ProductLineFieldItem[];
  total: number;
  page_no: number;
  page_size: number;
  has_next: boolean;
  period_value: string | null;
  calc_version: number;
  summary: ProductLineStats;
}

export interface ProductLineQuery {
  period_value?: string;
  calc_version?: number;
  product_line?: string;
  sku?: string;
  salesman?: string;
  order_type?: string;
  platform?: string;
  shop?: string;
  aggregate_level?: "detail" | "line" | "all";
  keyword?: string;
  page_no?: number;
  page_size?: number;
}

export interface ProductLineBuildRunItem {
  id: number;
  period_value: string;
  calc_version: number;
  status: string;
  line_count: number;
  sku_count: number;
  order_count: number;
  intake_untaxed_sum?: number | null;
  net_shipment_sum?: number | null;
  matched_rows: number;
  unmatched_rows: number;
  warnings?: string[] | null;
  error?: string | null;
  finished_at?: string | null;
}

export const ProductLineAPI = {
  fields() {
    return request<ApiResponse<ProductLineFieldItem[]>>({ url: "/product/fields", method: "get" });
  },
  periods() {
    return request<ApiResponse<string[]>>({ url: "/product/periods", method: "get" });
  },
  productLines(periodValue?: string) {
    return request<ApiResponse<string[]>>({
      url: "/product/product-lines",
      method: "get",
      params: { period_value: periodValue },
    });
  },
  stats(periodValue?: string) {
    return request<ApiResponse<ProductLineStats>>({
      url: "/product/stats",
      method: "get",
      params: { period_value: periodValue },
    });
  },
  page(params: ProductLineQuery) {
    return request<ApiResponse<ProductLinePageResult>>({ url: "/product/page", method: "get", params });
  },
  runs(periodValue?: string) {
    return request<ApiResponse<ProductLineBuildRunItem[]>>({
      url: "/product/runs",
      method: "get",
      params: { period_value: periodValue },
    });
  },
  rebuild(periodValue?: string) {
    return request<ApiResponse<Record<string, unknown>>>({
      url: "/product/rebuild",
      method: "post",
      data: { period_value: periodValue },
      timeout: 30 * 60 * 1000,
    });
  },
};
