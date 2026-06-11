"""Heuristic auto-player.

Strategy per piece:
  1. Enumerate all reachable (rot, x) landings via straight drop.
  2. For T pieces in tspin mode: also enumerate "soft-drop + rotate" entries
     that trigger the engine's T-spin detector (3-corner rule + last-action-rotate).
  3. Score each resulting board with El-Tetris-style weights.
  4. Also consider swapping hold (if available).
  5. Emit action queue: [rotations] + [lateral moves] (+ [soft_drop, final-rotate]
     for T-spin entries).

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
    # Multiplier applied to the T-spin score table when a placement triggers
    # the engine's T-spin detector. 0 in non-tspin modes.
    tspin_bonus: float = 0.0
    # Bonus per detectable T-slot left open on the resulting board. Encourages
    # the AI to preserve / build T-spin pockets between T pieces.
    tslot_preserve: float = 0.0


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
# wells penalty applies to columns 0-8 only (see _score) — the right-edge
# well is the one well we *want*, but a second well in the middle is junk.
WEIGHTS_TETRIS = Weights(
    landing=-2.5,
    rows=1.5,             # tetris = 1.5×4³ = 96 — must clearly beat the ~45
                          # right-well bonus forfeited by cashing in the well
    row_trans=-3.0,
    col_trans=-9.0,
    holes=-9.5,
    wells=-2.0,
    row_exp=3.0,
    right_well_bonus=9.0, # strongly reward depth on the rightmost column
)

# Depth past this earns no extra right-well shaping bonus: a tetris only needs
# 4 rows, and each extra well row already costs 2 row-transitions to maintain.
RIGHT_WELL_CAP = 5


def _ready_rows(grid, heights) -> int:
    """Rows the banked I would clear right now: counted upward from the top
    of column 9's stack, consecutive rows with columns 0-8 filled and the
    well cell empty. This — not min-column depth — is the actual tetris
    payout condition, so it's what the right-well bonus pays on."""
    h = len(grid)
    y = h - 1 - heights[9]
    ready = 0
    while y >= 0 and ready < 4:
        row = grid[y]
        if row[9] is None and all(row[x] is not None for x in range(9)):
            ready += 1
            y -= 1
        else:
            break
    return ready

# T-spin seeker: actively scores T-spin entries via SRS-kick rotation into
# 3-corner pockets, and rewards leaving open T-slots on the stack so future
# Ts have somewhere to land. Hole tolerance kept moderate so the AI doesn't
# bury the slots it just built.
WEIGHTS_TSPIN = Weights(
    landing=-3.0,
    rows=2.5,
    row_trans=-3.0,
    col_trans=-9.0,
    holes=-7.0,
    wells=-2.5,
    row_exp=1.0,
    tspin_bonus=5.0,
    tslot_preserve=30.0,
)

# Penalty applied when a T piece is placed without performing a T-spin —
# Cold Clear uses -152, but at our smaller score scale 60 is enough to make
# hold-swap dominate when an alternative exists.
WASTED_T_PENALTY = 60.0

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

# T-spin score table. Indexed by (kind, lines_cleared). Tracks the engine's
# actual scoring table (core/scoring.py ÷ 10) so the planner's preferences
# match what the game pays out; the AI weights them via tspin_bonus.
TSPIN_SCORE_TABLE = {
    ('mini', 0): 5,     # near-worthless, and it burns the T
    ('mini', 1): 20,
    ('mini', 2): 40,
    ('full', 0): 40,    # T-spin zero pays 400 in-game — worth taking
    ('full', 1): 80,
    ('full', 2): 120,   # T-spin double — the bread-and-butter
    ('full', 3): 160,   # TST
}

# SRS kicks whose y-offset is ±2 promote a mini T-spin to full (TST kick).
TST_KICKS = {(-1, -2), (1, -2), (-1, 2), (1, 2)}


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


def _piece_fits(grid, kind: str, rot: int, x: int, y: int) -> bool:
    h = len(grid)
    w = len(grid[0])
    for dx, dy in SHAPES[kind][rot]:
        gx = x + dx
        gy = y + dy
        if gx < 0 or gx >= w or gy >= h:
            return False
        if gy < 0:
            continue
        if grid[gy][gx] is not None:
            return False
    return True


def _is_grounded(grid, kind: str, rot: int, x: int, y: int) -> bool:
    return not _piece_fits(grid, kind, rot, x, y + 1)


