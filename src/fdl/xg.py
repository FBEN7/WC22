"""M3 - Expected goals (xG).

Build shot features from the warehouse (including the shot freeze frames),
train a model with match-grouped cross-validation, and compare it honestly to
StatsBomb's own xG.

Implemented for you: default_model, evaluate, calibration_table, feature_matrix.
To do: shot_geometry, build_shot_features, fit_predict_oof.
"""

from __future__ import annotations

from collections.abc import Callable

import duckdb
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from fdl.config import GOAL_CENTRE, GOAL_POSTS_Y  # noqa: F401  (you will need them)

REQUIRED_COLUMNS = [
    "event_id", "match_id", "is_goal", "statsbomb_xg", "distance", "angle", "is_header",
]


def shot_geometry(x, y) -> tuple[np.ndarray, np.ndarray]:
    """Distance and angle subtended by the goal posts."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)

    gx = GOAL_CENTRE[0]
    low, high = GOAL_POSTS_Y
    vx_low, vy_low = gx - x, low - y
    vx_high, vy_high = gx - x, high - y

    dot = vx_low * vx_high + vy_low * vy_high
    norms = np.sqrt(vx_low**2 + vy_low**2) * np.sqrt(vx_high**2 + vy_high**2)
    angle = np.zeros_like(dot if np.ndim(dot) else np.asarray(dot))
    np.divide(dot, norms, out=angle, where=norms > 0)
    angle = np.arccos(np.clip(angle, -1.0, 1.0))

    outside_goal_line = (x >= gx) & ((y < low) | (y > high))
    angle = np.where(outside_goal_line, 0.0, angle)
    distance = np.sqrt((gx - x) ** 2 + (GOAL_CENTRE[1] - y) ** 2)

    if np.ndim(distance) == 0:
        return float(distance), float(angle)
    return distance, angle


def build_shot_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per open-play/free-kick shot, excluding the penalty shoot-out."""
    df = con.execute("""
        SELECT s.event_id, s.match_id, s.shot_type,
               s.outcome = 'Goal' AS is_goal,
               s.statsbomb_xg,
               e.x, e.y,
               e.position_name,
               coalesce(s.shot_type = 'Penalty', false) AS is_penalty,
               coalesce(s.body_part = 'Head', false) AS is_header
        FROM shots s
        JOIN events e USING (event_id)
        WHERE s.shot_type != 'Penalty' AND e.period < 5
    """).df()

    distance, angle = shot_geometry(df["x"].to_numpy(), df["y"].to_numpy())
    df["distance"] = distance
    df["angle"] = angle
    df["is_goal"] = df["is_goal"].astype(int)
    df["is_header"] = df["is_header"].astype(int)

    ff = con.execute("""
        SELECT shot_event_id AS event_id, teammate, position_name, x, y
        FROM shot_freeze_frames
    """).df()

    opponents_in_cone = []
    defenders_within_5 = []
    keeper_distances = []

    for row in df.itertuples(index=False):
        frame = ff[ff["event_id"] == row.event_id]
        opponents = frame[~frame["teammate"]]

        bx, by = row.x, row.y
        p1 = np.array([120.0, 36.0])
        p2 = np.array([120.0, 44.0])
        ball = np.array([bx, by])

        def sign(a, b, c):
            return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])

        def inside(point, ball=ball, p1=p1, p2=p2):
            d1 = sign(ball, p1, point)
            d2 = sign(p1, p2, point)
            d3 = sign(p2, ball, point)
            has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
            has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)
            return not (has_neg and has_pos)

        opponents_in_cone.append(sum(inside(np.array([x, y]))
                                      for x, y in opponents[["x", "y"]].to_numpy()))
        defenders_within_5.append(sum(
            np.hypot(x - bx, y - by) <= 5.0
            for x, y in opponents[["x", "y"]].to_numpy()
        ))

        keepers = opponents[
            opponents["position_name"] .fillna("").str.contains("Goalkeeper", case=False)
        ]
        if keepers.empty:
            keeper_distances.append(40.0)
        else:
            keeper_distances.append(float(np.min(np.hypot(
                keepers["x"].to_numpy() - 120.0,
                keepers["y"].to_numpy() - 40.0,
            ))))

    df["opponents_in_cone"] = np.asarray(opponents_in_cone, dtype=int)
    df["defenders_within_5"] = np.asarray(defenders_within_5, dtype=int)
    df["keeper_distance"] = np.asarray(keeper_distances, dtype=float)

    return df[list(dict.fromkeys(REQUIRED_COLUMNS + [
        "opponents_in_cone", "defenders_within_5", "keeper_distance", "is_header",
    ]))]


def default_model():
    """A deliberately simple, well-calibrated baseline. Beat it, but explain how."""
    return make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))


def fit_predict_oof(
    df: pd.DataFrame,
    feature_cols: list[str],
    model_factory: Callable = default_model,
    n_splits: int = 5,
    group_col: str = "match_id",
) -> np.ndarray:
    """Match-grouped out-of-fold probabilities."""
    from sklearn.model_selection import GroupKFold

    X = feature_matrix(df, feature_cols)
    y = df["is_goal"].to_numpy(dtype=int)
    groups = df[group_col].to_numpy()
    predictions = np.zeros(len(df), dtype=float)

    splitter = GroupKFold(n_splits=n_splits)
    for train_idx, test_idx in splitter.split(X, y, groups):
        model = model_factory()
        model.fit(X[train_idx], y[train_idx])
        predictions[test_idx] = model.predict_proba(X[test_idx])[:, 1]

    return predictions


# ------------------------------------------------------------------ provided


def feature_matrix(df: pd.DataFrame, feature_cols: list[str]) -> np.ndarray:
    return df[feature_cols].to_numpy(dtype=float)


def evaluate(y, p) -> dict[str, float]:
    """Proper scoring rules first (log loss, Brier); AUC only says how well shots are ranked."""
    y, p = np.asarray(y), np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    base = np.full_like(p, y.mean())
    return {
        "n_shots": int(len(y)),
        "goal_rate": float(y.mean()),
        "log_loss": float(log_loss(y, p)),
        "log_loss_baseline": float(log_loss(y, base)),
        "brier": float(brier_score_loss(y, p)),
        "auc": float(roc_auc_score(y, p)),
        "sum_xg_minus_goals": float(p.sum() - y.sum()),
    }


def calibration_table(y, p, bins: int = 10) -> pd.DataFrame:
    """Predicted vs observed goal rate by quantile bin of the prediction."""
    df = pd.DataFrame({"y": np.asarray(y), "p": np.asarray(p, dtype=float)})
    df["bin"] = pd.qcut(df["p"].rank(method="first"), bins, labels=False)
    return (df.groupby("bin")
              .agg(n=("y", "size"), mean_pred=("p", "mean"), goal_rate=("y", "mean"))
              .reset_index())
