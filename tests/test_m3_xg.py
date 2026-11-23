"""M3 acceptance tests: expected goals."""

import numpy as np
import pandas as pd
import pytest

from fdl import xg

# ---------------------------------------------------------------- geometry


@pytest.mark.parametrize("x, y, dist, angle", [
    (108, 40, 12.0, 2 * np.arctan(4 / 12)),  # penalty spot
    (120, 40, 0.0, np.pi),  # on the goal line, between the posts
    (120, 30, 10.0, 0.0),  # on the goal line, outside the posts
    (100, 20, np.hypot(20, 20), np.arctan(24 / 20) - np.arctan(16 / 20)),
])
def test_shot_geometry_scalar(x, y, dist, angle):
    d, a = xg.shot_geometry(x, y)
    assert d == pytest.approx(dist)
    assert a == pytest.approx(angle)


def test_shot_geometry_vectorised():
    d, a = xg.shot_geometry(np.array([108.0, 100.0]), np.array([40.0, 20.0]))
    assert d.shape == a.shape == (2,)
    assert d[1] > d[0] and a[1] < a[0]


# ---------------------------------------------------------------- features


def test_shot_features(con):
    df = xg.build_shot_features(con)
    expected = con.execute("""
        SELECT count(*), count(*) FILTER (WHERE s.outcome = 'Goal')
        FROM shots s JOIN events e USING (event_id)
        WHERE s.shot_type <> 'Penalty' AND e.period < 5""").fetchone()
    assert (len(df), int(df["is_goal"].sum())) == expected
    assert set(xg.REQUIRED_COLUMNS) <= set(df.columns)
    assert df["event_id"].is_unique
    assert set(df["is_goal"].unique()) <= {0, 1}
    numeric = df.select_dtypes("number")
    assert not numeric.isna().any().any(), numeric.columns[numeric.isna().any()].tolist()
    own = set(numeric.columns) - set(xg.REQUIRED_COLUMNS)
    assert len(own) >= 2, "add at least two freeze-frame features"


# ---------------------------------------------------------------- cross-validation


def _synthetic_shots(n_matches=40, per_match=30, seed=0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = n_matches * per_match
    distance = rng.uniform(5, 35, n)
    p = 1 / (1 + np.exp(-(1.5 - 0.15 * distance)))
    df = pd.DataFrame({
        "match_id": np.repeat(np.arange(n_matches), per_match),
        "distance": distance,
        "noise": rng.normal(size=n),
        "is_goal": (rng.uniform(size=n) < p).astype(int),
    })
    # Shuffled, so that splitting rows in contiguous blocks does NOT keep matches together.
    return df.sample(frac=1, random_state=seed).reset_index(drop=True)


def test_oof_predictions_are_probabilities():
    df = _synthetic_shots()
    p = xg.fit_predict_oof(df, ["distance", "noise"])
    assert p.shape == (len(df),)
    assert ((p > 0) & (p < 1)).all()
    scores = xg.evaluate(df["is_goal"], p)
    assert scores["log_loss"] < scores["log_loss_baseline"]


def test_oof_splits_by_match():
    """The model must never be evaluated on a match it was trained on."""

    class Spy:
        def fit(self, X, y):
            self.seen = set(X[:, 0])
            return self

        def predict_proba(self, X):
            leaked = self.seen & set(X[:, 0])
            assert not leaked, f"matches in both train and test: {sorted(leaked)[:5]}"
            return np.column_stack([np.full(len(X), 0.9), np.full(len(X), 0.1)])

    df = _synthetic_shots()
    df["match_as_feature"] = df["match_id"].astype(float)
    xg.fit_predict_oof(df, ["match_as_feature"], model_factory=Spy)


# ---------------------------------------------------------------- full data (skipped in CI)


def test_model_on_full_data(full_con):
    df = xg.build_shot_features(full_con)
    cols = [c for c in df.select_dtypes("number").columns
            if c not in ("match_id", "is_goal", "statsbomb_xg")]
    ours = xg.evaluate(df["is_goal"], xg.fit_predict_oof(df, cols))
    geo = xg.evaluate(df["is_goal"], xg.fit_predict_oof(df, ["distance", "angle"]))
    sb = xg.evaluate(df["is_goal"], df["statsbomb_xg"])
    # Your features must add something over distance + angle...
    assert ours["log_loss"] < 0.98 * geo["log_loss"], (ours, geo)
    # ...but beating StatsBomb's xG by a wide margin with open data almost
    # always means leakage (information from after the shot, e.g. end_location).
    assert ours["log_loss"] > 0.95 * sb["log_loss"], "suspiciously good: check for leakage"