def _corner_filled(grid, x: int, y: int) -> bool:
    """Walls / floor count as filled (matches Board.is_free semantics)."""
    h = len(grid)
    w = len(grid[0])
    if x < 0 or x >= w or y >= h:
        return True
    if y < 0:
        return False
    return grid[y][x] is not None


def _detect_t_spin_pose(grid, rot: int, x: int, y: int, last_kick: Tuple[int, int]) -> str:
    """Returns '', 'mini', or 'full' — replicates Game._detect_t_spin for an
    arbitrary pose (so the planner can score un-locked candidates)."""
    cx, cy = x + 1, y + 1
    corners = [
        (cx - 1, cy - 1), (cx + 1, cy - 1),
        (cx - 1, cy + 1), (cx + 1, cy + 1),
    ]
    filled = [_corner_filled(grid, fx, fy) for fx, fy in corners]
    if sum(filled) < 3:
        return ''
    front_sets = {0: (0, 1), 1: (1, 3), 2: (2, 3), 3: (0, 2)}
    fa, fb = front_sets[rot]
    if filled[fa] + filled[fb] == 2:
        return 'full'
    if last_kick in TST_KICKS:
        return 'full'
    return 'mini'


# A mini-shaped slot is worth keeping, but far less than a full-shaped one
# (mini single pays 200 in-game vs 1200 for a T-spin double).
MINI_SLOT_WEIGHT = 0.35

_FRONT_SETS = {0: (0, 1), 1: (1, 3), 2: (2, 3), 3: (0, 2)}


def _t_slot_kind(grid, rot: int, cx: int, cy: int) -> str:
    """'' if no slot, else 'mini'/'full': the cells the T would occupy at
    center (cx, cy) are empty AND 3 of the 4 corners are filled; 'full' when
    both front corners are filled (same rule as the engine's detector).
    Reachability is not verified — this is a structural check used to reward
    leaving pockets open."""
    x = cx - 1
    y = cy - 1
    h = len(grid)
    w = len(grid[0])
    for dx, dy in SHAPES['T'][rot]:
        gx = x + dx
        gy = y + dy
        if gx < 0 or gx >= w or gy >= h:
            return ''
        if gy < 0:
            continue
        if grid[gy][gx] is not None:
            return ''
    corners = [
        (cx - 1, cy - 1), (cx + 1, cy - 1),
        (cx - 1, cy + 1), (cx + 1, cy + 1),
    ]
    filled = [_corner_filled(grid, fx, fy) for fx, fy in corners]
    if sum(filled) < 3:
        return ''
    fa, fb = _FRONT_SETS[rot]
    return 'full' if filled[fa] + filled[fb] == 2 else 'mini'


def _count_t_slots(grid) -> float:
    """Weighted slot count: full-shaped slots count 1.0, mini-shaped 0.35.
    Capped so a deeply pocked stack doesn't dominate the score.
    Only scans a window around the stack top — slots can't form in the empty
    region above or fully buried far below, so a full 24×10 sweep wastes time."""
    h = len(grid)
    w = len(grid[0])
    # Stack top: highest non-empty row.
    top = h
    for y in range(h):
        if any(c is not None for c in grid[y]):
            top = y
            break
    if top >= h - 1:
        return 0.0  # empty board
    y_min = max(1, top - 1)
    y_max = min(h - 1, top + 5)
    total = 0.0
    for cy in range(y_min, y_max):
        for cx in range(1, w - 1):
            best = 0.0
            for rot in range(4):
                kind = _t_slot_kind(grid, rot, cx, cy)
                if kind == 'full':
                    best = 1.0
                    break
                if kind == 'mini':
                    best = MINI_SLOT_WEIGHT
            total += best
    return min(total, 3.0)


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


def _row_transitions(grid, treat_last_filled: bool = False) -> int:
    """treat_last_filled: count the last column as always filled. In tetris
    mode the open right well would otherwise cost 2 transitions per row,
    which silently *rewards* dumping blocks into the well (-3 × 2 = +6 per
    cell dumped) — more than the well bonus can counter."""
    h = len(grid)
    w = len(grid[0])
    last = w - 1
    t = 0
    for y in range(h):
        prev = True  # left wall = filled
        for x in range(w):
            cur = grid[y][x] is not None or (treat_last_filled and x == last)
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


