"""Deterministically sample and stream the Bosch production-line source files."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_numeric_dtype

from src.config_loader import load_config


_NUMERIC_FEATURE = re.compile(r"^(L\d+)_(S\d+)_F\d+$")
_DATE_FEATURE = re.compile(r"^(L\d+)_(S\d+)_D\d+$")
_OUTPUT_KEYS = (
    "sampled_ids",
    "sampled_numeric",
    "station_timings",
    "ingestion_summary",
)
_STATION_OUTPUT_COLUMNS = (
    "Id",
    "line",
    "station",
    "station_start_time",
    "station_end_time",
    "dwell_time_units",
    "dwell_minutes",
)
_STATION_BUFFER_SIZE = 10_000


def sample_ids(ids: Iterable[int], sample_fraction: float, seed: int) -> list[int]:
    """Return a sorted, fixed-size uniform sample using only IDs and a seed."""

    if not 0 < sample_fraction <= 1:
        raise ValueError("sample_fraction must be greater than 0 and at most 1.")

    id_series = ids if isinstance(ids, pd.Series) else pd.Series(list(ids))
    values = _normalise_ids(id_series, "sampling IDs")
    if values.duplicated().any():
        raise ValueError("sampling IDs must be unique.")

    sample_size = round(len(values) * sample_fraction)
    selected = np.random.default_rng(seed).choice(
        values.to_numpy(dtype="int64"), size=sample_size, replace=False
    )
    return sorted(int(value) for value in selected.tolist())


def select_numeric_features(
    numeric_header: Sequence[str], features_per_station: int
) -> list[str]:
    """Select the first configured count of source-order numeric features per station."""

    if not isinstance(features_per_station, int) or features_per_station <= 0:
        raise ValueError("features_per_station must be a positive integer.")

    selected: list[str] = []
    counts_by_station: dict[tuple[str, str], int] = {}
    for column in numeric_header:
        match = _NUMERIC_FEATURE.fullmatch(column)
        if match is None:
            continue
        station = (match.group(1), match.group(2))
        selected_count = counts_by_station.get(station, 0)
        if selected_count < features_per_station:
            selected.append(column)
            counts_by_station[station] = selected_count + 1
    if not selected:
        raise ValueError(
            "Numeric header contains no Bosch Lx_Sy_Fz structural feature columns."
        )
    return selected


def run(config_path: str | Path | None = None) -> dict[str, Path]:
    """Run deterministic Bosch sampling and stream-filtered output generation."""

    config = load_config(config_path)
    bosch_config = _bosch_config(config)
    numeric_path, date_path = _source_paths(config, bosch_config)
    numeric_header = _read_csv_header(numeric_path, "numeric")
    date_header = _read_csv_header(date_path, "date")
    _require_columns(numeric_header, {"Id", "Response"}, "numeric")
    _require_columns(date_header, {"Id"}, "date")

    selected_features = select_numeric_features(
        numeric_header, int(bosch_config["features_per_station"])
    )
    station_groups = _date_station_groups(date_header)
    if not station_groups:
        raise ValueError("Date header contains no Bosch Lx_Sy_Dz station columns.")

    profile = _profile_numeric_source(numeric_path)
    expected_ids = sample_ids(
        profile["Id"],
        float(bosch_config["sample_fraction"]),
        int(config["random_seed"]),
    )
    output_paths = _configured_output_paths(bosch_config)
    for output_path in output_paths.values():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    sampled_ids = _load_or_write_sample_ids(output_paths["sampled_ids"], expected_ids)
    sampled_id_set = set(sampled_ids)
    chunk_size = int(bosch_config["chunk_size"])
    numeric_rows = _stream_numeric_rows(
        numeric_path,
        output_paths["sampled_numeric"],
        selected_features,
        sampled_id_set,
        chunk_size,
    )
    date_rows, station_record_count = _stream_station_timings(
        date_path,
        output_paths["station_timings"],
        station_groups,
        sampled_id_set,
        chunk_size,
        _time_conversion_config(bosch_config),
    )

    summary = _build_summary(
        profile=profile,
        sampled_ids=sampled_ids,
        sampled_id_set=sampled_id_set,
        configured_fraction=float(bosch_config["sample_fraction"]),
        numeric_rows=numeric_rows,
        date_rows=date_rows,
        station_record_count=station_record_count,
        selected_features=selected_features,
        station_groups=station_groups,
        seed=int(config["random_seed"]),
        chunk_size=chunk_size,
        numeric_path=numeric_path,
        date_path=date_path,
        output_paths=output_paths,
        time_conversion=_time_conversion_config(bosch_config),
    )
    _write_json(output_paths["ingestion_summary"], summary)
    return output_paths


def main(argv: Sequence[str] | None = None) -> int:
    """Run Bosch ingestion as a command-line program without downloading sources."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args(argv)
    try:
        output_paths = run(args.config)
    except Exception as exc:  # pragma: no cover - CLI error boundary
        print(f"Bosch ingestion failed: {exc}", file=sys.stderr)
        return 1
    for key in _OUTPUT_KEYS:
        print(f"{key}: {output_paths[key]}")
    return 0


