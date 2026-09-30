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
};
