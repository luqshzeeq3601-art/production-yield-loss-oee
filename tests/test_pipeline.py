"""Tests for the end-to-end pipeline orchestrator (src/run_pipeline.py)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch
import pytest

from src.run_pipeline import (
    DEFAULT_STAGES,
    StageDefinition,
    main,
    run_pipeline,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_stages_defined_and_ordered():
    """Verify all 14 pipeline stages are defined, ordered by dependency, and importable."""
    expected_order = [
        "ingest_secom",
        "ingest_metropt3",
        "simulate_mes",
        "load_db",
        "run_dq_checks",
        "feature_screening",
        "spc_engine",
        "spc_backtest",
        "rca_pareto",
        "rca_statistical",
        "oee_whatif",
        "manual_baseline",
        "powerbi_model",
        "dashboard_spec",
    ]

    actual_names = [s.name for s in DEFAULT_STAGES]
    assert actual_names == expected_order, f"Stages order mismatch: {actual_names}"

    # Verify each stage callable resolves to a valid function
    for stage in DEFAULT_STAGES:
        func = stage.get_callable()
        assert callable(func), f"Callable for stage '{stage.name}' could not be resolved."


def test_pipeline_dry_run(tmp_path):
    """Verify dry-run mode validates stages without running heavy processing."""
    log_file = tmp_path / "test_pipeline.log"
    summary = run_pipeline(
        config_path=None,
        stages=None,
        skip_db=False,
        dry_run=True,
        log_file=log_file,
    )

    assert summary["status"] == "SUCCESS"
    assert summary["stages_executed"] == len(DEFAULT_STAGES)
    assert summary["stages_succeeded"] == len(DEFAULT_STAGES)
    assert summary["stages_failed"] == 0
    assert summary["stages_skipped"] == 0
    assert all(s["status"] == "DRY_RUN" for s in summary["stages"])

    summary_file = REPO_ROOT / "reports" / "pipeline_run_summary.json"
    assert summary_file.is_file()
    saved_summary = json.loads(summary_file.read_text(encoding="utf-8"))
    assert saved_summary["status"] == "SUCCESS"


def test_pipeline_stage_subset_execution(tmp_path):
    """Verify running a targeted subset of stages executes and logs correctly."""
    log_file = tmp_path / "subset_pipeline.log"
    summary = run_pipeline(
        config_path=None,
        stages=["dashboard_spec", "manual_baseline"],
        skip_db=False,
        dry_run=False,
        log_file=log_file,
    )

    assert summary["status"] == "SUCCESS"
    assert summary["stages_executed"] == 2
    assert summary["stages_succeeded"] == 2
    assert summary["stages_failed"] == 0
    assert summary["stages_skipped"] == 0

    executed_names = [s["name"] for s in summary["stages"]]
    assert executed_names == ["dashboard_spec", "manual_baseline"]
    assert all(s["status"] == "SUCCESS" for s in summary["stages"])
    assert all(s["duration_seconds"] >= 0 for s in summary["stages"])
    assert log_file.is_file()


def test_pipeline_skip_db_flag(tmp_path):
    """Verify --skip-db skips DB-dependent stages and runs non-DB stages."""
    log_file = tmp_path / "skip_db.log"
    summary = run_pipeline(
        config_path=None,
        stages=["load_db", "dashboard_spec"],
        skip_db=True,
        dry_run=False,
        log_file=log_file,
    )

    assert summary["status"] == "SUCCESS"
    assert summary["stages_executed"] == 2
    assert summary["stages_succeeded"] == 1
    assert summary["stages_skipped"] == 1
    assert summary["stages_failed"] == 0

    load_db_stage = next(s for s in summary["stages"] if s["name"] == "load_db")
    dashboard_stage = next(s for s in summary["stages"] if s["name"] == "dashboard_spec")

    assert load_db_stage["status"] == "SKIPPED"
    assert dashboard_stage["status"] == "SUCCESS"


def test_pipeline_error_handling_and_non_zero_exit(tmp_path):
    """Verify failing stage marks failure, halts downstream stages, and returns non-zero code."""
    mock_failing_stage = StageDefinition(
        name="failing_stage",
        description="A stage that fails deliberately",
        module_path="src.dashboard_spec",
        function_name="run",
    )

    with patch.object(mock_failing_stage, "get_callable", side_effect=RuntimeError("Simulated pipeline crash")):
        with patch("src.run_pipeline.DEFAULT_STAGES", [mock_failing_stage, DEFAULT_STAGES[0]]):
            log_file = tmp_path / "failure.log"
            summary = run_pipeline(
                config_path=None,
                stages=None,
                skip_db=False,
                dry_run=False,
                log_file=log_file,
            )

            assert summary["status"] == "FAILED"
            assert summary["stages_executed"] == 1
            assert summary["stages_failed"] == 1
            assert summary["failure_stage"] == "failing_stage"
            assert "Simulated pipeline crash" in summary["failure_error"]


def test_pipeline_invalid_stage_name():
    """Verify specifying an invalid stage name raises a clear ValueError."""
    with pytest.raises(ValueError, match="Unknown stage"):
        run_pipeline(stages=["non_existent_stage_xyz"])


def test_cli_main_dry_run_success():
    """Verify CLI main entry point exits with code 0 on dry run."""
    exit_code = main(["--dry-run", "--stages", "dashboard_spec"])
    assert exit_code == 0


def test_cli_main_error_exit_code():
    """Verify CLI main entry point exits with code 1 on exception."""
    exit_code = main(["--stages", "non_existent_stage"])
    assert exit_code == 1
