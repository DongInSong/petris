"""Widget that paints the tetris board, pieces, ghost, preview, and score overlay."""
import time
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QWidget

from ..core.game import Game, Piece
from ..core.pieces import BOARD_H, BOARD_W, BUFFER, SHAPES, TOTAL_H
from .effects import EffectLayer
from .themes import Theme


HOLD_W_CELLS = 5
PREVIEW_W_CELLS = 5
PREVIEW_COUNT = 4
SCORE_BUMP_MS = 350
SCORE_BUMP_MAX = 1.35

# 8-direction offsets for drawing a text outline. A plain drop shadow only
# helps against dark backgrounds — the overlay can sit over a white browser
# or bright wallpaper, so we stroke in every direction.
_OUTLINE_OFFSETS = ((-1, -1), (-1, 0), (-1, 1),
                    (0, -1),           (0, 1),
                    (1, -1),  (1, 0),  (1, 1))

# Alpha steps for the neon halo passes (outermost → innermost). Actual pixel
# radii are derived per-call from font height so small text doesn't get
# swamped by a fixed 4 px glow.
_NEON_GLOW_ALPHAS = (28, 70, 130, 200)


def _draw_outlined_text(p: QPainter, x: int, y: int, text: str,
                        fill: QColor,
                        outline_rgb: tuple = (0, 0, 0),
                        outline_alpha: int = 210) -> None:
    outline = QColor(outline_rgb[0], outline_rgb[1], outline_rgb[2], outline_alpha)
    p.setPen(outline)
    for dx, dy in _OUTLINE_OFFSETS:
        p.drawText(x + dx, y + dy, text)
    p.setPen(fill)
    p.drawText(x, y, text)


