"""开放接口路由总表：对外前缀 /open/v1。

独立于管理端 /api/v1，便于网关只放行 /open/**，也便于单独限流与审计。
"""

from fastapi import APIRouter

from app.modules.customer.open_controller import OpenCustomerRouter
from app.modules.openapi.open_controller import OpenAuthRouter, OpenMetricRouter, OpenOrgRouter
from app.modules.order.open_controller import OpenOrderRouter
from app.modules.product.open_controller import OpenProductLineRouter
from app.modules.retail.open_controller import OpenRetailRouter

open_v1 = APIRouter(prefix="/open/v1")
for controller in (
    OpenAuthRouter,
    OpenMetricRouter,
    OpenOrgRouter,
    OpenOrderRouter,
    OpenCustomerRouter,
    OpenProductLineRouter,
    OpenRetailRouter,
):
    open_v1.include_router(controller)
