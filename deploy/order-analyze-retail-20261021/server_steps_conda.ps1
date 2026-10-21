# CRM orderAnalyze type=3（零售）Windows / conda 更新脚本
#
# 在项目根目录执行：
#   powershell -ExecutionPolicy Bypass -File .\deploy\order-analyze-retail-20261021\server_steps_conda.ps1
#   powershell -ExecutionPolicy Bypass -File .\deploy\order-analyze-retail-20261021\server_steps_conda.ps1 -Apply
#   powershell -ExecutionPolicy Bypass -File .\deploy\order-analyze-retail-20261021\server_steps_conda.ps1 -Apply -Service fastapiadmin
param(
    [switch]$Apply,
    [string]$Service = "",
    [string]$EnvName = "prod",
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Backend = Join-Path $Root "backend"
$SyncPeriods = "2023-11,2023-12,2024-01,2024-02,2024-03,2024-04,2024-05,2024-06,2024-07,2024-08,2024-09,2024-10,2024-11,2024-12,2025-01,2025-02,2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10"
$BuildPeriods = "2024-10,2024-11,2024-12,2025-01,2025-02,2025-03,2025-04,2025-05,2025-06,2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10"
$RetailPeriods = "2025-07,2025-08,2025-09,2025-10,2025-11,2025-12,2026-01,2026-02,2026-03,2026-04,2026-05,2026-06,2026-07,2026-08,2026-09,2026-10"

function Invoke-Step {
    param([string]$Label, [string[]]$Arguments)
    Write-Host "`n$Label"
    Write-Host "  > $Python $($Arguments -join ' ')"
    if (-not $Apply) { return }
    Push-Location $Backend
    try {
        & $Python @Arguments
        if ($LASTEXITCODE -ne 0) { throw "命令失败，退出码 $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
}

Write-Host "项目根目录：$Root"
Write-Host "后端环境：$EnvName"
Write-Host "模式：$(if ($Apply) { '执行' } else { '预演' })"

if (-not (Test-Path $Backend)) { throw "找不到 backend 目录：$Backend" }
$env:ENVIRONMENT = $EnvName
$env:PYTHONIOENCODING = "utf-8"

Invoke-Step "[1/8] 指标/来源对象定义" @("scripts/seed_crm_person_metrics.py")
Invoke-Step "[2/8] 订单全链路元数据" @("scripts/seed_order_module.py")
Invoke-Step "[3/8] 同步零售订单 type=3" @("scripts/run_meta_sync.py", "--name", "CRM业务员指标-CRM 订单明细（零售）", "--period", $SyncPeriods)
Invoke-Step "[4/8] 重建订单全链路" @("scripts/run_order_build.py", "--period", $BuildPeriods)
Invoke-Step "[5/8] 重建客户分析" @("scripts/run_customer_build.py", "--period", $RetailPeriods)
Invoke-Step "[6/8] 重建产品线分析" @("scripts/run_product_build.py", "--period", $RetailPeriods)
Invoke-Step "[7/8] 重算业务员指标及下游" @("scripts/recalc_metrics_batch.py", "--code-file", "scripts/metric_groups/order_retail.txt", "--with-dependents", "--period-from", "2025-07", "--period-to", "2026-10")
Invoke-Step "[8/8] 校验" @("scripts/run_meta_sync.py", "--name", "CRM业务员指标-CRM 订单明细（零售）", "--period", "2026-09", "--show-latest")

if (-not $Apply) {
    Write-Host "`n预演完成，未执行任何命令。确认后加 -Apply。"
    return
}

if ($Service) {
    Write-Host "`n重启 Windows 服务：$Service"
    Restart-Service -Name $Service -Force
    Get-Service -Name $Service | Format-Table Name, Status, StartType
} else {
    Write-Host "`n未指定 -Service：请按现有方式重启后端进程。"
}

Write-Host "`n服务器更新完成。"
