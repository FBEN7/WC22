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
    """The xT grid, shape (ny, nx): row iy, column ix (use cell_index to bin).

    `moves` needs x, y, end_x, end_y, success; `shots` needs x, y, is_goal.
    Run the iteration `n_iter` times (or until it stops changing).
    """
    raise NotImplementedError("M4: expected_threat")


def rate_moves(moves: pd.DataFrame, grid: np.ndarray) -> pd.Series:
    """xT added by each move: xT(end cell) - xT(start cell) if successful, else 0.
    Returned as a float Series aligned with `moves`."""
    raise NotImplementedError("M4: rate_moves")
