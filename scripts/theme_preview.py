#!/usr/bin/env python3
"""Offscreen theme preview renderer.

Renders every theme over a dark and a light backdrop (the window is
transparent in real use, so both extremes matter) and writes PNGs to
--outdir. Used to eyeball theme changes without launching the app.

Usage:
  QT_QPA_PLATFORM=offscreen python3 scripts/theme_preview.py --outdir /tmp/themes
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QPoint
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QApplication

from tetris_hover.core.game import Game, Piece
from tetris_hover.core.pieces import BUFFER, TOTAL_H
from tetris_hover.ui.board_view import BoardView
from tetris_hover.ui.themes import ORDER, get as get_theme

# A believable mid-game stack: column heights and a few overhangs, written
# as (row offset from bottom, col, kind).
STACK = [
    (0, 0, 'J'), (0, 1, 'J'), (0, 2, 'L'), (0, 3, 'L'), (0, 4, 'O'),
    (0, 5, 'O'), (0, 6, 'S'), (0, 7, 'Z'), (0, 8, 'I'),
    (1, 0, 'J'), (1, 1, 'T'), (1, 2, 'T'), (1, 3, 'L'), (1, 4, 'O'),
    (1, 5, 'O'), (1, 6, 'S'), (1, 7, 'S'), (1, 8, 'I'),
    (2, 0, 'Z'), (2, 1, 'T'), (2, 2, 'S'), (2, 3, 'I'), (2, 4, 'I'),
    (2, 6, 'J'), (2, 7, 'L'),
    (3, 0, 'Z'), (3, 1, 'Z'), (3, 3, 'T'), (3, 6, 'J'),
    (4, 0, 'L'), (4, 1, 'O'),
]


def build_game() -> Game:
    game = Game(seed=7)
    for up, col, kind in STACK:
        game.board.grid[TOTAL_H - 1 - up][col] = kind
    game.hold = 'I'
    # Falling T halfway down so piece + ghost both render.
    game.piece = Piece('T', 4, BUFFER + 6, 0)
    return game


def render(view: BoardView, w: int, h: int, bg: str) -> QImage:
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    if bg == 'dark':
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(34, 36, 46))
        grad.setColorAt(1.0, QColor(18, 18, 26))
        p.fillRect(0, 0, w, h, grad)
    else:
        grad = QLinearGradient(0, 0, w, h)
        grad.setColorAt(0.0, QColor(235, 238, 242))
        grad.setColorAt(0.5, QColor(208, 220, 235))
        grad.setColorAt(1.0, QColor(245, 235, 220))
        p.fillRect(0, 0, w, h, grad)
    view.render(p, QPoint(0, 0))
    p.end()
    return img


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', default='/tmp/themes')
    ap.add_argument('--width', type=int, default=340)
    ap.add_argument('--height', type=int, default=400)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication([])
    game = build_game()

    for name in ORDER:
        theme = get_theme(name)
        view = BoardView(game, theme)
        view.resize(args.width, args.height)
        view._score = 48230.0
        view._multiplier = 3.7
        # Burst a clear effect mid-stack so particle styles show up.
        cell = view._cell_size()
        bx, by, bw, bh = view._board_rect(cell)
        view.effects.burst(theme, bx + bw * 0.5, by + bh * 0.82,
                           theme.block_colors['T'])
        view.effects.burst(theme, bx + bw * 0.25, by + bh * 0.86,
                           theme.block_colors['I'])
        for _ in range(6):
            view.effects.step()
        for bg in ('dark', 'light'):
            img = render(view, args.width, args.height, bg)
            path = outdir / f'{name}_{bg}.png'
            img.save(str(path))
            print(path)


if __name__ == '__main__':
    main()