def _bosch_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    section = config.get("bosch")
    if not isinstance(section, Mapping):
        raise ValueError("Configuration must contain a mapping at bosch.")
    required = {
        "raw_filenames",
        "sample_fraction",
        "chunk_size",
        "features_per_station",
        "time_conversion",
        "outputs",
    }
    missing = sorted(required.difference(section))
    if missing:
        raise ValueError(f"Configuration bosch section is missing: {missing}.")
    filenames = section["raw_filenames"]
    if not isinstance(filenames, Mapping) or not {"numeric", "date"}.issubset(filenames):
        raise ValueError("Configuration bosch.raw_filenames must define numeric and date.")
    if not isinstance(section["chunk_size"], int) or section["chunk_size"] <= 0:
        raise ValueError("Configuration bosch.chunk_size must be a positive integer.")
    if not isinstance(section["features_per_station"], int) or section["features_per_station"] <= 0:
        raise ValueError("Configuration bosch.features_per_station must be a positive integer.")
    fraction = section["sample_fraction"]
    if not isinstance(fraction, (int, float)) or not 0 < fraction <= 1:
        raise ValueError("Configuration bosch.sample_fraction must be in (0, 1].")
    outputs = section["outputs"]
    if not isinstance(outputs, Mapping) or not set(_OUTPUT_KEYS).issubset(outputs):
        raise ValueError(f"Configuration bosch.outputs must define: {', '.join(_OUTPUT_KEYS)}.")
    _time_conversion_config(section)
    return section


def _time_conversion_config(bosch_config: Mapping[str, Any]) -> Mapping[str, Any]:
    conversion = bosch_config["time_conversion"]
    if not isinstance(conversion, Mapping):
        raise ValueError("Configuration bosch.time_conversion must be a mapping.")
    required = {"enabled", "minutes_per_0_01_unit", "note"}
    missing = sorted(required.difference(conversion))
    if missing:
        raise ValueError(f"Configuration bosch.time_conversion is missing: {missing}.")
    if not isinstance(conversion["enabled"], bool):
        raise ValueError("Configuration bosch.time_conversion.enabled must be boolean.")
    minutes = conversion["minutes_per_0_01_unit"]
    if not isinstance(minutes, (int, float)) or minutes <= 0:
        raise ValueError(
            "Configuration bosch.time_conversion.minutes_per_0_01_unit must be positive."
        )
    return conversion


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _source_paths(
    config: Mapping[str, Any], bosch_config: Mapping[str, Any]
) -> tuple[Path, Path]:
    paths = config.get("paths")
    if not isinstance(paths, Mapping) or "raw" not in paths:
        raise ValueError("Configuration must contain paths.raw for Bosch source files.")
    raw_directory = _resolve_configured_path(paths["raw"])
    filenames = bosch_config["raw_filenames"]
    return (
        raw_directory / str(filenames["numeric"]),
        raw_directory / str(filenames["date"]),
    )


