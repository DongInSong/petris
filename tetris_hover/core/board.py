"""Playfield: 10 wide, 24 tall (4 buffer rows above visible 20)."""
from typing import List, Optional

from .pieces import BOARD_W, TOTAL_H


class Board:
    def __init__(self) -> None:
        self.w = BOARD_W
        self.h = TOTAL_H
        self.grid: List[List[Optional[str]]] = [
            [None] * self.w for _ in range(self.h)
        ]

    def is_free(self, x: int, y: int) -> bool:
        if x < 0 or x >= self.w or y >= self.h:
            return False
        if y < 0:
            return True
        return self.grid[y][x] is None

    def set(self, x: int, y: int, kind: str) -> None:
        if 0 <= x < self.w and 0 <= y < self.h:
            self.grid[y][x] = kind

    def clear_full_lines(self) -> List[int]:
        """Remove full rows. Return indices of cleared rows (pre-shift)."""
        cleared: List[int] = []
        kept: List[List[Optional[str]]] = []
        for y in range(self.h):
            if all(c is not None for c in self.grid[y]):
                cleared.append(y)
            else:
                kept.append(self.grid[y][:])
        while len(kept) < self.h:
            kept.insert(0, [None] * self.w)
        self.grid = kept
        return cleared

    def column_heights(self) -> List[int]:
        """Height (0..h) of each column measured from bottom."""
        out = [0] * self.w
        for x in range(self.w):
            for y in range(self.h):
                if self.grid[y][x] is not None:
                    out[x] = self.h - y
                    break
        return out

    def snapshot(self) -> List[List[Optional[str]]]:
        return [row[:] for row in self.grid]

    def restore(self, snap: List[List[Optional[str]]]) -> None:
        self.grid = [row[:] for row in snap]