def _wells(grid, heights, exclude_col: int = -1) -> int:
    w = len(heights)
    total = 0
    for x in range(w):
        if x == exclude_col:
            continue
        left = heights[x - 1] if x > 0 else heights[x]
        right = heights[x + 1] if x < w - 1 else heights[x]
        depth = min(left, right) - heights[x]
        if depth > 0:
            total += depth * (depth + 1) // 2
    return total


def _score(
    grid,
    landing_y_from_bottom: int,
    rows_cleared: int,
    w: Weights,
    t_spin: str = '',
    t_factor: float = 1.0,
) -> float:
    heights = _column_heights(grid)
    holes = _count_holes(grid, heights)
    rowt = _row_transitions(grid, treat_last_filled=w.right_well_bonus > 0)
    colt = _col_transitions(grid)
    # In tetris mode the right-edge well is intentional — exempt it from the
    # wells penalty so only *unwanted* wells (columns 0-8) are punished.
    well_excl = len(heights) - 1 if w.right_well_bonus > 0 else -1
    wells = _wells(grid, heights, exclude_col=well_excl)
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
        # Pay full rate on tetris-ready rows, plus a smaller shaping term on
        # raw well depth so progress counts even before a row completes.
        score += w.right_well_bonus * _ready_rows(grid, heights)
        other_min = min(heights[:9])
        depth = other_min - heights[9]
        if depth > 0:
            score += 0.4 * w.right_well_bonus * min(depth, RIGHT_WELL_CAP)
        # Blocks dumped into the well column poison future tetrises until
        # they're dug back out — charge for each one directly.
        score -= 0.6 * w.right_well_bonus * heights[9]
    if w.tspin_bonus > 0 and t_spin:
        score += w.tspin_bonus * TSPIN_SCORE_TABLE.get((t_spin, rows_cleared), 0)
    if w.tslot_preserve > 0:
        # t_factor scales slot rewards by how close a T is — preserving slots
        # when T is 6 pieces away just towers the stack and ends the run.
        score += w.tslot_preserve * t_factor * _count_t_slots(grid)
    return score


def _t_proximity_factor(game: Game) -> float:
    """How close is the next T? Used to scale slot-preservation rewards.
    Floor at 0.4 because the 7-bag randomizer guarantees a T within 7 pieces —
    setting it lower made the AI flatten slots assuming T would never come."""
    if game.hold == 'T':
        return 1.0
    upcoming = game.bag.peek(7)
    for i, kind in enumerate(upcoming):
        if kind == 'T':
            return max(0.4, 1.0 - 0.12 * i)
    return 0.4


def _danger_factor(grid) -> float:
    """1.0 when stack is safe, decays toward 0 when the stack is dangerously
    high. Used to suppress slot-preservation and wasted-T penalties so the AI
    will sacrifice setups for survival when it's about to top out."""
    h = len(grid)
    top = h
    for y in range(h):
        if any(c is not None for c in grid[y]):
            top = y
            break
    # Stack height measured from the bottom of the visible playfield.
    # Visible playfield is rows (h-20) .. (h-1). top < (h-20) means stack is
    # already in the buffer rows — extreme danger.
    visible_top = h - 20  # row index where visible playfield begins
    headroom = top - visible_top  # +ve = empty space above stack within visible
    if headroom >= 10:
        return 1.0
    if headroom >= 5:
        return (headroom - 4) / 6.0  # smooth ramp 1.0 → 0.17
    return 0.0  # panic — stack > 15 rows tall, ignore setups, just clear


@dataclass
class Plan:
    rot: int
    x: int
    use_hold: bool
    score: float
    # Lines the simulated placement cleared (set for T-spin entries; used to
    # judge whether an immediate spin is worth spending the T on).
    cleared: int = 0
    # T-spin entry fields (only meaningful when is_tspin=True). The piece
    # rotates from approach_rot at approach_x, soft-drops, then a single
    # rotation in `tspin_direction` snaps it into the slot via SRS kick.
    is_tspin: bool = False
    tspin_kind: str = ''
    approach_rot: int = 0
    approach_x: int = 0
    tspin_direction: int = 0  # +1 cw, -1 ccw


