"""Particle effects for line clears."""
import math
import random
import time
from dataclasses import dataclass
from typing import List, Tuple

from PySide6.QtGui import QColor, QPainter

from .themes import Theme


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    rgb: Tuple[int, int, int]
    born_ms: float
    life_ms: float
    size: int = 4
    gravity: float = 0.15

    def alive(self, now_ms: float) -> bool:
        return (now_ms - self.born_ms) < self.life_ms

    def alpha(self, now_ms: float) -> int:
        t = (now_ms - self.born_ms) / self.life_ms
        return max(0, min(255, int(255 * (1 - t))))


class EffectLayer:
    def __init__(self) -> None:
        self.particles: List[Particle] = []

    def burst(self, theme: Theme, x: float, y: float, rgb: Tuple[int, int, int]) -> None:
        now = time.monotonic() * 1000
        for _ in range(theme.particle_count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(0.4, 1.6) * theme.particle_speed
            self.particles.append(Particle(
                x=x, y=y,
                vx=speed * math.cos(angle),
                vy=speed * math.sin(angle),
                rgb=rgb,
                born_ms=now,
                life_ms=theme.particle_life_ms * random.uniform(0.7, 1.1),
            ))

    def trail(self, x: float, y: float, rgb: Tuple[int, int, int]) -> None:
        """Short-lived, downward-biased particle for slam motion blur."""
        now = time.monotonic() * 1000
        self.particles.append(Particle(
            x=x + random.uniform(-3, 3),
            y=y,
            vx=random.uniform(-0.2, 0.2),
            vy=random.uniform(0.4, 1.2),
            rgb=rgb,
            born_ms=now,
            life_ms=230,
        ))

    def collapse(self, theme: Theme, bx: int, by: int, cell: int, buffer: int,
                 grid_snapshot: List[List]) -> None:
        """Spawn block-sized debris particles from a pre-wipe grid snapshot."""
        now = time.monotonic() * 1000
        size = max(2, cell - 2)
        for gy, row in enumerate(grid_snapshot):
            vy = gy - buffer
            if vy < 0 or vy >= len(grid_snapshot) - buffer:
                continue
            for gx, kind in enumerate(row):
                if kind is None:
                    continue
                rgb = theme.block_colors.get(kind, (255, 255, 255))
                cx = bx + gx * cell + cell // 2
                cyp = by + vy * cell + cell // 2
                self.particles.append(Particle(
                    x=cx, y=cyp,
                    vx=random.uniform(-1.2, 1.2),
                    vy=random.uniform(-0.5, 0.8),
                    rgb=rgb,
                    born_ms=now,
                    life_ms=1400,
                    size=size,
                    gravity=0.45,
                ))

    def step(self) -> None:
        now_ms = time.monotonic() * 1000
        alive: List[Particle] = []
        for p in self.particles:
            if not p.alive(now_ms):
                continue
            p.x += p.vx
            p.y += p.vy
            p.vy += p.gravity
            alive.append(p)
        self.particles = alive

    def draw(self, painter: QPainter, width: int, height: int) -> None:
        now_ms = time.monotonic() * 1000
        for p in self.particles:
            a = p.alpha(now_ms)
            if a <= 0:
                continue
            half = p.size // 2
            painter.fillRect(int(p.x) - half, int(p.y) - half, p.size, p.size,
                             QColor(p.rgb[0], p.rgb[1], p.rgb[2], a))
