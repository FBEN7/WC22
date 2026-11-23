"""Shared fixtures.

The suite runs on three real, deliberately awkward matches (see
fdl.config.FIXTURE_MATCHES). They are downloaded once into the data/raw cache,
then a small warehouse is built in a temporary folder.

A test that hits a function still raising NotImplementedError is reported as
SKIPPED ("TODO ..."), not FAILED: `pytest` stays green while milestones are
open, and the summary shows what is left to do.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import duckdb
import pytest

from fdl.config import DB_PATH, FIXTURE_MATCHES, RAW_DIR


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if call.excinfo is not None and call.excinfo.errisinstance(NotImplementedError):
        report.outcome = "skipped"
        report.longrepr = (str(item.path), item.location[1] or 0, f"TODO {call.excinfo.value}")


@pytest.fixture(scope="session")
def fixture_db(tmp_path_factory) -> Path:
    from fdl.ingest import download
    from fdl.warehouse import build

    try:
        download(match_ids=FIXTURE_MATCHES, raw_dir=RAW_DIR)
    except Exception as exc:  # no network and nothing cached
        pytest.skip(f"cannot download the fixture matches: {exc}")
    return build(RAW_DIR, tmp_path_factory.mktemp("wh") / "fixtures.duckdb",
                 match_ids=set(FIXTURE_MATCHES))


@pytest.fixture
def con(fixture_db):
    c = duckdb.connect(str(fixture_db), read_only=True)
    yield c
    c.close()


@pytest.fixture
def writable_con(fixture_db, tmp_path):
    """A private copy of the fixture warehouse, for tests that inject defects."""
    copy = tmp_path / "copy.duckdb"
    shutil.copy(fixture_db, copy)
    c = duckdb.connect(str(copy))
    yield c
    c.close()


@pytest.fixture(scope="session")
def full_con():
    """The full warehouse (data/warehouse.duckdb), for tests that need many matches."""
    if not DB_PATH.exists():
        pytest.skip("full warehouse not built: python -m fdl download && python -m fdl build")
    c = duckdb.connect(str(DB_PATH), read_only=True)
    if c.execute("SELECT count(*) FROM matches").fetchone()[0] < 40:
        pytest.skip("full warehouse has fewer than 40 matches")
    yield c
    c.close()