def _best_lookahead_t_bonus(grid, w: Weights) -> float:
    """Best T-spin bonus achievable by placing a T on `grid`. Returns 0 when
    no structural slot exists — short-circuits the 80-candidate enumeration
    in the common "no slot here" case, which is most placements."""
    if _count_t_slots(grid) <= 0.0:
        return 0.0
    best = 0.0
    for approach_rot in range(4):
        minos = SHAPES['T'][approach_rot]
        min_dx = min(m[0] for m in minos)
        max_dx = max(m[0] for m in minos)
        for approach_x in range(-min_dx, BOARD_W - max_dx):
            for direction in (1, -1):
                cand = _evaluate_tspin_entry(grid, approach_rot, approach_x, direction, w)
                if cand and cand.tspin_kind:
                    bonus = w.tspin_bonus * TSPIN_SCORE_TABLE.get(
                        (cand.tspin_kind, cand.cleared), 0
                    )
                    if bonus > best:
                        best = bonus
    return best


def _evaluate_placement(
    base_grid,
    kind: str,
    rot: int,
    x: int,
    w: Weights,
    t_factor: float = 1.0,
    slots_before: float = 0.0,
) -> Optional[Tuple[float, int, int]]:
    y = _drop_y(base_grid, kind, rot, x)
    if y is None:
        return None
    grid = [row[:] for row in base_grid]
    _apply_piece(grid, kind, rot, x, y)
    cleared = _clear_lines(grid)
    max_dy = max(dy for _, dy in SHAPES[kind][rot])
    landing_y_from_bottom = len(base_grid) - (y + max_dy)
    score = _score(grid, landing_y_from_bottom, cleared, w, t_factor=t_factor)
    if w.tspin_bonus > 0:
        if kind == 'T' and not cleared:
            # Wasted-T penalty: a T placed as filler is a missed T-spin
            # opportunity. The hold logic in plan() should usually catch this,
            # but when hold is already used or held piece is also T, we end up
            # here. Make plopping the T expensive so any non-trivial alternative
            # (e.g. odd-shape stacking by another piece) is preferred.
            score -= WASTED_T_PENALTY
        elif kind != 'T':
            # Slot-destruction penalty.
            if slots_before > 0:
                slots_after = _count_t_slots(grid)
                if slots_after < slots_before:
                    score -= (slots_before - slots_after) * w.tslot_preserve * 1.5 * t_factor
            # Lookahead is the most expensive scoring branch — only run when a
            # T is close enough that the projection actually pays off.
            if t_factor >= 0.55:
                score += 0.5 * t_factor * _best_lookahead_t_bonus(grid, w)
    return score, y, cleared


def _evaluate_tspin_entry(
    base_grid,
    approach_rot: int,
    approach_x: int,
    direction: int,
    w: Weights,
    t_factor: float = 1.0,
) -> Optional[Plan]:
    y = _drop_y(base_grid, 'T', approach_rot, approach_x)
    if y is None:
        return None
    target_rot = (approach_rot + direction) % 4
    kicks = get_kicks('T', approach_rot, target_rot)
    for kick_dx, kick_dy in kicks:
        final_x = approach_x + kick_dx
        final_y = y + kick_dy
        if not _piece_fits(base_grid, 'T', target_rot, final_x, final_y):
            continue
        # Engine takes the first non-colliding kick — break either way.
        # Reject if rotated pose isn't grounded; gravity would pull it further
        # and reset last_action_rotate, killing the T-spin detect.
        if not _is_grounded(base_grid, 'T', target_rot, final_x, final_y):
            return None
        t_spin = _detect_t_spin_pose(
            base_grid, target_rot, final_x, final_y, (kick_dx, kick_dy)
        )
        if not t_spin:
            return None
        grid = [row[:] for row in base_grid]
        _apply_piece(grid, 'T', target_rot, final_x, final_y)
        cleared = _clear_lines(grid)
        max_dy = max(dy for _, dy in SHAPES['T'][target_rot])
        landing_y_from_bottom = len(base_grid) - (final_y + max_dy)
        score = _score(grid, landing_y_from_bottom, cleared, w, t_spin=t_spin, t_factor=t_factor)
        return Plan(
            rot=target_rot,
            x=final_x,
            use_hold=False,
            score=score,
            cleared=cleared,
            is_tspin=True,
            tspin_kind=t_spin,
            approach_rot=approach_rot,
            approach_x=approach_x,
            tspin_direction=direction,
        )
    return None


