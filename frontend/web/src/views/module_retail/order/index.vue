<template>
  <div class="retail-sync-page">
    <ElCard shadow="never">
      <div class="page-head">
        <span class="page-title">零售订单同步</span>
        <ElButton
          v-hasPerm="'module_retail:shop:sync'"
          size="small"
          type="primary"
          plain
          :loading="shopSyncing"
          @click="handleSyncShops"
        >
          同步店铺
        </ElButton>
      </div>
      <ElTabs v-model="activeTab" @tab-change="handleTabChange">
        <ElTabPane label="零售订单" name="orders">
          <div class="toolbar">
            <ElSelect v-model="orderSearch.period_value" placeholder="期间" clearable style="width: 120px">
              <ElOption v-for="item in periods" :key="item" :label="item" :value="item" />
            </ElSelect>
            <ElInputNumber
              v-model="orderSearch.shop_id"
              :min="0"
              :controls="false"
              placeholder="店铺ID"
              style="width: 120px"
            />
            <ElInput
              v-model="orderSearch.shop_name"
              placeholder="店铺名称"
              clearable
              style="width: 150px"
              @keyup.enter="queryOrders"
            />
            <ElInput
              v-model="orderSearch.so_id"
              placeholder="线上/内部单号"
              clearable
              style="width: 170px"
              @keyup.enter="queryOrders"
            />
            <ElInput
              v-model="orderSearch.status"
              placeholder="订单状态"
              clearable
              style="width: 130px"
              @keyup.enter="queryOrders"
            />
            <ElInput
              v-model="orderSearch.source"
              placeholder="来源"
              clearable
              style="width: 110px"
              @keyup.enter="queryOrders"
            />
            <ElInput
              v-model="orderSearch.keyword"
              placeholder="单号/买家/备注"
              clearable
              style="width: 170px"
              @keyup.enter="queryOrders"
            />
            <ElButton type="primary" :loading="orderLoading" @click="queryOrders">查询</ElButton>
            <ElButton @click="resetOrderSearch">重置</ElButton>
          </div>

          <div class="summary">
            <span>订单 {{ orderPage.summary.order_count }} 张</span>
            <span>买家实付合计（含税） {{ formatMoney(orderPage.summary.buyer_paid_amount_sum) }}</span>
            <span class="summary-tax">
              接单未税（÷{{ orderPage.summary.tax_rate }}%）{{ formatMoney(orderPage.summary.untaxed_amount_sum) }}
            </span>
            <span>明细行合计 {{ orderPage.summary.item_count_sum }}</span>
            <span class="summary-extra">点「明细」查看 SKU 与金额</span>
          </div>

          <ElTable v-loading="orderLoading" :data="orders" border stripe height="calc(100vh - 360px)">
            <ElTableColumn prop="period_value" label="期间" width="90" fixed />
            <ElTableColumn prop="source" label="来源" width="90" />
            <ElTableColumn label="店铺" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.shop_name || "-" }}<span class="muted"> / {{ row.shop_id }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="so_id" label="线上单号" min-width="180" show-overflow-tooltip />
            <ElTableColumn prop="o_id" label="内部单号" width="110" show-overflow-tooltip />
            <ElTableColumn label="状态" width="110" align="center">
              <template #default="{ row }">
                <ElTag :type="orderStatusType(row.status)" size="small">{{ row.status || "-" }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="buyer_nick" label="买家" width="110" show-overflow-tooltip>
              <template #default="{ row }">{{ row.buyer_nick || "-" }}</template>
            </ElTableColumn>
            <ElTableColumn label="买家实付" width="110" align="right">
              <template #default="{ row }">{{ formatMoney(row.buyer_paid_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn label="接单未税" width="110" align="right">
              <template #default="{ row }">{{ formatMoney(row.untaxed_amount) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="item_count" label="明细" width="70" align="center" />
            <ElTableColumn label="上游修改" width="165">
              <template #default="{ row }">{{ formatTime(row.modified_time) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="last_batch_id" label="最近批次" min-width="190" show-overflow-tooltip />
            <ElTableColumn label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <ElButton link type="primary" @click="openOrder(row as RetailOrderRow)">明细</ElButton>
              </template>
            </ElTableColumn>
          </ElTable>

          <div class="pager">
            <ElPagination
              v-model:current-page="orderPage.page_no"
              v-model:page-size="orderPage.page_size"
              :total="orderPage.total"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="loadOrders"
              @size-change="queryOrders"
            />
          </div>
        </ElTabPane>

        <ElTabPane label="推送批次" name="batches">
          <div class="toolbar">
            <ElInput
              v-model="batchSearch.request_id"
              placeholder="请求ID"
              clearable
              style="width: 200px"
              @keyup.enter="queryBatches"
            />
            <ElInput
              v-model="batchSearch.source"
              placeholder="来源"
              clearable
              style="width: 120px"
              @keyup.enter="queryBatches"
            />
            <ElSelect v-model="batchSearch.status" placeholder="状态" clearable style="width: 130px">
              <ElOption label="成功" value="success" />
              <ElOption label="部分成功" value="partial" />
              <ElOption label="失败" value="failed" />
              <ElOption label="处理中" value="running" />
            </ElSelect>
            <ElButton type="primary" :loading="batchLoading" @click="queryBatches">查询</ElButton>
            <ElButton @click="resetBatchSearch">重置</ElButton>
          </div>

          <ElTable v-loading="batchLoading" :data="batches" border stripe height="calc(100vh - 300px)">
            <ElTableColumn label="推送时间" width="165">
              <template #default="{ row }">{{ formatTime(row.created_time) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="request_id" label="请求ID" min-width="190" show-overflow-tooltip />
            <ElTableColumn prop="source" label="来源" width="90" />
            <ElTableColumn label="类型" width="80" align="center">
              <template #default="{ row }">{{ row.biz_type === "after_sale" ? "售后" : "订单" }}</template>
            </ElTableColumn>
            <ElTableColumn label="状态" width="100" align="center">
              <template #default="{ row }">
                <ElTag :type="batchStatusType(row.status)" size="small">{{ batchStatusText(row.status) }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="received_count" label="收到" width="70" align="center" />
            <ElTableColumn prop="created_count" label="新增" width="70" align="center" />
            <ElTableColumn prop="updated_count" label="更新" width="70" align="center" />
            <ElTableColumn prop="stale_count" label="跳过" width="70" align="center" />
            <ElTableColumn prop="failed_count" label="失败" width="70" align="center" />
            <ElTableColumn prop="item_count" label="明细" width="70" align="center" />
            <ElTableColumn label="期间" width="110">
              <template #default="{ row }">{{ row.periods?.join("、") || "-" }}</template>
            </ElTableColumn>
            <ElTableColumn label="下一页" width="80" align="center">
              <template #default="{ row }">{{ row.has_next ? "是" : "否" }}</template>
            </ElTableColumn>
            <ElTableColumn label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <ElButton link type="primary" @click="openBatch(row as RetailBatchRow)">详情</ElButton>
              </template>
            </ElTableColumn>
          </ElTable>

          <div class="pager">
            <ElPagination
              v-model:current-page="batchPage.page_no"
              v-model:page-size="batchPage.page_size"
              :total="batchPage.total"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="loadBatches"
              @size-change="queryBatches"
            />
          </div>
        </ElTabPane>
        <ElTabPane label="退款售后" name="aftersales">
          <div class="toolbar">
            <ElSelect v-model="afterSaleSearch.period_value" placeholder="期间" clearable style="width: 120px">
              <ElOption v-for="item in periods" :key="item" :label="item" :value="item" />
            </ElSelect>
            <ElInputNumber
              v-model="afterSaleSearch.shop_id"
              :min="0"
              :controls="false"
              placeholder="店铺ID"
              style="width: 120px"
            />
            <ElInput
              v-model="afterSaleSearch.shop_name"
              placeholder="店铺名称"
              clearable
              style="width: 150px"
              @keyup.enter="queryAfterSales"
            />
            <ElInput
              v-model="afterSaleSearch.as_id"
              placeholder="售后单号"
              clearable
              style="width: 170px"
              @keyup.enter="queryAfterSales"
            />
            <ElInput
              v-model="afterSaleSearch.so_id"
              placeholder="订单号"
              clearable
              style="width: 170px"
              @keyup.enter="queryAfterSales"
            />
            <ElSelect v-model="afterSaleSearch.type" placeholder="售后类型" clearable style="width: 130px">
              <ElOption label="退货退款" value="退货退款" />
              <ElOption label="仅退款" value="仅退款" />
              <ElOption label="换货" value="换货" />
            </ElSelect>
            <ElInput
              v-model="afterSaleSearch.keyword"
              placeholder="售后/订单/店铺/备注"
              clearable
              style="width: 190px"
              @keyup.enter="queryAfterSales"
            />
            <ElButton type="primary" :loading="afterSaleLoading" @click="queryAfterSales">查询</ElButton>
            <ElButton @click="resetAfterSaleSearch">重置</ElButton>
            <ElButton
              v-hasPerm="'module_retail:shop:sync'"
              type="success"
              plain
              :loading="afterSaleSyncing"
              @click="handlePullAfterSales"
            >
              同步聚水潭售后
            </ElButton>
          </div>

          <div class="summary">
            <span>售后单 {{ afterSalePage.summary.after_sale_count }} 张</span>
            <span>实退合计（含税） {{ formatMoney(afterSalePage.summary.actual_refund_sum) }}</span>
            <span class="summary-tax">
              实退未税（÷{{ afterSalePage.summary.tax_rate }}%）
              {{ formatMoney(afterSalePage.summary.untaxed_actual_refund_sum) }}
            </span>
            <span>应退合计 {{ formatMoney(afterSalePage.summary.refund_sum) }}</span>
            <span>明细行合计 {{ afterSalePage.summary.item_count_sum }}</span>
            <span class="summary-extra">淘系走奇门推送，非淘系由聚水潭定时同步</span>
          </div>

          <ElTable v-loading="afterSaleLoading" :data="afterSales" border stripe height="calc(100vh - 360px)">
            <ElTableColumn prop="period_value" label="期间" width="90" fixed />
            <ElTableColumn prop="source" label="来源" width="90" />
            <ElTableColumn label="店铺" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.shop_name || "-" }}<span class="muted"> / {{ row.shop_id }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn label="售后单号" min-width="170" show-overflow-tooltip>
              <template #default="{ row }">{{ row.as_id || row.outer_as_id || "-" }}</template>
            </ElTableColumn>
            <ElTableColumn prop="so_id" label="订单号" min-width="180" show-overflow-tooltip />
            <ElTableColumn prop="type" label="类型" width="100" />
            <ElTableColumn label="状态" width="110" align="center">
              <template #default="{ row }">
                <ElTag :type="afterSaleStatusType(row.status)" size="small">{{ row.status || "-" }}</ElTag>
              </template>
            </ElTableColumn>
            <ElTableColumn label="申请时间" width="165">
              <template #default="{ row }">{{ formatTime(row.as_date) }}</template>
            </ElTableColumn>
            <ElTableColumn label="应退" width="100" align="right">
              <template #default="{ row }">{{ formatMoney(row.refund) }}</template>
            </ElTableColumn>
            <ElTableColumn label="实退" width="100" align="right">
              <template #default="{ row }">{{ formatMoney(row.actual_refund) }}</template>
            </ElTableColumn>
            <ElTableColumn label="实退未税" width="100" align="right">
              <template #default="{ row }">{{ formatMoney(row.untaxed_actual_refund) }}</template>
            </ElTableColumn>
            <ElTableColumn prop="item_count" label="明细" width="70" align="center" />
            <ElTableColumn label="操作" width="80" fixed="right">
              <template #default="{ row }">
                <ElButton link type="primary" @click="openAfterSale(row as RetailAfterSaleRow)">明细</ElButton>
              </template>
            </ElTableColumn>
          </ElTable>

          <div class="pager">
            <ElPagination
              v-model:current-page="afterSalePage.page_no"
              v-model:page-size="afterSalePage.page_size"
              :total="afterSalePage.total"
              :page-sizes="[20, 50, 100]"
              layout="total, sizes, prev, pager, next, jumper"
              @current-change="loadAfterSales"
              @size-change="queryAfterSales"
            />
          </div>
        </ElTabPane>
        <ElTabPane label="平台店铺分析" name="analysis">
          <div class="toolbar">
            <ElSelect v-model="analysisSearch.period_value" placeholder="期间" clearable style="width: 130px">
              <ElOption v-for="item in periods" :key="item" :label="item" :value="item" />
            </ElSelect>
            <ElInputNumber
              v-model="analysisSearch.shop_id"
              :min="0"
              :controls="false"
              placeholder="店铺ID"
              style="width: 120px"
            />
            <ElButton type="primary" :loading="analysisLoading" @click="loadAnalysis">查询</ElButton>
            <ElButton @click="resetAnalysisSearch">重置</ElButton>
            <span class="muted">
              货物出货 = 订单状态 {{ analysis.shipped_statuses.join("/") || "Sent" }}（已发货）；
              金额均已 ÷{{ analysis.tax_rate }}% 去税
            </span>
          </div>

          <div class="summary">
            <span>店铺 {{ analysis.total.shop_count }} 个</span>
            <span>
              订单 {{ analysis.total.order_count }} 张 / 已发货 {{ analysis.total.shipped_order_count }} 张 /
              取消 {{ analysis.total.cancelled_order_count }} 张
            </span>
            <span>接单未税 {{ formatMoney(analysis.total.intake_untaxed) }}</span>
            <span class="summary-tax">出货未税 {{ formatMoney(analysis.total.shipment_untaxed) }}</span>
            <span>退货退款未税 {{ formatMoney(analysis.total.return_untaxed) }}</span>
            <span class="summary-tax">净额 {{ formatMoney(analysis.total.net_shipment_untaxed) }}</span>
            <span>退货率 {{ formatRate(analysis.total.return_rate) }}</span>
          </div>

          <ElTable v-loading="analysisLoading" :data="analysis.items" border stripe max-height="calc(100vh - 360px)">
            <ElTableColumn prop="period_value" label="期间" width="90" fixed />
            <ElTableColumn label="店铺" min-width="200" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.shop_name || "-" }}<span class="muted"> / {{ row.shop_id }}</span>
              </template>
            </ElTableColumn>
            <ElTableColumn prop="order_count" label="订单数" width="90" align="right" />
            <ElTableColumn prop="shipped_order_count" label="已发货" width="90" align="right" />
            <ElTableColumn prop="cancelled_order_count" label="取消单" width="90" align="right" />
            <ElTableColumn label="接单未税" width="120" align="right">
              <template #default="{ row }">{{ formatMoney(row.intake_untaxed) }}</template>
            </ElTableColumn>
            <ElTableColumn label="出货未税" width="120" align="right">
              <template #default="{ row }">{{ formatMoney(row.shipment_untaxed) }}</template>
            </ElTableColumn>
            <ElTableColumn label="取消未税" width="120" align="right">
              <template #default="{ row }">{{ formatMoney(row.cancelled_untaxed) }}</template>
            </ElTableColumn>
            <ElTableColumn label="售后未税" width="120" align="right">
              <template #default="{ row }">{{ formatMoney(row.refund_untaxed) }}</template>
            </ElTableColumn>
            <ElTableColumn label="退货退款" width="120" align="right">
              <template #default="{ row }">{{ formatMoney(row.return_untaxed) }}</template>
            </ElTableColumn>
            <ElTableColumn label="净额" width="120" align="right">
              <template #default="{ row }">{{ formatMoney(row.net_shipment_untaxed) }}</template>
            </ElTableColumn>
            <ElTableColumn label="退货率" width="100" align="right">
              <template #default="{ row }">{{ formatRate(row.return_rate) }}</template>
            </ElTableColumn>
          </ElTable>
        </ElTabPane>
      </ElTabs>
    </ElCard>

    <ElDrawer v-model="orderVisible" title="零售订单明细" size="760px">
      <template v-if="orderDetail">
        <ElDescriptions :column="2" border>
          <ElDescriptionsItem label="期间">{{ orderDetail.order.period_value }}</ElDescriptionsItem>
          <ElDescriptionsItem label="状态">{{ orderDetail.order.status || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="店铺">
            {{ orderDetail.order.shop_name || "-" }} / {{ orderDetail.order.shop_id }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="线上单号">{{ orderDetail.order.so_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="内部单号">{{ orderDetail.order.o_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="买家">{{ orderDetail.order.buyer_nick || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="买家实付">{{ formatMoney(orderDetail.order.buyer_paid_amount) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="接单未税">{{ formatMoney(orderDetail.order.untaxed_amount) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="应付金额">{{ formatMoney(orderDetail.order.pay_amount) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="支付时间">{{ formatTime(orderDetail.order.pay_date) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="上游修改">{{ formatTime(orderDetail.order.modified_time) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="收货地址" :span="2">
            {{ [orderDetail.order.receiver_state, orderDetail.order.receiver_city, orderDetail.order.receiver_district, orderDetail.order.receiver_town].filter(Boolean).join(" / ") || "-" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="备注" :span="2">{{ orderDetail.order.remark || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="最近批次" :span="2">{{ orderDetail.order.last_batch_id || "-" }}</ElDescriptionsItem>
        </ElDescriptions>

        <ElTable :data="orderDetail.items" border stripe class="detail-table">
          <ElTableColumn prop="sku_id" label="SKU" min-width="130" show-overflow-tooltip />
          <ElTableColumn prop="name" label="商品名称" min-width="220" show-overflow-tooltip />
          <ElTableColumn prop="properties_value" label="规格" min-width="150" show-overflow-tooltip />
          <ElTableColumn label="数量" width="75" align="right">
            <template #default="{ row }">{{ row.qty ?? "-" }}</template>
          </ElTableColumn>
          <ElTableColumn label="单价" width="90" align="right">
            <template #default="{ row }">{{ formatMoney(row.price) }}</template>
          </ElTableColumn>
          <ElTableColumn label="买家实付" width="100" align="right">
            <template #default="{ row }">{{ formatMoney(row.buyer_paid_amount) }}</template>
          </ElTableColumn>
          <ElTableColumn label="卖家实收" width="100" align="right">
            <template #default="{ row }">{{ formatMoney(row.seller_income_amount) }}</template>
          </ElTableColumn>
          <ElTableColumn prop="item_status" label="明细状态" width="100">
            <template #default="{ row }">{{ row.item_status || "-" }}</template>
          </ElTableColumn>
        </ElTable>
      </template>
    </ElDrawer>

    <ElDrawer v-model="batchVisible" title="推送批次详情" size="680px">
      <template v-if="batchDetail">
        <ElDescriptions :column="2" border>
          <ElDescriptionsItem label="请求ID">{{ batchDetail.request_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="来源">{{ batchDetail.source }}</ElDescriptionsItem>
          <ElDescriptionsItem label="状态">{{ batchStatusText(batchDetail.status) }}</ElDescriptionsItem>
          <ElDescriptionsItem label="期间">{{ batchDetail.periods?.join("、") || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="收到">{{ batchDetail.received_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="新增 / 更新">{{ batchDetail.created_count }} / {{ batchDetail.updated_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="跳过 / 失败">{{ batchDetail.stale_count }} / {{ batchDetail.failed_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="明细行">{{ batchDetail.item_count }}</ElDescriptionsItem>
          <ElDescriptionsItem label="推送时间" :span="2">{{ formatTime(batchDetail.created_time) }}</ElDescriptionsItem>
        </ElDescriptions>
        <div class="json-block">
          <div class="json-title">请求参数</div>
          <pre>{{ prettyJson(batchDetail.params) }}</pre>
        </div>
        <div v-if="batchDetail.errors?.length" class="json-block">
          <div class="json-title">错误</div>
          <pre>{{ prettyJson(batchDetail.errors) }}</pre>
        </div>
        <div class="json-block">
          <div class="json-title">处理结果</div>
          <pre>{{ prettyJson(batchDetail.result) }}</pre>
        </div>
      </template>
    </ElDrawer>

    <ElDrawer v-model="afterSaleVisible" title="售后单明细" size="780px">
      <template v-if="afterSaleDetail">
        <ElDescriptions :column="2" border>
          <ElDescriptionsItem label="期间">{{ afterSaleDetail.after_sale.period_value }}</ElDescriptionsItem>
          <ElDescriptionsItem label="状态">{{ afterSaleDetail.after_sale.status || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="售后单号">
            {{ afterSaleDetail.after_sale.as_id || "-" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="平台单号">
            {{ afterSaleDetail.after_sale.outer_as_id || "-" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="店铺">
            {{ afterSaleDetail.after_sale.shop_name || "-" }} /
            {{ afterSaleDetail.after_sale.shop_id }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="平台">{{ afterSaleDetail.after_sale.shop_site || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="订单号">{{ afterSaleDetail.after_sale.so_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="内部单号">{{ afterSaleDetail.after_sale.o_id || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="售后类型">{{ afterSaleDetail.after_sale.type || "-" }}</ElDescriptionsItem>
          <ElDescriptionsItem label="货物状态">
            {{ afterSaleDetail.after_sale.good_status || "-" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="商品应退">
            {{ formatMoney(afterSaleDetail.after_sale.refund) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="实退金额">
            {{ formatMoney(afterSaleDetail.after_sale.actual_refund) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="实退未税">
            {{ formatMoney(afterSaleDetail.after_sale.untaxed_actual_refund) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="运费">
            {{ formatMoney(afterSaleDetail.after_sale.freight) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="补偿/优惠">
            {{ formatMoney(afterSaleDetail.after_sale.payment) }} /
            {{ formatMoney(afterSaleDetail.after_sale.free_amount) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="申请时间">
            {{ formatTime(afterSaleDetail.after_sale.as_date) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="确认时间">
            {{ formatTime(afterSaleDetail.after_sale.confirm_date) }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="退回物流">
            {{ afterSaleDetail.after_sale.logistics_company || "-" }}
            {{ afterSaleDetail.after_sale.l_id || "" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="退回仓库">
            {{ afterSaleDetail.after_sale.warehouse || "-" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="备注" :span="2">
            {{ afterSaleDetail.after_sale.remark || "-" }}
          </ElDescriptionsItem>
          <ElDescriptionsItem label="最近批次" :span="2">
            {{ afterSaleDetail.after_sale.last_batch_id || "-" }}
          </ElDescriptionsItem>
        </ElDescriptions>

        <ElTable :data="afterSaleDetail.items" border stripe class="detail-table">
          <ElTableColumn prop="sku_id" label="SKU" min-width="130" show-overflow-tooltip />
          <ElTableColumn prop="name" label="商品名称" min-width="220" show-overflow-tooltip />
          <ElTableColumn prop="properties_value" label="规格" min-width="140" show-overflow-tooltip />
          <ElTableColumn label="申请数量" width="90" align="right">
            <template #default="{ row }">{{ row.qty ?? "-" }}</template>
          </ElTableColumn>
          <ElTableColumn label="实退数量" width="90" align="right">
            <template #default="{ row }">{{ row.r_qty ?? "-" }}</template>
          </ElTableColumn>
          <ElTableColumn label="单价" width="90" align="right">
            <template #default="{ row }">{{ formatMoney(row.price) }}</template>
          </ElTableColumn>
          <ElTableColumn label="金额" width="100" align="right">
            <template #default="{ row }">{{ formatMoney(row.amount) }}</template>
          </ElTableColumn>
        </ElTable>
      </template>
    </ElDrawer>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { ElMessage } from "element-plus";
import {
  RetailAPI,
  type RetailAnalysisResult,
  type RetailAfterSaleDetail,
  type RetailAfterSaleRow,
  type RetailBatchDetail,
  type RetailBatchRow,
  type RetailOrderDetail,
  type RetailOrderRow,
} from "@/api/module_retail";

defineOptions({ name: "RetailOrderSync" });

const activeTab = ref("orders");
const periods = ref<string[]>([]);
const orderLoading = ref(false);
const batchLoading = ref(false);
const shopSyncing = ref(false);
const afterSaleLoading = ref(false);
const afterSaleSyncing = ref(false);
const analysisLoading = ref(false);
const orders = ref<RetailOrderRow[]>([]);
const batches = ref<RetailBatchRow[]>([]);
const afterSales = ref<RetailAfterSaleRow[]>([]);

const orderSearch = reactive<{
  period_value?: string;
  shop_id?: number;
  shop_name?: string;
  so_id?: string;
  status?: string;
  source?: string;
  keyword?: string;
}>({});
const batchSearch = reactive<{ request_id?: string; source?: string; status?: string }>({});
const afterSaleSearch = reactive<{
  period_value?: string;
  shop_id?: number;
  shop_name?: string;
  as_id?: string;
  so_id?: string;
  type?: string;
  keyword?: string;
}>({});
const analysisSearch = reactive<{ period_value?: string; shop_id?: number }>({});

const orderPage = reactive({
  page_no: 1,
  page_size: 20,
  total: 0,
  summary: {
    order_count: 0,
    buyer_paid_amount_sum: 0,
    untaxed_amount_sum: 0,
    tax_rate: 13,
    item_count_sum: 0,
  },
});
const batchPage = reactive({ page_no: 1, page_size: 20, total: 0 });
const afterSalePage = reactive({
  page_no: 1,
  page_size: 20,
  total: 0,
  summary: {
    after_sale_count: 0,
    actual_refund_sum: 0,
    untaxed_actual_refund_sum: 0,
    tax_rate: 13,
    refund_sum: 0,
    item_count_sum: 0,
  },
});

const orderVisible = ref(false);
const orderDetail = ref<RetailOrderDetail | null>(null);
const batchVisible = ref(false);
const batchDetail = ref<RetailBatchDetail | null>(null);
const afterSaleVisible = ref(false);
const afterSaleDetail = ref<RetailAfterSaleDetail | null>(null);
const analysis = ref<RetailAnalysisResult>({
  tax_rate: 13,
  shipped_statuses: ["Sent"],
  cancelled_statuses: ["Cancelled"],
  items: [],
  total: {
    shop_count: 0,
    order_count: 0,
    shipped_order_count: 0,
    cancelled_order_count: 0,
    intake_untaxed: 0,
    shipment_untaxed: 0,
    cancelled_untaxed: 0,
    refund_untaxed: 0,
    return_untaxed: 0,
    net_shipment_untaxed: 0,
    return_rate: 0,
  },
});

function formatTime(value?: string | null) {
  if (!value) return "-";
  return value.replace("T", " ").slice(0, 19);
}

function formatMoney(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatRate(value?: number | null) {
  if (value === undefined || value === null || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function orderStatusType(status?: string | null) {
  if (!status) return "info";
  if (["Cancelled", "Delete", "Refunded"].includes(status)) return "danger";
  if (["WaitConfirm", "WaitPay"].includes(status)) return "warning";
  return "success";
}

function batchStatusType(status: string) {
  if (status === "failed") return "danger";
  if (status === "partial" || status === "running") return "warning";
  return "success";
}

function afterSaleStatusType(status?: string | null) {
  if (!status) return "info";
  if (["WaitConfirm", "WaitReturn", "WaitReceive"].includes(status)) return "warning";
  if (["Refused", "Closed", "Cancel"].includes(status)) return "danger";
  return "success";
}

function batchStatusText(status: string) {
  const labels: Record<string, string> = {
    success: "成功",
    partial: "部分成功",
    failed: "失败",
    running: "处理中",
  };
  return labels[status] ?? status;
}

function prettyJson(value: unknown) {
  return JSON.stringify(value ?? {}, null, 2);
}

async function loadPeriods() {
  try {
    const res = await RetailAPI.periods();
    periods.value = res.data?.data ?? [];
  } catch {
    periods.value = [];
  }
}

async function loadOrders() {
  orderLoading.value = true;
  try {
    const res = await RetailAPI.orders({
      period_value: orderSearch.period_value,
      shop_id: orderSearch.shop_id ?? undefined,
      shop_name: orderSearch.shop_name || undefined,
      so_id: orderSearch.so_id || undefined,
      status: orderSearch.status || undefined,
      source: orderSearch.source || undefined,
      keyword: orderSearch.keyword || undefined,
      page_no: orderPage.page_no,
      page_size: orderPage.page_size,
    });
    const data = res.data?.data;
    orders.value = data?.items ?? [];
    orderPage.total = data?.total ?? 0;
    orderPage.summary =
      data?.summary ?? {
        order_count: 0,
        buyer_paid_amount_sum: 0,
        untaxed_amount_sum: 0,
        tax_rate: 13,
        item_count_sum: 0,
      };
  } catch (error) {
    orders.value = [];
    ElMessage.error("查询零售订单失败");
    console.error(error);
  } finally {
    orderLoading.value = false;
  }
}

async function loadBatches() {
  batchLoading.value = true;
  try {
    const res = await RetailAPI.batches({
      request_id: batchSearch.request_id || undefined,
      source: batchSearch.source || undefined,
      status: batchSearch.status || undefined,
      page_no: batchPage.page_no,
      page_size: batchPage.page_size,
    });
    const data = res.data?.data;
    batches.value = data?.items ?? [];
    batchPage.total = data?.total ?? 0;
  } catch (error) {
    batches.value = [];
    ElMessage.error("查询推送批次失败");
    console.error(error);
  } finally {
    batchLoading.value = false;
  }
}

async function handleSyncShops() {
  shopSyncing.value = true;
  try {
    const res = await RetailAPI.syncShops();
    const data = (res.data?.data ?? {}) as { received?: number; created?: number; updated?: number };
    ElMessage.success(
      `店铺同步完成：收到 ${data.received ?? 0}，新增 ${data.created ?? 0}，更新 ${data.updated ?? 0}`,
    );
  } catch (error) {
    ElMessage.error("同步店铺失败，请查看后端日志");
    console.error(error);
  } finally {
    shopSyncing.value = false;
  }
}

async function loadAfterSales() {
  afterSaleLoading.value = true;
  try {
    const res = await RetailAPI.afterSales({
      period_value: afterSaleSearch.period_value,
      shop_id: afterSaleSearch.shop_id ?? undefined,
      shop_name: afterSaleSearch.shop_name || undefined,
      as_id: afterSaleSearch.as_id || undefined,
      so_id: afterSaleSearch.so_id || undefined,
      type: afterSaleSearch.type || undefined,
      keyword: afterSaleSearch.keyword || undefined,
      page_no: afterSalePage.page_no,
      page_size: afterSalePage.page_size,
    });
    const data = res.data?.data;
    afterSales.value = data?.items ?? [];
    afterSalePage.total = data?.total ?? 0;
    afterSalePage.summary =
      data?.summary ?? {
        after_sale_count: 0,
        actual_refund_sum: 0,
        untaxed_actual_refund_sum: 0,
        tax_rate: 13,
        refund_sum: 0,
        item_count_sum: 0,
      };
  } catch (error) {
    afterSales.value = [];
    ElMessage.error("查询零售售后失败");
    console.error(error);
  } finally {
    afterSaleLoading.value = false;
  }
}

async function handlePullAfterSales() {
  afterSaleSyncing.value = true;
  try {
    const res = await RetailAPI.pullAfterSales({
      period_value: afterSaleSearch.period_value || undefined,
      days: 7,
    });
    const data = (res.data?.data ?? {}) as {
      received?: number;
      created?: number;
      updated?: number;
      unchanged?: number;
      failed?: number;
    };
    ElMessage.success(
      `售后同步完成：收到 ${data.received ?? 0}，新增 ${data.created ?? 0}，` +
        `更新 ${data.updated ?? 0}，未变 ${data.unchanged ?? 0}，失败 ${data.failed ?? 0}`,
    );
    queryAfterSales();
  } catch (error) {
    ElMessage.error("同步聚水潭售后失败，请查看后端日志");
    console.error(error);
  } finally {
    afterSaleSyncing.value = false;
  }
}

function queryAfterSales() {
  afterSalePage.page_no = 1;
  loadAfterSales();
}

async function loadAnalysis() {
  analysisLoading.value = true;
  try {
    const res = await RetailAPI.analysisSummary({
      period_value: analysisSearch.period_value || undefined,
      shop_id: analysisSearch.shop_id ?? undefined,
    });
    const data = res.data?.data;
    if (data) {
      analysis.value = data;
    }
  } catch (error) {
    analysis.value.items = [];
    ElMessage.error("查询平台店铺分析失败");
    console.error(error);
  } finally {
    analysisLoading.value = false;
  }
}

function resetAnalysisSearch() {
  Object.assign(analysisSearch, { period_value: undefined, shop_id: undefined });
  loadAnalysis();
}

function resetAfterSaleSearch() {
  Object.assign(afterSaleSearch, {
    period_value: undefined,
    shop_id: undefined,
    shop_name: "",
    as_id: "",
    so_id: "",
    type: undefined,
    keyword: "",
  });
  queryAfterSales();
}

async function openAfterSale(row: RetailAfterSaleRow) {
  try {
    const res = await RetailAPI.afterSaleDetail(row.id);
    afterSaleDetail.value = res.data?.data ?? null;
    afterSaleVisible.value = true;
  } catch (error) {
    ElMessage.error("加载售后明细失败");
    console.error(error);
  }
}

function queryOrders() {
  orderPage.page_no = 1;
  loadOrders();
}

function resetOrderSearch() {
  Object.assign(orderSearch, {
    period_value: undefined,
    shop_id: undefined,
    shop_name: "",
    so_id: "",
    status: "",
    source: "",
    keyword: "",
  });
  queryOrders();
}

function queryBatches() {
  batchPage.page_no = 1;
  loadBatches();
}

function resetBatchSearch() {
  Object.assign(batchSearch, { request_id: "", source: "", status: undefined });
  queryBatches();
}

async function openOrder(row: RetailOrderRow) {
  try {
    const res = await RetailAPI.orderDetail(row.id);
    orderDetail.value = res.data?.data ?? null;
    orderVisible.value = true;
  } catch (error) {
    ElMessage.error("加载订单明细失败");
    console.error(error);
  }
}

async function openBatch(row: RetailBatchRow) {
  try {
    const res = await RetailAPI.batchDetail(row.id);
    batchDetail.value = res.data?.data ?? null;
    batchVisible.value = true;
  } catch (error) {
    ElMessage.error("加载批次详情失败");
    console.error(error);
  }
}

function handleTabChange(name: string | number) {
  if (name === "batches" && !batches.value.length) {
    loadBatches();
  }
  if (name === "aftersales" && !afterSales.value.length) {
    loadAfterSales();
  }
  if (name === "analysis" && !analysis.value.items.length) {
    loadAnalysis();
  }
}

onMounted(async () => {
  await loadPeriods();
  await loadOrders();
});
</script>

<style lang="scss" scoped>
.retail-sync-page {
  height: 100%;
  padding: 12px;

  .page-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
  }

  .page-title {
    font-size: 16px;
    font-weight: 600;
  }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
    margin-bottom: 12px;
  }

  .summary {
    display: flex;
    flex-wrap: wrap;
    gap: 18px;
    margin-bottom: 10px;
    font-size: 13px;
    color: var(--el-text-color-regular);
  }

  .summary-extra,
  .muted {
    color: var(--el-text-color-secondary);
  }

  .summary-tax {
    font-weight: 600;
    color: var(--el-color-primary);
  }

  .pager {
    display: flex;
    justify-content: flex-end;
    margin-top: 12px;
  }

  .detail-table {
    margin-top: 14px;
  }

  .json-block {
    margin-top: 14px;
  }

  .json-title {
    margin-bottom: 6px;
    font-size: 13px;
    font-weight: 600;
  }

  pre {
    max-height: 260px;
    padding: 10px;
    margin: 0;
    overflow: auto;
    font-size: 12px;
    white-space: pre-wrap;
    word-break: break-all;
    background: var(--el-fill-color-lighter);
    border-radius: 4px;
  }
}
</style>
