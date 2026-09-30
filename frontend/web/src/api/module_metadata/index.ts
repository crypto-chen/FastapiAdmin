import { request } from "@utils";

export interface MetaPageQuery {
  page_no?: number;
  page_size?: number;
  [key: string]: unknown;
}

export interface MetaPageResult<T = Record<string, unknown>> {
  items: T[];
  total: number;
  page_no: number;
  page_size: number;
  has_next?: boolean;
}

export type MetaItem = Record<string, unknown> & {
  id?: number;
  name?: string;
  code?: string;
};

function crudApi(path: string) {
  return {
    page(params: MetaPageQuery) {
      return request<ApiResponse<MetaPageResult<MetaItem>>>({ url: `${path}/page`, method: "get", params });
    },
    detail(id: number) {
      return request<ApiResponse<MetaItem>>({ url: `${path}/detail/${id}`, method: "get" });
    },
    create(body: Record<string, unknown>) {
      return request<ApiResponse<MetaItem>>({ url: `${path}/create`, method: "post", data: body });
    },
    update(id: number, body: Record<string, unknown>) {
      return request<ApiResponse<MetaItem>>({ url: `${path}/update/${id}`, method: "put", data: body });
    },
    remove(ids: number[]) {
      return request<ApiResponse>({ url: `${path}/delete`, method: "delete", data: ids });
    },
  };
}

export const MetadataAPI = {
  sourceSystem: crudApi("/metadata/source-system"),
  sourceObject: crudApi("/metadata/source-object"),
  sourceField: crudApi("/metadata/source-field"),
  standardEntity: crudApi("/metadata/standard-entity"),
  standardField: crudApi("/metadata/standard-field"),
  fieldMapping: crudApi("/metadata/field-mapping"),
  metricDef: crudApi("/metric/def"),
  syncJob: {
    ...crudApi("/metadata/sync-job"),
    runNow(id: number) {
      return request<ApiResponse>({ url: `/metadata/sync-job/run/${id}`, method: "post" });
    },
    runPage(params: MetaPageQuery) {
      return request<ApiResponse<MetaPageResult<MetaItem>>>({
        url: "/metadata/sync-job/run/page",
        method: "get",
        params,
      });
    },
    runDetail(id: number) {
      return request<ApiResponse<MetaItem>>({ url: `/metadata/sync-job/run/detail/${id}`, method: "get" });
    },
  },
};
