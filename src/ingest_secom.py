"""Load and deterministically clean the UCI SECOM dataset."""

from __future__ import annotations

import argparse
import io
import json
import re
import shlex
import shutil
import sys
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pandas as pd

from src.config_loader import load_config


TARGET_MAPPING = {
    -1: {"target": 0, "target_label": "pass"},
    1: {"target": 1, "target_label": "fail"},
}
_TARGET_TOKEN = re.compile(r"^[+-]?(?:1(?:\.0*)?)$")
_PROFILE_COLUMNS = ("sensor", "missing_count", "missing_fraction", "zero_variance")
_OUTPUT_KEYS = ("cleaned_data", "missingness_profile", "cleaning_summary")
_TIMESTAMP_FORMATS = ("%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S")


def load_secom_files(
    sensor_path: str | Path,
    labels_path: str | Path,
) -> tuple[pd.DataFrame, list[str]]:
    """Load SECOM sensor values, labels, and parsed timestamps.

    The returned frame contains ``timestamp`` and ``target_raw`` metadata columns
    followed by deterministic ``sensor_NNN`` columns in source order.  The sensor
    matrix is not imputed and source row order is retained.
    """

    sensor_file = Path(sensor_path)
    labels_file = Path(labels_path)

    try:
        sensor_frame = pd.read_csv(
            sensor_file,
            sep=r"\s+",
            header=None,
            na_values=["NaN"],
            keep_default_na=True,
            engine="python",
        )
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ValueError(f"Unable to read SECOM sensor file {sensor_file}: {exc}") from exc

    if sensor_frame.empty or sensor_frame.shape[1] == 0:
        raise ValueError(f"SECOM sensor file {sensor_file} contains no sensor values.")

    try:
        sensor_frame = sensor_frame.apply(pd.to_numeric, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"SECOM sensor file {sensor_file} contains non-numeric values.") from exc

    sensor_columns = [f"sensor_{index:03d}" for index in range(sensor_frame.shape[1])]
    sensor_frame.columns = sensor_columns
    label_frame = _load_label_timestamp_file(labels_file)

    if len(sensor_frame) != len(label_frame):
        raise ValueError(
            "SECOM sensor and label row counts do not match: "
            f"{len(sensor_frame)} != {len(label_frame)}."
        )

    raw = pd.concat(
        [label_frame.reset_index(drop=True), sensor_frame.reset_index(drop=True)],
        axis=1,
    )
    return raw, sensor_columns