def _best_placement(
    base_grid,
    kind: str,
    w: Weights,
    t_factor: float = 1.0,
) -> Optional[Plan]:
    best: Optional[Plan] = None
    slots_before = _count_t_slots(base_grid) if (kind != 'T' and w.tspin_bonus > 0 and t_factor > 0.0) else 0.0
    for rot in range(4):
        minos = SHAPES[kind][rot]
        min_dx = min(m[0] for m in minos)
        max_dx = max(m[0] for m in minos)
        for x in range(-min_dx, BOARD_W - max_dx):
            r = _evaluate_placement(base_grid, kind, rot, x, w, t_factor, slots_before)
            if r is None:
                continue
            score, _y, cleared = r
            if best is None or score > best.score:
                best = Plan(rot=rot, x=x, use_hold=False, score=score, cleared=cleared)
    if kind == 'T' and w.tspin_bonus > 0:
        for approach_rot in range(4):
            minos = SHAPES['T'][approach_rot]
            min_dx = min(m[0] for m in minos)
            max_dx = max(m[0] for m in minos)
            for approach_x in range(-min_dx, BOARD_W - max_dx):
                for direction in (1, -1):
                    cand = _evaluate_tspin_entry(
                        base_grid, approach_rot, approach_x, direction, w, t_factor
                    )
                    if cand is None:
                        continue
                    if best is None or cand.score > best.score:
                        best = cand
    return best


# Below this danger level the AI abandons setup play entirely and falls back
# to pure-survival weights. Corresponds to a stack ≥ ~14 rows tall.
PANIC_DANGER = 0.35


def plan(game: Game, mode: str = 'calm') -> Optional[Plan]:
    if game.piece is None:
        return None
    w = MODES.get(mode, WEIGHTS_CALM)
    grid = game.board.snapshot()

    danger = _danger_factor(grid)
    if danger <= PANIC_DANGER and (w.tspin_bonus > 0 or w.right_well_bonus > 0):
        # Panic: stack is near the ceiling. Drop all setup play — well
        # discipline, slot preservation, wasted-T penalties — and dig with
        # survival weights until there's headroom again.
        w = WEIGHTS_CALM

    if w.tspin_bonus > 0:
        # Multiplied factor: T proximity × stack-danger gating. When stack is
        # high, slot-preservation rewards collapse to keep the AI alive.
        t_factor = _t_proximity_factor(game) * danger
    else:
        t_factor = 0.0

    # Tspin mode: when the *current* piece is T and no worthwhile T-spin
    # entry exists on the current board, save it for later by holding instead
    # of plopping it down as a normal piece. "Worthwhile" = any full spin, or
    # a mini that clears a line — a mini T-spin zero pays ~nothing and burns
    # the T, so we hold through those too. This is the single biggest
    # behavioral fix — without it the AI burns Ts on flat boards and never
    # has one in reserve when a slot finally appears.
    if (
        w.tspin_bonus > 0
        and game.piece.kind == 'T'
        and not game.hold_used
        and game.hold != 'T'
    ):
        immediate = _best_tspin_only(grid, w)
        worthwhile = immediate is not None and (
            immediate.tspin_kind == 'full' or immediate.cleared >= 1
        )
        if not worthwhile:
            hold_kind = game.hold if game.hold is not None else game.bag.peek(1)[0]
            # After hold-swap, the held T is in reserve → t_factor=1.0.
            alt = _best_placement(grid, hold_kind, w, t_factor=1.0)
            if alt is not None:
                alt.use_hold = True
                return alt

    # Tetris mode: manage the I piece around the right-edge well. The test
    # for both banking and firing is the same: can an I clear 4 lines on this
    # board right now?
    if w.right_well_bonus > 0 and not game.hold_used:
        if game.piece.kind == 'I' and game.hold != 'I':
            # Bank the I unless it can pay out a tetris immediately —
            # otherwise the eval happily spends it as flat filler and the
            # well starves.
            best_i = _best_placement(grid, 'I', w)
            if best_i is None or best_i.cleared < 4:
                hold_kind = game.hold if game.hold is not None else game.bag.peek(1)[0]
                alt = _best_placement(grid, hold_kind, w)
                if alt is not None:
                    alt.use_hold = True
                    return alt
            # else: fall through — the generic plan below picks the tetris.
        elif game.hold == 'I' and game.piece.kind != 'I':
            # Fire the banked I as soon as it can clear a tetris. Without
            # this the generic hold compare below (with its anti-waste
            # margin) keeps the I locked up while the well sits ready.
            alt = _best_placement(grid, 'I', w)
            if alt is not None and alt.cleared >= 4:
                alt.use_hold = True
                return alt

    cur = _best_placement(grid, game.piece.kind, w, t_factor=t_factor)

    if not game.hold_used:
        hold_kind = game.hold if game.hold is not None else game.bag.peek(1)[0]
        alt = _best_placement(grid, hold_kind, w, t_factor=t_factor)
        # A banked I is for the tetris — only release it for a 4-line clear
        # (or under a much larger margin, e.g. the stack badly needs an I).
        margin = 5.0
        if w.right_well_bonus > 0 and hold_kind == 'I' and (alt is None or alt.cleared < 4):
            margin = 60.0
        if alt is not None and (cur is None or alt.score > cur.score + margin):
            alt.use_hold = True
            return alt
    return cur


