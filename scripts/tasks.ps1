# Lightweight task runner for this Windows/Python repository.
# Thin wrappers only — every command below maps 1:1 to a verified command in README.md.
# Usage: powershell -ExecutionPolicy Bypass -File scripts/tasks.ps1 <target>
# Targets: test | validate | pipeline-dry-run | impact | reconcile | figures | data

param(
    [string]$Target = "test"
)

$ErrorActionPreference = "Stop"

function Invoke-Step([string]$Label, [string]$Command) {
    Write-Host "==> $Label" -ForegroundColor Cyan
    Write-Host "    $Command" -ForegroundColor DarkGray
    Invoke-Expression $Command
}

switch ($Target) {
    "test" {
        Invoke-Step "focused documentation gates" "py -3.11 -m pytest tests/test_documentation_claims.py tests/test_final_portfolio_audit.py -q -W error"
    }
    "validate" {
        Invoke-Step "full suite" "py -3.11 -m pytest -q -W error"
    }
    "pipeline-dry-run" {
        Invoke-Step "pipeline dry run" "py -3.11 -m src.run_pipeline --dry-run --stages dashboard_spec"
    }
    "impact" {
        Invoke-Step "impact metrics" "py -3.11 -m src.impact_metrics"
    }
    "reconcile" {
        Invoke-Step "cross-system reconciliation" "py -3.11 -m src.cross_system_reconciliation"
    }
    "figures" {
        Invoke-Step "portfolio figures" "py -3.11 -m src.generate_portfolio_figures"
    }
    "data" {
        Invoke-Step "data verification" "py -3.11 -m scripts.verify_data --processed-only"
    }
    default {
        Write-Host "Unknown target: $Target (test|validate|pipeline-dry-run|impact|reconcile|figures|data)"
        exit 1
    }
}
