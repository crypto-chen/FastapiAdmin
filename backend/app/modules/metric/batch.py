"""指标批量计算：按依赖分层（拓扑排序）后逐层执行。

背景：派生指标（``metric_sum`` / ``metric_scale`` / ``metric_ratio`` / ``metric_diff`` /
``metric_balance_avg``）自身不取数，值由其它指标的当期结果算出，依赖声明在
``metric_def.measures`` 里（如 ``component_metric_codes``）。原先每个指标各挂一个
02:30 的定时任务，同点触发、并发执行、先后顺序不确定，派生指标可能先于组成指标跑完，
从而读到组成指标上一天 02:30 的旧版本。

现在改为**一个批次任务**：先按依赖关系把启用指标拓扑分层，同层互不依赖、可并发，
层与层之间串行——组成指标一定先于依赖它的派生指标完成。运行期还有一层
「组成指标当天算过」的新鲜度校验（``engine._ensure_component_values``），
兜住单指标重算与开放接口触发。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from sqlalchemy import false, select

from app.core.database import async_db_session
from app.core.logger import logger
from app.modules.metadata.sync import execute_meta_sync_job

from . import engine
from .model import MetricDefModel

# 重拉同步批次的并发度：金蝶单组织科目余额表一次约 2000+ 行、翻页取全量
REFRESH_CONCURRENCY = 4


async def load_enabled_metrics(codes: list[str] | None = None) -> list[dict]:
    """启用中的指标定义（``codes`` 指定时只取这些），按 id 升序返回纯数据。"""
    async with async_db_session() as db:
        stmt = (
            select(MetricDefModel)
            .where(MetricDefModel.is_deleted == false(), MetricDefModel.status == 0)
            .order_by(MetricDefModel.id)
        )
        if codes:
            stmt = stmt.where(MetricDefModel.code.in_(codes))
        rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": int(row.id),
            "code": str(row.code),
            "name": str(row.name or ""),
            "period_type": str(row.period_type or "month"),
            "measures": dict(row.measures or {}),
        }
        for row in rows
    ]


def build_metric_layers(metrics: list[dict]) -> tuple[list[list[dict]], list[str]]:
    """把指标按依赖分层，返回 ``(layers, problems)``。

    - 同层内指标互不依赖，可并发执行；层序即执行顺序（组成指标所在层一定在前）。
    - ``problems`` 记录配置问题（依赖编码不存在/未启用、依赖自身、成环），不阻断其它
      指标：问题指标仍会排进兜底层，由运行期的环保护与缺失告警兜住。
    - 层内按 id 升序，保证同一份配置每天的执行顺序稳定、结果可复现。
    """
    by_code = {item["code"]: item for item in metrics}
    deps: dict[str, list[str]] = {}
    problems: list[str] = []
    for item in metrics:
        code = item["code"]
        resolved: list[str] = []
        for dep in engine.metric_dependency_codes(item["measures"]):
            if dep == code:
                problems.append(f"{code} 依赖自身，已忽略该依赖")
                continue
            if dep not in by_code:
                problems.append(f"{code} 依赖的指标 {dep} 不存在或未启用，运行期将按 0 计入")
                continue
            if dep not in resolved:
                resolved.append(dep)
        deps[code] = resolved

    remaining = {item["code"] for item in metrics}
    layers: list[list[dict]] = []
    while remaining:
        ready = sorted(
            (code for code in remaining if all(dep not in remaining for dep in deps[code])),
            key=lambda code: by_code[code]["id"],
        )
        if not ready:
            # 剩下每个指标都还有未完成的依赖 → 成环；按 id 兜底成一层，交给运行期环保护报错
            cycle = sorted(remaining, key=lambda code: by_code[code]["id"])
            problems.append(f"指标依赖存在环，涉及 {', '.join(cycle)}（该层指标会因环保护报错）")
            layers.append([by_code[code] for code in cycle])
            break
        layers.append([by_code[code] for code in ready])
        remaining -= set(ready)
    return layers, problems


async def refresh_metric_batches(metrics: list[dict], period_value: str | None) -> dict:
    """按期间重拉这批指标用到的全部同步批次（同一任务只拉一次）。

    实时取数类指标（账龄计提）不落同步批次，自动跳过；``period_value`` 为空时
    按各指标自己的当前期间取数（不同 ``period_type`` 互不干扰）。
    """
    pending: dict[int, tuple[str, str]] = {}
    failures: list[str] = []
    for item in metrics:
        try:
            context = await engine._load_metric_context(item["id"], period_value, None)
        except Exception as e:
            failures.append(f"{item['code']}: 读取配置失败 {e}")
            continue
        if str(context["config"].get("kind") or "") in engine.LIVE_KINDS:
            continue
        for job_id, org_code, _params, _variables in context["jobs"]:
            pending.setdefault(int(job_id), (org_code, context["period"]))

    semaphore = asyncio.Semaphore(REFRESH_CONCURRENCY)
    done = 0

    async def run(job_id: int, org_code: str, period: str) -> None:
        nonlocal done
        async with semaphore:
            try:
                await execute_meta_sync_job(job_id, period_value=period)
            except Exception as e:  # 单个任务失败不阻断整体重算
                failures.append(f"job {job_id}(组织 {org_code}): {e}")
                logger.warning(f"同步任务 {job_id}（组织 {org_code}）重拉失败: {e}")
            done += 1
            if done % 5 == 0 or done == len(pending):
                logger.info(f"批次刷新进度 {done}/{len(pending)}")

    await asyncio.gather(*(run(job_id, org_code, period) for job_id, (org_code, period) in pending.items()))
    return {"refreshed": [str(job_id) for job_id in pending], "failed": failures}


async def _calc_one(item: dict, period_value: str | None) -> dict[str, Any]:
    """计算单个指标并归一结果；异常在这里兜住，避免拖垮同层其它指标。"""
    begin = time.time()
    try:
        summary = await engine.execute_metric_calc(metric_id=item["id"], period_value=period_value)
    except Exception as e:
        logger.exception(f"指标 {item['code']} 计算失败: {e}")
        return {"ok": False, "code": item["code"], "error": str(e), "seconds": round(time.time() - begin, 1)}
    return {
        "ok": True,
        "code": item["code"],
        "summary": summary,
        "seconds": round(time.time() - begin, 1),
    }


async def run_metric_batch(
    *,
    period_value: str | None = None,
    codes: list[str] | None = None,
    refresh: bool = False,
    label: str = "",
) -> dict[str, Any]:
    """按依赖分层计算全部启用指标（或 ``codes`` 指定的子集）。

    ``refresh=True`` 时先按期间重拉所有同步批次（同一任务只拉一次，并发 4），
    用于次月结转与手动全量重算。返回批次摘要：分层清单、逐指标结果、失败与配置问题。
    """
    started = time.time()
    metrics = await load_enabled_metrics(codes)
    if not metrics:
        raise ValueError("没有匹配的启用指标")
    layers, problems = build_metric_layers(metrics)
    for problem in problems:
        logger.warning(f"指标依赖配置问题: {problem}")
    tag = f"[{label}] " if label else ""

    refreshed: dict[str, Any] | None = None
    if refresh:
        refreshed = await refresh_metric_batches(metrics, period_value)
        logger.info(
            f"{tag}批次刷新完成: 任务 {len(refreshed['refreshed'])} 个，失败 {len(refreshed['failed'])} 个"
        )

    results: list[dict] = []
    failures: list[str] = []
    layer_codes: list[list[str]] = []
    for depth, layer in enumerate(layers, start=1):
        layer_codes.append([item["code"] for item in layer])
        logger.info(f"{tag}第 {depth}/{len(layers)} 层开始，共 {len(layer)} 个指标")
        outcomes = await asyncio.gather(*(_calc_one(item, period_value) for item in layer))
        for item, outcome in zip(layer, outcomes, strict=True):
            if outcome["ok"]:
                results.append(outcome["summary"])
                total = outcome["summary"].get("total")
                logger.info(f"{tag}{item['code']} v{outcome['summary'].get('calc_version')} 合计 {total}（{outcome['seconds']}s）")
            else:
                failures.append(f"{item['code']}: {outcome['error']}")

    summary: dict[str, Any] = {
        "label": label,
        "period": period_value,
        "metric_count": len(metrics),
        "layer_count": len(layers),
        "layers": layer_codes,
        "problems": problems,
        "success": len(results),
        "failed": failures,
        "elapsed_seconds": round(time.time() - started, 1),
        "totals": {item["metric_code"]: item["total"] for item in results},
    }
    if refreshed is not None:
        summary["refreshed"] = refreshed
    logger.info(
        f"{tag}指标批次结束: 成功 {summary['success']}/{summary['metric_count']}，"
        f"失败 {len(failures)}，用时 {summary['elapsed_seconds']}s"
    )
    return summary
