import { request } from "@utils";

export interface MetricPageQuery {
  page_no?: number;
  page_size?: number;
  [key: string]: unknown;
}

export interface MetricPageResult<T = Record<string, unknown>> {
  items: T[];
  total: number;
  page_no: number;
  page_size: number;
  has_next?: boolean;
}

export interface MetricDefItem {
  id: number;
  code: string;
  name: string;
  category?: string;
  period_type: string;
  status?: number;
  description?: string | null;
}

export interface MetricValueItem {
  id?: number;
  metric_id: number;
  period_type: string;
  period_value: string;
  org_id?: number | null;
  org_code?: string | null;
  org_name?: string | null;
  dept_id?: number | null;
  dept_code?: string | null;
  dept_name?: string | null;
  value: number;
  calc_version: number;
  calc_time?: string | null;
  batch_id?: string | null;
}

export interface MetricCalcResult {
  metric_id: number;
  metric_code: string;
  period_type: string;
  period_value: string;
  calc_version: number;
  partial: boolean;
  backfilled_orgs: string[];
  org_count: number;
  total: number;
  skipped_orgs: string[];
}

export interface MetricMatrixColumn {
  metric_id: number;
  code: string;
  name: string;
  period_type: string;
  description?: string | null;
}

export interface MetricMatrixRow {
  row_key: string;
  period_value: string;
  org_id?: number | null;
  org_code?: string | null;
  org_name?: string | null;
  dept_id?: number | null;
  dept_code?: string | null;
  dept_name?: string | null;
  person_id?: number | null;
  person_code?: string | null;
  person_name?: string | null;
  values: Record<string, number>;
  calc_versions: Record<string, number>;
  calc_times: Record<string, string | null>;
}

export interface MetricMatrixResult {
  columns: MetricMatrixColumn[];
  items: MetricMatrixRow[];
  page_no: number;
  page_size: number;
  total: number;
  has_next: boolean;
}

export interface MetricMatrixQuery {
  metric_ids: string;
  period_type?: string;
  period_value?: string;
  org_id?: number;
  level?: "org" | "dept" | "person" | "all";
  page_no?: number;
  page_size?: number;
}

export interface MetricBatchResult {
  label: string;
  period?: string | null;
  metric_count: number;
  layer_count: number;
  success: number;
  failed: string[];
  problems: string[];
  elapsed_seconds: number;
  totals: Record<string, number>;
  results: Record<string, unknown>[];
}

export const MetricAPI = {
  defPage(params: MetricPageQuery) {
    return request<ApiResponse<MetricPageResult<MetricDefItem>>>({
      url: "/metric/def/page",
      method: "get",
      params,
    });
  },
  valuePage(params: MetricPageQuery) {
    return request<ApiResponse<MetricPageResult<MetricValueItem>>>({
      url: "/metric/value/page",
      method: "get",
      params,
    });
  },
  /** 指标表单：一次查询多个指标，按组织/核算维度并排返回。 */
  matrix(params: MetricMatrixQuery) {
    return request<ApiResponse<MetricMatrixResult>>({
      url: "/metric/value/matrix",
      method: "get",
      params,
    });
  },
  runCalc(metricId: number, body: { period_value?: string; org_codes?: string[] } = {}) {
    // 历史期间首次重算会先按期间回补取数（每个组织一次 ERP 同步），耗时可达数分钟，
    // 因此单独放宽超时（默认全局 15s）。
    return request<ApiResponse<MetricCalcResult>>({
      url: `/metric/def/run/${metricId}`,
      method: "post",
      data: body,
      timeout: 15 * 60 * 1000,
    });
  },
  /** 批量重算：metric_ids 为空表示重算全部启用指标（按依赖分层执行）。 */
  runBatch(body: { metric_ids?: number[]; codes?: string[]; period_value?: string } = {}) {
    return request<ApiResponse<MetricBatchResult>>({
      url: "/metric/def/run-batch",
      method: "post",
      data: body,
      timeout: 30 * 60 * 1000,
    });
  },
};
