"""Deterministically ingest the UCI MetroPT-3 industrial time-series source."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.config_loader import load_config


TIMESTAMP_COLUMN = "timestamp"
ANALOG_SIGNALS = (
    "TP2",
    "TP3",
    "H1",
    "DV_pressure",
    "Reservoirs",
    "Oil_temperature",
    "Motor_current",
)
DIGITAL_SIGNALS = (
    "COMP",
    "DV_eletric",
    "Towers",
    "MPG",
    "LPS",
    "Pressure_switch",
    "Oil_level",
    "Caudal_impulses",
)
SOURCE_INDEX_COLUMN = "Unnamed: 0"
OUTPUT_INDEX_COLUMN = "source_index"
_OUTPUT_KEYS = (
    "processed_readings",
    "failure_intervals",
    "state_periods",
    "ingestion_summary",
)
_PERIOD_COLUMNS = (
    "period_id",
    "operating_state",
    "start_timestamp",
    "end_timestamp",
    "row_count",
    "duration_seconds",
)
_INTERVAL_COLUMNS = (
    "event_id",
    "kind",
    "window_start",
    "window_end",
    "readings_in_window",
    "prefailure_readings",
)
_TIMESTAMP_OUTPUT_FORMAT = "%Y-%m-%d %H:%M:%S"


def classify_operating_state(current_amps: float, thresholds: Mapping[str, float]) -> str:
    """Map motor current to an operating state using configured bands."""

    if current_amps < thresholds["off_amps_below"]:
        return "off"
    if current_amps < thresholds["offloaded_amps_below"]:
        return "offloaded"
    if current_amps < thresholds["load_amps_below"]:
        return "load"
    return "starting"


def run(config_path: str | Path | None = None) -> dict[str, Path]:
    """Stream the MetroPT-3 source into deterministic processed outputs."""

    config = load_config(config_path)
    metropt_config = _metropt_config(config)
    source_path = _source_path(config, metropt_config)
    header, leading_empty_index = _read_csv_header(source_path)
    _require_columns(header, {TIMESTAMP_COLUMN, *ANALOG_SIGNALS, *DIGITAL_SIGNALS})
    signal_columns = [column for column in header if column in {*ANALOG_SIGNALS, *DIGITAL_SIGNALS}]
    if len(signal_columns) != len(ANALOG_SIGNALS) + len(DIGITAL_SIGNALS):
        raise ValueError("MetroPT-3 source is missing expected signal columns.")
    keep_index = SOURCE_INDEX_COLUMN in header or leading_empty_index
    if leading_empty_index:
        usecols = [0, header.index(TIMESTAMP_COLUMN)] + [
            header.index(column) for column in signal_columns
        ]
    else:
        index_usecol = (
            SOURCE_INDEX_COLUMN if SOURCE_INDEX_COLUMN in header else header[0]
        )
        usecols = (
            ([index_usecol] if keep_index else [])
            + [TIMESTAMP_COLUMN]
            + signal_columns
        )
    events = _parse_failure_events(metropt_config["failure_events"])
    thresholds = _state_thresholds(metropt_config["operating_state"])
    prefailure_hours = float(metropt_config["prefailure_hours"])
    chunk_size = int(metropt_config["chunk_size"])
    expected_rows = int(metropt_config["expected_rows"])

    output_paths = _configured_output_paths(metropt_config)
    for output_path in output_paths.values():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    readings_columns = (
        ([OUTPUT_INDEX_COLUMN] if keep_index else [])
        + [TIMESTAMP_COLUMN]
        + signal_columns
        + ["operating_state", "failure_event_id", "in_failure_window", "in_prefailure_window"]
    )
    pd.DataFrame(columns=readings_columns).to_csv(
        output_paths["processed_readings"], index=False, lineterminator="\n"
    )
    pd.DataFrame(columns=_PERIOD_COLUMNS).to_csv(
        output_paths["state_periods"], index=False, lineterminator="\n"
    )

    tracker = _StreamTracker(events, thresholds, prefailure_hours)
    try:
        with pd.read_csv(source_path, usecols=usecols, chunksize=chunk_size) as chunks:
            for chunk in chunks:
                tracker.process_chunk(chunk, output_paths, readings_columns, keep_index)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ValueError(f"Unable to stream MetroPT-3 source: {exc}") from exc
    tracker.finish(output_paths)

    if tracker.total_rows != expected_rows:
        raise ValueError(
            f"MetroPT-3 row count {tracker.total_rows} does not match "
            f"configured expected_rows {expected_rows}."
        )

    _write_intervals(output_paths["failure_intervals"], events, tracker)
    summary = _build_summary(
        tracker=tracker,
        events=events,
        expected_rows=expected_rows,
        chunk_size=chunk_size,
        prefailure_hours=prefailure_hours,
        thresholds=thresholds,
        metropt_config=metropt_config,
        source_path=source_path,
        output_paths=output_paths,
    )
    _write_json(output_paths["ingestion_summary"], summary)
    return output_paths


def main(argv: Sequence[str] | None = None) -> int:
    """Run MetroPT-3 ingestion as a command-line program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        output_paths = run(args.config)
    except Exception as exc:  # pragma: no cover - CLI error boundary
        print(f"MetroPT-3 ingestion failed: {exc}", file=sys.stderr)
        return 1
    for key in _OUTPUT_KEYS:
        print(f"{key}: {output_paths[key]}")
    return 0