def _configured_output_paths(bosch_config: Mapping[str, Any]) -> dict[str, Path]:
    outputs = bosch_config["outputs"]
    return {key: _resolve_configured_path(outputs[key]) for key in _OUTPUT_KEYS}


def _read_csv_header(path: Path, source_name: str) -> list[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Bosch {source_name} source file is missing: {path}")
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as source_file:
            header = next(csv.reader(source_file, strict=True), None)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ValueError(f"Unable to read Bosch {source_name} CSV header at {path}: {exc}") from exc
    if not header or any(not column for column in header):
        raise ValueError(f"Bosch {source_name} CSV header is missing or contains empty columns.")
    duplicates = sorted({column for column in header if header.count(column) > 1})
    if duplicates:
        raise ValueError(f"Bosch {source_name} CSV header has duplicate column(s): {duplicates}.")
    return header


def _require_columns(header: Sequence[str], required: set[str], source_name: str) -> None:
    missing = sorted(required.difference(header))
    if missing:
        raise ValueError(f"Bosch {source_name} CSV is missing required column(s): {missing}.")


def _normalise_ids(values: pd.Series, context: str) -> pd.Series:
    if values.isna().any():
        raise ValueError(f"Bosch {context} contains missing Id values.")
    try:
        numeric = pd.to_numeric(values, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Bosch {context} contains non-numeric Id values.") from exc
    if numeric.isna().any() or (numeric % 1 != 0).any():
        raise ValueError(f"Bosch {context} contains non-integer Id values.")
    return numeric.astype("int64")


def _profile_numeric_source(numeric_path: Path) -> pd.DataFrame:
    try:
        profile = pd.read_csv(numeric_path, usecols=["Id", "Response"])
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ValueError(f"Unable to read Bosch numeric Id/Response profile: {exc}") from exc
    if profile.empty:
        raise ValueError("Bosch numeric source contains no data rows.")
    profile["Id"] = _normalise_ids(profile["Id"], "numeric source")
    if profile["Id"].duplicated().any():
        raise ValueError("Bosch numeric source contains duplicate Id values.")
    try:
        response = pd.to_numeric(profile["Response"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("Bosch numeric source contains non-numeric Response values.") from exc
    if response.isna().any() or (response % 1 != 0).any() or not response.isin([0, 1]).all():
        raise ValueError("Bosch numeric source Response values must be binary 0 or 1.")
    profile["Response"] = response.astype("int64")
    return profile


def _load_or_write_sample_ids(sample_path: Path, expected_ids: Sequence[int]) -> list[int]:
    if sample_path.exists():
        header = _read_csv_header(sample_path, "persisted sample")
        _require_columns(header, {"Id"}, "persisted sample")
        if header != ["Id"]:
            raise ValueError("Persisted Bosch sampled-ID CSV must contain exactly one Id column.")
        persisted = pd.read_csv(sample_path, usecols=["Id"])
        actual_ids = _normalise_ids(persisted["Id"], "persisted sample")
        if actual_ids.duplicated().any():
            raise ValueError("Persisted Bosch sampled-ID CSV contains duplicate Id values.")
        actual = actual_ids.tolist()
        if actual != list(expected_ids):
            raise ValueError(
                "Persisted Bosch sampled-ID CSV does not match the deterministic "
                "sample for the current source, fraction, and seed."
            )
        return actual
    pd.DataFrame({"Id": list(expected_ids)}).to_csv(
        sample_path, index=False, lineterminator="\n"
    )
    return list(expected_ids)


def _stream_numeric_rows(
    numeric_path: Path,
    output_path: Path,
    selected_features: Sequence[str],
    sampled_id_set: set[int],
    chunk_size: int,
) -> int:
    usecols = ["Id", "Response", *selected_features]
    pd.DataFrame(columns=usecols).to_csv(output_path, index=False, lineterminator="\n")
    retained_ids: set[int] = set()
    retained_rows = 0
    try:
        with pd.read_csv(numeric_path, usecols=usecols, chunksize=chunk_size) as chunks:
            for chunk in chunks:
                chunk["Id"] = _normalise_ids(chunk["Id"], "numeric chunk")
                _validate_wide_values(chunk, selected_features, "numeric selected feature")
                retained = chunk.loc[chunk["Id"].isin(sampled_id_set)]
                retained = retained.loc[:, usecols]
                retained_id_values = retained["Id"].tolist()
                _record_retained_ids(retained_id_values, retained_ids, "numeric")
                if not retained.empty:
                    retained.to_csv(
                        output_path,
                        mode="a",
                        index=False,
                        header=False,
                        lineterminator="\n",
                    )
                    retained_rows += len(retained)
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ValueError(f"Unable to stream Bosch numeric source: {exc}") from exc
    _validate_retained_ids(retained_ids, sampled_id_set, "numeric")
    return retained_rows


def _date_station_groups(date_header: Sequence[str]) -> list[tuple[str, str, list[str]]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for column in date_header:
        match = _DATE_FEATURE.fullmatch(column)
        if match is not None:
            groups.setdefault((match.group(1), match.group(2)), []).append(column)
    return [(line, station, columns) for (line, station), columns in groups.items()]


def _stream_station_timings(
    date_path: Path,
    output_path: Path,
    station_groups: Sequence[tuple[str, str, Sequence[str]]],
    sampled_id_set: set[int],
    chunk_size: int,
    time_conversion: Mapping[str, Any],
) -> tuple[int, int]:
    date_columns = [column for _, _, columns in station_groups for column in columns]
    usecols = ["Id", *date_columns]
    pd.DataFrame(columns=_STATION_OUTPUT_COLUMNS).to_csv(
        output_path, index=False, lineterminator="\n"
    )
    retained_ids: set[int] = set()
    source_rows_retained = 0
    station_record_count = 0
    buffer: list[dict[str, Any]] = []
    try:
        with pd.read_csv(date_path, usecols=usecols, chunksize=chunk_size) as chunks:
            for chunk in chunks:
                chunk["Id"] = _normalise_ids(chunk["Id"], "date chunk")
                _validate_wide_values(chunk, date_columns, "date feature")
                retained = chunk.loc[chunk["Id"].isin(sampled_id_set)]
                retained_id_values = retained["Id"].tolist()
                _record_retained_ids(retained_id_values, retained_ids, "date")
                source_rows_retained += len(retained)
                if retained.empty:
                    continue
                for row in retained.itertuples(index=False, name=None):
                    record = dict(zip(usecols, row, strict=True))
                    for line, station, columns in station_groups:
                        values = [record[column] for column in columns if pd.notna(record[column])]
                        if not values:
                            continue
                        start = min(values)
                        end = max(values)
                        dwell = end - start
                        station_row: dict[str, Any] = {
                            "Id": int(record["Id"]),
                            "line": line,
                            "station": station,
                            "station_start_time": start,
                            "station_end_time": end,
                            "dwell_time_units": dwell,
                            "dwell_minutes": np.nan,
                        }
                        if time_conversion["enabled"]:
                            station_row["dwell_minutes"] = (
                                dwell / 0.01 * float(time_conversion["minutes_per_0_01_unit"])
                            )
                        buffer.append(station_row)
                        station_record_count += 1
                        if len(buffer) >= _STATION_BUFFER_SIZE:
                            _append_station_rows(output_path, buffer)
                            buffer.clear()
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ValueError(f"Unable to stream Bosch date source: {exc}") from exc
    if buffer:
        _append_station_rows(output_path, buffer)
    _validate_retained_ids(retained_ids, sampled_id_set, "date")
    return source_rows_retained, station_record_count


def _append_station_rows(output_path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    pd.DataFrame(rows, columns=_STATION_OUTPUT_COLUMNS).to_csv(
        output_path, mode="a", index=False, header=False, lineterminator="\n"
    )


def _validate_wide_values(
    chunk: pd.DataFrame, columns: Sequence[str], source_name: str
) -> None:
    """Reject non-numeric selected values without changing raw source values."""

    for column in columns:
        values = chunk[column]
        if is_numeric_dtype(values):
            continue
        try:
            pd.to_numeric(values, errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Bosch {source_name} columns must contain only numeric values or NaN."
            ) from exc


def _record_retained_ids(ids: Sequence[int], seen: set[int], source_name: str) -> None:
    current_ids: set[int] = set()
    duplicate_ids: set[int] = set()
    for part_id in ids:
        if part_id in seen or part_id in current_ids:
            duplicate_ids.add(part_id)
        current_ids.add(part_id)
    if duplicate_ids:
        raise ValueError(
            f"Bosch {source_name} source contains duplicate sampled Id values: "
            f"{sorted(duplicate_ids)}."
        )
    seen.update(current_ids)


def _validate_retained_ids(
    retained_ids: set[int], sampled_id_set: set[int], source_name: str
) -> None:
    if retained_ids != sampled_id_set:
        missing = sorted(sampled_id_set.difference(retained_ids))
        unexpected = sorted(retained_ids.difference(sampled_id_set))
        raise ValueError(
            f"Bosch {source_name} sampled Id set does not align with persisted sample; "
            f"missing={missing[:10]}, unexpected={unexpected[:10]}."
        )


def _build_summary(
    *,
    profile: pd.DataFrame,
    sampled_ids: Sequence[int],
    sampled_id_set: set[int],
    configured_fraction: float,
    numeric_rows: int,
    date_rows: int,
    station_record_count: int,
    selected_features: Sequence[str],
    station_groups: Sequence[tuple[str, str, Sequence[str]]],
    seed: int,
    chunk_size: int,
    numeric_path: Path,
    date_path: Path,
    output_paths: Mapping[str, Path],
    time_conversion: Mapping[str, Any],
) -> dict[str, Any]:
    source_fail_count = int(profile["Response"].sum())
    source_pass_count = int(len(profile) - source_fail_count)
    sampled = profile.loc[profile["Id"].isin(sampled_id_set)]
    sampled_fail_count = int(sampled["Response"].sum())
    sampled_pass_count = int(len(sampled) - sampled_fail_count)
    source_failure_rate = source_fail_count / len(profile)
    sampled_failure_rate = sampled_fail_count / len(sampled_ids) if sampled_ids else 0.0
    return {
        "total_source_ids": int(len(profile)),
        "sampled_id_count": int(len(sampled_ids)),
        "configured_sample_fraction": configured_fraction,
        "actual_sample_fraction": len(sampled_ids) / len(profile),
        "source_pass_count": source_pass_count,
        "source_fail_count": source_fail_count,
        "sampled_pass_count": sampled_pass_count,
        "sampled_fail_count": sampled_fail_count,
        "source_failure_rate": source_failure_rate,
        "sampled_failure_rate": sampled_failure_rate,
        "failure_rate_difference": sampled_failure_rate - source_failure_rate,
        "numeric_rows_retained": int(numeric_rows),
        "date_rows_retained": int(date_rows),
        "station_record_count": int(station_record_count),
        "retained_numeric_features": list(selected_features),
        "retained_stations": [
            {"line": line, "station": station, "date_columns": list(columns)}
            for line, station, columns in station_groups
        ],
        "seed": seed,
        "chunk_size": chunk_size,
        "paths": {
            "numeric_source": str(numeric_path),
            "date_source": str(date_path),
            **{key: str(path) for key, path in output_paths.items()},
        },
        "time_conversion_assumption": {
            "enabled": bool(time_conversion["enabled"]),
            "minutes_per_0_01_unit": float(time_conversion["minutes_per_0_01_unit"]),
            "note": str(time_conversion["note"]),
            "observed_bosch_fact": False,
        },
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as output_file:
        json.dump(payload, output_file, indent=2, sort_keys=True, ensure_ascii=False)
        output_file.write("\n")


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
