"""Particle effects for line clears.

Each theme picks a particle_style; the spawn parameters and the draw shape
both branch on it:
    square   — small solid squares (ambient, retro). The classic.
    confetti — mixed-size candy rects with white sparkles, floaty fall.
    spark    — velocity-aligned streaks that fly fast and die young.
    orb      — soft round motes that drift up like aurora dust.
"""
import math
import random
import time
from dataclasses import dataclass
from typing import List, Tuple

from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QPainter, QPen

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
    style: str = 'square'

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
        style = theme.particle_style
        for _ in range(theme.particle_count):
            angle = random.uniform(0, math.tau)
            speed = random.uniform(0.4, 1.6) * theme.particle_speed
            size = 4
            gravity = 0.15
            prgb = rgb
            if style == 'confetti':
                # Candy shrapnel: varied sizes, one in four flashes white,
                # light gravity so pieces tumble instead of plummet.
                size = random.choice((2, 3, 3, 4, 5))
                gravity = 0.09
                if random.random() < 0.25:
                    prgb = (255, 255, 255)
            elif style == 'spark':
                # Fast, hot, brief — embers off a cut neon tube.
                speed *= random.uniform(1.0, 1.6)
                size = 3
                gravity = 0.05
            elif style == 'orb':
                # Aurora dust: slow, buoyant, long-lived.
                speed *= 0.6
                size = random.choice((3, 4, 5))
                gravity = -0.025
            self.particles.append(Particle(
                x=x, y=y,
                vx=speed * math.cos(angle),
                vy=speed * math.sin(angle),
                rgb=prgb,
                born_ms=now,
                life_ms=theme.particle_life_ms * random.uniform(0.7, 1.1),
                size=size,
                gravity=gravity,
                style=style,
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
            if p.style == 'spark':
                self._draw_spark(painter, p, a)
            elif p.style == 'orb':
                self._draw_orb(painter, p, a)
            else:
                # square + confetti are both rects; confetti varies size/color
                # at spawn time instead of draw time.
                half = p.size // 2
                painter.fillRect(int(p.x) - half, int(p.y) - half, p.size, p.size,
                                 QColor(p.rgb[0], p.rgb[1], p.rgb[2], a))

    @staticmethod
    def _draw_spark(painter: QPainter, p: Particle, a: int) -> None:
        """Streak from the particle back along its velocity: a saturated tail
        with a near-white head, so fast sparks read as light, not confetti."""
        tail_x = p.x - p.vx * 2.4
        tail_y = p.y - p.vy * 2.4
        pen = QPen(QColor(p.rgb[0], p.rgb[1], p.rgb[2], a * 70 // 100))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawLine(QPointF(tail_x, tail_y), QPointF(p.x, p.y))
        head = QPen(QColor(min(255, p.rgb[0] + 160), min(255, p.rgb[1] + 160),
                           min(255, p.rgb[2] + 160), a))
        head.setWidthF(1.4)
        painter.setPen(head)
        painter.drawLine(QPointF(p.x - p.vx * 0.8, p.y - p.vy * 0.8),
                         QPointF(p.x, p.y))

    @staticmethod
    def _draw_orb(painter: QPainter, p: Particle, a: int) -> None:
        """Soft mote: dim wide halo under a brighter core, both round."""
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(QColor(0, 0, 0, 0))
        halo = p.size * 1.9
        painter.setBrush(QColor(p.rgb[0], p.rgb[1], p.rgb[2], a * 30 // 100))
        painter.drawEllipse(QPointF(p.x, p.y), halo / 2, halo / 2)
        painter.setBrush(QColor(min(255, p.rgb[0] + 70), min(255, p.rgb[1] + 70),
                                min(255, p.rgb[2] + 70), a))
        painter.drawEllipse(QPointF(p.x, p.y), p.size / 2, p.size / 2)
        painter.restore()
