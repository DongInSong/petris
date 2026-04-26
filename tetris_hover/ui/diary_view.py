"""Diary dialog: per-day record list with sort toggle."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..diary import Diary, DayRecord


_COLUMNS = ["#", "date", "score", "lines", "pieces", "keys", "time", "combo"]
_COLUMN_WIDTHS = [32, 88, 88, 52, 56, 60, 60, 52]

# Palette — kept as constants so the QSS below stays readable.
_BG          = "#0f1218"
_BG_ELEVATED = "#161a22"
_BG_HOVER    = "#1f2533"
_BORDER      = "#262b36"
_BORDER_SOFT = "#1d212a"
_TEXT        = "#e6e8ee"
_TEXT_DIM    = "#8a90a0"
_TEXT_MUTED  = "#5a606e"
_ACCENT      = "#7dd3fc"
_ACCENT_BG   = "#1a3046"
_GOLD        = "#ffd54f"
_SILVER      = "#cfd8dc"
_BRONZE      = "#ff8a65"

# Explicit palette so the dialog renders the same regardless of the host
# OS/Qt style. Selectors are scoped per widget class/object name to avoid
# the cascade-leak problem that previously broke popup menus elsewhere.
_DIALOG_STYLE = f"""
QDialog {{
    background: {_BG};
}}
QLabel#title {{
    color: {_TEXT};
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 2px;
}}
QLabel#subtitle {{
    color: {_TEXT_MUTED};
    font-size: 9px;
    letter-spacing: 1px;
}}
QFrame#card {{
    background: {_BG_ELEVATED};
    border: 1px solid {_BORDER};
    border-radius: 6px;
}}
QLabel#statValue {{
    color: {_TEXT};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#statValueAccent {{
    color: {_ACCENT};
    font-size: 14px;
    font-weight: 600;
}}
QLabel#statLabel {{
    color: {_TEXT_DIM};
    font-size: 8px;
    letter-spacing: 1px;
}}
QPushButton#segLeft, QPushButton#segRight {{
    background: {_BG_ELEVATED};
    color: {_TEXT_DIM};
    border: 1px solid {_BORDER};
    padding: 4px 12px;
    font-size: 10px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QPushButton#segLeft:hover, QPushButton#segRight:hover {{
    color: {_TEXT};
    background: {_BG_HOVER};
}}
QPushButton#segLeft:checked, QPushButton#segRight:checked {{
    background: {_ACCENT_BG};
    color: {_ACCENT};
    border-color: {_ACCENT};
}}
QPushButton#segLeft {{
    border-top-left-radius: 5px;
    border-bottom-left-radius: 5px;
    border-right: 0;
}}
QPushButton#segRight {{
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
}}
QFrame#tableWrap {{
    background: {_BG_ELEVATED};
    border: 1px solid {_BORDER};
    border-radius: 6px;
}}
QTableWidget {{
    background: transparent;
    color: {_TEXT};
    gridline-color: transparent;
    selection-background-color: {_ACCENT_BG};
    selection-color: {_TEXT};
    border: 0;
    outline: none;
}}
QTableWidget::item {{
    padding: 4px 4px;
    border: 0;
    border-bottom: 1px solid {_BORDER_SOFT};
}}
QTableWidget::item:hover {{
    background: {_BG_HOVER};
}}
QHeaderView {{
    background: transparent;
    border: 0;
}}
QHeaderView::section {{
    background: transparent;
    color: {_TEXT_DIM};
    padding: 6px 4px;
    border: 0;
    border-bottom: 1px solid {_BORDER};
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 1px;
}}
QTableCornerButton::section {{
    background: transparent;
    border: 0;
    border-bottom: 1px solid {_BORDER};
}}
QLabel#emptyState {{
    color: {_TEXT_MUTED};
    font-size: 11px;
    letter-spacing: 1px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 3px 2px 3px 0;
}}
QScrollBar::handle:vertical {{
    background: {_BORDER};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {_TEXT_MUTED};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
"""


def _fmt_duration(seconds: int) -> str:
    h = seconds // 3600
    m = (seconds % 3600) // 60
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m"


def _fmt_score(v: float) -> str:
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 10_000:
        return f"{v / 1_000:.1f}k"
    return f"{int(v)}"


def _make_card(value: str, label: str, *, accent: bool = False) -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(10, 6, 10, 6)
    lay.setSpacing(0)
    val = QLabel(value)
    val.setObjectName("statValueAccent" if accent else "statValue")
    lbl = QLabel(label.upper())
    lbl.setObjectName("statLabel")
    lay.addWidget(val)
    lay.addWidget(lbl)
    return card


class DiaryDialog(QDialog):
    def __init__(self, diary: Diary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .. import __version__
        self.setWindowTitle(f"{__version__.APP_NAME} diary")
        self.resize(560, 400)
        self.setMinimumSize(460, 320)
        self.setStyleSheet(_DIALOG_STYLE)
        self._diary = diary
        self._sort_mode = "date"
        self._app_name = __version__.APP_NAME
        self._version = __version__.__version__

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        outer.addLayout(self._build_header())
        self._cards_row = QHBoxLayout()
        self._cards_row.setSpacing(6)
        outer.addLayout(self._cards_row)
        outer.addLayout(self._build_toggle())
        outer.addWidget(self._build_table_wrap(), 1)

        self._refresh_cards()
        self._refresh_table()

    # ---- builders ----------------------------------------------------------
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)
        title = QLabel(f"{self._app_name.upper()} · DIARY")
        title.setObjectName("title")
        sub = QLabel(f"v{self._version}")
        sub.setObjectName("subtitle")
        row.addWidget(title)
        row.addWidget(sub)
        row.addStretch(1)
        return row

    def _build_toggle(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(0)
        self.btn_date = QPushButton("BY DATE")
        self.btn_date.setObjectName("segLeft")
        self.btn_date.setCheckable(True)
        self.btn_date.setChecked(True)
        self.btn_date.setCursor(Qt.PointingHandCursor)
        self.btn_score = QPushButton("TOP SCORES")
        self.btn_score.setObjectName("segRight")
        self.btn_score.setCheckable(True)
        self.btn_score.setCursor(Qt.PointingHandCursor)
        self.btn_date.clicked.connect(lambda: self._set_sort("date"))
        self.btn_score.clicked.connect(lambda: self._set_sort("score"))
        row.addWidget(self.btn_date)
        row.addWidget(self.btn_score)
        row.addStretch(1)
        return row

    def _build_table_wrap(self) -> QFrame:
        wrap = QFrame()
        wrap.setObjectName("tableWrap")
        lay = QVBoxLayout(wrap)
        lay.setContentsMargins(1, 1, 1, 1)
        lay.setSpacing(0)

        self.table = QTableWidget(wrap)
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels([c.upper() for c in _COLUMNS])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setFocusPolicy(Qt.NoFocus)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.table.verticalHeader().setDefaultSectionSize(24)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        header.setHighlightSections(False)
        for i, w in enumerate(_COLUMN_WIDTHS):
            self.table.setColumnWidth(i, w)
        # Stretch the date column so the table fills horizontal space cleanly.
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        lay.addWidget(self.table)

        self.empty_label = QLabel("no records yet — play a session and come back")
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.hide()
        lay.addWidget(self.empty_label)
        return wrap

    # ---- data --------------------------------------------------------------
    def _set_sort(self, mode: str) -> None:
        self._sort_mode = mode
        self.btn_date.setChecked(mode == "date")
        self.btn_score.setChecked(mode == "score")
        self._refresh_table()

    def _refresh_cards(self) -> None:
        # Drain any prior cards so re-open after a session reflects fresh totals.
        while self._cards_row.count():
            item = self._cards_row.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        rows = self._diary.by_date_desc()
        days = len(rows)
        total_score = sum(r.score for r in rows)
        best = max((r.score for r in rows), default=0.0)
        total_seconds = sum(r.duration_sec for r in rows)

        self._cards_row.addWidget(_make_card(_fmt_score(total_score), "total score"))
        self._cards_row.addWidget(_make_card(_fmt_score(best), "best day", accent=True))
        self._cards_row.addWidget(_make_card(_fmt_duration(total_seconds), "play time"))
        self._cards_row.addWidget(_make_card(f"{days}", "days logged"))

    def _refresh_table(self) -> None:
        rows: List[DayRecord] = (
            self._diary.by_score_desc() if self._sort_mode == "score"
            else self._diary.by_date_desc()
        )
        self.empty_label.setVisible(not rows)
        self.table.setVisible(bool(rows))
        self.table.setRowCount(len(rows))

        podium_colors = (QColor(_GOLD), QColor(_SILVER), QColor(_BRONZE))
        dim = QColor(_TEXT_MUTED)

        for i, rec in enumerate(rows):
            rank = i + 1
            values = [
                str(rank),
                rec.date,
                _fmt_score(rec.score),
                str(rec.lines),
                str(rec.pieces),
                str(rec.keystrokes),
                _fmt_duration(rec.duration_sec),
                f"{rec.max_combo}x",
            ]
            for j, v in enumerate(values):
                item = QTableWidgetItem(v)
                if j == 0:
                    item.setTextAlignment(Qt.AlignCenter | Qt.AlignVCenter)
                    item.setForeground(dim)
                elif j == 1:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

                if self._sort_mode == "score" and i < 3:
                    color = podium_colors[i]
                    if j == 0:
                        # Bold rank chip color for podium positions.
                        item.setForeground(color)
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)
                    elif j == 2:
                        item.setForeground(color)
                        f = item.font()
                        f.setBold(True)
                        item.setFont(f)

                self.table.setItem(i, j, item)