class _StreamTracker:
    """Accumulate validated rows, flags, and run-length state periods."""

    def __init__(
        self,
        events: list[dict[str, Any]],
        thresholds: Mapping[str, float],
        prefailure_hours: float,
    ) -> None:
        self._events = events
        self._thresholds = thresholds
        self._prefailure_hours = prefailure_hours
        self.total_rows = 0
        self.timestamp_min: pd.Timestamp | None = None
        self.timestamp_max: pd.Timestamp | None = None
        self.null_counts: dict[str, int] = {}
        self.state_counts: dict[str, int] = {}
        self.failure_rows = 0
        self.prefailure_rows = 0
        self.event_window_counts = [0] * len(events)
        self.event_prefailure_counts = [0] * len(events)
        self._open_period: dict[str, Any] | None = None
        self._period_id = 0

    def process_chunk(
        self,
        chunk: pd.DataFrame,
        output_paths: Mapping[str, Path],
        readings_columns: Sequence[str],
        keep_index: bool,
    ) -> None:
        if chunk.empty:
            return
        if keep_index and SOURCE_INDEX_COLUMN not in chunk.columns:
            chunk = chunk.rename(columns={chunk.columns[0]: SOURCE_INDEX_COLUMN})
        timestamps = _parse_timestamps(chunk[TIMESTAMP_COLUMN])
        _require_monotonic(timestamps, self.timestamp_max)
        signals = _validate_signals(chunk)
        for column in chunk.columns:
            nulls = int(chunk[column].isna().sum())
            if nulls:
                self.null_counts[column] = self.null_counts.get(column, 0) + nulls

        states = [
            classify_operating_state(float(value), self._thresholds)
            for value in signals["Motor_current"].tolist()
        ]
        failure_ids, in_failure, in_prefailure = _map_event_windows(
            timestamps, self._events, self._prefailure_hours
        )
        for event_id in failure_ids:
            if event_id:
                self.event_window_counts[event_id - 1] += 1
        for timestamp, flag in zip(timestamps, in_prefailure, strict=True):
            if flag:
                owner = _prefailure_owner(timestamp, self._events, self._prefailure_hours)
                self.event_prefailure_counts[owner - 1] += 1

        output = pd.DataFrame(
            {
                TIMESTAMP_COLUMN: timestamps.dt.strftime(_TIMESTAMP_OUTPUT_FORMAT),
                **{column: signals[column].tolist() for column in signals.columns},
                "operating_state": states,
                "failure_event_id": failure_ids,
                "in_failure_window": in_failure,
                "in_prefailure_window": in_prefailure,
            }
        )
        if keep_index:
            output.insert(0, OUTPUT_INDEX_COLUMN, chunk[SOURCE_INDEX_COLUMN].tolist())
        output = output.loc[:, list(readings_columns)]
        output.to_csv(
            output_paths["processed_readings"],
            mode="a",
            index=False,
            header=False,
            lineterminator="\n",
        )

        for timestamp, state in zip(timestamps, states, strict=True):
            self.state_counts[state] = self.state_counts.get(state, 0) + 1
            self._extend_period(state, timestamp, output_paths["state_periods"])
        self.failure_rows += int(sum(in_failure))
        self.prefailure_rows += int(sum(in_prefailure))
        self.total_rows += len(chunk)
        self.timestamp_min = (
            timestamps.min()
            if self.timestamp_min is None
            else min(self.timestamp_min, timestamps.min())
        )
        self.timestamp_max = timestamps.max()

    def finish(self, output_paths: Mapping[str, Path]) -> None:
        if self._open_period is not None:
            self._flush_period(output_paths["state_periods"])
        if self.total_rows == 0:
            raise ValueError("MetroPT-3 source contains no data rows.")

    def _extend_period(
        self, state: str, timestamp: pd.Timestamp, periods_path: Path
    ) -> None:
        if self._open_period is not None and self._open_period["operating_state"] != state:
            self._flush_period(periods_path)
        if self._open_period is None:
            self._period_id += 1
            self._open_period = {
                "period_id": self._period_id,
                "operating_state": state,
                "start_timestamp": timestamp,
                "end_timestamp": timestamp,
                "row_count": 1,
            }
            return
        self._open_period["end_timestamp"] = timestamp
        self._open_period["row_count"] += 1

    def _flush_period(self, output_path: Path) -> None:
        period = self._open_period
        assert period is not None
        duration = (
            period["end_timestamp"] - period["start_timestamp"]
        ).total_seconds()
        pd.DataFrame(
            [
                {
                    "period_id": period["period_id"],
                    "operating_state": period["operating_state"],
                    "start_timestamp": period["start_timestamp"].strftime(
                        _TIMESTAMP_OUTPUT_FORMAT
                    ),
                    "end_timestamp": period["end_timestamp"].strftime(
                        _TIMESTAMP_OUTPUT_FORMAT
                    ),
                    "row_count": period["row_count"],
                    "duration_seconds": duration,
                }
            ],
            columns=_PERIOD_COLUMNS,
        ).to_csv(
            output_path, mode="a", index=False, header=False, lineterminator="\n"
        )
        self._open_period = None


