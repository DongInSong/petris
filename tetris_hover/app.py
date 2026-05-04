"""Application controller: runs the AI, routes keystrokes into speed + scoring,
and persists a per-day diary of how hard the user typed.
"""
import sys
import time
from typing import List, Optional

from PySide6.QtCore import QElapsedTimer, QTimer
from PySide6.QtWidgets import QApplication

from .ai.player import plan, plan_to_actions, Plan
from .core.pieces import SHAPES
from .core.game import ClearEvent, Game, TopOutEvent
from .core.scoring import Session
from .diary import Diary
from .input_hook.keyhook import KeyHook
from .settings import Settings
from .ui.diary_view import DiaryDialog
from .ui.themes import AMBIENT
from .ui.window import HoverWindow

FRAME_MS = 16
AUTOSAVE_MS = 30_000
# Count a second as "active" if a keystroke occurred within this many ms of it.
ACTIVE_WINDOW_MS = 3_000
# Poll cadence for the fullscreen-app check (Win32 shell call). Once a second
# is plenty — the user doesn't notice a 1s delay before Petris hides for a game.
FULLSCREEN_CHECK_MS = 1_000


def _is_other_app_fullscreen() -> bool:
    """True if a D3D fullscreen app or presentation-mode app is foregrounded.
    Windows-only; returns False on other platforms (so auto-hide is a no-op)."""
    if sys.platform != 'win32':
        return False
    try:
        import ctypes
        state = ctypes.c_int(0)
        # SHQueryUserNotificationState: same signal Windows uses to suppress
        # notifications. 3 = QUNS_RUNNING_D3D_FULL_SCREEN, 4 = QUNS_PRESENTATION_MODE.
        hr = ctypes.windll.shell32.SHQueryUserNotificationState(ctypes.byref(state))
        if hr != 0:
            return False
        return state.value in (3, 4)
    except Exception:
        return False

# Gravity: time for a piece to fall one row. Scales with mult^1.5 — fast but
# not chaotic at high mult. Slam kicks in separately past the threshold.
GRAVITY_BASE_MS = 500
# Rotation / lateral step cadence. Scales linearly with multiplier.
MOVE_BASE_MS = 120
MIN_GRAVITY_MS = 40
MIN_MOVE_MS = 25
# Pieces can't slam more often than this; makes each slam feel deliberate
# rather than becoming a continuous drop waterfall.
SLAM_COOLDOWN_MS = 500