def _draw_neon_text(p: QPainter, x: int, y: int, text: str,
                    glow_rgb: tuple, core_alpha: int = 250) -> None:
    """Cyberpunk halo on a transparent canvas: dark backstop → colored glow
    → lit core. The backstop is what keeps the text readable on white
    wallpapers (saturated colors alone disappear into bright pixels). Glow
    radius is derived from font height so a tiny multiplier readout doesn't
    drown under the same halo as the big score number.
    """
    # Dark backstop: a single tight outline that anchors the glyphs against
    # bright wallpapers and gives the colored halo a darker pixel to land on.
    # Kept to radius 1 so small text (multiplier at 50% scale) doesn't get
    # eaten by its own outline.
    p.setPen(QColor(0, 0, 0, 200))
    for dx, dy in _OUTLINE_OFFSETS:
        p.drawText(x + dx, y + dy, text)

    fh = p.fontMetrics().height()
    # Outer radius ~12% of text height, capped at 4 px. At 7 pt this is 1 px;
    # at 24 pt it's 4 px. Inner passes step down to 1.
    outer = max(1, min(4, fh * 12 // 100))
    radii = (outer,
             max(1, outer * 3 // 4),
             max(1, outer // 2),
             1)
    for radius, alpha in zip(radii, _NEON_GLOW_ALPHAS):
        p.setPen(QColor(glow_rgb[0], glow_rgb[1], glow_rgb[2], alpha))
        for dx, dy in _OUTLINE_OFFSETS:
            p.drawText(x + dx * radius, y + dy * radius, text)
    # Core: brighten by a fixed amount so the color stays recognizable (cyan
    # ×1.0 reads as cyan, not pale lavender) while still being clearly lighter
    # than the saturated halo behind it.
    cr = min(255, glow_rgb[0] + 100)
    cg = min(255, glow_rgb[1] + 100)
    cb = min(255, glow_rgb[2] + 100)
    p.setPen(QColor(cr, cg, cb, core_alpha))
    p.drawText(x, y, text)


def _bump_scale(elapsed_ms: float) -> float:
    """Ease the bounce: 1.0 → SCORE_BUMP_MAX at the halfway point → 1.0."""
    if elapsed_ms <= 0 or elapsed_ms >= SCORE_BUMP_MS:
        return 1.0
    t = elapsed_ms / SCORE_BUMP_MS  # 0..1
    if t < 0.5:
        k = t / 0.5  # 0..1
    else:
        k = (1.0 - t) / 0.5  # 1..0
    return 1.0 + (SCORE_BUMP_MAX - 1.0) * k


class BoardView(QWidget):
    def __init__(self, game: Game, theme: Theme, parent=None) -> None:
        super().__init__(parent)
        self.game = game
        self.theme = theme
        self.effects = EffectLayer()
        # Widget itself must also be translucent — WA_TranslucentBackground on
        # the top-level window doesn't propagate to child widgets, so without
        # these two the child paints its default background as a visible rect.
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMinimumSize(30, 40)
        self._score: float = 0.0
        self._score_bump_start_ms: float = -1.0
        self._multiplier: float = 1.0

    def set_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.update()

    def set_score(self, score: float) -> None:
        if score > self._score + 0.01:
            self._score_bump_start_ms = time.monotonic() * 1000
        self._score = score

    def set_multiplier(self, m: float) -> None:
        if abs(m - self._multiplier) > 0.02:
            self._multiplier = m
            self.update()

    # ---- geometry ---------------------------------------------------------
    def _cell_size(self) -> int:
        total_cols = HOLD_W_CELLS + BOARD_W + PREVIEW_W_CELLS
        total_rows = max(BOARD_H, 16)
        w = self.width() // total_cols
        h = self.height() // total_rows
        return max(1, min(w, h))

    def _board_origin(self, cell: int) -> tuple:
        # Horizontally centered, bottom-anchored: blocks appear to pile up on
        # whatever the widget is resting on (taskbar, desktop, other windows).
        total_w = (HOLD_W_CELLS + BOARD_W + PREVIEW_W_CELLS) * cell
        ox = (self.width() - total_w) // 2
        oy = self.height() - BOARD_H * cell
        return ox, oy

    def _board_rect(self, cell: int):
        ox, oy = self._board_origin(cell)
        return ox + HOLD_W_CELLS * cell, oy, BOARD_W * cell, BOARD_H * cell

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        cell = self._cell_size()
        bx, by, bw, bh = self._board_rect(cell)

        # Fully transparent playfield — blocks float against whatever is behind
        # the widget (desktop, taskbar). No fill, no border. Neon's per-block
        # shadow gives local contrast without painting a panel.

        self._draw_stack(painter, bx, by, cell)
        if self.game.piece is not None:
            self._draw_ghost(painter, bx, by, cell, self.game.piece)
            self._draw_piece(painter, bx, by, cell, self.game.piece)

        ox, oy = self._board_origin(cell)
        self._draw_hold(painter, ox, oy, cell)
        self._draw_preview(painter, ox + (HOLD_W_CELLS + BOARD_W) * cell, oy, cell)

        self.effects.draw(painter, self.width(), self.height())
        self._draw_score_overlay(painter, bx, by, bw, bh)

    def _draw_score_overlay(self, p: QPainter, bx: int, by: int, bw: int, bh: int) -> None:
        if bw < 30 or bh < 30:
            return  # too tiny to show readable text
        text = self._format_score(self._score)

        now_ms = time.monotonic() * 1000
        elapsed = now_ms - self._score_bump_start_ms if self._score_bump_start_ms > 0 else SCORE_BUMP_MS
        scale = _bump_scale(elapsed)
        if elapsed < SCORE_BUMP_MS:
            # Repaint next frame to continue the animation smoothly.
            self.update()

        # Base size scales with the board width so the overlay feels part of the game.
        base_pt = max(8, min(48, bw // 7))
        font = QFont()
        font.setFamily("Consolas")
        font.setPointSize(int(base_pt * scale))
        font.setBold(True)
        p.setFont(font)

        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        cx = bx + bw // 2
        ty = by + int(bh * 0.12) + th // 2  # near top of playfield

        theme = self.theme
        score_rgb = theme.score_rgb
        if theme.text_glow:
            _draw_neon_text(p, cx - tw // 2, ty, text, score_rgb)
        else:
            # Bump glow: stronger color during bounce, softer when resting.
            glow_strength = int(60 + 120 * (scale - 1.0) / (SCORE_BUMP_MAX - 1.0)) if scale > 1.0 else 60
            main = QColor(score_rgb[0], score_rgb[1], score_rgb[2],
                          180 + min(60, glow_strength))
            _draw_outlined_text(p, cx - tw // 2, ty, text, main,
                                outline_rgb=theme.text_outline_rgb)

        # Always-visible multiplier readout right under the score. Color
        # interpolates between theme-defined low/high endpoints with speed.
        m = self._multiplier
        mfont = QFont()
        mfont.setFamily("Consolas")
        # Bumped from base_pt//2 → ~62%. The old size sat just at the edge of
        # legible at small board scales and got swamped by the neon halo.
        mfont.setPointSize(max(9, base_pt * 5 // 8))
        mfont.setBold(True)
        p.setFont(mfont)
        mtext = f"×{m:.1f}"
        mfm = p.fontMetrics()
        mtw = mfm.horizontalAdvance(mtext)
        frac = max(0.0, min(1.0, (m - 1.0) / 7.0))
        lo, hi = theme.multiplier_low_rgb, theme.multiplier_high_rgb
        mr = int(lo[0] + (hi[0] - lo[0]) * frac)
        mg = int(lo[1] + (hi[1] - lo[1]) * frac)
        mb = int(lo[2] + (hi[2] - lo[2]) * frac)
        if theme.text_glow:
            _draw_neon_text(p, cx - mtw // 2, ty + th - 2, mtext, (mr, mg, mb))
        else:
            malpha = int(230 + 25 * frac)
            _draw_outlined_text(p, cx - mtw // 2, ty + th - 2, mtext,
                                QColor(mr, mg, mb, malpha),
                                outline_rgb=theme.text_outline_rgb)

    @staticmethod
    def _format_score(score: float) -> str:
        if score >= 1_000_000:
            return f"{score / 1_000_000:.2f}M"
        if score >= 10_000:
            return f"{score / 1_000:.1f}k"
        return f"{int(score)}"

    def _draw_stack(self, p: QPainter, ox: int, oy: int, cell: int) -> None:
        grid = self.game.board.grid
        # Only rows BUFFER .. BUFFER+BOARD_H-1 are visible.
        for y in range(BOARD_H):
            row = grid[y + BUFFER]
            for x in range(BOARD_W):
                kind = row[x]
                if kind is None:
                    continue
                self._draw_cell(p, ox + x * cell, oy + y * cell, cell, kind, alpha=255)

    def _draw_piece(self, p: QPainter, ox: int, oy: int, cell: int, piece: Piece) -> None:
        for mx, my in piece.minos():
            vy = my - BUFFER
            if vy < 0 or vy >= BOARD_H:
                continue
            self._draw_cell(p, ox + mx * cell, oy + vy * cell, cell, piece.kind, alpha=255)

    def _draw_ghost(self, p: QPainter, ox: int, oy: int, cell: int, piece: Piece) -> None:
        # Find ghost landing.
        ghost = piece.clone()
        while True:
            test = ghost.clone()
            test.y += 1
            collides = False
            for x, y in test.minos():
                if x < 0 or x >= BOARD_W or y >= TOTAL_H:
                    collides = True
                    break
                if y >= 0 and self.game.board.grid[y][x] is not None:
                    collides = True
                    break
            if collides:
                break
            ghost = test
        for mx, my in ghost.minos():
            vy = my - BUFFER
            if vy < 0 or vy >= BOARD_H:
                continue
            self._draw_cell(p, ox + mx * cell, oy + vy * cell, cell, piece.kind, alpha=self.theme.ghost_alpha, ghost=True)

    def _draw_cell(self, p: QPainter, x: int, y: int, cell: int, kind: str, alpha: int = 255, ghost: bool = False) -> None:
        rgb = self.theme.block_colors[kind]
        if ghost:
            p.fillRect(x, y, cell, cell, QColor(rgb[0], rgb[1], rgb[2], alpha))
            return
        if self.theme.block_glow:
            self._draw_cell_neon(p, x, y, cell, rgb, alpha)
            return
        base = QColor(rgb[0], rgb[1], rgb[2], alpha)
        p.fillRect(x, y, cell, cell, base)
        # Highlight edge (top + left)
        hi = QColor(min(255, rgb[0] + 60), min(255, rgb[1] + 60), min(255, rgb[2] + 60), alpha)
        p.fillRect(x, y, cell, 2, hi)
        p.fillRect(x, y, 2, cell, hi)
        # Shadow edge (bottom + right)
        sh = QColor(max(0, rgb[0] - 60), max(0, rgb[1] - 60), max(0, rgb[2] - 60), alpha)
        p.fillRect(x, y + cell - 2, cell, 2, sh)
        p.fillRect(x + cell - 2, y, 2, cell, sh)

    def _draw_cell_neon(self, p: QPainter, x: int, y: int, cell: int,
                        rgb: tuple, alpha: int) -> None:
        """Cyberpunk lit-tube look on a transparent canvas. Three layers:
          1. Dark drop-shadow halo — gives bright wallpapers a local "wall"
             for the colored glow to land on; invisible on dark backgrounds.
          2. Colored glow halo — the actual neon bleed, on top of the shadow.
          3. Dim interior + bright rim — the lit glass tube itself.
        Adjacent cells' shadows stack into a darker zone (good — reads as a
        single lit object), while empty cells stay fully transparent.
        """
        # Layer 1: black drop-shadow halo. Reach a bit further than the color
        # halo so the colored bleed always lands on a darker pixel.
        sh_r = max(2, cell // 4)
        for r, base_a in ((sh_r, 30), (max(1, sh_r * 2 // 3), 70),
                          (max(1, sh_r // 3), 120)):
            sa = base_a * alpha // 255 if alpha < 255 else base_a
            p.fillRect(x - r, y - r, cell + 2 * r, cell + 2 * r,
                       QColor(0, 0, 0, sa))
        # Layer 2: colored glow. Tighter radius than the shadow so the dark
        # outer ring frames the colored inner ring.
        glow_r = max(2, cell // 6)
        for r, base_a in ((glow_r, 60), (max(1, glow_r // 2), 130)):
            ga = base_a * alpha // 255 if alpha < 255 else base_a
            p.fillRect(x - r, y - r, cell + 2 * r, cell + 2 * r,
                       QColor(rgb[0], rgb[1], rgb[2], ga))
        # Layer 3: dimmed interior + bright rim — the glass tube. Skip the dim
        # interior on tiny cells where the rim would already eat the square.
        if cell >= 10:
            dim = QColor(rgb[0] * 32 // 100, rgb[1] * 32 // 100,
                         rgb[2] * 32 // 100, alpha)
            p.fillRect(x, y, cell, cell, dim)
            rim_w = 2 if cell >= 14 else 1
        else:
            p.fillRect(x, y, cell, cell, QColor(rgb[0], rgb[1], rgb[2], alpha))
            rim_w = 1
        # Bright rim — pushed close to white so it reads as the lit gas inside
        # the glass, not just a slightly-lighter version of the fill.
        rim = QColor(min(255, rgb[0] + 130), min(255, rgb[1] + 130),
                     min(255, rgb[2] + 130), alpha)
        p.fillRect(x, y, cell, rim_w, rim)
        p.fillRect(x, y + cell - rim_w, cell, rim_w, rim)
        p.fillRect(x, y, rim_w, cell, rim)
        p.fillRect(x + cell - rim_w, y, rim_w, cell, rim)

    def _draw_hold(self, p: QPainter, ox: int, oy: int, cell: int) -> None:
        kind = self.game.hold
        if kind is None:
            return
        self._draw_mini_piece(p, ox, oy, cell, kind, dim=self.game.hold_used)

    def _draw_preview(self, p: QPainter, ox: int, oy: int, cell: int) -> None:
        queue = self.game.bag.peek(PREVIEW_COUNT)
        for i, kind in enumerate(queue):
            self._draw_mini_piece(p, ox, oy + i * 3 * cell, cell, kind, dim=False)

    def _draw_mini_piece(self, p: QPainter, ox: int, oy: int, cell: int, kind: str, dim: bool) -> None:
        minos = SHAPES[kind][0]
        min_dx = min(m[0] for m in minos)
        max_dx = max(m[0] for m in minos)
        min_dy = min(m[1] for m in minos)
        max_dy = max(m[1] for m in minos)
        w_cells = max_dx - min_dx + 1
        h_cells = max_dy - min_dy + 1
        # Center in a 4x3 area
        scale = int(cell * 0.72)
        area_w = 4 * scale
        area_h = 3 * scale
        off_x = ox + (HOLD_W_CELLS * cell - area_w) // 2 + (4 - w_cells) * scale // 2
        off_y = oy + cell // 2 + (3 - h_cells) * scale // 2
        alpha = 100 if dim else 255
        for dx, dy in minos:
            x = off_x + (dx - min_dx) * scale
            y = off_y + (dy - min_dy) * scale
            rgb = self.theme.block_colors[kind]
            p.fillRect(x, y, scale, scale, QColor(rgb[0], rgb[1], rgb[2], alpha))

    # ---- effects trigger --------------------------------------------------
    def trigger_clear_effect(self, rows: List[int], piece_kind: str) -> None:
        cell = self._cell_size()
        bx, by, _, _ = self._board_rect(cell)
        rgb = self.theme.block_colors.get(piece_kind, (255, 255, 255))
        for raw_y in rows:
            vy = raw_y - BUFFER
            if vy < 0 or vy >= BOARD_H:
                continue
            cy = by + vy * cell + cell // 2
            for gx in range(BOARD_W):
                cx = bx + gx * cell + cell // 2
                self.effects.burst(self.theme, cx, cy, rgb)

    def trigger_collapse_effect(self, grid_snapshot) -> None:
        """Spawn debris from the entire pre-wipe stack and stop showing the
        playfield blocks until the animation ends."""
        cell = self._cell_size()
        bx, by, _, _ = self._board_rect(cell)
        self.effects.collapse(self.theme, bx, by, cell, BUFFER, grid_snapshot)

    def trigger_slam_effect(self, cols: List[int], start_row: int, end_row: int,
                            piece_kind: str) -> None:
        """Sparse motion trail through `cols` + a single impact pop at end_row.
        Deliberately quiet so slams read as a punctuation, not fireworks."""
        cell = self._cell_size()
        bx, by, _, _ = self._board_rect(cell)
        rgb = self.theme.block_colors.get(piece_kind, (255, 255, 255))

        # Trail: every other row, one particle per column (not every col).
        for row in range(start_row, end_row + 1, 2):
            vy = row - BUFFER
            if vy < 0 or vy >= BOARD_H:
                continue
            cy = by + vy * cell + cell // 2
            # Single particle at the piece's horizontal center for minimal noise.
            if not cols:
                continue
            mid_col = cols[len(cols) // 2]
            cx = bx + mid_col * cell + cell // 2
            self.effects.trail(cx, cy, rgb)

        # Impact: one small pop at the landing row center (no per-column burst).
        end_vy = end_row - BUFFER
        if 0 <= end_vy < BOARD_H and cols:
            cy = by + end_vy * cell + cell
            mid_col = cols[len(cols) // 2]
            cx = bx + mid_col * cell + cell // 2
            for _ in range(4):  # tiny burst — 4 particles
                self.effects.trail(cx, cy, rgb)
