"""M4 acceptance tests: expected threat."""

import numpy as np
import pandas as pd
import pytest

from fdl import xt


def _toy():
    """Two cells (left half = 0, right half = 1), worked out by hand:
    cell 0: 4 moves (2 successful to cell 1, 2 failed), no shot
            -> s0 = 0, m0 = 1, T01 = 2/4
    cell 1: 2 moves (both successful to cell 0) + 2 shots (1 goal)
            -> s1 = 1/2, g1 = 1/2, m1 = 1/2, T10 = 2/2
    xT1 = 1/4 + 1/2 * xT0 ;  xT0 = 1/2 * xT1   =>  xT1 = 1/3, xT0 = 1/6
    """
    moves = pd.DataFrame({
        "x":       [30, 30, 30, 30, 90, 90],
        "y":       [40] * 6,
        "end_x":   [90, 90, 40, 50, 30, 20],
        "end_y":   [40] * 6,
        "success": [True, True, False, False, True, True],
    })
    shots = pd.DataFrame({"x": [100, 110], "y": [40, 40], "is_goal": [1, 0]})
    return moves, shots


def test_toy_grid():
    moves, shots = _toy()
    grid = xt.expected_threat(moves, shots, nx=2, ny=1, n_iter=100)
    assert grid.shape == (1, 2)
    assert grid[0] == pytest.approx([1 / 6, 1 / 3], abs=1e-6)


def test_empty_cells_are_zero():
    moves, shots = _toy()
    grid = xt.expected_threat(moves, shots, nx=4, ny=2, n_iter=100)
    assert grid.shape == (2, 4)
    assert np.isfinite(grid).all()
    # Every action is at y = 40, which falls in row 1: row 0 never sees the ball.
    assert (grid[0] == 0).all()


def test_rate_moves_toy():
    moves, shots = _toy()
    grid = xt.expected_threat(moves, shots, nx=2, ny=1, n_iter=100)
    v = xt.rate_moves(moves, grid)
    assert isinstance(v, pd.Series) and v.index.equals(moves.index)
    assert v.tolist() == pytest.approx([1 / 6, 1 / 6, 0, 0, -1 / 6, -1 / 6], abs=1e-6)


def test_real_grid(con):
    moves, shots = xt.load_actions(con)
    grid = xt.expected_threat(moves, shots)
    assert grid.shape == (12, 16)
    assert ((grid >= 0) & (grid <= 1)).all()
    iy, ix = np.unravel_index(grid.argmax(), grid.shape)
    assert ix >= 14, "the most threatening cell should be next to the goal"
    assert grid[:, -3:].mean() > 5 * grid[:, :8].mean()
