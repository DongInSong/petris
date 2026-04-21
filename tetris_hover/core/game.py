"""Guideline tetris state machine.

Exposes atomic actions (move, rotate, soft_drop, hard_drop, hold) plus a tick()
that advances lock delay. Gravity is not automatic — callers (the AI) request
soft_drop when they want the piece to fall. This keeps play deterministic for
the auto-player.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .board import Board
from .bag import SevenBag
from .pieces import (
    SHAPES,
    SPAWN_COL,
    SPAWN_ROW,
    get_kicks,
)

LOCK_DELAY_MS = 500
LOCK_MOVE_RESETS = 15
# Pause after a top-out so the collapse animation has time to play out before
# the next piece spawns.
DEATH_PAUSE_MS = 1500


@dataclass
class Piece:
    kind: str
    x: int
    y: int
    rot: int = 0

    def minos(self) -> List[Tuple[int, int]]:
        return [(self.x + dx, self.y + dy) for dx, dy in SHAPES[self.kind][self.rot]]

    def clone(self) -> 'Piece':
        return Piece(self.kind, self.x, self.y, self.rot)


@dataclass
class ClearEvent:
    rows: List[int]
    t_spin: str  # '', 'mini', 'full'
    piece_kind: str
    perfect_clear: bool = False


@dataclass
class TopOutEvent:
    """Emitted on top-out. Carries a snapshot of the pre-wipe grid so the UI
    can animate the stack collapsing before the next piece spawns."""
    grid_snapshot: list = field(default_factory=list)


@dataclass
class Game:
    seed: Optional[int] = None
    board: Board = field(default_factory=Board)
    bag: SevenBag = field(init=False)
    piece: Optional[Piece] = None
    hold: Optional[str] = None
    hold_used: bool = False
    lock_timer_ms: int = 0
    on_ground: bool = False
    lock_resets_left: int = LOCK_MOVE_RESETS
    last_action_rotate: bool = False
    last_kick: Tuple[int, int] = (0, 0)
    pending_events: List = field(default_factory=list)
    death_remaining_ms: int = 0

    def __post_init__(self) -> None:
        self.bag = SevenBag(self.seed)
        self._spawn()

    # ---- spawn / collision -------------------------------------------------
    def _spawn(self, kind: Optional[str] = None) -> None:
        if kind is None:
            kind = self.bag.next()
        self.piece = Piece(kind=kind, x=SPAWN_COL, y=SPAWN_ROW, rot=0)
        self.hold_used = False
        self.lock_timer_ms = 0
        self.lock_resets_left = LOCK_MOVE_RESETS
        self.last_action_rotate = False
        self.last_kick = (0, 0)
        self._refresh_ground()
        if self._collides(self.piece):
            # Spawn collision = board too high. Wipe and retry.
            self._wipe_board()
            self.piece.x = SPAWN_COL
            self.piece.y = SPAWN_ROW
            self.piece.rot = 0
            self._refresh_ground()

    def _wipe_board(self) -> None:
        snap = [row[:] for row in self.board.grid]
        for row in self.board.grid:
            for i in range(len(row)):
                row[i] = None
        self.pending_events.append(TopOutEvent(grid_snapshot=snap))

    def _collides(self, p: Piece) -> bool:
        for x, y in p.minos():
            if not self.board.is_free(x, y):
                return True
        return False

    def _refresh_ground(self) -> None:
        if self.piece is None:
            self.on_ground = False
            return
        below = self.piece.clone()
        below.y += 1
        self.on_ground = self._collides(below)

    def _note_successful_move(self) -> None:
        # Reset lock timer on successful move/rotate while grounded, up to a cap.
        if self.on_ground and self.lock_resets_left > 0:
            self.lock_timer_ms = 0
            self.lock_resets_left -= 1

    # ---- actions -----------------------------------------------------------
    def move(self, dx: int) -> bool:
        if self.piece is None:
            return False
        test = self.piece.clone()
        test.x += dx
        if self._collides(test):
            return False
        self.piece = test
        self.last_action_rotate = False
        self._refresh_ground()
        self._note_successful_move()
        return True

    def soft_drop(self) -> bool:
        if self.piece is None:
            return False
        test = self.piece.clone()
        test.y += 1
        if self._collides(test):
            self.on_ground = True
            return False
        self.piece = test
        self.last_action_rotate = False
        self._refresh_ground()
        # Don't count gravity drop as a lock-reset move.
        return True

    def hard_drop(self) -> None:
        if self.piece is None:
            return
        while True:
            test = self.piece.clone()
            test.y += 1
            if self._collides(test):
                break
            self.piece = test
        self._lock()

    def rotate(self, direction: int) -> bool:
        if self.piece is None or self.piece.kind == 'O':
            return False
        from_rot = self.piece.rot
        to_rot = (from_rot + direction) % 4
        for dx, dy in get_kicks(self.piece.kind, from_rot, to_rot):
            test = self.piece.clone()
            test.x += dx
            test.y += dy
            test.rot = to_rot
            if not self._collides(test):
                self.piece = test
                self.last_action_rotate = True
                self.last_kick = (dx, dy)
                self._refresh_ground()
                self._note_successful_move()
                return True
        return False

    def swap_hold(self) -> bool:
        if self.piece is None or self.hold_used:
            return False
        current_kind = self.piece.kind
        if self.hold is None:
            self.hold = current_kind
            self._spawn()
        else:
            new_kind = self.hold
            self.hold = current_kind
            self._spawn(kind=new_kind)
        self.hold_used = True
        return True

    # ---- locking / line clears --------------------------------------------
    def _detect_t_spin(self) -> str:
        """Returns '', 'mini', or 'full'. Uses 3-corner rule + last action rotation."""
        if self.piece is None or self.piece.kind != 'T' or not self.last_action_rotate:
            return ''
        # T's center mino is at (x+1, y+1) in its 3x3 bbox.
        cx, cy = self.piece.x + 1, self.piece.y + 1
        corners = [
            (cx - 1, cy - 1), (cx + 1, cy - 1),
            (cx - 1, cy + 1), (cx + 1, cy + 1),
        ]
        filled = [not self.board.is_free(x, y) for (x, y) in corners]
        if sum(filled) < 3:
            return ''
        # Front corners (the two on the "open" side of the T).
        front_sets = {
            0: (0, 1),  # facing up: top-left, top-right
            1: (1, 3),  # facing right: top-right, bottom-right
            2: (2, 3),  # facing down: bottom-left, bottom-right
            3: (0, 2),  # facing left: top-left, bottom-left
        }
        fa, fb = front_sets[self.piece.rot]
        front_filled = filled[fa] + filled[fb]
        if front_filled == 2:
            return 'full'
        # TST-style kick: last test in kick table produces full T-spin.
        if self.last_kick in [(-1, -2), (1, -2), (-1, 2), (1, 2)]:
            return 'full'
        return 'mini'

    def _lock(self) -> None:
        if self.piece is None:
            return
        t_spin = self._detect_t_spin()
        piece_kind = self.piece.kind
        for x, y in self.piece.minos():
            self.board.set(x, y, piece_kind)
        # Top-out: locked piece entirely in buffer above visible area and nothing cleared.
        top_out = all(y < self.board.h - 20 for _, y in self.piece.minos())
        cleared = self.board.clear_full_lines()
        perfect = all(c is None for row in self.board.grid for c in row)
        self.pending_events.append(
            ClearEvent(rows=cleared, t_spin=t_spin, piece_kind=piece_kind, perfect_clear=perfect)
        )
        self.piece = None
        if top_out and not cleared:
            self._wipe_board()
            self.death_remaining_ms = DEATH_PAUSE_MS
            return  # hold off on spawning until the collapse animation plays
        self._spawn()

    def tick(self, dt_ms: int) -> None:
        """Advance lock delay or death countdown. No automatic gravity."""
        if self.death_remaining_ms > 0:
            self.death_remaining_ms -= dt_ms
            if self.death_remaining_ms <= 0:
                self.death_remaining_ms = 0
                if self.piece is None:
                    self._spawn()
            return
        if self.piece is None:
            return
        self._refresh_ground()
        if self.on_ground:
            self.lock_timer_ms += dt_ms
            if self.lock_timer_ms >= LOCK_DELAY_MS:
                self._lock()
        else:
            self.lock_timer_ms = 0

    def drain_events(self) -> List:
        evts, self.pending_events = self.pending_events, []
        return evts
