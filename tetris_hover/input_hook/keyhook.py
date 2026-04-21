"""Global keystroke listener → exponentially-decaying boost → speed multiplier.

Unlike a rolling-window average, each keystroke bumps a boost value immediately
(so a single key press is felt within one frame). The boost decays between
strokes with a fixed half-life, so if you stop typing the multiplier slides
back to idle over ~1 second instead of staying stale for the whole window.

The listener is best-effort: if pynput is unavailable or lacks permissions the
hook silently keeps the multiplier at IDLE_MULT.
"""
import math
import threading
import time
from typing import Callable, Optional

try:
    from pynput import keyboard as _keyboard  # type: ignore
    _HAS_PYNPUT = True
except Exception:
    _HAS_PYNPUT = False


IDLE_MULT = 1.0
MAX_MULT = 8.0
MAX_BOOST = MAX_MULT - IDLE_MULT  # 7.0 — room for combo-multiplied spikes
# Each keystroke adds this much to the boost. Halved so a burst of ~5 keys
# lands in the 3–4× range instead of saturating immediately. A ~14-key burst
# is needed to reach the top, which makes slam territory (≥5×) feel earned.
PER_KEY_BOOST = 0.5
# Exponential decay half-life (seconds). Lower = snappier comedown.
DECAY_TAU = 0.6

# Sustained-typing combo buff (applied on top of boost). Reward for typing
# continuously — keys separated by more than COMBO_BREAK_MS reset the streak.
COMBO_BREAK_MS = 500
COMBO_TIER1_SEC = 3.0   # 3s sustained → ×1.5
COMBO_TIER2_SEC = 5.0   # 5s+ sustained → ×2.0
COMBO_TIER1 = 1.5
COMBO_TIER2 = 2.0


def _combo_multiplier(sustain_sec: float) -> float:
    if sustain_sec < COMBO_TIER1_SEC:
        # Smooth ramp from 1.0 at 0s to 1.5 at 3s so you feel the buildup.
        return 1.0 + (COMBO_TIER1 - 1.0) * (sustain_sec / COMBO_TIER1_SEC)
    if sustain_sec < COMBO_TIER2_SEC:
        t = (sustain_sec - COMBO_TIER1_SEC) / (COMBO_TIER2_SEC - COMBO_TIER1_SEC)
        return COMBO_TIER1 + (COMBO_TIER2 - COMBO_TIER1) * t
    return COMBO_TIER2


class KeyHook:
    def __init__(self, on_change: Optional[Callable[[float], None]] = None) -> None:
        self._lock = threading.Lock()
        self._listener = None
        self._on_change = on_change
        self._last_mult = IDLE_MULT

        # Decay state.
        self._boost = 0.0
        self._last_update = time.monotonic()

        # Sustain streak for combo buff.
        self._streak_started = 0.0  # 0 = no active streak
        self._streak_last_key = 0.0

        # Session counters (separate from the boost; these persist across decay).
        self._total = 0
        self._last_press_ms: float = 0.0

    # ---- listener ---------------------------------------------------------
    def _on_press(self, _key) -> None:
        now = time.monotonic()
        with self._lock:
            # Decay existing boost to *now*, then add this keystroke.
            dt = now - self._last_update
            if dt > 0:
                self._boost *= math.exp(-dt / DECAY_TAU)
            self._boost = min(MAX_BOOST, self._boost + PER_KEY_BOOST)
            self._last_update = now

            # Sustain streak: reset if previous key was too long ago.
            if self._streak_started == 0.0 or (now - self._streak_last_key) * 1000 > COMBO_BREAK_MS:
                self._streak_started = now
            self._streak_last_key = now

            self._total += 1
            self._last_press_ms = now * 1000

    def start(self) -> bool:
        if not _HAS_PYNPUT:
            return False
        if self._listener is not None:
            return True
        try:
            self._listener = _keyboard.Listener(on_press=self._on_press)
            self._listener.daemon = True
            self._listener.start()
            return True
        except Exception:
            self._listener = None
            return False

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None

    # ---- queries ----------------------------------------------------------
    def _current_boost_and_combo(self) -> tuple:
        """Decayed boost and current combo multiplier, evaluated at 'now'."""
        now = time.monotonic()
        with self._lock:
            dt = now - self._last_update
            decayed = self._boost * math.exp(-dt / DECAY_TAU) if dt > 0 else self._boost
            # Combo breaks if last key was more than COMBO_BREAK_MS ago.
            if self._streak_started == 0.0 or (now - self._streak_last_key) * 1000 > COMBO_BREAK_MS:
                combo = 1.0
            else:
                combo = _combo_multiplier(now - self._streak_started)
        return decayed, combo

    def current_multiplier(self) -> float:
        boost, combo = self._current_boost_and_combo()
        # Boost adds a base speedup; combo is an on-top reward for sustaining.
        mult = (IDLE_MULT + boost) * combo
        if mult > MAX_MULT:
            mult = MAX_MULT
        if self._on_change and abs(mult - self._last_mult) > 0.05:
            self._last_mult = mult
            try:
                self._on_change(mult)
            except Exception:
                pass
        return mult

    def current_combo(self) -> float:
        _, combo = self._current_boost_and_combo()
        return combo

    def total_keystrokes(self) -> int:
        with self._lock:
            return self._total

    def last_press_ms(self) -> float:
        with self._lock:
            return self._last_press_ms
