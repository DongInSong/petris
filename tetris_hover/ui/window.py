"""Frameless, translucent, always-on-top hover window.

Title bar controls (left → right):
    ○/●   theme toggle
    score       today's total (restarts carry over)
    speed bar   current typing multiplier
    %           UI scale cycle (75/100/125/150)
    opacity     10–100% window opacity slider
    ↖ ↗ ↙ ↘   corner snap
    ⋯           diary
    ×           hide to system tray
    ⏻           quit (persist diary, exit app)

The window's close event hides to tray (if tray is available); only the power
button actually exits. Tray left-click toggles show/hide; tray right-click menu
mirrors the title-bar actions.
"""
import sys
from typing import Callable, Optional

from PySide6.QtCore import QPoint, QSize, Qt

from ..__version__ import __version__
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QGuiApplication,
    QIcon,
    QMouseEvent,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QSlider,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..core.game import Game
from ..settings import Settings
from .board_view import BoardView
from .themes import AMBIENT, NEON, ORDER as THEME_ORDER, Theme, VIVID, get as get_theme

THEME_GLYPHS = {'ambient': '○', 'vivid': '●', 'neon': '◆'}

# Side bar is a fixed-size overlay on the right edge; its dimensions don't
# change with UI scale, so buttons never squish.
SIDE_BAR_W = 24
SIDE_BAR_H = 276
DEFAULT_SIZE = QSize(340, 400)
MIN_SIZE = QSize(160, 190)
SNAP_MARGIN = 8
SCALE_PRESETS = [50, 75, 100, 125, 150]
OPACITY_MIN = 30
OPACITY_MAX = 100

# Idle fade: window opacity drops smoothly while no keys are pressed, snaps
# back on the next keystroke. Times in seconds; floor is a fraction applied
# on top of the user's configured opacity.
IDLE_FADE_START_SEC = 60
IDLE_FADE_FULL_SEC = 180
IDLE_FADE_FLOOR = 0.20


_BUTTON_STYLE = """
QPushButton {
    background: rgba(40, 40, 55, 150);
    color: rgba(220, 220, 230, 220);
    border: 1px solid rgba(120, 120, 150, 100);
    border-radius: 3px;
    padding: 0;
    font-size: 11px;
}
QPushButton:hover { background: rgba(70, 70, 100, 180); }
QPushButton:pressed { background: rgba(30, 30, 45, 200); }
QPushButton:checked { background: rgba(90, 110, 140, 200); }
"""

_QUIT_BUTTON_STYLE = """
QPushButton {
    background: rgba(40, 40, 55, 150);
    color: rgba(240, 96, 110, 235);
    border: 1px solid rgba(240, 96, 110, 170);
    border-radius: 3px;
    padding: 0;
    font-size: 11px;
}
QPushButton:hover { background: rgba(80, 35, 45, 190); }
QPushButton:pressed { background: rgba(50, 20, 30, 210); }
"""

_SLIDER_STYLE = """
QSlider::groove:horizontal {
    height: 4px;
    background: rgba(40, 40, 55, 180);
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: rgba(180, 200, 230, 220);
    width: 10px;
    height: 10px;
    margin: -4px 0;
    border-radius: 5px;
}
QSlider::sub-page:horizontal { background: rgba(120, 170, 220, 200); border-radius: 2px; }
"""


def _theme_from_name(name: str, fallback: Theme) -> Theme:
    if name in THEME_ORDER:
        return get_theme(name)
    return fallback