def clean_secom(
    raw: pd.DataFrame,
    sensor_columns: Sequence[str],
    high_null_threshold: float = 0.50,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Apply SECOM cleaning rules without imputing sensor values.

    Sensors with ``missing_fraction > high_null_threshold`` are removed first.
    Zero variance is then evaluated from non-null values for the remaining
    sensors.  The profile always describes every original sensor.
    """

    if not 0 <= high_null_threshold <= 1:
        raise ValueError("high_null_threshold must be between 0 and 1 inclusive.")
    if not isinstance(raw, pd.DataFrame):
        raise TypeError("raw must be a pandas DataFrame.")
    if raw.empty:
        raise ValueError("SECOM input contains no rows.")

    sensors = list(sensor_columns)
    if not sensors:
        raise ValueError("sensor_columns must contain at least one sensor.")
    if len(set(sensors)) != len(sensors):
        raise ValueError("sensor_columns must not contain duplicates.")

    required_metadata = {"timestamp", "target_raw"}
    missing_metadata = sorted(required_metadata.difference(raw.columns))
    if missing_metadata:
        raise ValueError(f"SECOM raw data is missing metadata column(s): {missing_metadata}.")
    missing_sensors = [sensor for sensor in sensors if sensor not in raw.columns]
    if missing_sensors:
        raise ValueError(f"SECOM raw data is missing sensor column(s): {missing_sensors}.")

    try:
        target_raw = pd.to_numeric(raw["target_raw"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("SECOM target_raw values must be numeric -1 or 1 values.") from exc
    if target_raw.isna().any() or (target_raw % 1 != 0).any():
        raise ValueError("SECOM target_raw values must be integer -1 or 1 values.")
    target_raw = target_raw.astype("int64")
    invalid_targets = sorted(set(target_raw.unique()).difference(TARGET_MAPPING))
    if invalid_targets:
        raise ValueError(f"SECOM target_raw contains unsupported values: {invalid_targets}.")

    timestamps = pd.to_datetime(raw["timestamp"], errors="coerce")
    invalid_timestamps = timestamps.isna()
    if invalid_timestamps.any():
        rows = [index + 1 for index in invalid_timestamps[invalid_timestamps].index]
        raise ValueError(f"Invalid SECOM timestamp value(s) at row(s): {rows}.")

    try:
        sensor_matrix = raw.loc[:, sensors].apply(pd.to_numeric, errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("SECOM sensor values must be numeric or NaN.") from exc

    missing_counts = sensor_matrix.isna().sum().astype("int64")
    missing_fractions = missing_counts.astype("float64") / len(sensor_matrix)
    high_null_flags = missing_fractions > high_null_threshold
    zero_variance_flags = pd.Series(
        {
            sensor: sensor_matrix[sensor].dropna().nunique(dropna=True) <= 1
            for sensor in sensors
        },
        dtype="bool",
    )

    profile = pd.DataFrame(
        {
            "sensor": sensors,
            "missing_count": [int(missing_counts[sensor]) for sensor in sensors],
            "missing_fraction": [float(missing_fractions[sensor]) for sensor in sensors],
            "zero_variance": [bool(zero_variance_flags[sensor]) for sensor in sensors],
        },
        columns=_PROFILE_COLUMNS,
    )

    removed_high_null = [
        sensor for sensor in sensors if bool(high_null_flags[sensor])
    ]
    removed_zero_variance = [
        sensor
        for sensor in sensors
        if not bool(high_null_flags[sensor]) and bool(zero_variance_flags[sensor])
    ]
    removed = set(removed_high_null).union(removed_zero_variance)
    retained_sensors = [sensor for sensor in sensors if sensor not in removed]

    normalized_target = target_raw.map({-1: 0, 1: 1}).astype("int64")
    target_label = normalized_target.map({0: "pass", 1: "fail"})
    metadata = pd.DataFrame(
        {
            "timestamp": timestamps.reset_index(drop=True),
            "target_raw": target_raw.reset_index(drop=True),
            "target": normalized_target.reset_index(drop=True),
            "target_label": target_label.reset_index(drop=True),
        }
    )
    retained_matrix = sensor_matrix.loc[:, retained_sensors].reset_index(drop=True)
    cleaned = pd.concat([metadata, retained_matrix], axis=1)

    target_distribution = {
        label: int((target_label == label).sum()) for label in ("pass", "fail")
    }
    timestamp_range = {
        "min": pd.Timestamp(timestamps.min()).isoformat(),
        "max": pd.Timestamp(timestamps.max()).isoformat(),
    }
    target_mapping = {
        str(raw_value): dict(mapping)
        for raw_value, mapping in sorted(TARGET_MAPPING.items())
    }
    summary: dict[str, Any] = {
        "original_row_count": int(len(raw)),
        "original_sensor_count": int(len(sensors)),
        "removed_high_null_sensors": {
            "names": removed_high_null,
            "count": int(len(removed_high_null)),
        },
        "removed_zero_variance_sensors": {
            "names": removed_zero_variance,
            "count": int(len(removed_zero_variance)),
        },
        "final_sensor_count": int(len(retained_sensors)),
        "target_distribution": target_distribution,
        "timestamp_range": timestamp_range,
        "target_mapping": target_mapping,
        "high_null_threshold": float(high_null_threshold),
        "threshold_metadata": {
            "high_null_rule": "remove when missing_fraction > high_null_threshold",
            "zero_variance_rule": (
                "remove non-high-null sensors with at most one distinct non-null value"
            ),
        },
        "output_paths": {},
    }
    return cleaned, profile, summary


def write_cleaning_outputs(
    cleaned: pd.DataFrame,
    profile: pd.DataFrame,
    summary: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Path]:
    """Write deterministic cleaned CSV, profile CSV, and summary JSON files."""

    output_paths = _configured_output_paths(config)
    for output_path in output_paths.values():
        output_path.parent.mkdir(parents=True, exist_ok=True)

    cleaned.to_csv(output_paths["cleaned_data"], index=False, lineterminator="\n")
    profile.to_csv(
        output_paths["missingness_profile"],
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )

    summary_payload = dict(summary)
    summary_payload["output_paths"] = {
        key: str(path) for key, path in output_paths.items()
    }
    secom_config = _secom_config(config)
    summary_payload["output_metadata"] = {
        "source_url": str(secom_config["source_url"]),
        "raw_filenames": dict(secom_config["raw_filenames"]),
    }
    with output_paths["cleaning_summary"].open(
        "w", encoding="utf-8", newline="\n"
    ) as summary_file:
        json.dump(summary_payload, summary_file, indent=2, sort_keys=True, ensure_ascii=False)
        summary_file.write("\n")

    if isinstance(summary, dict):
        summary.clear()
        summary.update(summary_payload)
    return output_paths


def run(config_path: str | Path | None = None) -> dict[str, Path]:
    """Run the configured SECOM download, cleaning, and output pipeline."""

    config = load_config(config_path)
    sensor_path, labels_path = _ensure_raw_files(config)
    raw, sensor_columns = load_secom_files(sensor_path, labels_path)
    secom_config = _secom_config(config)
    cleaned, profile, summary = clean_secom(
        raw,
        sensor_columns,
        high_null_threshold=float(secom_config["high_null_threshold"]),
    )
    return write_cleaning_outputs(cleaned, profile, summary, config)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the SECOM pipeline as a command-line program."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Optional path to a repository-compatible YAML configuration file.",
    )
    args = parser.parse_args(argv)
    try:
        output_paths = run(args.config)
    except Exception as exc:  # pragma: no cover - CLI error boundary
        print(f"SECOM ingestion failed: {exc}", file=sys.stderr)
        return 1

    for key in _OUTPUT_KEYS:
        print(f"{key}: {output_paths[key]}")
    return 0


def _load_label_timestamp_file(path: Path) -> pd.DataFrame:
    """Parse a whitespace label file with either target/timestamp order."""

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Unable to read SECOM label file {path}: {exc}") from exc

    target_values: list[int] = []
    timestamp_texts: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        try:
            tokens = shlex.split(line, comments=False, posix=True)
        except ValueError as exc:
            raise ValueError(
                f"SECOM label file {path} line {line_number} has invalid quoting."
            ) from exc
        if not tokens:
            continue
        target_indexes = [
            index for index, token in enumerate(tokens) if _TARGET_TOKEN.fullmatch(token)
        ]
        if len(target_indexes) != 1:
            raise ValueError(
                f"SECOM label file {path} line {line_number} must contain one -1/1 target."
            )

        target_index = target_indexes[0]
        target_value = int(float(tokens[target_index]))
        timestamp_tokens = tokens[:target_index] + tokens[target_index + 1 :]
        if not timestamp_tokens:
            raise ValueError(
                f"SECOM label file {path} line {line_number} has no timestamp value."
            )
        target_values.append(target_value)
        timestamp_texts.append(" ".join(timestamp_tokens))

    if not target_values:
        raise ValueError(f"SECOM label file {path} contains no data rows.")

    timestamps = _parse_timestamps(timestamp_texts)
    invalid_timestamps = timestamps.isna()
    if invalid_timestamps.any():
        rows = [index + 1 for index in invalid_timestamps[invalid_timestamps].index]
        raise ValueError(f"Invalid SECOM timestamp value(s) at row(s): {rows}.")

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "target_raw": pd.Series(target_values, dtype="int64"),
        }
    )


def _parse_timestamps(timestamp_texts: Sequence[str]) -> pd.Series:
    """Parse supported SECOM timestamp formats with explicit format order."""

    timestamp_series = pd.Series(timestamp_texts, dtype="string")
    timestamps = pd.Series(
        pd.NaT,
        index=timestamp_series.index,
        dtype="datetime64[ns]",
    )
    for timestamp_format in _TIMESTAMP_FORMATS:
        remaining = timestamps.isna()
        if not remaining.any():
            break
        timestamps.loc[remaining] = pd.to_datetime(
            timestamp_series.loc[remaining],
            format=timestamp_format,
            errors="coerce",
        )
    return timestamps


def _secom_config(config: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return and minimally validate the configured SECOM section."""

    section = config.get("secom")
    if not isinstance(section, Mapping):
        raise ValueError("Configuration must contain a mapping at secom.")
    required = {"source_url", "raw_filenames", "high_null_threshold", "outputs"}
    missing = sorted(required.difference(section))
    if missing:
        raise ValueError(f"Configuration secom section is missing: {missing}.")
    raw_filenames = section["raw_filenames"]
    if not isinstance(raw_filenames, Mapping) or not {"sensor", "labels"}.issubset(
        raw_filenames
    ):
        raise ValueError("Configuration secom.raw_filenames must define sensor and labels.")
    outputs = section["outputs"]
    if not isinstance(outputs, Mapping) or not set(_OUTPUT_KEYS).issubset(outputs):
        raise ValueError(
            "Configuration secom.outputs must define cleaned_data, "
            "missingness_profile, and cleaning_summary."
        )
    return section


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _resolve_configured_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else _repository_root() / path


def _configured_output_paths(config: Mapping[str, Any]) -> dict[str, Path]:
    """Resolve configured output paths while keeping relative paths repository-local."""

    outputs = _secom_config(config)["outputs"]
    return {key: _resolve_configured_path(outputs[key]) for key in _OUTPUT_KEYS}


def _ensure_raw_files(config: Mapping[str, Any]) -> tuple[Path, Path]:
    """Return configured raw files, downloading the official archive when needed."""

    secom_config = _secom_config(config)
    paths = config.get("paths")
    if not isinstance(paths, Mapping) or "raw" not in paths:
        raise ValueError("Configuration must contain paths.raw for SECOM input files.")

    raw_directory = _resolve_configured_path(paths["raw"])
    raw_filenames = secom_config["raw_filenames"]
    sensor_path = raw_directory / str(raw_filenames["sensor"])
    labels_path = raw_directory / str(raw_filenames["labels"])
    if sensor_path.is_file() and labels_path.is_file():
        return sensor_path, labels_path

    raw_directory.mkdir(parents=True, exist_ok=True)
    try:
        with urllib.request.urlopen(str(secom_config["source_url"]), timeout=60) as response:
            archive_bytes = response.read()
    except (OSError, ValueError) as exc:
        raise RuntimeError(
            f"Unable to download the configured UCI SECOM archive: {exc}"
        ) from exc

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise RuntimeError("The configured UCI SECOM source is not a valid ZIP archive.") from exc

    with archive:
        members_by_basename: dict[str, list[str]] = {}
        for member in archive.namelist():
            if not member.endswith("/"):
                members_by_basename.setdefault(Path(member).name, []).append(member)

        for expected_name, destination in (
            (sensor_path.name, sensor_path),
            (labels_path.name, labels_path),
        ):
            if destination.is_file():
                continue
            matching_members = members_by_basename.get(expected_name, [])
            if len(matching_members) != 1:
                raise RuntimeError(
                    f"UCI SECOM archive does not contain one unambiguous {expected_name} file."
                )
            with archive.open(matching_members[0]) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)

    if not sensor_path.is_file() or not labels_path.is_file():
        raise RuntimeError("UCI SECOM archive extraction did not produce both configured raw files.")
    return sensor_path, labels_path


if __name__ == "__main__":  # pragma: no cover - exercised through the CLI
    raise SystemExit(main())
