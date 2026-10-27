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
  untaxed_amount?: number | null;
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
    untaxed_amount_sum: number;
    tax_rate: number;
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
  biz_type?: string;
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
  biz_type?: string;
  request_id?: string;
  app_id?: string;
  source?: string;
  status?: string;
  page_no?: number;
  page_size?: number;
}

export interface RetailAfterSaleItem {
  id: number;
  asi_id?: string | null;
  sku_id?: string | null;
  i_id?: string | null;
  name?: string | null;
  properties_value?: string | null;
  qty?: number | null;
  r_qty?: number | null;
  defective_qty?: number | null;
  price?: number | null;
  amount?: number | null;
  shop_amount?: number | null;
  buyer_paid_amount?: number | null;
  seller_income_amount?: number | null;
  type?: string | null;
  is_gift: boolean;
  outer_oi_id?: string | null;
}

export interface RetailAfterSaleRow {
  id: number;
  source: string;
  period_value: string;
  as_id?: string | null;
  outer_as_id?: string | null;
  o_id?: string | null;
  so_id?: string | null;
  shop_id: number;
  shop_name?: string | null;
  shop_site?: string | null;
  type?: string | null;
  status?: string | null;
  shop_status?: string | null;
  good_status?: string | null;
  order_status?: string | null;
  as_date?: string | null;
  registered_time?: string | null;
  modified_time?: string | null;
  confirm_date?: string | null;
  refund?: number | null;
  freight?: number | null;
  payment?: number | null;
  free_amount?: number | null;
  actual_refund?: number | null;
  untaxed_actual_refund?: number | null;
  buyer_apply_refund?: number | null;
  receive_refund?: number | null;
  seller_real_refund?: number | null;
  buyer_paid_amount?: number | null;
  seller_income_amount?: number | null;
  l_id?: string | null;
  logistics_company?: string | null;
  warehouse?: string | null;
  remark?: string | null;
  item_count: number;
  last_batch_id?: string | null;
  created_time?: string | null;
  updated_time?: string | null;
}

export interface RetailAfterSalePageResult extends RetailPageResult<RetailAfterSaleRow> {
  summary: {
    after_sale_count: number;
    actual_refund_sum: number;
    untaxed_actual_refund_sum: number;
    tax_rate: number;
    refund_sum: number;
    item_count_sum: number;
  };
}

export interface RetailAfterSaleDetail {
  after_sale: RetailAfterSaleRow & {
    platform_promotion?: number | null;
    platform_free_amount?: number | null;
    government_free_amount?: number | null;
    currency?: string | null;
    result?: string | null;
    node?: string | null;
    wms_co_id?: string | null;
  };
  items: RetailAfterSaleItem[];
}

export interface RetailAfterSaleQuery {
  period_value?: string;
  shop_id?: number;
  shop_name?: string;
  as_id?: string;
  so_id?: string;
  status?: string;
  type?: string;
  keyword?: string;
  page_no?: number;
  page_size?: number;
}

export interface RetailAnalysisRow {
  period_value: string;
  shop_id: number;
  shop_name?: string | null;
  order_count: number;
  shipped_order_count: number;
  cancelled_order_count: number;
  intake_untaxed: number;
  shipment_untaxed: number;
  cancelled_untaxed: number;
  refund_untaxed: number;
  return_untaxed: number;
  net_shipment_untaxed: number;
  settlement_income_untaxed: number;
  hq_allocation_untaxed: number;
  return_rate: number;
}

export interface RetailAnalysisResult {
  tax_rate: number;
  settlement_rate: number;
  shipped_statuses: string[];
  cancelled_statuses: string[];
  items: RetailAnalysisRow[];
  total: {
    shop_count: number;
    order_count: number;
    shipped_order_count: number;
    cancelled_order_count: number;
    intake_untaxed: number;
    shipment_untaxed: number;
    cancelled_untaxed: number;
    refund_untaxed: number;
    return_untaxed: number;
    net_shipment_untaxed: number;
    settlement_income_untaxed: number;
    hq_allocation_untaxed: number;
    return_rate: number;
  };
}

export const RetailAPI = {
  syncShops() {
    return request<ApiResponse<Record<string, unknown>>>({
      url: "/retail/shops/sync",
      method: "post",
      timeout: 60 * 1000,
    });
  },
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
  afterSales(params: RetailAfterSaleQuery) {
    return request<ApiResponse<RetailAfterSalePageResult>>({
      url: "/retail/aftersales/page",
      method: "get",
      params,
    });
  },
  afterSaleDetail(id: number) {
    return request<ApiResponse<RetailAfterSaleDetail>>({
      url: `/retail/aftersales/${id}`,
      method: "get",
    });
  },
  pullAfterSales(params: { period_value?: string; days?: number }) {
    return request<ApiResponse<Record<string, unknown>>>({
      url: "/retail/aftersales/pull",
      method: "post",
      params,
      timeout: 120 * 1000,
    });
  },
  analysisSummary(params: { period_value?: string; shop_id?: number }) {
    return request<ApiResponse<RetailAnalysisResult>>({
      url: "/retail/analysis/summary",
      method: "get",
      params,
    });
  },
};
