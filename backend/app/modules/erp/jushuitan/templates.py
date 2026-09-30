"""聚水潭取数模板（元数据同步任务复用）。

``MONTHLY_SALES_OUTBOUND_BIZ`` 是销售出库查询的 ``biz`` 模板：
出库状态=已出库（``Confirmed``）、按出库时间（``date_type=2``）取**整月**单据。

模板里的 ``{{ ... }}`` 由元数据同步任务渲染（见 ``app.modules.metadata.sync.render_request_params``）：
``now`` 是取数时点——正常调度是当前时间，按期间回补时会替换成目标期间的 1 日 00:00，
因此同一条任务既能跑当月也能回补历史月份。
"""

MONTHLY_SALES_OUTBOUND_BIZ: dict = {
    "status": "Confirmed",
    "date_type": 2,
    "modified_begin": "{{ now.replace(day=1).strftime('%Y-%m-%d 00:00:00') }}",
    "modified_end": "{{ ((now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(seconds=1)).strftime('%Y-%m-%d %H:%M:%S') }}",
}
