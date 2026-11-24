"""M4 - Expected threat (xT), a simple possession-value model (Karun Singh, 2018).

Split the pitch into a grid. For each cell z, from all ball moves (passes and
carries) and shots starting in z:
    s_z  share of actions in z that are shots,      m_z = 1 - s_z
    g_z  share of shots from z that are goals
    T_zz' successful moves from z ending in z' / ALL moves from z (failed ones included)
and iterate, starting from xT = 0:
    xT_z = s_z * g_z + m_z * sum_z' T_zz' * xT_z'
A cell with no action has xT = 0. The value of a successful move from z to z'
is xT_z' - xT_z.

Providers sell far richer versions of this (StatsBomb's OBV, for instance);
this one is enough to understand the idea and its limits.

Implemented for you: load_actions, cell_index. To do: expected_threat, rate_moves.
"""

from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

from fdl.config import PITCH_LENGTH, PITCH_WIDTH


def load_actions(con: duckdb.DuckDBPyConnection) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(moves, shots), periods 1-4 only.

    moves: event_id, match_id, team_id, player_id, player_name, type_name, x, y, end_x, end_y,
           success (passes: outcome IS NULL; carries: always true)
    shots: event_id, x, y, is_goal (penalties excluded)
    """
    moves = con.execute("""
        SELECT e.event_id, e.match_id, e.team_id, e.player_id, e.player_name, e.type_name,
               e.x, e.y, p.end_x, p.end_y, p.outcome IS NULL AS success
        FROM passes p JOIN events e USING (event_id) WHERE e.period < 5
        UNION ALL
        SELECT e.event_id, e.match_id, e.team_id, e.player_id, e.player_name, e.type_name,
               e.x, e.y, c.end_x, c.end_y, true
        FROM carries c JOIN events e USING (event_id) WHERE e.period < 5
    """).df()
    shots = con.execute("""
        SELECT e.event_id, e.x, e.y, (s.outcome = 'Goal')::INT AS is_goal
        FROM shots s JOIN events e USING (event_id)
        WHERE e.period < 5 AND s.shot_type <> 'Penalty'
    """).df()
    return moves, shots


def cell_index(x, y, nx: int, ny: int) -> np.ndarray:
    """Flat cell index (row-major: iy * nx + ix) of points on the 120 x 80 pitch.
    Points on the far edges (x = 120 or y = 80) go into the last column / row."""
    ix = np.clip((np.asarray(x, dtype=float) / PITCH_LENGTH * nx).astype(int), 0, nx - 1)
    iy = np.clip((np.asarray(y, dtype=float) / PITCH_WIDTH * ny).astype(int), 0, ny - 1)
    return iy * nx + ix


def expected_threat(
    moves: pd.DataFrame,
    shots: pd.DataFrame,
    nx: int = 16,
    ny: int = 12,
    n_iter: int = 50,
) -> np.ndarray:
    """Karun Singh-style expected-threat grid by fixed-point iteration."""
    n_cells = nx * ny
    move_start = cell_index(moves["x"].to_numpy(), moves["y"].to_numpy(), nx, ny)
    move_end = cell_index(moves["end_x"].to_numpy(), moves["end_y"].to_numpy(), nx, ny)
    shot_start = cell_index(shots["x"].to_numpy(), shots["y"].to_numpy(), nx, ny)

    move_count = np.bincount(move_start, minlength=n_cells).astype(float)
    shot_count = np.bincount(shot_start, minlength=n_cells).astype(float)
    action_count = move_count + shot_count

    goal_count = np.bincount(
        shot_start,
        weights=shots["is_goal"].to_numpy(dtype=float),
        minlength=n_cells,
    )
    shot_goal_rate = np.divide(goal_count, shot_count, out=np.zeros(n_cells), where=shot_count > 0)

    transition = np.zeros((n_cells, n_cells), dtype=float)
    successful = moves["success"].to_numpy(dtype=bool)
    if successful.any():
        np.add.at(transition, (move_start[successful], move_end[successful]), 1.0)
    transition = np.divide(transition, move_count[:, None], out=np.zeros_like(transition),
                           where=move_count[:, None] > 0)

    shot_share = np.divide(shot_count, action_count, out=np.zeros(n_cells), where=action_count > 0)
    move_share = np.divide(move_count, action_count, out=np.zeros(n_cells), where=action_count > 0)

    grid = np.zeros(n_cells, dtype=float)
    for _ in range(n_iter):
        continuation = transition @ grid
        updated = shot_share * shot_goal_rate + move_share * continuation
        updated[action_count == 0] = 0.0
        if np.allclose(updated, grid, rtol=1e-10, atol=1e-12):
            grid = updated
            break
        grid = updated

    return grid.reshape(ny, nx)


def rate_moves(moves: pd.DataFrame, grid: np.ndarray) -> pd.Series:
    """xT end minus start for successful moves; unsuccessful moves add zero."""
    nx = grid.shape[1]
    ny = grid.shape[0]
    start = cell_index(moves["x"].to_numpy(), moves["y"].to_numpy(), nx, ny)
    end = cell_index(moves["end_x"].to_numpy(), moves["end_y"].to_numpy(), nx, ny)

    flat = grid.ravel()
    values = np.where(moves["success"].to_numpy(dtype=bool), flat[end] - flat[start], 0.0)
    return pd.Series(values, index=moves.index, dtype=float)
