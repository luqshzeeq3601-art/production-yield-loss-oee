import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.ingest_bosch import run, sample_ids, select_numeric_features


def _write_config(tmp_path, *, enabled=True, chunk_size=3):
    raw = tmp_path / "raw"
    interim = tmp_path / "interim"
    processed = tmp_path / "processed"
    reports = tmp_path / "reports"
    raw.mkdir()
    config = {
        "paths": {
            "raw": str(raw),
            "interim": str(interim),
            "processed": str(processed),
            "reports": str(reports),
        },
        "database": {},
        "cost_assumptions": {},
        "spc": {},
        "random_seed": 42,
        "bosch": {
            "raw_filenames": {"numeric": "train_numeric.csv", "date": "train_date.csv"},
            "sample_fraction": 0.10,
            "chunk_size": chunk_size,
            "features_per_station": 1,
            "time_conversion": {
                "enabled": enabled,
                "minutes_per_0_01_unit": 6.0,
                "note": "Project/community assumption; not an observed Bosch fact.",
            },
            "outputs": {
                "sampled_ids": str(interim / "bosch_sampled_ids.csv"),
                "sampled_numeric": str(processed / "bosch_sampled_numeric.csv"),
                "station_timings": str(processed / "bosch_station_timings.csv"),
                "ingestion_summary": str(reports / "bosch_ingestion_summary.json"),
            },
        },
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return config_path, config


def _write_bosch_fixture(config, *, date_ids=None):
    raw = Path(config["paths"]["raw"])
    ids = list(range(20))
    sampled_nan_id = sample_ids(ids, 0.10, 42)[0]
    numeric = pd.DataFrame(
        {
            "Id": ids,
            "L0_S0_F0": [
                np.nan if part_id == sampled_nan_id else part_id * 1.5
                for part_id in ids
            ],
            "L0_S0_F1": [100 + part_id for part_id in ids],
            "L1_S2_F0": [200 + part_id for part_id in ids],
            "L1_S2_F1": [300 + part_id for part_id in ids],
            "Response": [part_id % 4 == 0 for part_id in ids],
        }
    )
    numeric.to_csv(raw / "train_numeric.csv", index=False, lineterminator="\n")
    source_date_ids = ids if date_ids is None else date_ids
    dates = pd.DataFrame(
        {
            "Id": source_date_ids,
            "L0_S0_D0": [part_id / 10 for part_id in source_date_ids],
            "L0_S0_D1": [part_id / 10 + 0.02 for part_id in source_date_ids],
            "L1_S2_D0": [part_id / 10 + 1 for part_id in source_date_ids],
        }
    )
    dates.to_csv(raw / "train_date.csv", index=False, lineterminator="\n")


def test_sample_ids_matches_exact_numpy_rng_choice_and_is_response_blind():
    ids = list(range(20))
    expected = sorted(
        np.random.default_rng(42).choice(ids, size=round(len(ids) * 0.10), replace=False).tolist()
    )

    assert list(inspect.signature(sample_ids).parameters) == ["ids", "sample_fraction", "seed"]
    assert sample_ids(ids, 0.10, 42) == expected
    assert len(sample_ids(ids, 0.10, 42)) == 2
    assert sample_ids(ids, 0.10, 42) == sample_ids(ids, 0.10, 42)


def test_select_numeric_features_is_source_ordered_and_station_bounded():
    header = [
        "Id",
        "Response",
        "L1_S2_F0",
        "L1_S2_F1",
        "L0_S0_F0",
        "L1_S2_F2",
        "L0_S0_F1",
    ]

    assert select_numeric_features(header, 1) == ["L1_S2_F0", "L0_S0_F0"]
    assert select_numeric_features(header, 2) == [
        "L1_S2_F0",
        "L1_S2_F1",
        "L0_S0_F0",
        "L0_S0_F1",
    ]


def test_run_streams_multichunk_outputs_preserves_raw_values_and_is_deterministic(tmp_path):
    config_path, config = _write_config(tmp_path, chunk_size=3)
    _write_bosch_fixture(config)

    output_paths = run(config_path)
    first_output_bytes = {key: path.read_bytes() for key, path in output_paths.items()}
    second_output_paths = run(config_path)

    assert {key: path.read_bytes() for key, path in second_output_paths.items()} == first_output_bytes
    expected_ids = sample_ids(range(20), 0.10, 42)
    persisted = pd.read_csv(output_paths["sampled_ids"])
    numeric = pd.read_csv(output_paths["sampled_numeric"])
    station = pd.read_csv(output_paths["station_timings"])
    summary = json.loads(output_paths["ingestion_summary"].read_text(encoding="utf-8"))

    assert persisted["Id"].tolist() == expected_ids
    assert numeric.columns.tolist() == ["Id", "Response", "L0_S0_F0", "L1_S2_F0"]
    assert numeric["Id"].tolist() == expected_ids
    sampled_nan_id = expected_ids[0]
    assert (numeric["Id"] == sampled_nan_id).any()
    assert numeric.loc[numeric["Id"] == sampled_nan_id, "L0_S0_F0"].isna().all()
    value_id = next(part_id for part_id in expected_ids if part_id != sampled_nan_id)
    value_row = numeric.loc[numeric["Id"] == value_id].iloc[0]
    assert value_row["Response"] == int(value_id % 4 == 0)
    assert value_row["L0_S0_F0"] == pytest.approx(value_id * 1.5)
    assert value_row["L1_S2_F0"] == pytest.approx(200 + value_id)
    assert station["Id"].drop_duplicates().tolist() == expected_ids
    assert station["line"].tolist() == ["L0", "L1", "L0", "L1"]
    first_station = station.iloc[0]
    assert first_station["station_start_time"] == pytest.approx(expected_ids[0] / 10)
    assert first_station["station_end_time"] == pytest.approx(expected_ids[0] / 10 + 0.02)
    assert first_station["dwell_time_units"] == pytest.approx(0.02)
    assert first_station["dwell_minutes"] == pytest.approx(12.0)
    assert summary["total_source_ids"] == 20
    assert summary["sampled_id_count"] == 2
    assert summary["configured_sample_fraction"] == pytest.approx(0.10)
    fixture_response = {part_id: int(part_id % 4 == 0) for part_id in range(20)}
    expected_source_fail_count = sum(fixture_response.values())
    expected_source_pass_count = len(fixture_response) - expected_source_fail_count
    expected_sampled_fail_count = sum(fixture_response[part_id] for part_id in expected_ids)
    expected_sampled_pass_count = len(expected_ids) - expected_sampled_fail_count
    expected_source_failure_rate = expected_source_fail_count / len(fixture_response)
    expected_sampled_failure_rate = expected_sampled_fail_count / len(expected_ids)
    assert summary["source_pass_count"] == expected_source_pass_count
    assert summary["source_fail_count"] == expected_source_fail_count
    assert summary["sampled_pass_count"] == expected_sampled_pass_count
    assert summary["sampled_fail_count"] == expected_sampled_fail_count
    assert summary["source_failure_rate"] == pytest.approx(expected_source_failure_rate)
    assert summary["sampled_failure_rate"] == pytest.approx(expected_sampled_failure_rate)
    assert summary["failure_rate_difference"] == pytest.approx(
        expected_sampled_failure_rate - expected_source_failure_rate
    )
    assert summary["numeric_rows_retained"] == 2
    assert summary["date_rows_retained"] == 2
    assert summary["station_record_count"] == len(station)
    assert summary["retained_numeric_features"] == ["L0_S0_F0", "L1_S2_F0"]
    assert summary["time_conversion_assumption"]["observed_bosch_fact"] is False


def test_run_allows_configurable_disabled_time_conversion(tmp_path):
    config_path, config = _write_config(tmp_path, enabled=False)
    _write_bosch_fixture(config)

    output_paths = run(config_path)
    station = pd.read_csv(output_paths["station_timings"])

    assert station["dwell_minutes"].isna().all()


def test_run_rejects_incompatible_persisted_sample(tmp_path):
    config_path, config = _write_config(tmp_path)
    _write_bosch_fixture(config)
    output_paths = run(config_path)
    output_paths["sampled_ids"].write_text("Id\n999\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match the deterministic sample"):
        run(config_path)


def test_run_rejects_sampled_date_id_misalignment(tmp_path):
    config_path, config = _write_config(tmp_path)
    expected_ids = sample_ids(range(20), 0.10, 42)
    _write_bosch_fixture(config, date_ids=[part_id for part_id in range(20) if part_id != expected_ids[0]])

    with pytest.raises(ValueError, match="date sampled Id set does not align"):
        run(config_path)


def test_run_rejects_malformed_selected_numeric_values(tmp_path):
    config_path, config = _write_config(tmp_path)
    _write_bosch_fixture(config)
    numeric_path = Path(config["paths"]["raw"]) / "train_numeric.csv"
    numeric = pd.read_csv(numeric_path)
    numeric["L0_S0_F0"] = numeric["L0_S0_F0"].astype("object")
    numeric.loc[0, "L0_S0_F0"] = "not-a-number"
    numeric.to_csv(numeric_path, index=False, lineterminator="\n")

    with pytest.raises(ValueError, match="numeric selected feature columns must contain"):
        run(config_path)


def test_run_rejects_malformed_date_values(tmp_path):
    config_path, config = _write_config(tmp_path)
    _write_bosch_fixture(config)
    date_path = Path(config["paths"]["raw"]) / "train_date.csv"
    dates = pd.read_csv(date_path)
    dates["L0_S0_D0"] = dates["L0_S0_D0"].astype("object")
    dates.loc[0, "L0_S0_D0"] = "not-a-number"
    dates.to_csv(date_path, index=False, lineterminator="\n")

    with pytest.raises(ValueError, match="date feature columns must contain"):
        run(config_path)


def test_run_rejects_missing_and_malformed_sources(tmp_path):
    config_path, config = _write_config(tmp_path)

    with pytest.raises(FileNotFoundError, match="numeric source file is missing"):
        run(config_path)

    raw = Path(config["paths"]["raw"])
    (raw / "train_numeric.csv").write_text("Id,Id,Response\n1,1,0\n", encoding="utf-8")
    (raw / "train_date.csv").write_text("Id,L0_S0_D0\n1,0.1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate column"):
        run(config_path)
