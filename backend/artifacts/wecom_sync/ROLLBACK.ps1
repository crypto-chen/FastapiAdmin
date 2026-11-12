$ErrorActionPreference = "Stop"

# 回滚范围：删除本次新增的企业微信模块/脚本/测试/迁移，并还原两个注册文件
# 如需同时回滚数据库，请先执行：python -m alembic downgrade -1
$backend = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))

$targets = @(
    (Join-Path $backend "app\modules\erp\wecom"),
    (Join-Path $backend "scripts\wecom_backfill.py"),
    (Join-Path $backend "scripts\seed_wecom_token_connection.py"),
    (Join-Path $backend "scripts\seed_opcenter_worktime_metrics.py"),
    (Join-Path $backend "tests\test_wecom.py"),
    (Join-Path $backend "app\alembic\versions\2026_11_12_1200_wecomsync01.py"),
    (Join-Path $backend "app\alembic\versions\2026_11_12_1430_wecomtoken01.py")
)

foreach ($target in $targets) {
    $resolved = [System.IO.Path]::GetFullPath($target)
    if (-not $resolved.StartsWith($backend, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "拒绝删除工作区外路径: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}

git -C $backend checkout -- app/__init__.py app/api/v1/routers.py app/modules/metric/engine.py
Write-Output "企业微信同步模块代码已回滚。"
Write-Output "如已写入 TM-01/TM-02 指标定义，请按需删除："
Write-Output "  DELETE FROM metric_def WHERE code IN ('TM-01','TM-02');"
