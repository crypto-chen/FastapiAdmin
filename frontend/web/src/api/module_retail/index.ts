import { request } from "@utils";

export interface RetailPageResult<T> {
  items: T[];
  total: number;
  page_no: number;
  page_size: number;
  has_next?: boolean;
}

export interface RetailOrderItem {
  id: number;
  oi_id?: string | null;
  sku_id?: string | null;
  i_id?: string | null;
  name?: string | null;
  properties_value?: string | null;
  qty?: number | null;
  price?: number | null;
  base_price?: number | null;
  amount?: number | null;
  buyer_paid_amount?: number | null;
  seller_income_amount?: number | null;
  item_pay_amount?: number | null;
  item_status?: string | null;
  refund_status?: string | null;
  is_gift: boolean;
  src_combine_sku_id?: string | null;
}

export interface RetailOrderRow {
  id: number;
  source: string;
  period_value: string;
  shop_id: number;
  shop_name?: string | null;
  so_id?: string | null;
  o_id?: string | null;
  co_id?: string | null;
  status?: string | null;
  order_from?: string | null;
  buyer_nick?: string | null;
  order_date?: string | null;
  pay_date?: string | null;
  modified_time?: string | null;
  paid_amount?: number | null;
  pay_amount?: number | null;
  buyer_paid_amount?: number | null;
  seller_income_amount?: number | null;
  freight?: number | null;
  free_amount?: number | null;
  receiver_state?: string | null;
  receiver_city?: string | null;
  receiver_district?: string | null;
  receiver_town?: string | null;
  remark?: string | null;
  item_count: number;
  last_batch_id?: string | null;
  created_time?: string | null;
  updated_time?: string | null;
}

export interface RetailOrderPageResult extends RetailPageResult<RetailOrderRow> {
  summary: {
    order_count: number;
    buyer_paid_amount_sum: number;
    item_count_sum: number;
  };
}

export interface RetailOrderDetail {
  order: RetailOrderRow;
  items: RetailOrderItem[];
}

export interface RetailBatchRow {
  id: number;
  app_id: string;
  request_id?: string | null;
  source: string;
  status: string;
  received_count: number;
  created_count: number;
  updated_count: number;
  unchanged_count: number;
  stale_count: number;
  failed_count: number;
  item_count: number;
  periods: string[];
  has_next: boolean;
  page_index?: number | null;
  page_size?: number | null;
  created_time?: string | null;
}

export interface RetailBatchDetail extends RetailBatchRow {
  params?: Record<string, unknown>;
  errors?: Array<Record<string, unknown>>;
  result?: Record<string, unknown>;
}

export interface RetailOrderQuery {
  period_value?: string;
  shop_id?: number;
  shop_name?: string;
  so_id?: string;
  status?: string;
  source?: string;
  keyword?: string;
  page_no?: number;
  page_size?: number;
}

export interface RetailBatchQuery {
  request_id?: string;
  app_id?: string;
  source?: string;
  status?: string;
  page_no?: number;
  page_size?: number;
}

export const RetailAPI = {
  periods() {
    return request<ApiResponse<string[]>>({ url: "/retail/periods", method: "get" });
  },
  orders(params: RetailOrderQuery) {
    return request<ApiResponse<RetailOrderPageResult>>({
      url: "/retail/orders/page",
      method: "get",
      params,
    });
  },
  orderDetail(id: number) {
    return request<ApiResponse<RetailOrderDetail>>({
      url: `/retail/orders/${id}`,
      method: "get",
    });
  },
  batches(params: RetailBatchQuery) {
    return request<ApiResponse<RetailPageResult<RetailBatchRow>>>({
      url: "/retail/batches/page",
      method: "get",
      params,
    });
  },
  batchDetail(id: number) {
    return request<ApiResponse<RetailBatchDetail>>({
      url: `/retail/batches/${id}`,
      method: "get",
    });
  },
};