def _best_tspin_only(base_grid, w: Weights) -> Optional[Plan]:
    """Returns the best T-spin entry on this grid, or None if none reachable."""
    best: Optional[Plan] = None
    for approach_rot in range(4):
        minos = SHAPES['T'][approach_rot]
        min_dx = min(m[0] for m in minos)
        max_dx = max(m[0] for m in minos)
        for approach_x in range(-min_dx, BOARD_W - max_dx):
            for direction in (1, -1):
                cand = _evaluate_tspin_entry(
                    base_grid, approach_rot, approach_x, direction, w
                )
                if cand is None:
                    continue
                if best is None or cand.score > best.score:
                    best = cand
    return best


def _shortest_rot_seq(from_rot: int, to_rot: int) -> List[str]:
    diff = (to_rot - from_rot) % 4
    if diff == 0:
        return []
    if diff == 1:
        return ['cw']
    if diff == 2:
        return ['cw', 'cw']
    return ['ccw']


def _simulate_rotation(grid, p: Piece, direction: int) -> Optional[Piece]:
    from_rot = p.rot
    to_rot = (from_rot + direction) % 4
    for dx, dy in get_kicks(p.kind, from_rot, to_rot):
        test = Piece(p.kind, p.x + dx, p.y + dy, to_rot)
        if not _collides_grid(grid, test):
            return test
    return None


def plan_to_actions(game: Game, plan_: Plan) -> List[str]:
    """Convert a plan to an action queue, simulating rotations/kicks on a shadow copy."""
    if plan_.use_hold:
        return ['hold']  # caller should re-plan after hold swap resolves
    if plan_.is_tspin:
        return _tspin_to_actions(game, plan_)

    actions: List[str] = []
    # Simulate on a shadow piece to track x shifts from wall kicks.
    p = game.piece.clone()
    rot_seq = _shortest_rot_seq(p.rot, plan_.rot)

    for r in rot_seq:
        direction = 1 if r == 'cw' else -1
        rotated = _simulate_rotation(game.board.grid, p, direction)
        if rotated is None:
            # Planned rotation isn't reachable. Drop whatever we've queued;
            # gravity will land the piece and the next plan runs against the
            # post-lock state.
            return actions
        p = rotated
        actions.append(r)

    dx = plan_.x - p.x
    if dx > 0:
        actions.extend(['right'] * dx)
    elif dx < 0:
        actions.extend(['left'] * (-dx))
    # No hard_drop — gravity carries the piece down and lock delay finalizes it.
    return actions


def _tspin_to_actions(game: Game, plan_: Plan) -> List[str]:
    """T-spin entry sequence: pre-rotate, slide, soft-drop, then a final
    rotation that triggers the SRS kick into the slot. The last action MUST
    be the rotation so last_action_rotate stays True at lock time."""
    actions: List[str] = []
    p = game.piece.clone()
    grid = game.board.grid

    rot_seq = _shortest_rot_seq(p.rot, plan_.approach_rot)
    for r in rot_seq:
        direction = 1 if r == 'cw' else -1
        rotated = _simulate_rotation(grid, p, direction)
        if rotated is None:
            return actions
        p = rotated
        actions.append(r)

    dx = plan_.approach_x - p.x
    if dx > 0:
        actions.extend(['right'] * dx)
    elif dx < 0:
        actions.extend(['left'] * (-dx))

    actions.append('soft_drop')
    actions.append('cw' if plan_.tspin_direction == 1 else 'ccw')
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
