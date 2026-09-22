import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.ingest_metropt3 import (
    ANALOG_SIGNALS,
    DIGITAL_SIGNALS,
    classify_operating_state,
    run,
)

THRESHOLDS = {"off_amps_below": 2.0, "offloaded_amps_below": 5.5, "load_amps_below": 8.0}

BASE_COLUMNS = ["Unnamed: 0", "timestamp", *ANALOG_SIGNALS, *DIGITAL_SIGNALS]


def _write_config(tmp_path, *, chunk_size=7, expected_rows=30):
    raw = tmp_path / "raw"
    processed = tmp_path / "processed"
    reports = tmp_path / "reports"
    raw.mkdir()
    config = {
        "paths": {
            "raw": str(raw),
            "interim": str(tmp_path / "interim"),
            "processed": str(processed),
            "reports": str(reports),
        },
        "database": {},
        "cost_assumptions": {},
        "spc": {},
        "random_seed": 42,
        "metropt3": {
            "source_url": "https://example.invalid/metropt3.zip",
            "source_doi": "10.24432/C5VW3R",
            "license": "CC-BY-4.0",
            "raw_filenames": {"readings": "metropt3.csv"},
            "chunk_size": chunk_size,
            "expected_rows": expected_rows,
            "failure_events": [
                {
                    "id": 1,
                    "start": "2020-04-18 00:02:00",
                    "end": "2020-04-18 00:03:00",
                    "kind": "Air leak",
                }
            ],
            "failure_events_note": "Fixture event.",
            "prefailure_hours": 1 / 60,
            "operating_state": {
                "note": "Fixture thresholds.",
                **THRESHOLDS,
            },
            "outputs": {
                "processed_readings": str(processed / "readings.csv"),
                "failure_intervals": str(processed / "intervals.csv"),
                "state_periods": str(processed / "periods.csv"),
                "ingestion_summary": str(reports / "summary.json"),
            },
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path, config


def _write_fixture(config, *, mutate=None):
    raw = Path(config["paths"]["raw"])
    stamps = pd.date_range("2020-04-18 00:00:00", periods=30, freq="10s")
    currents = [0.1, 4.0, 7.0, 9.0] + [7.0] * 26
    frame = pd.DataFrame({"Unnamed: 0": range(30), "timestamp": stamps.strftime("%Y-%m-%d %H:%M:%S")})
    for position, signal in enumerate(ANALOG_SIGNALS):
        if signal == "Motor_current":
            frame[signal] = currents
        else:
            frame[signal] = [10.0 + position + row / 100 for row in range(30)]
    for position, signal in enumerate(DIGITAL_SIGNALS):
        frame[signal] = [(row + position) % 2 for row in range(30)]
    if mutate is not None:
        mutate(frame)
    frame.to_csv(raw / "metropt3.csv", index=False, lineterminator="\n")


def test_classify_operating_state_uses_configured_boundaries():
    assert classify_operating_state(0.0, THRESHOLDS) == "off"
    assert classify_operating_state(1.999, THRESHOLDS) == "off"
    assert classify_operating_state(2.0, THRESHOLDS) == "offloaded"
    assert classify_operating_state(4.0, THRESHOLDS) == "offloaded"
    assert classify_operating_state(5.5, THRESHOLDS) == "load"
    assert classify_operating_state(7.0, THRESHOLDS) == "load"
    assert classify_operating_state(8.0, THRESHOLDS) == "starting"
    assert classify_operating_state(9.0, THRESHOLDS) == "starting"


def test_run_flags_windows_periods_and_is_deterministic(tmp_path):
    config_path, _ = _write_config(tmp_path)
    _write_fixture(_read_config(config_path))

    output_paths = run(config_path)
    first_bytes = {key: path.read_bytes() for key, path in output_paths.items()}
    assert run(config_path) is not None
    assert {key: path.read_bytes() for key, path in output_paths.items()} == first_bytes

    readings = pd.read_csv(output_paths["processed_readings"])
    assert readings.columns.tolist() == [
        "source_index",
        "timestamp",
        *ANALOG_SIGNALS,
        *DIGITAL_SIGNALS,
        "operating_state",
        "failure_event_id",
        "in_failure_window",
        "in_prefailure_window",
    ]
    assert len(readings) == 30
    assert readings["operating_state"].tolist()[:4] == ["off", "offloaded", "load", "starting"]
    assert set(readings["operating_state"].tolist()[4:]) == {"load"}
    assert readings["Motor_current"].tolist() == [0.1, 4.0, 7.0, 9.0] + [7.0] * 26

    assert readings["in_prefailure_window"].tolist() == [0] * 6 + [1] * 6 + [0] * 18
    assert readings["failure_event_id"].tolist() == [0] * 12 + [1] * 7 + [0] * 11
    assert readings["in_failure_window"].tolist() == [0] * 12 + [1] * 7 + [0] * 11

    periods = pd.read_csv(output_paths["state_periods"])
    assert periods["operating_state"].tolist() == ["off", "offloaded", "load", "starting", "load"]
    assert periods["row_count"].tolist() == [1, 1, 1, 1, 26]
    assert periods["row_count"].sum() == 30
    assert periods["period_id"].tolist() == [1, 2, 3, 4, 5]

    intervals = pd.read_csv(output_paths["failure_intervals"])
    assert intervals["readings_in_window"].tolist() == [7]
    assert intervals["prefailure_readings"].tolist() == [6]

    summary = json.loads(output_paths["ingestion_summary"].read_text(encoding="utf-8"))
    assert summary["total_rows"] == 30
    assert summary["expected_rows"] == 30
    assert summary["timestamp_min"] == "2020-04-18 00:00:00"
    assert summary["timestamp_max"] == "2020-04-18 00:04:50"
    assert summary["failure_window_rows"] == 7
    assert summary["prefailure_window_rows"] == 6
    assert summary["state_counts"] == {"off": 1, "offloaded": 1, "load": 27, "starting": 1}
    assert summary["null_counts"] == {}


def test_run_accepts_empty_leading_index_header(tmp_path):
    config_path, config = _write_config(tmp_path)
    _write_fixture(config)
    source = Path(config["paths"]["raw"]) / "metropt3.csv"
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("Unnamed: 0,", ",", 1), encoding="utf-8")

    output_paths = run(config_path)
    readings = pd.read_csv(output_paths["processed_readings"])
    assert readings["source_index"].tolist() == list(range(30))
    assert len(readings) == 30


def _read_config(config_path):
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def test_run_rejects_bad_timestamp(tmp_path):
    config_path, config = _write_config(tmp_path)

    def mutate(frame):
        frame.loc[5, "timestamp"] = "not-a-timestamp"

    _write_fixture(config, mutate=mutate)
    with pytest.raises(ValueError, match="unparsable"):
        run(config_path)


def test_run_rejects_non_numeric_analog(tmp_path):
    config_path, config = _write_config(tmp_path)

    def mutate(frame):
        frame["TP2"] = frame["TP2"].astype(object)
        frame.loc[3, "TP2"] = "bad"

    _write_fixture(config, mutate=mutate)
    with pytest.raises(ValueError, match="must contain only numeric"):
        run(config_path)


def test_run_rejects_non_binary_digital(tmp_path):
    config_path, config = _write_config(tmp_path)

    def mutate(frame):
        frame.loc[3, "COMP"] = 2

    _write_fixture(config, mutate=mutate)
    with pytest.raises(ValueError, match="must contain only 0 or 1"):
        run(config_path)


def test_run_rejects_row_count_mismatch(tmp_path):
    config_path, config = _write_config(tmp_path, expected_rows=29)
    _write_fixture(config)
    with pytest.raises(ValueError, match="does not match"):
        run(config_path)


def test_run_rejects_decreasing_timestamps(tmp_path):
    config_path, config = _write_config(tmp_path)

    def mutate(frame):
        frame.loc[10, "timestamp"] = "2020-04-18 00:00:00"

    _write_fixture(config, mutate=mutate)
    with pytest.raises(ValueError, match="non-decreasing"):
        run(config_path)


def test_run_rejects_missing_signal_column(tmp_path):
    config_path, config = _write_config(tmp_path)
    _write_fixture(config)
    source = Path(config["paths"]["raw"]) / "metropt3.csv"
    frame = pd.read_csv(source)
    frame.drop(columns=["TP2"]).to_csv(source, index=False, lineterminator="\n")
    with pytest.raises(ValueError, match="missing required column"):
        run(config_path)
