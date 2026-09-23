"""Production Yield Loss & OEE Early-Warning System — End-to-End Orchestrator.

Orchestrates the entire manufacturing analytics pipeline:
Ingestion -> Simulation -> DB Staging -> DQ Checks -> SPC Engine -> Backtest ->
RCA & Pareto -> What-If Modeling -> Manual Baseline -> Power BI Model -> Dashboard Spec.

Usage:
    python src/run_pipeline.py [--config PATH] [--skip-db] [--stages S1,S2] [--dry-run]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib
import json
import logging
import os
from pathlib import Path
import platform
import sys
import time
from typing import Any, Callable, Mapping, Sequence

from src.config_loader import load_config

# Configure logging
logger = logging.getLogger("pipeline_orchestrator")


class StageDefinition:
    """Metadata and execution callable for a pipeline stage."""

    def __init__(
        self,
        name: str,
        description: str,
        module_path: str,
        function_name: str = "run",
        db_dependent: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.module_path = module_path
        self.function_name = function_name
        self.db_dependent = db_dependent

    def get_callable(self) -> Callable[..., Any]:
        module = importlib.import_module(self.module_path)
        func = getattr(module, self.function_name)
        return func


DEFAULT_STAGES: list[StageDefinition] = [
    StageDefinition(
        name="ingest_secom",
        description="Download/clean/profile UCI SECOM semiconductor lot sensor data",
        module_path="src.ingest_secom",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="ingest_metropt3",
        description="Stream/validate/chunk UCI MetroPT-3 compressor sensor time-series",
        module_path="src.ingest_metropt3",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="simulate_mes",
        description="Simulate MES operations (work orders, downtime, shifts, scrap)",
        module_path="src.simulate_mes",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="load_db",
        description="Stage CSVs and populate PostgreSQL star schema dimensions and facts",
        module_path="src.load_db",
        function_name="run",
        db_dependent=True,
    ),
    StageDefinition(
        name="run_dq_checks",
        description="Execute automated SQL data quality constraint assertions",
        module_path="src.run_dq_checks",
        function_name="run",
        db_dependent=True,
    ),
    StageDefinition(
        name="feature_screening",
        description="Screen critical sensors with FDR-adjusted statistical tests",
        module_path="src.feature_screening",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="spc_engine",
        description="Compute SPC limits, Western Electric rules 1-4, EWMA, and Hotelling T2",
        module_path="src.spc_engine",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="spc_backtest",
        description="Chronological backtest comparing univariate vs multivariate early detection",
        module_path="src.spc_backtest",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="rca_pareto",
        description="Scrap cost and downtime minutes Pareto 80/20 concentration analysis",
        module_path="src.rca_pareto",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="rca_statistical",
        description="Cross-system statistical root cause analysis (chi-square, bottlenecks, sensors)",
        module_path="src.rca_statistical",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="oee_whatif",
        description="OEE uplift scenario modeling, bottleneck recovery, and financial value",
        module_path="src.oee_whatif",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="manual_baseline",
        description="Manual Excel baseline replication, step timing, and labor savings quantification",
        module_path="src.manual_baseline",
        function_name="run",
        db_dependent=False,
    ),
    StageDefinition(
        name="powerbi_model",
        description="Power BI semantic model validation and SQL-to-DAX KPI reconciliation",
        module_path="src.powerbi_model",
        function_name="run",
        db_dependent=True,
    ),
    StageDefinition(
        name="dashboard_spec",
        description="7-page Power BI dashboard visual mappings, layout specs, and assembly guide",
        module_path="src.dashboard_spec",
        function_name="run",
        db_dependent=False,
    ),
]


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _setup_logging(log_file: Path | None = None, verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    format_str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(str(log_file), mode="w", encoding="utf-8"))

    logging.basicConfig(level=level, format=format_str, handlers=handlers, force=True)


def _serialize_for_json(obj: Any) -> Any:
    """Helper to convert non-serializable objects (Paths, Sets, etc.) to JSON primitives."""
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, tuple)):
        return [_serialize_for_json(v) for v in obj]
    if isinstance(obj, dict):
        return {str(k): _serialize_for_json(v) for k, v in obj.items()}
    if hasattr(obj, "to_dict"):
        return _serialize_for_json(obj.to_dict())
    return obj


def run_pipeline(
    config_path: str | Path | None = None,
    stages: Sequence[str] | None = None,
    skip_db: bool = False,
    dry_run: bool = False,
    log_file: Path | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Execute the full end-to-end pipeline with stage tracking and execution logging."""
    started_wall = datetime.now(timezone.utc)
    started_perf = time.perf_counter()

    repo_root = _repository_root()
    config = load_config(config_path)
    reports_dir = repo_root / config["paths"]["reports"]
    reports_dir.mkdir(parents=True, exist_ok=True)

    if log_file is None:
        log_file = reports_dir / "pipeline_run.log"

    _setup_logging(log_file=log_file, verbose=verbose)
    logger.info("================================================================")
    logger.info("Starting Production Yield Loss & OEE Early-Warning Pipeline")
    logger.info("================================================================")
    logger.info(f"Configuration: {config_path or 'src/config.yaml'}")
    logger.info(f"Reports Directory: {reports_dir}")
    logger.info(f"Skip Database Stages: {skip_db}")
    logger.info(f"Dry Run Mode: {dry_run}")

    available_stages = {s.name: s for s in DEFAULT_STAGES}

    if stages:
        invalid = [s for s in stages if s not in available_stages]
        if invalid:
            raise ValueError(f"Unknown stage(s) specified: {invalid}. Available: {list(available_stages.keys())}")
        stages_to_run = [available_stages[s] for s in stages]
    else:
        stages_to_run = DEFAULT_STAGES

    stage_results: list[dict[str, Any]] = []
    pipeline_status = "SUCCESS"
    failure_stage: str | None = None
    failure_error: str | None = None

    for stage in stages_to_run:
        stage_started_wall = datetime.now(timezone.utc)
        stage_started_perf = time.perf_counter()

        stage_record: dict[str, Any] = {
            "name": stage.name,
            "description": stage.description,
            "db_dependent": stage.db_dependent,
            "started_at": stage_started_wall.isoformat(),
            "completed_at": None,
            "duration_seconds": 0.0,
            "status": "PENDING",
            "outputs": None,
            "error": None,
        }

        if skip_db and stage.db_dependent:
            logger.info(f"[STAGE: {stage.name}] SKIPPED (database stages disabled via --skip-db)")
            stage_record["status"] = "SKIPPED"
            stage_record["completed_at"] = datetime.now(timezone.utc).isoformat()
            stage_record["duration_seconds"] = 0.0
            stage_results.append(stage_record)
            continue

        if dry_run:
            logger.info(f"[STAGE: {stage.name}] DRY-RUN (simulated execution)")
            stage_record["status"] = "DRY_RUN"
            stage_record["completed_at"] = datetime.now(timezone.utc).isoformat()
            stage_record["duration_seconds"] = 0.0
            stage_record["outputs"] = {"simulated": True}
            stage_results.append(stage_record)
            continue

        logger.info(f"--> [STAGE: {stage.name}] Starting: {stage.description}")
        try:
            func = stage.get_callable()
            outputs = func(config_path)
            duration = round(time.perf_counter() - stage_started_perf, 3)
            stage_completed_wall = datetime.now(timezone.utc)

            stage_record["status"] = "SUCCESS"
            stage_record["completed_at"] = stage_completed_wall.isoformat()
            stage_record["duration_seconds"] = duration
            stage_record["outputs"] = _serialize_for_json(outputs)
            logger.info(f"<-- [STAGE: {stage.name}] COMPLETED successfully in {duration:.2f}s")
            stage_results.append(stage_record)

        except Exception as exc:
            duration = round(time.perf_counter() - stage_started_perf, 3)
            stage_completed_wall = datetime.now(timezone.utc)
            stage_record["status"] = "FAILED"
            stage_record["completed_at"] = stage_completed_wall.isoformat()
            stage_record["duration_seconds"] = duration
            stage_record["error"] = str(exc)
            logger.error(f"<-- [STAGE: {stage.name}] FAILED after {duration:.2f}s: {exc}", exc_info=True)
            stage_results.append(stage_record)

            pipeline_status = "FAILED"
            failure_stage = stage.name
            failure_error = str(exc)
            break

    total_duration = round(time.perf_counter() - started_perf, 3)
    completed_wall = datetime.now(timezone.utc)

    summary: dict[str, Any] = {
        "pipeline_name": "Production Yield Loss & OEE Early-Warning Pipeline",
        "status": pipeline_status,
        "started_at": started_wall.isoformat(),
        "completed_at": completed_wall.isoformat(),
        "total_duration_seconds": total_duration,
        "stages_executed": len(stage_results),
        "stages_succeeded": sum(1 for s in stage_results if s["status"] in ("SUCCESS", "DRY_RUN")),
        "stages_failed": sum(1 for s in stage_results if s["status"] == "FAILED"),
        "stages_skipped": sum(1 for s in stage_results if s["status"] == "SKIPPED"),
        "failure_stage": failure_stage,
        "failure_error": failure_error,
        "environment": {
            "python_version": sys.version,
            "platform": platform.platform(),
            "config_path": str(config_path) if config_path else "src/config.yaml",
        },
        "stages": stage_results,
    }

    summary_file = reports_dir / "pipeline_run_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("================================================================")
    logger.info(f"Pipeline finished with status: {pipeline_status} in {total_duration:.2f}s")
    logger.info(f"Run summary written to: {summary_file}")
    logger.info(f"Execution log written to: {log_file}")
    logger.info("================================================================")

    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Run pipeline as CLI executable."""
    parser = argparse.ArgumentParser(
        description="Production Yield Loss & OEE Early-Warning System — End-to-End Orchestrator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to repository YAML configuration file",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="Skip database loading, SQL DQ checks, and DB-dependent reconciliation",
    )
    parser.add_argument(
        "--stages",
        type=str,
        default=None,
        help="Comma-separated list of stages to execute (e.g. 'ingest_secom,simulate_mes')",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate configuration and stage availability without executing processing",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Custom path for execution log file output",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed DEBUG logging output",
    )

    args = parser.parse_args(argv)

    stage_list = [s.strip() for s in args.stages.split(",") if s.strip()] if args.stages else None

    try:
        summary = run_pipeline(
            config_path=args.config,
            stages=stage_list,
            skip_db=args.skip_db,
            dry_run=args.dry_run,
            log_file=args.log_file,
            verbose=args.verbose,
        )
    except Exception as exc:
        print(f"Pipeline orchestration error: {exc}", file=sys.stderr)
        return 1

    return 0 if summary["status"] == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
