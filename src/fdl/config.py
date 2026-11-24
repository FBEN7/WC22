"""Paths and data selection. Override the locations with FDL_DATA_DIR / FDL_DB."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("FDL_DATA_DIR", ROOT / "data"))
RAW_DIR = DATA_DIR / "raw"
DB_PATH = Path(os.environ.get("FDL_DB", DATA_DIR / "warehouse.duckdb"))

BASE_URL = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"

# (competition_id, season_id): the six men's senior tournaments 2018-2024 in the open data.
DEFAULT_SEASONS: list[tuple[int, int]] = [
    (43, 3),  # FIFA World Cup 2018
    (43, 106),  # FIFA World Cup 2022  (360)
    (55, 43),  # UEFA Euro 2020  (360)
    (55, 282),  # UEFA Euro 2024  (360)
    (223, 282),  # Copa America 2024
    (1267, 107),  # African Cup of Nations 2023  (360)
]

# Small, deliberately awkward matches used by the test suite.
FIXTURE_MATCHES: dict[int, str] = {
    3869685: "WC 2022 final, Argentina 3-3 France: extra time + penalty shoot-out",
    3857276: "WC 2022, Canada 1-2 Morocco: Canada's goal is a Moroccan own goal",
    3857273: "WC 2022, Wales 0-2 Iran: red card, two goals in stoppage time",
}

# StatsBomb pitch: 120 x 80 (yards), every event seen from the acting team
# attacking left to right. The goal being attacked is at x = 120.
PITCH_LENGTH = 120.0
PITCH_WIDTH = 80.0
GOAL_CENTRE = (120.0, 40.0)
GOAL_POSTS_Y = (36.0, 44.0)
