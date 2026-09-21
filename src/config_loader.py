from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


REQUIRED_TOP_LEVEL_SECTIONS = (
    "paths",
    "database",
    "cost_assumptions",
    "spc",
    "random_seed",
)
DEFAULT_CONFIG_PATH = Path(__file__).resolve().with_name("config.yaml")


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH

    with config_path.open("r", encoding="utf-8") as config_file:
        document = yaml.safe_load(config_file)

    if not isinstance(document, Mapping):
        raise ValueError(
            f"Configuration at {config_path} must contain a mapping at the top level."
        )

    missing_sections = [
        section
        for section in REQUIRED_TOP_LEVEL_SECTIONS
        if section not in document
    ]
    if missing_sections:
        missing = ", ".join(missing_sections)
        raise ValueError(
            f"Configuration at {config_path} is missing required top-level "
            f"section(s): {missing}."
        )

    return dict(document)