def _strip_win11_border(hwnd: int) -> None:
    """Tell DWM not to draw the 1px border + rounded corners that Windows 11
    paints on every top-level window, including frameless Qt ones. No-op on
    anything that isn't Windows 11+; older platforms ignore the attribute IDs.
    """
    if sys.platform != 'win32' or not hwnd:
        return
    try:
        import ctypes
        dwmapi = ctypes.windll.dwmapi
        DWMWA_WINDOW_CORNER_PREFERENCE = 33
        DWMWCP_DONOTROUND = 1
        DWMWA_BORDER_COLOR = 34
        DWMWA_COLOR_NONE = 0xFFFFFFFE

        corner = ctypes.c_int(DWMWCP_DONOTROUND)
        dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd) if hasattr(ctypes, 'wintypes') else hwnd,
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner),
            ctypes.sizeof(corner),
        )
        color = ctypes.c_uint32(DWMWA_COLOR_NONE)
        dwmapi.DwmSetWindowAttribute(
            ctypes.wintypes.HWND(hwnd) if hasattr(ctypes, 'wintypes') else hwnd,
            DWMWA_BORDER_COLOR,
            ctypes.byref(color),
            ctypes.sizeof(color),
        )
    except Exception:
        pass


def _icon_path() -> Optional[str]:
    """Locate petris.ico: next to main.py in dev, bundled via PyInstaller in prod."""
    import os
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "petris.ico"))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(here, "..", "..", "petris.ico"))
    for p in candidates:
        if os.path.exists(p):
            return p
    return None


def _make_tray_icon() -> QIcon:
    path = _icon_path()
    if path is not None:
        icon = QIcon(path)
        if not icon.isNull():
            return icon
    # Fallback: programmatic T-block if the .ico isn't around (dev/tests).
    pm = QPixmap(32, 32)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, False)
    c = QColor(230, 130, 140)
    p.fillRect(4, 8, 8, 8, c)
    p.fillRect(12, 8, 8, 8, c)
    p.fillRect(20, 8, 8, 8, c)
    p.fillRect(12, 16, 8, 8, c)
    p.end()
    return QIcon(pm)


class DragHandle(QWidget):
    """Hatched grab handle at the top of the sidebar. Captures the mouse so
    the window follows the cursor even as it leaves the handle's own rect."""

    def __init__(self, parent: QWidget, window: "HoverWindow") -> None:
        super().__init__(parent)
        self._win = window
        self.setFixedSize(18, 14)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("drag to move")
        self._offset: Optional[QPoint] = None

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(40, 40, 55, 150))
        pen = QColor(210, 210, 225, 200)
        p.setPen(pen)
        # Diagonal hatch — 4 lines at 45°.
        for offset in (-10, -4, 2, 8):
            p.drawLine(offset, self.height(), offset + self.height(), 0)
        # Border
        p.setPen(QColor(120, 120, 150, 140))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._offset = event.globalPosition().toPoint() - self._win.frameGeometry().topLeft()
            self.grabMouse()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._offset is not None and event.buttons() & Qt.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._offset
            self._win.move(new_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._offset is not None:
            self.releaseMouse()
            self._win.settings.x = self._win.x()
            self._win.settings.y = self._win.y()
            self._win._persist_settings()
            self._offset = None
            event.accept()


class OpacityPopup(QWidget):
    """Small floating slider that opens from the opacity button.

    Uses Qt.Popup so clicking outside dismisses it automatically.
    """

    def __init__(self, parent: QWidget, value: int, on_change) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFixedSize(34, 120)
        self._on_change = on_change

        self.slider = QSlider(Qt.Vertical, self)
        self.slider.setRange(30, 100)
        self.slider.setValue(value)
        self.slider.setGeometry(5, 8, 24, 104)
        self.slider.setStyleSheet(_SLIDER_STYLE)
        self.slider.valueChanged.connect(self._on_change)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(25, 25, 35, 210))
        p.setPen(QColor(120, 120, 150, 160))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))


