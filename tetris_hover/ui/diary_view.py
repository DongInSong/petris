"""Diary dialog: per-day record list with sort toggle."""
from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..diary import Diary, DayRecord


_COLUMNS = ["date", "score", "lines", "pieces", "keys", "time", "combo"]
_COLUMN_WIDTHS = [96, 80, 56, 60, 72, 64, 56]

# Explicit palette so the dialog renders the same regardless of whether the
# host OS/Qt style hands us a dark or light system palette. Without this, on
# environments that don't auto-apply a dark palette the table falls back to
# default black-on-dark and becomes unreadable.
_DIALOG_STYLE = """
QDialog { background: #1c1e24; }
QPushButton {
    background: rgba(40, 40, 55, 180);
    color: #dcdce6;
    border: 1px solid rgba(120, 120, 150, 140);
    border-radius: 3px;
    padding: 4px 10px;
}
QPushButton:hover { background: rgba(70, 70, 100, 200); }
QPushButton:checked { background: rgba(90, 110, 140, 220); }
QTableWidget {
    background: #1c1e24;
    alternate-background-color: #23252d;
    color: #dcdce6;
    gridline-color: #3a3d47;
    selection-background-color: #3a4a6a;
    selection-color: #ffffff;
    border: 1px solid rgba(120, 120, 150, 100);
}
QHeaderView::section {
    background: #2a2d36;
    color: #b8b8c4;
    padding: 4px;
    border: 0;
    border-right: 1px solid #3a3d47;
}
QTableCornerButton::section { background: #2a2d36; border: 0; }
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


class DiaryDialog(QDialog):
    def __init__(self, diary: Diary, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        from .. import __version__
        self.setWindowTitle(f"{__version__.APP_NAME} diary · v{__version__.__version__}")
        self.resize(520, 360)
        self.setStyleSheet(_DIALOG_STYLE)
        self._diary = diary
        self._sort_mode = "date"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)

        top = QHBoxLayout()
        self.btn_date = QPushButton("by date")
        self.btn_score = QPushButton("top scores")
        self.btn_date.setCheckable(True)
        self.btn_score.setCheckable(True)
        self.btn_date.setChecked(True)
        self.btn_date.clicked.connect(lambda: self._set_sort("date"))
        self.btn_score.clicked.connect(lambda: self._set_sort("score"))
        top.addWidget(self.btn_date)
        top.addWidget(self.btn_score)
        top.addStretch(1)
        outer.addLayout(top)

        self.table = QTableWidget(self)
        self.table.setColumnCount(len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setAlternatingRowColors(True)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Fixed)
        header.setStretchLastSection(False)
        for i, w in enumerate(_COLUMN_WIDTHS):
            self.table.setColumnWidth(i, w)
        outer.addWidget(self.table)

        self._refresh()

    def _set_sort(self, mode: str) -> None:
        self._sort_mode = mode
        self.btn_date.setChecked(mode == "date")
        self.btn_score.setChecked(mode == "score")
        self._refresh()

    def _refresh(self) -> None:
        rows: List[DayRecord] = (
            self._diary.by_score_desc() if self._sort_mode == "score"
            else self._diary.by_date_desc()
        )
        self.table.setRowCount(len(rows))
        for i, rec in enumerate(rows):
            values = [
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
                if j > 0:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if self._sort_mode == "score" and i < 3 and j == 1:
                    # Highlight podium.
                    item.setForeground(QColor(255, 215, 64))
                self.table.setItem(i, j, item)
