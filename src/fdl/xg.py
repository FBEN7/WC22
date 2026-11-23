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
    """Distance and angle of shots taken from (x, y) - scalars or arrays.

    distance: yards from (x, y) to the centre of the goal (120, 40).
    angle: radians, the angle the goal mouth subtends from (x, y), i.e. the
    angle between the lines to the two posts (120, 36) and (120, 44).
    It is pi on the goal line between the posts and 0 on the goal line outside them.
    """
    raise NotImplementedError("M3: shot_geometry")


def build_shot_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per shot, PENALTIES AND THE SHOOT-OUT (period 5) EXCLUDED.

    Must contain REQUIRED_COLUMNS (is_goal and is_header as 0/1 integers) plus at
    least two features of your own built from `shot_freeze_frames`, for example:
    the number of opponents inside the triangle formed by the ball and the two
    posts, the goalkeeper's distance from the centre of the goal, the number of
    opponents within 5 yards of the shooter. No NaN in any numeric column: decide
    explicitly what to do with shots that have no freeze frame, and say so.
    """
    raise NotImplementedError("M3: build_shot_features")


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
    """Out-of-fold P(goal) for every row of `df`.

    Split with sklearn's GroupKFold on `group_col`: all shots of a match must
    land in the same fold, otherwise the model is evaluated on matches it has
    partly seen. For each fold, build a fresh model with `model_factory()`,
    fit it on df[feature_cols] / df['is_goal'] of the other folds, and fill in
    predict_proba(...)[:, 1] for this fold. Return an array aligned with df.
    """
    raise NotImplementedError("M3: fit_predict_oof")


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