def _metropt_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    section = config.get("metropt3")
    if not isinstance(section, Mapping):
        raise ValueError("Configuration must contain a mapping at metropt3.")
    required = {
        "raw_filenames",
        "chunk_size",
        "expected_rows",
        "failure_events",
        "prefailure_hours",
        "operating_state",
        "outputs",
    }
    missing = sorted(required.difference(section))
    if missing:
        raise ValueError(f"Configuration metropt3 section is missing: {missing}.")
    filenames = section["raw_filenames"]
    if not isinstance(filenames, Mapping) or "readings" not in filenames:
        raise ValueError("Configuration metropt3.raw_filenames must define readings.")
    if not isinstance(section["chunk_size"], int) or section["chunk_size"] <= 0:
        raise ValueError("Configuration metropt3.chunk_size must be a positive integer.")
    if not isinstance(section["expected_rows"], int) or section["expected_rows"] <= 0:
        raise ValueError("Configuration metropt3.expected_rows must be a positive integer.")
    if not isinstance(section["failure_events"], list) or not section["failure_events"]:
        raise ValueError("Configuration metropt3.failure_events must be a non-empty list.")
    hours = section["prefailure_hours"]
    if not isinstance(hours, (int, float)) or hours <= 0:
        raise ValueError("Configuration metropt3.prefailure_hours must be positive.")
    state = section["operating_state"]
    if not isinstance(state, Mapping):
        raise ValueError("Configuration metropt3.operating_state must be a mapping.")
    outputs = section["outputs"]
    if not isinstance(outputs, Mapping) or not set(_OUTPUT_KEYS).issubset(outputs):
        raise ValueError(
            f"Configuration metropt3.outputs must define: {', '.join(_OUTPUT_KEYS)}."
        )
    _state_thresholds(state)
    _parse_failure_events(section["failure_events"])
    return section


