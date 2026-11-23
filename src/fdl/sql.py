"""M2 - SQL exercises (sql/*.sql), run as DuckDB views.

Each file sql/NN_name.sql holds ONE SELECT and becomes the temporary view
`name`, so later files can build on earlier ones (02 uses `minutes_played`).
A file that still contains a line starting with "-- TODO" counts as not done.
"""

from __future__ import annotations

import duckdb
import pandas as pd

from fdl.config import ROOT

SQL_DIR = ROOT / "sql"


def exercises() -> list[str]:
    """File stems in order, e.g. ['00_example_team_shots', '01_minutes_played', ...]."""
    return sorted(p.stem for p in SQL_DIR.glob("[0-9][0-9]_*.sql"))


def view_name(stem: str) -> str:
    name = stem.split("_", 1)[1]
    return name.removeprefix("example_")


def query_text(stem: str) -> str:
    text = (SQL_DIR / f"{stem}.sql").read_text(encoding="utf-8")
    if any(line.lstrip().startswith("-- TODO") for line in text.splitlines()):
        raise NotImplementedError(f"M2: sql/{stem}.sql")
    return text.strip().rstrip(";")


def create_views(con: duckdb.DuckDBPyConnection, upto: str | None = None) -> list[str]:
    """Create the views of every finished exercise (up to and including `upto`)."""
    created = []
    for stem in exercises():
        try:
            sql = query_text(stem)
        except NotImplementedError:
            if stem == upto:
                raise
            continue
        con.execute(f"CREATE OR REPLACE TEMP VIEW {view_name(stem)} AS {sql}")
        created.append(view_name(stem))
        if stem == upto:
            break
    return created


def run(con: duckdb.DuckDBPyConnection, name: str) -> pd.DataFrame:
    """Result of an exercise, by view name ('minutes_played') or file stem."""
    stem = next(s for s in exercises() if name in (s, view_name(s)))
    create_views(con, upto=stem)
    return con.execute(f"SELECT * FROM {view_name(stem)}").df()
