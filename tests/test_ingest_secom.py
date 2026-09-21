import json

import pandas as pd
import pytest

from src.ingest_secom import clean_secom, load_secom_files, write_cleaning_outputs


@pytest.fixture
def secom_fixture_files(tmp_path):
    sensor_path = tmp_path / "secom.data"
    labels_path = tmp_path / "secom_labels.data"
    sensor_path.write_text(
        "\n".join(
            [
                "0 1 NaN NaN 5",
                "0 2 NaN 8 5",
                "0 3 NaN NaN 5",
                "0 4 7 9 5",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    labels_path.write_text(
        "\n".join(
            [
                "-1 2020-01-01 00:00:00",
                "1 2020-01-01 01:00:00",
                "-1 2020-01-01 02:00:00",
                "1 2020-01-01 03:00:00",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return sensor_path, labels_path


def test_load_secom_files_preserves_order_and_normalizes_sensor_names(secom_fixture_files):
    sensor_path, labels_path = secom_fixture_files

    raw, sensor_columns = load_secom_files(sensor_path, labels_path)

    assert sensor_columns == [
        "sensor_000",
        "sensor_001",
        "sensor_002",
        "sensor_003",
        "sensor_004",
    ]
    assert list(raw.columns) == ["timestamp", "target_raw", *sensor_columns]
    assert raw["target_raw"].tolist() == [-1, 1, -1, 1]
    assert raw["timestamp"].tolist() == list(
        pd.date_range("2020-01-01", periods=4, freq="h")
    )
    assert raw["sensor_001"].tolist() == [1, 2, 3, 4]
    assert raw["sensor_002"].isna().sum() == 3


def test_load_secom_files_accepts_quoted_dd_mm_yyyy_timestamps(tmp_path):
    sensor_path = tmp_path / "secom.data"
    labels_path = tmp_path / "secom_labels.data"
    sensor_path.write_text("1 2\n3 4\n", encoding="utf-8")
    labels_path.write_text(
        '-1 "19/07/2008 11:55:00"\n1 "19/07/2008 13:17:00"\n',
        encoding="utf-8",
    )

    raw, _ = load_secom_files(sensor_path, labels_path)

    assert raw["target_raw"].tolist() == [-1, 1]
    assert raw["timestamp"].tolist() == [
        pd.Timestamp("2008-07-19 11:55:00"),
        pd.Timestamp("2008-07-19 13:17:00"),
    ]


def test_clean_secom_applies_high_null_then_zero_variance_rules(secom_fixture_files):
    sensor_path, labels_path = secom_fixture_files
    raw, sensor_columns = load_secom_files(sensor_path, labels_path)

    cleaned, profile, summary = clean_secom(raw, sensor_columns)

    assert list(cleaned.columns) == [
        "timestamp",
        "target_raw",
        "target",
        "target_label",
        "sensor_001",
        "sensor_003",
    ]
    assert cleaned["target"].tolist() == [0, 1, 0, 1]
    assert cleaned["target_label"].tolist() == ["pass", "fail", "pass", "fail"]
    assert cleaned["sensor_003"].isna().tolist() == [True, False, True, False]

    assert profile.columns.tolist() == [
        "sensor",
        "missing_count",
        "missing_fraction",
        "zero_variance",
    ]
    assert profile["sensor"].tolist() == sensor_columns
    assert profile.loc[profile["sensor"] == "sensor_002", "missing_fraction"].item() == 0.75
    assert profile.loc[profile["sensor"] == "sensor_003", "missing_fraction"].item() == 0.5
    assert profile.loc[profile["sensor"] == "sensor_000", "zero_variance"].item()
    assert profile.loc[profile["sensor"] == "sensor_004", "zero_variance"].item()

    assert summary["original_row_count"] == 4
    assert summary["original_sensor_count"] == 5
    assert summary["removed_high_null_sensors"] == {
        "names": ["sensor_002"],
        "count": 1,
    }
    assert summary["removed_zero_variance_sensors"] == {
        "names": ["sensor_000", "sensor_004"],
        "count": 2,
    }
    assert summary["final_sensor_count"] == 2
    assert summary["target_distribution"] == {"pass": 2, "fail": 2}
    assert summary["target_mapping"] == {
        "-1": {"target": 0, "target_label": "pass"},
        "1": {"target": 1, "target_label": "fail"},
    }
    assert summary["timestamp_range"] == {
        "min": "2020-01-01T00:00:00",
        "max": "2020-01-01T03:00:00",
    }


def test_clean_secom_rejects_invalid_timestamps(secom_fixture_files):
    sensor_path, labels_path = secom_fixture_files
    labels_path.write_text("-1 2020-01-01 00:00:00\n1 not-a-timestamp\n", encoding="utf-8")
    sensor_path.write_text("0 1\n0 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid SECOM timestamp"):
        load_secom_files(sensor_path, labels_path)


def test_write_cleaning_outputs_is_deterministic(tmp_path, secom_fixture_files):
    sensor_path, labels_path = secom_fixture_files
    raw, sensor_columns = load_secom_files(sensor_path, labels_path)
    cleaned, profile, summary = clean_secom(raw, sensor_columns)
    config = {
        "secom": {
            "source_url": "https://archive.ics.uci.edu/static/public/179/secom.zip",
            "raw_filenames": {"sensor": "secom.data", "labels": "secom_labels.data"},
            "high_null_threshold": 0.50,
            "outputs": {
                "cleaned_data": tmp_path / "processed" / "secom_cleaned.csv",
                "missingness_profile": tmp_path / "reports" / "profile.csv",
                "cleaning_summary": tmp_path / "reports" / "summary.json",
            },
        }
    }

    output_paths = write_cleaning_outputs(cleaned, profile, summary, config)

    assert set(output_paths) == {
        "cleaned_data",
        "missingness_profile",
        "cleaning_summary",
    }
    assert output_paths["cleaned_data"].read_text(encoding="utf-8").splitlines()[0] == (
        "timestamp,target_raw,target,target_label,sensor_001,sensor_003"
    )
    profile_text = output_paths["missingness_profile"].read_text(encoding="utf-8")
    assert profile_text.splitlines()[0] == "sensor,missing_count,missing_fraction,zero_variance"
    summary_json = json.loads(
        output_paths["cleaning_summary"].read_text(encoding="utf-8")
    )
    assert summary_json["output_paths"]["cleaned_data"] == str(
        output_paths["cleaned_data"]
    )
    assert summary_json["high_null_threshold"] == 0.5
