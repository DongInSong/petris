"""Heuristic auto-player.

Strategy per piece:
  1. Enumerate all reachable (rot, x) landings via straight drop.
  2. Score each resulting board with El-Tetris-style weights.
  3. Also consider swapping hold (if available).
  4. Emit action queue: [rotations] + [lateral moves] + [hard_drop].

The emitted action queue is consumed one action per tick by the engine, which
gives pieces a visible slide/rotate animation instead of teleporting.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple

from ..core.game import Game, Piece
from ..core.pieces import BOARD_W, SHAPES, get_kicks

# Weight profiles shape how the AI plays. Swap between them via the
# `mode` argument on `plan()`.


@dataclass(frozen=True)
class Weights:
    landing: float
    rows: float
    row_trans: float
    col_trans: float
    holes: float
    wells: float
    # row_exp > 1 makes multi-line clears disproportionately more valuable
    # than singles (encourages tetrises over trickle clears).
    row_exp: float = 1.0
    # When > 0 the AI earns a bonus for every row of "depth" the rightmost
    # column is kept below the minimum of the other nine — i.e., it protects
    # a tetris well on the right edge.
    right_well_bonus: float = 0.0


# Original El-Tetris (Dellacherie + improvements). Steady, mostly singles.
WEIGHTS_CALM = Weights(
    landing=-4.500158825082766,
    rows=3.4181268101392694,
    row_trans=-3.2178882868487753,
    col_trans=-9.348695305445199,
    holes=-7.899265427351652,
    wells=-3.3855972247263626,
)

# Tetris-chaser: exponential reward for bigger clears + right-edge well.
WEIGHTS_TETRIS = Weights(
    landing=-2.5,
    rows=1.0,
    row_trans=-3.0,
    col_trans=-9.0,
    holes=-9.5,
    wells=0.0,            # allow an arbitrarily deep well (no penalty)
    row_exp=3.0,          # tetris = 4^3 = 64× single
    right_well_bonus=9.0, # strongly reward depth on the rightmost column
)

# Messy / T-spin seeker: tolerates holes so "shelves" form that occasionally
# let the game's T-spin detector trigger. No true pattern-matching — the AI
# just builds stranger stacks and lets luck + combo scoring do the rest.
WEIGHTS_TSPIN = Weights(
    landing=-2.0,
    rows=0.8,
    row_trans=-2.0,
    col_trans=-6.0,
    holes=-1.5,           # very tolerant — encourages overhangs / shelves
    wells=-1.5,
    row_exp=1.8,
)

MODES = {
    'calm': WEIGHTS_CALM,
    'tetris': WEIGHTS_TETRIS,
    'tspin': WEIGHTS_TSPIN,
}

# Back-compat constants some callers or tests may use.
W_LANDING = WEIGHTS_CALM.landing
W_ROWS = WEIGHTS_CALM.rows
W_ROW_TRANS = WEIGHTS_CALM.row_trans
W_COL_TRANS = WEIGHTS_CALM.col_trans
W_HOLES = WEIGHTS_CALM.holes
W_WELLS = WEIGHTS_CALM.wells


def _drop_y(grid, kind: str, rot: int, x: int) -> Optional[int]:
    minos = SHAPES[kind][rot]
    min_dx = min(m[0] for m in minos)
    max_dx = max(m[0] for m in minos)
    if x + min_dx < 0 or x + max_dx >= BOARD_W:
        return None
    h = len(grid)
    # Binary search via simulation: start at top, increment until collision.
    y = -3
    while True:
        test_y = y + 1
        collides = False
        for dx, dy in minos:
            mx = x + dx
            my = test_y + dy
            if my >= h:
                collides = True
                break
            if my >= 0 and grid[my][mx] is not None:
                collides = True
                break
        if collides:
            break
        y = test_y
    # Reject if piece ends above the buffer entirely (nothing supporting it).
    if y < -3:
        return None
    # Reject placements fully above visible area (top-out).
    minos_y = [y + dy for _, dy in minos]
    if max(minos_y) < h - 20:
        return None
    return y


def _apply_piece(grid, kind: str, rot: int, x: int, y: int):
    for dx, dy in SHAPES[kind][rot]:
        gx = x + dx
        gy = y + dy
        if 0 <= gy < len(grid) and 0 <= gx < len(grid[0]):
            grid[gy][gx] = kind


def _clear_lines(grid) -> int:
    h = len(grid)
    w = len(grid[0])
    kept = [row[:] for row in grid if not all(c is not None for c in row)]
    cleared = h - len(kept)
    while len(kept) < h:
        kept.insert(0, [None] * w)
    grid[:] = kept
    return cleared


def _column_heights(grid) -> List[int]:
    h = len(grid)
    w = len(grid[0])
    out = [0] * w
    for x in range(w):
        for y in range(h):
            if grid[y][x] is not None:
                out[x] = h - y
                break
    return out


def _count_holes(grid, heights) -> int:
    h = len(grid)
    w = len(grid[0])
    holes = 0
    for x in range(w):
        top_y = h - heights[x]
        for y in range(top_y + 1, h):
            if grid[y][x] is None:
                holes += 1
    return holes


def _row_transitions(grid) -> int:
    h = len(grid)
    w = len(grid[0])
    t = 0
    for y in range(h):
        prev = True  # left wall = filled
        for x in range(w):
            cur = grid[y][x] is not None
            if cur != prev:
                t += 1
            prev = cur
        if not prev:
            t += 1  # right wall
    return t


def _col_transitions(grid) -> int:
    h = len(grid)
    w = len(grid[0])
    t = 0
    for x in range(w):
        prev = True  # floor = filled (but we measure top-to-bottom, start from above = empty)
        prev = False
        for y in range(h):
            cur = grid[y][x] is not None
            if cur != prev:
                t += 1
            prev = cur
        if not prev:
            t += 1  # bottom wall is filled, so last empty->wall is a transition
    return t


def _wells(grid, heights) -> int:
    w = len(heights)
    total = 0
    for x in range(w):
        left = heights[x - 1] if x > 0 else heights[x]
        right = heights[x + 1] if x < w - 1 else heights[x]
        depth = min(left, right) - heights[x]
        if depth > 0:
            total += depth * (depth + 1) // 2
    return total


def _score(grid, landing_y_from_bottom: int, rows_cleared: int, w: Weights) -> float:
    heights = _column_heights(grid)
    holes = _count_holes(grid, heights)
    rowt = _row_transitions(grid)
    colt = _col_transitions(grid)
    wells = _wells(grid, heights)
    row_reward = w.rows * (rows_cleared ** w.row_exp) if rows_cleared > 0 else 0.0
    score = (
        w.landing * landing_y_from_bottom
        + row_reward
        + w.row_trans * rowt
        + w.col_trans * colt
        + w.holes * holes
        + w.wells * wells
    )
    if w.right_well_bonus > 0:
        other_min = min(heights[:9])
        depth = other_min - heights[9]
        if depth > 0:
            score += w.right_well_bonus * depth
    return score


@dataclass
class Plan:
    rot: int
    x: int
    use_hold: bool
    score: float


def _evaluate_placement(base_grid, kind: str, rot: int, x: int, w: Weights) -> Optional[Tuple[float, int]]:
    y = _drop_y(base_grid, kind, rot, x)
    if y is None:
        return None
    grid = [row[:] for row in base_grid]
    _apply_piece(grid, kind, rot, x, y)
    cleared = _clear_lines(grid)
    max_dy = max(dy for _, dy in SHAPES[kind][rot])
    landing_y_from_bottom = len(base_grid) - (y + max_dy)
    score = _score(grid, landing_y_from_bottom, cleared, w)
    return score, y


def _best_placement(base_grid, kind: str, w: Weights) -> Optional[Plan]:
    best: Optional[Plan] = None
    for rot in range(4):
        minos = SHAPES[kind][rot]
        min_dx = min(m[0] for m in minos)
        max_dx = max(m[0] for m in minos)
        for x in range(-min_dx, BOARD_W - max_dx):
            r = _evaluate_placement(base_grid, kind, rot, x, w)
            if r is None:
                continue
            score, _y = r
            if best is None or score > best.score:
                best = Plan(rot=rot, x=x, use_hold=False, score=score)
    return best


def plan(game: Game, mode: str = 'calm') -> Optional[Plan]:
    if game.piece is None:
        return None
    w = MODES.get(mode, WEIGHTS_CALM)
    grid = game.board.snapshot()
    cur = _best_placement(grid, game.piece.kind, w)

    if not game.hold_used:
        hold_kind = game.hold if game.hold is not None else game.bag.peek(1)[0]
        alt = _best_placement(grid, hold_kind, w)
        if alt is not None and (cur is None or alt.score > cur.score + 5.0):
            alt.use_hold = True
            return alt
    return cur


def plan_to_actions(game: Game, plan_: Plan) -> List[str]:
    """Convert a plan to an action queue, simulating rotations/kicks on a shadow copy."""
    if plan_.use_hold:
        return ['hold']  # caller should re-plan after hold swap resolves

    actions: List[str] = []
    # Simulate on a shadow piece to track x shifts from wall kicks.
    p = game.piece.clone()
    target_rot = plan_.rot
    # Pick shortest rotation path.
    diff = (target_rot - p.rot) % 4
    rot_seq: List[str] = []
    if diff == 1:
        rot_seq = ['cw']
    elif diff == 2:
        rot_seq = ['cw', 'cw']
    elif diff == 3:
        rot_seq = ['ccw']

    for r in rot_seq:
        direction = 1 if r == 'cw' else -1
        from_rot = p.rot
        to_rot = (from_rot + direction) % 4
        applied = False
        for dx, dy in get_kicks(p.kind, from_rot, to_rot):
            test = Piece(p.kind, p.x + dx, p.y + dy, to_rot)
            if not _collides_grid(game.board.grid, test):
                p = test
                actions.append(r)
                applied = True
                break
        if not applied:
            # Planned rotation isn't reachable. Drop whatever we've queued;
            # gravity will land the piece and the next plan runs against the
            # post-lock state.
            return actions

    dx = plan_.x - p.x
    if dx > 0:
        actions.extend(['right'] * dx)
    elif dx < 0:
        actions.extend(['left'] * (-dx))
    # No hard_drop — gravity carries the piece down and lock delay finalizes it.
    return actions


def _collides_grid(grid, p: Piece) -> bool:
    h = len(grid)
    w = len(grid[0])
    for x, y in p.minos():
        if x < 0 or x >= w or y >= h:
            return True
        if y < 0:
            continue
        if grid[y][x] is not None:
            return True
    return False
