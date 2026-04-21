"""Guideline-style scoring + session tracking.

Scoring table (guideline-ish):
    single   = 100
    double   = 300
    triple   = 500
    tetris   = 800
    t_mini   = 100         (no lines)
    t_mini_single = 200
    t_mini_double = 400
    t_single = 800
    t_double = 1200
    t_triple = 1600
    combo    = +50 per consecutive-clear step
    b2b      = ×1.5 for consecutive "hard" clears (tetris or t-spin-with-clear)
    perfect_clear = +1000 (regardless of line count; simplified)

Session scoring = base_score × current_typing_multiplier at the moment of the clear.
Idle play still earns points (at 1.0×), typing accelerates both piece rate *and*
per-clear reward.
"""
from dataclasses import dataclass

from .game import ClearEvent

BASE_BY_LINES = {0: 0, 1: 100, 2: 300, 3: 500, 4: 800}
T_SPIN_FULL = {0: 400, 1: 800, 2: 1200, 3: 1600}
T_SPIN_MINI = {0: 100, 1: 200, 2: 400, 3: 400}
COMBO_STEP = 50
B2B_MULT = 1.5
PERFECT_CLEAR_BONUS = 1000


def _base_score(evt: ClearEvent) -> int:
    n = len(evt.rows)
    if evt.t_spin == 'full':
        return T_SPIN_FULL[n]
    if evt.t_spin == 'mini':
        return T_SPIN_MINI[n]
    return BASE_BY_LINES[n]


def _is_hard_clear(evt: ClearEvent) -> bool:
    """A 'hard' clear extends B2B: tetris or T-spin with at least one line."""
    if len(evt.rows) == 4:
        return True
    if evt.t_spin and len(evt.rows) >= 1:
        return True
    return False


@dataclass
class Session:
    """Running totals for the current app session."""
    score: float = 0.0
    raw_score: float = 0.0  # unweighted tetris score
    lines: int = 0
    pieces: int = 0
    keystrokes: int = 0
    combo: int = -1  # -1 = no active combo; advances on each consecutive line clear
    b2b: int = 0     # consecutive hard clears; 0 = no bonus
    max_combo: int = 0
    max_b2b: int = 0
    started_at_ms: float = 0.0
    last_active_ms: float = 0.0
    active_ms: float = 0.0  # total time with keystrokes (for "active minutes")

    def on_piece_locked(self) -> None:
        self.pieces += 1

    def on_clear(self, evt: ClearEvent, multiplier: float) -> float:
        """Apply a clear event. Returns points awarded (weighted)."""
        n = len(evt.rows)
        if n == 0 and evt.t_spin == '':
            # Not a clear and not a T-spin; reset combo only.
            self.combo = -1
            return 0.0

        base = _base_score(evt)
        if n > 0:
            self.combo += 1
            if self.combo > self.max_combo:
                self.max_combo = self.combo
            base += COMBO_STEP * self.combo
        else:
            # T-spin with no lines doesn't advance combo but doesn't break it either.
            pass

        if _is_hard_clear(evt):
            self.b2b += 1
            if self.b2b > self.max_b2b:
                self.max_b2b = self.b2b
            if self.b2b > 1:
                base = int(base * B2B_MULT)
        elif n > 0:
            # Non-hard clear resets B2B.
            self.b2b = 0

        if evt.perfect_clear and n > 0:
            base += PERFECT_CLEAR_BONUS

        if n == 0:
            # No line → no combo progression, keep combo alive for T-spin zero.
            # (Guideline actually does reset combo here; simplified to keep.)
            pass

        weighted = base * max(1.0, multiplier)
        self.score += weighted
        self.raw_score += base
        self.lines += n
        return weighted

    def on_top_out(self) -> None:
        """Board was wiped. Reset combo/b2b but keep totals."""
        self.combo = -1
        self.b2b = 0
