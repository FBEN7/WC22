"""Pressing analysis: SQL views on the fixture matches, models on synthetic data."""

import numpy as np
import pandas as pd
import pytest

from fdl import pressing, sql

FINAL, CAN_MAR, WAL_IRN = 3869685, 3857276, 3857273
RESTARTS = {"Throw-in", "Free Kick", "Goal Kick", "Corner", "Kick Off", "Goal Keeper",
            "Referee Ball-Drop", "Shot"}


@pytest.fixture
def tm(con):
    return sql.run(con, "team_match_pressing")


def test_game_state_final(con):
    gs = sql.run(con, "game_state")
    final = gs[gs["match_id"] == FINAL].sort_values("idx")
    assert (final["seconds"] >= 0).all()
    last = final.iloc[-1]
    assert (last.goals_for, last.goals_against) == (3, 3)  # 3-3 after extra time
    assert set(final["state"]) == {"level", "leading", "trailing"}


def test_team_match_table(con, tm):
    assert len(tm) == 6
    score = con.execute("""
        SELECT match_id, home_team_id AS team_id, home_score AS goals FROM matches
        UNION ALL SELECT match_id, away_team_id, away_score FROM matches""").df()
    merged = tm.merge(score, on=["match_id", "team_id"])
    assert (merged["goals_for"] == merged["goals"]).all()  # own goals in, shoot-out out
    by_match = tm.groupby("match_id")
    assert by_match["npxgd"].sum().abs().max() < 1e-9
    assert by_match["possession"].sum().to_numpy() == pytest.approx(1.0)
    assert (tm["level_minutes"] <= tm["minutes"]).all()
    assert (tm["high_regains"] <= tm["regains"]).all()
    assert (tm["high_regain_npxg"] <= tm["npxg"] + 1e-9).all()


def test_ppda_matches_the_m2_view(con, tm):
    m2 = sql.run(con, "ppda")[["match_id", "team_id", "ppda"]]
    both = tm.merge(m2, on=["match_id", "team_id"], suffixes=("", "_m2"))
    assert len(both) == 6
    assert both["ppda"].to_numpy() == pytest.approx(both["ppda_m2"].to_numpy())


def test_level_minutes(tm):
    minutes = tm.drop_duplicates("match_id").set_index("match_id")["level_minutes"]
    # Final: 0-0 until 23', 2-2 from 81' to 108', 3-3 from 118' to the end.
    assert minutes[FINAL] == pytest.approx(66.1, abs=0.5)
    # Morocco scored after 4 minutes and never let Canada draw level.
    assert minutes[CAN_MAR] < 6


def test_regains(con):
    r = sql.run(con, "regains")
    assert not set(r["start_type"]) & RESTARTS
    assert (r["is_high"] == (r["x"] >= pressing.HIGH_REGAIN_X)).all()
    assert r["state"].isin(["level", "leading", "trailing"]).all()


def _synthetic(n_teams=300, matches=5, seed=0) -> pd.DataFrame:
    """npxG difference driven by possession only; PPDA tied to possession."""
    rng = np.random.default_rng(seed)
    n = n_teams * matches
    team = np.repeat(np.arange(n_teams), matches)
    possession = np.clip(rng.normal(0.5, 0.1, n), 0.2, 0.8)
    log2_ppda = 4 - 4 * (possession - 0.5) + rng.normal(0, 0.3, n)
    npxgd = 3 * (possession - 0.5) + rng.normal(0, 0.4, n)
    return pd.DataFrame({
        "team_id": team, "team_tournament": team.astype(str), "possession": possession,
        "log2_ppda": log2_ppda, "npxgd": npxgd,
        "strength_loo": rng.normal(0, 0.1, n), "opp_strength_loo": rng.normal(0, 0.1, n),
        "level_minutes": 50.0, "def_actions_level": 10, "possession_level": possession,
        "log2_ppda_level": log2_ppda, "npxgd_level_p90": npxgd,
    })


def test_effects_separate_pressing_from_possession():
    eff = pressing.effects(_synthetic()).set_index("model")
    assert len(eff) == len(pressing.SPECS)
    raw = eff.loc["Raw association"]
    assert raw.ci_high < 0  # PPDA "predicts" xG difference through possession...
    controlled = eff.loc["+ strength + possession share"]
    assert abs(controlled.effect) < 0.1  # ...and nothing once possession is in the model