def _state_thresholds(state: Mapping[str, Any]) -> dict[str, float]:
    required = {"off_amps_below", "offloaded_amps_below", "load_amps_below"}
    missing = sorted(required.difference(state))
    if missing:
        raise ValueError(f"Configuration metropt3.operating_state is missing: {missing}.")
    thresholds = {key: float(state[key]) for key in required}
    if not (
        0 < thresholds["off_amps_below"]
        < thresholds["offloaded_amps_below"]
        < thresholds["load_amps_below"]
    ):
        raise ValueError(
            "Configuration metropt3.operating_state thresholds must be "
            "strictly increasing positive values."
        )
    return thresholds


def _parse_failure_events(events: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    parsed: list[dict[str, Any]] = []
    seen_ids: set[int] = set()
    for event in events:
        if not isinstance(event, Mapping):
            raise ValueError("Configuration metropt3.failure_events entries must be mappings.")
        for key in ("id", "start", "end", "kind"):
            if key not in event:
                raise ValueError(f"Failure event is missing required key: {key}.")
        event_id = int(event["id"])
        if event_id in seen_ids:
            raise ValueError(f"Duplicate failure event id: {event_id}.")
        seen_ids.add(event_id)
        try:
            start = pd.Timestamp(str(event["start"]))
            end = pd.Timestamp(str(event["end"]))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Failure event {event_id} has unparsable bounds.") from exc
        if start > end:
            raise ValueError(f"Failure event {event_id} start is after its end.")
        parsed.append(
            {"id": event_id, "start": start, "end": end, "kind": str(event["kind"])}
        )
    parsed.sort(key=lambda item: item["start"])
    for first, second in zip(parsed, parsed[1:], strict=False):
        if first["end"] >= second["start"]:
            raise ValueError("Failure events must not overlap.")
    return parsed


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _source_path(config: Mapping[str, Any], metropt_config: Mapping[str, Any]) -> Path:
    paths = config.get("paths")
    if not isinstance(paths, Mapping) or "raw" not in paths:
        raise ValueError("Configuration must contain paths.raw for MetroPT-3 source.")
    raw_directory = _resolve_configured_path(paths["raw"])
    return raw_directory / str(metropt_config["raw_filenames"]["readings"])


def _configured_output_paths(metropt_config: Mapping[str, Any]) -> dict[str, Path]:
    outputs = metropt_config["outputs"]
    return {key: _resolve_configured_path(outputs[key]) for key in _OUTPUT_KEYS}


def _read_csv_header(path: Path) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"MetroPT-3 source file is missing: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source_file:
            header = next(csv.reader(source_file, strict=True), None)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Unable to read MetroPT-3 CSV header at {path}: {exc}") from exc
    if not header:
        raise ValueError("MetroPT-3 CSV header is missing.")
    if any(not column for column in header[1:]):
        raise ValueError("MetroPT-3 CSV header is missing or contains empty columns.")
    duplicates = sorted({column for column in header[1:] if header.count(column) > 1})
    if duplicates:
        raise ValueError(f"MetroPT-3 CSV header has duplicate column(s): {duplicates}.")
    return header, header[0] == ""


def _require_columns(header: Sequence[str], required: set[str]) -> None:
    missing = sorted(required.difference(header))
    if missing:
        raise ValueError(f"MetroPT-3 CSV is missing required column(s): {missing}.")


def _parse_timestamps(values: pd.Series) -> pd.Series:
    try:
        parsed = pd.to_datetime(values, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"MetroPT-3 timestamp values are unparsable: {exc}") from exc
    if parsed.isna().any():
        raise ValueError("MetroPT-3 timestamp column contains missing values.")
    return parsed


def _require_monotonic(timestamps: pd.Series, previous_max: pd.Timestamp | None) -> None:
    if previous_max is not None and timestamps.min() < previous_max:
        raise ValueError("MetroPT-3 timestamps must be non-decreasing in source order.")
    if (timestamps.diff().dropna() < pd.Timedelta(0)).any():
        raise ValueError("MetroPT-3 timestamps must be non-decreasing in source order.")


def _validate_signals(chunk: pd.DataFrame) -> pd.DataFrame:
    signals = pd.DataFrame(index=chunk.index)
    for column in (*ANALOG_SIGNALS, *DIGITAL_SIGNALS):
        try:
            values = pd.to_numeric(chunk[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"MetroPT-3 signal column {column} must contain only numeric values."
            ) from exc
        if values.isna().any():
            raise ValueError(
                f"MetroPT-3 signal column {column} contains missing values."
            )
        signals[column] = values
    for column in DIGITAL_SIGNALS:
        if not signals[column].isin([0, 1]).all():
            raise ValueError(
                f"MetroPT-3 digital column {column} must contain only 0 or 1 values."
            )
    return signals


def _map_event_windows(
    timestamps: pd.Series,
    events: Sequence[Mapping[str, Any]],
    prefailure_hours: float,
) -> tuple[list[int], list[int], list[int]]:
    failure_ids: list[int] = []
    in_failure: list[int] = []
    in_prefailure: list[int] = []
    for timestamp in timestamps:
        event_id = 0
        for event in events:
            if event["start"] <= timestamp <= event["end"]:
                event_id = int(event["id"])
                break
        failure_ids.append(event_id)
        in_failure.append(1 if event_id else 0)
        prefailure = 0
        if not event_id:
            for event in events:
                window_start = event["start"] - pd.Timedelta(hours=prefailure_hours)
                if window_start <= timestamp < event["start"]:
                    prefailure = 1
                    break
        in_prefailure.append(prefailure)
    return failure_ids, in_failure, in_prefailure


def _prefailure_owner(
    timestamp: pd.Timestamp,
    events: Sequence[Mapping[str, Any]],
    prefailure_hours: float,
) -> int:
    for event in events:
        window_start = event["start"] - pd.Timedelta(hours=prefailure_hours)
        if window_start <= timestamp < event["start"]:
            return int(event["id"])
    raise ValueError(f"Timestamp {timestamp} is not in any pre-failure window.")


def _write_intervals(
    path: Path, events: Sequence[Mapping[str, Any]], tracker: _StreamTracker
) -> None:
    rows = [
        {
            "event_id": event["id"],
            "kind": event["kind"],
            "window_start": event["start"].strftime(_TIMESTAMP_OUTPUT_FORMAT),
            "window_end": event["end"].strftime(_TIMESTAMP_OUTPUT_FORMAT),
            "readings_in_window": tracker.event_window_counts[position],
            "prefailure_readings": tracker.event_prefailure_counts[position],
        }
        for position, event in enumerate(events)
    ]
    pd.DataFrame(rows, columns=_INTERVAL_COLUMNS).to_csv(
        path, index=False, lineterminator="\n"
    )


def _build_summary(
    *,
    tracker: _StreamTracker,
    events: Sequence[Mapping[str, Any]],
    expected_rows: int,
    chunk_size: int,
    prefailure_hours: float,
    thresholds: Mapping[str, float],
    metropt_config: Mapping[str, Any],
    source_path: Path,
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    return {
        "total_rows": tracker.total_rows,
        "expected_rows": expected_rows,
        "timestamp_min": tracker.timestamp_min.strftime(_TIMESTAMP_OUTPUT_FORMAT)
        if tracker.timestamp_min is not None
        else None,
        "timestamp_max": tracker.timestamp_max.strftime(_TIMESTAMP_OUTPUT_FORMAT)
        if tracker.timestamp_max is not None
        else None,
        "null_counts": dict(tracker.null_counts),
        "state_counts": dict(tracker.state_counts),
        "failure_window_rows": tracker.failure_rows,
        "prefailure_window_rows": tracker.prefailure_rows,
        "failure_events": [
            {
                "id": event["id"],
                "kind": event["kind"],
                "start": event["start"].strftime(_TIMESTAMP_OUTPUT_FORMAT),
                "end": event["end"].strftime(_TIMESTAMP_OUTPUT_FORMAT),
            }
            for event in events
        ],
        "prefailure_hours": prefailure_hours,
        "operating_state_thresholds": dict(thresholds),
        "chunk_size": chunk_size,
        "paths": {
            "source": str(source_path),
            **{key: str(path) for key, path in output_paths.items()},
        },
        "assumptions": {
            "failure_windows_documented_not_observed": str(
                metropt_config.get("failure_events_note", "")
            ),
            "operating_state_rule": str(
                metropt_config.get("operating_state", {}).get("note", "")
            ),
            "observed_cadence_note": "Source timestamps advance ~10s (0.1 Hz observed); "
            "UCI page states both 1 Hz and 0.1 Hz in different sections.",
        },
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True, ensure_ascii=False)
        output_file.write("\n")


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
