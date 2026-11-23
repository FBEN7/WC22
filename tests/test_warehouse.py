"""The foundation (ingest + warehouse). These must always pass."""

from fdl.warehouse import clock_to_seconds

FINAL, CAN_MAR, WAL_IRN = 3869685, 3857276, 3857273


def test_clock_to_seconds():
    assert clock_to_seconds("00:04:40.798") == 280.798
    assert clock_to_seconds("01:02:03.500") == 3723.5


def test_tables_exist(con):
    tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    assert tables >= {
        "competitions", "matches", "lineups", "events", "passes", "carries",
        "shots", "shot_freeze_frames", "frames_360",
    }


def test_fixture_matches(con):
    rows = con.execute(
        "SELECT match_id, home_team_name, home_score, away_score, away_team_name "
        "FROM matches ORDER BY match_id"
    ).fetchall()
    assert rows == [
        (WAL_IRN, "Wales", 0, 2, "Iran"),
        (CAN_MAR, "Canada", 1, 2, "Morocco"),
        (FINAL, "Argentina", 3, 3, "France"),
    ]


def test_event_ids_unique(con):
    n, ids = con.execute("SELECT count(*), count(DISTINCT event_id) FROM events").fetchone()
    assert n == ids > 10_000


def test_type_tables_match_events(con):
    for table, type_name in [("passes", "Pass"), ("carries", "Carry"), ("shots", "Shot")]:
        a = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        b = con.execute("SELECT count(*) FROM events WHERE type_name = ?",
                        [type_name]).fetchone()[0]
        assert a == b > 0, table


def test_final_has_shootout_in_period_5(con):
    kicks, goals = con.execute(
        "SELECT count(*), count(*) FILTER (WHERE s.outcome = 'Goal') "
        "FROM events e JOIN shots s USING (event_id) WHERE e.match_id = ? AND e.period = 5",
        [FINAL],
    ).fetchone()
    assert (kicks, goals) == (8, 6)  # Argentina 4/4, France 2/4


def test_360_frames_loaded(con):
    n = con.execute("SELECT count(DISTINCT match_id) FROM frames_360").fetchone()[0]
    assert n == 3
