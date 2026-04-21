"""7-bag randomizer with peek support."""
import random
from typing import List, Optional

from .pieces import KINDS


class SevenBag:
    def __init__(self, seed: Optional[int] = None) -> None:
        self._rng = random.Random(seed)
        self._queue: List[str] = []
        self._refill()

    def _refill(self) -> None:
        while len(self._queue) < 14:
            new = list(KINDS)
            self._rng.shuffle(new)
            self._queue.extend(new)

    def next(self) -> str:
        v = self._queue.pop(0)
        self._refill()
        return v

    def peek(self, n: int) -> List[str]:
        self._refill()
        return self._queue[:n]
