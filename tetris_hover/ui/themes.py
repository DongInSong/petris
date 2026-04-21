"""Theme presets: ambient (pastel + soft fade) and vivid (bright + burst)."""
from dataclasses import dataclass
from typing import Dict, Tuple

from ..core.pieces import COLORS_AMBIENT, COLORS_VIVID


RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class Theme:
    name: str
    block_colors: Dict[str, RGB]
    bg_alpha: int  # overall window alpha, 0..255
    bg_rgb: RGB
    ghost_alpha: int
    particle_life_ms: int
    particle_speed: float
    particle_count: int


AMBIENT = Theme(
    name='ambient',
    block_colors=COLORS_AMBIENT,
    bg_alpha=130,
    bg_rgb=(28, 30, 36),
    ghost_alpha=35,
    particle_life_ms=700,
    particle_speed=1.2,
    particle_count=10,
)

VIVID = Theme(
    name='vivid',
    block_colors=COLORS_VIVID,
    bg_alpha=170,
    bg_rgb=(10, 10, 20),
    ghost_alpha=70,
    particle_life_ms=500,
    particle_speed=3.5,
    particle_count=24,
)


def get(name: str) -> Theme:
    return AMBIENT if name == 'ambient' else VIVID