class App:
    def __init__(self, use_keyhook: bool = True) -> None:
        self.game = Game()
        self.session = Session()
        self.session.started_at_ms = time.monotonic() * 1000
        self.diary = Diary.load()

        self.settings = Settings.load()
        self.window = HoverWindow(self.game, theme=AMBIENT, settings=self.settings)
        self.window.on_before_exit = self._on_exit
        self.window.on_open_diary = self._open_diary_dialog

        self.keyhook = KeyHook() if use_keyhook else None

        self._action_queue: List[str] = []
        self._current_plan: Optional[Plan] = None
        self._gravity_accum_ms = 0.0
        self._move_accum_ms = 0.0
        self._multiplier = 1.0
        self._autosave_ms = 0.0
        self._session_start_wall = time.monotonic() * 1000
        # Anchor for idle-fade so the fade timer doesn't reset every autosave.
        self._launch_monotonic_ms = self._session_start_wall
        self._fullscreen_check_accum_ms = 0.0
        self._last_keystroke_seen = 0

        self._elapsed = QElapsedTimer()
        self._elapsed.start()
        self._last_ms = self._elapsed.elapsed()

        self._frame_timer = QTimer()
        self._frame_timer.setInterval(FRAME_MS)
        self._frame_timer.timeout.connect(self._on_frame)

        # Diagnostic trackers for the log.
        self._diag_peak_mult = 1.0
        self._diag_slam_count = 0
        self._last_slam_ms = 0.0

    def start(self) -> None:
        self.window.show()
        # If a saved position exists and is still on-screen, honor it.
        # Otherwise fall back to the default snap.
        if not self.window.restore_position():
            self.window._snap('br')
        keyhook_ok = False
        if self.keyhook is not None:
            keyhook_ok = self.keyhook.start()
        # Always write a small diagnostic log so the user can verify whether
        # the global key hook is wired up in the running exe.
        self._diag_init(keyhook_ok)
        # If we've already played today, show that running total so a restart
        # visually continues from where we left off.
        self.window.set_score(self._today_total())
        self._frame_timer.start()
        self._diag_last_log_ms = 0.0

    def _diag_init(self, keyhook_ok: bool) -> None:
        from pathlib import Path
        from .diary import _data_dir
        try:
            from .input_hook.keyhook import _HAS_PYNPUT
        except Exception:
            _HAS_PYNPUT = False
        path = _data_dir() / "diagnostic.log"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                import datetime
                f.write(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] startup\n")
                f.write(f"  pynput available: {_HAS_PYNPUT}\n")
                f.write(f"  keyhook.start(): {keyhook_ok}\n")
                f.write(f"  use_keyhook flag: {self.keyhook is not None}\n")
            self._diag_log_path = path
        except Exception:
            self._diag_log_path = None

    def _diag_tick(self, now_ms: float) -> None:
        if self._diag_log_path is None:
            return
        # Track peak multiplier across every frame, not just the sampled one.
        if self._multiplier > self._diag_peak_mult:
            self._diag_peak_mult = self._multiplier
        if now_ms - self._diag_last_log_ms < 10_000:
            return
        self._diag_last_log_ms = now_ms
        keys = self.keyhook.total_keystrokes() if self.keyhook else 0
        try:
            with self._diag_log_path.open("a", encoding="utf-8") as f:
                f.write(
                    f"  t+{int(now_ms/1000)}s "
                    f"keys={keys} "
                    f"mult_now={self._multiplier:.2f} "
                    f"mult_peak={self._diag_peak_mult:.2f} "
                    f"slams={self._diag_slam_count} "
                    f"threshold={self.settings.hard_drop_threshold:.1f}\n"
                )
        except Exception:
            pass
        # Reset peak for next window.
        self._diag_peak_mult = self._multiplier

    def _today_total(self) -> float:
        rec = self.diary.days.get(_today())
        return rec.score if rec is not None else 0.0

    # ---- frame ------------------------------------------------------------
    def _gravity_interval_ms(self) -> float:
        m = max(0.1, self._multiplier)
        threshold = self.settings.hard_drop_threshold
        if m < threshold:
            # Below threshold: normal gradient, mult^1.5 scaling.
            return max(MIN_GRAVITY_MS, GRAVITY_BASE_MS / (m ** 1.5))
        # Above threshold: gravity slows so the slam drops from further away,
        # but capped so the piece never appears frozen. At full 8× the piece
        # still visibly descends (~200ms/row) before the slam connects.
        base_at_thresh = GRAVITY_BASE_MS / (threshold ** 1.5)
        over = m - threshold
        slowdown = min(150.0, (over * over) * 100.0)
        return base_at_thresh + slowdown

    def _move_interval_ms(self) -> float:
        m = max(0.1, self._multiplier)
        return max(MIN_MOVE_MS, MOVE_BASE_MS / m)

    def _on_frame(self) -> None:
        now = self._elapsed.elapsed()
        dt = now - self._last_ms
        self._last_ms = now
        if dt <= 0:
            return

        # Typing → multiplier, keystrokes, active time.
        wall_now_ms = time.monotonic() * 1000
        last_press_ms = 0.0
        if self.keyhook is not None:
            self._multiplier = self.keyhook.current_multiplier()
            total = self.keyhook.total_keystrokes()
            delta_keys = total - self._last_keystroke_seen
            if delta_keys > 0:
                self.session.keystrokes += delta_keys
                self._last_keystroke_seen = total
            last_press_ms = self.keyhook.last_press_ms()
            if last_press_ms and (wall_now_ms - last_press_ms) <= ACTIVE_WINDOW_MS:
                self.session.active_ms += dt
        self.window.set_multiplier(self._multiplier)

        # Idle fade: measure from the most recent keystroke (or app launch if
        # nothing has been pressed yet — using session_start would reset on
        # every autosave). Window decides the actual opacity blend.
        ref_ms = last_press_ms if last_press_ms > 0 else self._launch_monotonic_ms
        idle_sec = max(0.0, (wall_now_ms - ref_ms) / 1000.0)
        self.window.apply_idle_fade(idle_sec)

        # Fullscreen auto-hide: throttled — the shell call is cheap but there's
        # no point hammering it 60×/s for a state that only changes when the
        # user alt-tabs into a game or full-screens a video.
        self._fullscreen_check_accum_ms += dt
        if self._fullscreen_check_accum_ms >= FULLSCREEN_CHECK_MS:
            self._fullscreen_check_accum_ms = 0
            self.window.apply_fullscreen_autohide(_is_other_app_fullscreen())

        # Rotate / lateral moves: discrete steps at move_interval.
        self._move_accum_ms += dt
        move_interval = self._move_interval_ms()
        while self._move_accum_ms >= move_interval:
            self._move_accum_ms -= move_interval
            self._step_move()

        # Gravity: one-row descent at gravity_interval. Scaled 1/mult² so
        # hard typing almost slams pieces down.
        self._gravity_accum_ms += dt
        grav_interval = self._gravity_interval_ms()
        while self._gravity_accum_ms >= grav_interval:
            self._gravity_accum_ms -= grav_interval
            if self.game.piece is not None:
                self.game.soft_drop()

        # Once AI has finished rotating/moving the piece, and the user is
        # typing hard enough, slam the piece down instead of waiting for
        # gravity. This is the "hard-drop" feel at high multiplier.
        self._try_slam()

        # Lock delay advances faster when typing (pass scaled dt).
        self.game.tick(int(dt * self._multiplier))

        # Drain events → scoring + visuals.
        for evt in self.game.drain_events():
            if isinstance(evt, TopOutEvent):
                self.session.on_top_out()
                self._current_plan = None
                self._action_queue = []
                # Debris animation + score penalty.
                self.window.view.trigger_collapse_effect(evt.grid_snapshot)
                self._apply_death_penalty()
                continue
            if isinstance(evt, ClearEvent):
                # Every lock emits a ClearEvent (rows may be empty).
                self.session.on_piece_locked()
                awarded = self.session.on_clear(evt, self._multiplier)
                # New piece just spawned — fresh plan needed.
                self._current_plan = None
                self._action_queue = []
                if evt.rows:
                    self.window.view.trigger_clear_effect(evt.rows, evt.piece_kind)
                if awarded > 0:
                    self.window.set_score(self._today_total() + self.session.score)

        # Hover-reveal sidebar.
        self.window.poll_hover()

        # Particle animation + repaint.
        self.window.view.effects.step()
        self.window.view.update()

        # Autosave.
        self._autosave_ms += dt
        if self._autosave_ms >= AUTOSAVE_MS:
            self._autosave_ms = 0
            self._persist(commit=False)

        # Diagnostic sample (append-only).
        self._diag_tick(now)

    def _apply_death_penalty(self) -> None:
        pct = max(0.0, min(100.0, self.settings.death_penalty_pct))
        if pct <= 0:
            return
        factor = 1.0 - pct / 100.0
        self.session.score *= factor
        today = _today()
        rec = self.diary.days.get(today)
        if rec is not None:
            rec.score *= factor
            try:
                self.diary.save()
            except Exception:
                pass
        self.window.set_score(self._today_total() + self.session.score)

    def _try_slam(self) -> None:
        """Hard-drop the current piece if the AI is done positioning and
        the typing multiplier is past the configured threshold."""
        threshold = self.settings.hard_drop_threshold
        if self._multiplier < threshold:
            return
        piece = self.game.piece
        if piece is None or self._action_queue or self._current_plan is None:
            return
        now_ms = time.monotonic() * 1000
        if now_ms - self._last_slam_ms < SLAM_COOLDOWN_MS:
            return  # honor cooldown to prevent slam-chain overload
        self._last_slam_ms = now_ms
        # Compute landing y via ghost-drop so we can paint the trail.
        ghost = piece.clone()
        grid = self.game.board.grid
        w, h = self.game.board.w, self.game.board.h
        while True:
            step_y = ghost.y + 1
            hits = False
            for dx, dy in _shape_minos(ghost):
                gx = ghost.x + dx
                gy = step_y + dy
                if gx < 0 or gx >= w or gy >= h:
                    hits = True
                    break
                if gy >= 0 and grid[gy][gx] is not None:
                    hits = True
                    break
            if hits:
                break
            ghost.y = step_y
        # Top row (where piece currently is) and bottom row (landing).
        start_row = min(piece.y + dy for _, dy in _shape_minos(piece))
        end_row = max(ghost.y + dy for _, dy in _shape_minos(ghost))
        cols = sorted({piece.x + dx for dx, _ in _shape_minos(piece)})
        self.window.view.trigger_slam_effect(cols, start_row, end_row, piece.kind)
        self.game.hard_drop()
        self._diag_slam_count += 1

    def _step_move(self) -> None:
        """Consume one rotation or lateral move; plan a new queue if empty."""
        if not self._action_queue:
            # Only plan once per piece; the lock handler clears _current_plan.
            if self._current_plan is None and self.game.piece is not None:
                self._current_plan = plan(self.game, mode=self.settings.ai_mode)
                if self._current_plan is None:
                    return
                self._action_queue = plan_to_actions(self.game, self._current_plan)
            if not self._action_queue:
                return  # queue still empty (plan reached target); let gravity finish
        action = self._action_queue.pop(0)
        if action == 'cw':
            self.game.rotate(1)
        elif action == 'ccw':
            self.game.rotate(-1)
        elif action == 'left':
            self.game.move(-1)
        elif action == 'right':
            self.game.move(1)
        elif action == 'soft_drop':
            # T-spin entries need the piece grounded before the final rotation
            # so the SRS kick seats it into the slot. Drop in one tick.
            while self.game.soft_drop():
                pass
        elif action == 'hold':
            self.game.swap_hold()
            self._current_plan = None
            self._action_queue = []

    # ---- persistence ------------------------------------------------------
    def _persist(self, commit: bool) -> None:
        wall_now = time.monotonic() * 1000
        duration_sec = int((wall_now - self._session_start_wall) / 1000)
        # Merge a *snapshot* of the session into today's record.
        # For autosaves we fold the delta in and reset counters so the next
        # autosave doesn't double-count. For the final save we do the same.
        snapshot = Session(
            score=self.session.score,
            raw_score=self.session.raw_score,
            lines=self.session.lines,
            pieces=self.session.pieces,
            keystrokes=self.session.keystrokes,
            max_combo=self.session.max_combo,
            max_b2b=self.session.max_b2b,
            active_ms=self.session.active_ms,
        )
        if snapshot.score == 0 and snapshot.keystrokes == 0 and duration_sec < 5:
            return
        self.diary.merge_session(session=snapshot, duration_sec=duration_sec)
        self.diary.save()
        # Reset the per-interval counters so subsequent autosaves only fold in new activity.
        self.session.score = 0.0
        self.session.raw_score = 0.0
        self.session.lines = 0
        self.session.pieces = 0
        self.session.keystrokes = 0
        self.session.max_combo = 0
        self.session.max_b2b = 0
        self.session.active_ms = 0.0
        self._session_start_wall = wall_now
        # Refresh the displayed score to reflect today's total.
        today_score = sum(r.score for r in self.diary.days.values() if r.date == _today())
        self.window.set_score(today_score)

    def _on_exit(self) -> None:
        # Capture final window position in case the user never dragged/snapped
        # during this session (restoring an existing position alone wouldn't
        # rewrite the file).
        self.settings.x = self.window.x()
        self.settings.y = self.window.y()
        try:
            self.settings.save()
        except Exception:
            pass
        self._persist(commit=True)
        if self.keyhook is not None:
            self.keyhook.stop()

    def _open_diary_dialog(self) -> None:
        dlg = DiaryDialog(self.diary, self.window)
        dlg.exec()


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


def _shape_minos(piece):
    return SHAPES[piece.kind][piece.rot]


def _install_crash_handler() -> None:
    """Append unhandled exception tracebacks to crash.log. With console=False
    under PyInstaller there's no visible output, so this is the only way the
    user can see and report errors after a crash."""
    import datetime
    import traceback
    from .diary import _data_dir

    try:
        log_path = _data_dir() / "crash.log"
    except Exception:
        return

    previous = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as f:
                f.write(f"\n=== {datetime.datetime.now().isoformat(timespec='seconds')} ===\n")
                traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
        except Exception:
            pass
        try:
            previous(exc_type, exc_value, exc_tb)
        except Exception:
            pass

    sys.excepthook = _hook


def main() -> int:
    _install_crash_handler()
    qt_app = QApplication.instance() or QApplication(sys.argv)
    # Keep running when hidden to tray; only the ⏻ quit action (or tray "quit")
    # calls QApplication.quit().
    qt_app.setQuitOnLastWindowClosed(False)
    app = App(use_keyhook=True)
    app.start()
    return qt_app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