class MultiplierBar(QWidget):
    """Vertical fill bar: fills bottom-up as typing multiplier rises."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setFixedSize(18, 36)
        self._mult = 1.0
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_multiplier(self, m: float) -> None:
        if abs(m - self._mult) > 0.02:
            self._mult = m
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.fillRect(0, 0, self.width(), self.height(), QColor(40, 40, 55, 150))
        frac = max(0.0, min(1.0, (self._mult - 1.0) / 7.0))
        fill_h = int(self.height() * frac)
        r = int(120 + 135 * frac)
        g = int(200 - 80 * frac)
        b = int(230 - 150 * frac)
        p.fillRect(0, self.height() - fill_h, self.width(), fill_h, QColor(r, g, b, 220))
        p.setPen(QColor(120, 120, 150, 120))
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)


class HoverWindow(QWidget):
    def __init__(self, game: Game, theme: Theme = AMBIENT, settings: Optional[Settings] = None) -> None:
        super().__init__()
        self.game = game
        self.settings = settings or Settings()
        self.theme = _theme_from_name(self.settings.theme, fallback=theme)
        self.on_before_exit: Optional[Callable[[], None]] = None
        self.on_open_diary: Optional[Callable[[], None]] = None

        self._quitting = False
        init_pct = self.settings.scale_pct if self.settings.scale_pct in SCALE_PRESETS else 100
        self._scale_idx = SCALE_PRESETS.index(init_pct)
        self._sidebar_side = self.settings.sidebar_side if self.settings.sidebar_side in ('left', 'right') else 'left'

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setAutoFillBackground(False)
        self.setWindowTitle("Petris")
        icon_path = _icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        self.setMinimumSize(MIN_SIZE)
        init_w = DEFAULT_SIZE.width() * init_pct // 100
        init_h = DEFAULT_SIZE.height() * init_pct // 100
        self.resize(init_w, init_h)
        # Effective opacity = settings.opacity_pct × idle-fade fraction. Set on
        # every change to either input via _apply_window_opacity().
        self._idle_fade_frac = 1.0
        self._hidden_for_fullscreen = False
        self._apply_window_opacity()

        self._drag_offset: Optional[QPoint] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.view = BoardView(game, self.theme, self)
        outer.addWidget(self.view, stretch=1)

        # Title bar is an overlay, not a layout child — so showing/hiding it
        # doesn't push the board around. Blocks stay anchored to the bottom.
        self.title_bar = self._build_title_bar()
        self.title_bar.setParent(self)
        self.title_bar.hide()
        self.title_bar.raise_()

        # Reflect persisted settings onto controls built above.
        self.btn_scale.setText(str(init_pct))
        self.btn_theme.setText(THEME_GLYPHS.get(self.theme.name, '○'))

        self.tray: Optional[QSystemTrayIcon] = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = self._build_tray()

        # Track mouse even when no button is down so enter/leave fires reliably.
        self.setMouseTracking(True)

    # ---- side bar ---------------------------------------------------------
    def _build_title_bar(self) -> QWidget:
        bar = QWidget(self)
        bar.setFixedWidth(SIDE_BAR_W)
        bar.setMaximumHeight(SIDE_BAR_H)
        bar.setAttribute(Qt.WA_TranslucentBackground, True)
        bar.setAttribute(Qt.WA_NoSystemBackground, True)
        bar.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(bar)
        vl.setContentsMargins(3, 3, 3, 3)
        vl.setSpacing(2)

        # Order (top → bottom) prioritizes drag handle + escape hatches so
        # they stay visible even if the widget is shrunk and the bottom is
        # clipped.
        self.drag_handle = DragHandle(bar, self)
        self.btn_quit = self._mk_btn(bar, "⏻", "quit (save diary)", self._power_off)
        self.btn_hide = self._mk_btn(bar, "×", "hide to tray", self._hide_to_tray)
        self.btn_scale = self._mk_btn(bar, "100", "UI scale (left=cycle · right=menu)", self._cycle_scale)
        self.btn_scale.setContextMenuPolicy(Qt.CustomContextMenu)
        self.btn_scale.customContextMenuRequested.connect(self._show_scale_menu)
        self.btn_theme = self._mk_btn(bar, "○", "theme: ambient (click to toggle)", self._toggle_theme)
        self.btn_diary = self._mk_btn(bar, "⋯", "diary", self._open_diary)
        # Opacity lives behind a button that pops up a slider on click. Small
        # footprint (survives at 50% scale) and avoids the visual confusion
        # of a number next to the scale % button.
        self.btn_opacity = self._mk_btn(bar, "◐", "opacity (click to adjust)", self._open_opacity_popup)
        self._opacity_popup: Optional["OpacityPopup"] = None

        self.btn_tl = self._mk_btn(bar, "↖", "snap top-left", lambda: self._snap('tl'))
        self.btn_tr = self._mk_btn(bar, "↗", "snap top-right", lambda: self._snap('tr'))
        self.btn_bl = self._mk_btn(bar, "↙", "snap bottom-left", lambda: self._snap('bl'))
        self.btn_br = self._mk_btn(bar, "↘", "snap bottom-right", lambda: self._snap('br'))

        self.mult_bar = MultiplierBar(bar)
        self.mult_bar.setToolTip("typing speed multiplier")

        for b in (
            self.btn_hide, self.btn_scale, self.btn_theme,
            self.btn_diary, self.btn_opacity,
            self.btn_tl, self.btn_tr, self.btn_bl, self.btn_br,
        ):
            b.setStyleSheet(_BUTTON_STYLE)
        # Quit gets its own red tint so it's visually distinct from × (hide).
        self.btn_quit.setStyleSheet(_QUIT_BUTTON_STYLE)

        vl.addWidget(self.drag_handle, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_quit, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_hide, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_scale, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_opacity, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_tl, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_tr, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_bl, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_br, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_theme, alignment=Qt.AlignHCenter)
        vl.addWidget(self.btn_diary, alignment=Qt.AlignHCenter)
        vl.addWidget(self.mult_bar, alignment=Qt.AlignHCenter)
        vl.addStretch(1)

        return bar

    def _mk_btn(self, parent: QWidget, text: str, tip: str, slot) -> QPushButton:
        b = QPushButton(text, parent)
        b.setFixedSize(18, 18)
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    # ---- tray -------------------------------------------------------------
    def _build_tray(self) -> QSystemTrayIcon:
        tray = QSystemTrayIcon(_make_tray_icon(), self)
        tray.setToolTip(f"Petris · v{__version__}")
        menu = QMenu()

        self._act_show = QAction("show/hide", menu)
        self._act_show.triggered.connect(self._toggle_visible)
        menu.addAction(self._act_show)
        menu.addSeparator()

        theme_menu = menu.addMenu("theme")
        for label, theme_obj in (("ambient", AMBIENT), ("vivid", VIVID), ("neon", NEON)):
            act = QAction(label, theme_menu)
            act.triggered.connect(lambda _=False, t=theme_obj: self._set_theme(t))
            theme_menu.addAction(act)

        snap_menu = menu.addMenu("snap to")
        for label, key in (("↖ top-left", 'tl'), ("↗ top-right", 'tr'),
                           ("↙ bottom-left", 'bl'), ("↘ bottom-right", 'br')):
            act = QAction(label, snap_menu)
            act.triggered.connect(lambda _=False, k=key: self._snap(k))
            snap_menu.addAction(act)

        ai_menu = menu.addMenu("AI mode")
        ai_group = QActionGroup(ai_menu)
        ai_group.setExclusive(True)
        self._ai_actions = {}
        # Death rates measured empirically over 3000 pieces per mode.
        for mode_key, mode_label in (
            ('calm', 'calm — singles · death ~1.5%/piece'),
            ('tetris', 'tetris — big clears · death ~1.2%/piece'),
            ('tspin', 't-spin — messy · death ~0.5%/piece'),
        ):
            act = QAction(mode_label, ai_menu)
            act.setCheckable(True)
            act.setChecked(self.settings.ai_mode == mode_key)
            ai_group.addAction(act)
            ai_menu.addAction(act)
            act.triggered.connect(lambda _=False, m=mode_key: self._set_ai_mode(m))
            self._ai_actions[mode_key] = act

        act_diary = QAction("diary…", menu)
        act_diary.triggered.connect(self._open_diary)
        menu.addAction(act_diary)

        act_reset = QAction("reset size (100%)", menu)
        act_reset.triggered.connect(self._reset_size)
        menu.addAction(act_reset)

        menu.addSeparator()
        act_quit = QAction("quit", menu)
        act_quit.triggered.connect(self._power_off)
        menu.addAction(act_quit)

        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        return tray

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:  # left click
            self._toggle_visible()

    def _toggle_visible(self) -> None:
        # Any explicit user toggle defeats the fullscreen auto-hide bookkeeping
        # so we don't overwrite their choice when fullscreen ends.
        self._hidden_for_fullscreen = False
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.raise_()
            self.activateWindow()

    # ---- external updates -------------------------------------------------
    def set_score(self, score: float) -> None:
        # Delegated to BoardView so the number lives on the playfield itself
        # and can run the bump animation.
        self.view.set_score(score)

    def set_multiplier(self, m: float) -> None:
        self.mult_bar.set_multiplier(m)
        # Mirror on the board overlay so the user sees current multiplier
        # without hovering the sidebar.
        self.view.set_multiplier(m)

    # ---- actions ----------------------------------------------------------
    def _set_theme(self, theme: Theme) -> None:
        if self.theme is theme:
            return
        self.theme = theme
        self.view.set_theme(theme)
        self.btn_theme.setText(THEME_GLYPHS.get(theme.name, '○'))
        self.btn_theme.setToolTip(f"theme: {theme.name} (click to cycle)")
        self.settings.theme = theme.name
        self._persist_settings()

    def _toggle_theme(self) -> None:
        # Cycle through THEME_ORDER so the single button keeps working as
        # themes get added (ambient → vivid → neon → ambient).
        try:
            idx = THEME_ORDER.index(self.theme.name)
        except ValueError:
            idx = -1
        nxt = THEME_ORDER[(idx + 1) % len(THEME_ORDER)]
        self._set_theme(get_theme(nxt))

    def _set_ai_mode(self, mode: str) -> None:
        if mode not in ('calm', 'tetris', 'tspin'):
            return
        self.settings.ai_mode = mode
        self._persist_settings()
        act = getattr(self, '_ai_actions', {}).get(mode)
        if act is not None:
            act.setChecked(True)

    def _cycle_scale(self) -> None:
        self._scale_idx = (self._scale_idx + 1) % len(SCALE_PRESETS)
        self._apply_scale(SCALE_PRESETS[self._scale_idx])

    def _show_scale_menu(self, pos) -> None:
        menu = QMenu(self.btn_scale)
        current = SCALE_PRESETS[self._scale_idx]
        for pct in SCALE_PRESETS:
            label = f"● {pct}%" if pct == current else f"   {pct}%"
            act = QAction(label, menu)
            act.triggered.connect(lambda _=False, p=pct: self._pick_scale(p))
            menu.addAction(act)
        menu.exec(self.btn_scale.mapToGlobal(pos))

    def _pick_scale(self, pct: int) -> None:
        self._scale_idx = SCALE_PRESETS.index(pct)
        self._apply_scale(pct)

    def _apply_scale(self, pct: int) -> None:
        new_w = DEFAULT_SIZE.width() * pct // 100
        new_h = DEFAULT_SIZE.height() * pct // 100

        # Infer which edge(s) the window is currently anchored to by comparing
        # its rect against the screen's work area. After resize, keep whatever
        # edge(s) were anchored so snap-to-corner behavior survives scaling.
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            tol = SNAP_MARGIN + 4
            right_anchored = abs((self.x() + self.width()) - geo.right()) <= tol
            bottom_anchored = abs((self.y() + self.height()) - geo.bottom()) <= tol

            new_x = (geo.right() - new_w - SNAP_MARGIN) if right_anchored else self.x()
            new_y = (geo.bottom() - new_h + 1) if bottom_anchored else self.y()
            self.move(new_x, new_y)

        self.resize(new_w, new_h)
        self.btn_scale.setText(str(pct))
        self.settings.scale_pct = pct
        self.settings.x = self.x()
        self.settings.y = self.y()
        self._persist_settings()

    def _reset_size(self) -> None:
        self._scale_idx = SCALE_PRESETS.index(100)
        self._apply_scale(100)
        if not self.isVisible():
            self.show()
        self.raise_()
        self.activateWindow()

    def _persist_settings(self) -> None:
        try:
            self.settings.save()
        except Exception:
            pass

    def restore_position(self) -> bool:
        """Move to previously saved position if still on-screen. Returns True
        if restored (caller shouldn't auto-snap), False if caller should snap."""
        if self.settings.x is None or self.settings.y is None:
            return False
        screen = QGuiApplication.screenAt(QPoint(self.settings.x, self.settings.y))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is None:
            return False
        geo = screen.availableGeometry()
        # Require at least 40px of the window to stay inside the screen so
        # users never wake up to an off-screen widget.
        x = max(geo.left() - self.width() + 40, min(geo.right() - 40, self.settings.x))
        y = max(geo.top(), min(geo.bottom() - 40, self.settings.y))
        self.move(x, y)
        return True

    def _on_opacity(self, v: int) -> None:
        self.settings.opacity_pct = v
        self._apply_window_opacity()
        self._persist_settings()

    def _apply_window_opacity(self) -> None:
        target = max(OPACITY_MIN, min(OPACITY_MAX, self.settings.opacity_pct)) / 100.0
        self.setWindowOpacity(target * self._idle_fade_frac)

    def apply_idle_fade(self, idle_sec: float) -> None:
        """Update the idle-fade fraction from a measured idle duration."""
        if not self.settings.idle_fade_enabled or idle_sec <= IDLE_FADE_START_SEC:
            frac = 1.0
        elif idle_sec >= IDLE_FADE_FULL_SEC:
            frac = IDLE_FADE_FLOOR
        else:
            t = (idle_sec - IDLE_FADE_START_SEC) / (IDLE_FADE_FULL_SEC - IDLE_FADE_START_SEC)
            frac = 1.0 - (1.0 - IDLE_FADE_FLOOR) * t
        # Quantize to ~1% steps so we don't repaint every frame.
        if abs(frac - self._idle_fade_frac) < 0.01:
            return
        self._idle_fade_frac = frac
        self._apply_window_opacity()

    def apply_fullscreen_autohide(self, fullscreen_active: bool) -> None:
        """Hide to tray on fullscreen detect; restore only if WE caused the hide."""
        if not self.settings.fullscreen_autohide_enabled:
            # If a previous fullscreen hide is still in effect when the user
            # disabled the feature, undo it on the next non-fullscreen tick.
            if self._hidden_for_fullscreen and not fullscreen_active:
                self._hidden_for_fullscreen = False
                if not self.isVisible():
                    self.show()
            return
        if fullscreen_active:
            if self.isVisible():
                self.hide()
                self._hidden_for_fullscreen = True
        elif self._hidden_for_fullscreen:
            self._hidden_for_fullscreen = False
            if not self.isVisible():
                self.show()

    def _open_opacity_popup(self) -> None:
        if self._opacity_popup is not None and self._opacity_popup.isVisible():
            self._opacity_popup.close()
            self._opacity_popup = None
            return
        popup = OpacityPopup(self, self.settings.opacity_pct, self._on_opacity)
        btn_pos = self.btn_opacity.mapToGlobal(self.btn_opacity.rect().topRight())
        # Position to the side opposite the sidebar edge.
        x = btn_pos.x() + 4 if self._sidebar_side == 'left' else btn_pos.x() - popup.width() - 26
        y = btn_pos.y() - 8
        popup.move(x, y)
        popup.show()
        self._opacity_popup = popup

    def _open_diary(self) -> None:
        if self.on_open_diary is not None:
            self.on_open_diary()

    def _hide_to_tray(self) -> None:
        self._hidden_for_fullscreen = False
        if self.tray is not None:
            self.hide()
        else:
            # Fallback: no tray available, treat X as quit.
            self._power_off()

    def _power_off(self) -> None:
        self._quitting = True
        if self.on_before_exit is not None:
            try:
                self.on_before_exit()
            except Exception:
                pass
        if self.tray is not None:
            self.tray.hide()
        QApplication.quit()

    def _snap(self, corner: str) -> None:
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        w, h = self.width(), self.height()
        # Bottom edge hugs the taskbar (no margin); top/sides keep SNAP_MARGIN.
        # QRect.bottom() is inclusive, so flush-bottom is `bottom() - h + 1`.
        if corner == 'tl':
            x, y = geo.left() + SNAP_MARGIN, geo.top() + SNAP_MARGIN
        elif corner == 'tr':
            x, y = geo.right() - w - SNAP_MARGIN, geo.top() + SNAP_MARGIN
        elif corner == 'bl':
            x, y = geo.left() + SNAP_MARGIN, geo.bottom() - h + 1
        else:
            x, y = geo.right() - w - SNAP_MARGIN, geo.bottom() - h + 1
        # Sidebar faces inward so it doesn't end up off-screen.
        self._sidebar_side = 'right' if corner in ('tl', 'bl') else 'left'
        self._reposition_sidebar()
        if not self.isVisible():
            self.show()
        self.move(x, y)
        self.settings.x, self.settings.y = x, y
        self.settings.sidebar_side = self._sidebar_side
        self._persist_settings()

    # ---- drag to move -----------------------------------------------------
    def mousePressEvent(self, event: QMouseEvent) -> None:
        # Primary drag handle lives on the sidebar (see DragHandle). This
        # fallback only fires if the click lands directly on the window (not
        # on a child) — edge case.
        if event.button() == Qt.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            new_pos = event.globalPosition().toPoint() - self._drag_offset
            self.move(new_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            # User finished a manual drag — remember the landing spot.
            self.settings.x = self.x()
            self.settings.y = self.y()
            self._persist_settings()
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Applied on every show (Win11 resets the attribute after hide/show).
        _strip_win11_border(int(self.winId()))

    def resizeEvent(self, event) -> None:
        self._reposition_sidebar()
        super().resizeEvent(event)

    def _reposition_sidebar(self) -> None:
        x = 0 if self._sidebar_side == 'left' else max(0, self.width() - SIDE_BAR_W)
        # Sidebar height adapts to the widget so it's never clipped mid-button.
        # Items that don't fit are hidden entirely (see _refit_sidebar_items).
        h = min(SIDE_BAR_H, max(40, self.height()))
        self.title_bar.setGeometry(x, 0, SIDE_BAR_W, h)
        self._refit_sidebar_items(h)

    def _refit_sidebar_items(self, available_h: int) -> None:
        """Hide bottom-of-sidebar items whose full height won't fit.

        Priority: escape hatches (quit/hide/scale) first, then the 4 snap
        corners — those have to stay as a group since users reposition often —
        then cosmetic controls.
        """
        # (widget, height-with-spacing)
        items = [
            (self.drag_handle, 16),
            (self.btn_quit, 20),
            (self.btn_hide, 20),
            (self.btn_scale, 20),
            (self.btn_opacity, 20),
            (self.btn_tl, 20),
            (self.btn_tr, 20),
            (self.btn_bl, 20),
            (self.btn_br, 20),
            (self.btn_theme, 20),
            (self.btn_diary, 20),
            (self.mult_bar, 38),
        ]
        used = 6
        for w, h in items:
            if used + h <= available_h:
                w.setVisible(True)
                used += h
            else:
                w.setVisible(False)

    # ---- hover reveal -----------------------------------------------------
    def poll_hover(self) -> None:
        """Show/hide the sidebar based on live cursor position. Called once
        per frame from the main loop — more reliable than enterEvent/leaveEvent
        on translucent frameless windows where those don't always fire."""
        pos = self.mapFromGlobal(self.cursor().pos())
        hovering = self.rect().contains(pos)
        if hovering and not self.title_bar.isVisible():
            self.title_bar.raise_()
            self.title_bar.show()
        elif not hovering and self.title_bar.isVisible():
            self.title_bar.hide()

    # ---- close semantics --------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        # External close (Alt+F4, OS session end) should:
        #   - hide to tray if one is available and we aren't explicitly quitting
        #   - otherwise perform the full exit path (persist diary)
        if self._quitting or self.tray is None:
            if self.on_before_exit is not None and not self._quitting:
                try:
                    self.on_before_exit()
                except Exception:
                    pass
            super().closeEvent(event)
        else:
            event.ignore()
            self.hide()
