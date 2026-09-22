import matplotlib
from matplotlib import colors as matplotlib_colors
import numpy as np
import pandas as pd
import psycopg2
from psycopg2 import extensions as psycopg2_extensions
import pytest
import scipy
from scipy import stats
import sqlalchemy
import yaml

from src.config_loader import load_config


EXPECTED_TOP_LEVEL_SECTIONS = {
    "paths",
    "database",
    "cost_assumptions",
    "spc",
    "random_seed",
}


def test_required_dependencies_support_basic_operations():
    assert np.array([1, 2, 3]).sum() == 6
    assert pd.DataFrame({"value": [1, 2, 3]})["value"].sum() == 6
    assert scipy.__version__
    assert stats.norm.cdf(0.0) == pytest.approx(0.5)
    assert sqlalchemy.create_engine("sqlite:///:memory:").dialect.name == "sqlite"
    assert psycopg2.__version__
    assert psycopg2_extensions.adapt(42).getquoted() == b"42"
    assert yaml.safe_load("value: 1") == {"value": 1}
    assert matplotlib.__version__
    assert matplotlib_colors.to_hex("red") == "#ff0000"


def test_default_configuration_loads_with_required_sections_and_values():
    config = load_config()

    assert EXPECTED_TOP_LEVEL_SECTIONS.issubset(config)
    assert "secom" in config
    assert "metropt3" in config
    assert set(config["paths"]) == {"raw", "interim", "processed", "reports"}
    assert config["paths"]["raw"] == "data/raw"
    assert config["paths"]["interim"] == "data/interim"
    assert config["paths"]["processed"] == "data/processed"
    assert config["paths"]["reports"] == "reports"
    assert config["database"]["host"] == "localhost"
    assert config["database"]["port"] == 5432
    assert config["database"]["name"] == "production_yield_oee"
    assert config["database"]["user_env"] == "POSTGRES_USER"
    assert config["database"]["password_env"] == "POSTGRES_PASSWORD"
    assert config["cost_assumptions"]["status"] == "placeholder"
    assert config["cost_assumptions"]["unit_scrap_cost"] is None
    assert config["cost_assumptions"]["analyst_hourly_rate"] is None
    assert config["spc"]["phase_i_fraction"] == pytest.approx(0.30)
    assert config["spc"]["ewma_lambda"] == pytest.approx(0.20)
    assert config["random_seed"] == 42
    assert config["metropt3"]["raw_filenames"] == {
        "readings": "metropt3/MetroPT3(AirCompressor).csv",
    }
    assert config["metropt3"]["expected_rows"] == 1516948
    assert len(config["metropt3"]["failure_events"]) == 4
    assert config["metropt3"]["chunk_size"] > 0
    assert config["screening"]["window_fraction"] == pytest.approx(0.30)
    assert config["screening"]["fdr_alpha"] == pytest.approx(0.05)
    assert config["screening"]["correlation_threshold"] == pytest.approx(0.90)
    assert config["screening"]["min_selected"] == 10
    assert config["screening"]["max_selected"] == 15
    assert config["spc"]["phase1_fraction"] == pytest.approx(0.30)
    assert config["spc"]["mr_d2"] == pytest.approx(1.128)
    assert config["spc"]["mr_d4"] == pytest.approx(3.267)
    assert config["spc"]["p_chart_min_daily_n"] == 10
    assert config["spc"]["ewma_lambda"] == pytest.approx(0.20)
    assert config["spc"]["ewma_L"] == pytest.approx(3.0)
    assert config["spc"]["ewma_use_time_varying_limits"] is True
    assert config["spc"]["hotelling_t2_alpha"] == pytest.approx(0.01)


def test_loader_rejects_a_non_mapping_document(tmp_path):
    config_path = tmp_path / "invalid.yaml"
    config_path.write_text("- item\n", encoding="utf-8")

    with pytest.raises(ValueError, match="mapping"):
        load_config(config_path)


def test_loader_reports_missing_required_sections(tmp_path):
    config_path = tmp_path / "incomplete.yaml"
    config_path.write_text("paths: {}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="database"):
        load_config(config_path)
