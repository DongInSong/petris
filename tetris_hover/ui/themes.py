"""Theme presets: ambient (pastel), vivid (bright burst), neon (cyberpunk glow)."""
from dataclasses import dataclass
from typing import Dict, Tuple

from ..core.pieces import COLORS_AMBIENT, COLORS_NEON, COLORS_VIVID


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
    # Score / multiplier overlay styling. Defaults match ambient+vivid; neon
    # overrides text_glow=True to render a colored halo around a near-white core.
    score_rgb: RGB = (255, 255, 255)
    multiplier_low_rgb: RGB = (120, 230, 255)   # at multiplier ≈ 1.0
    multiplier_high_rgb: RGB = (255, 160, 60)   # at multiplier ≈ 8.0
    text_outline_rgb: RGB = (0, 0, 0)
    text_glow: bool = False
    # If True, blocks render as flat fills with an outer halo + bright rim
    # instead of the default beveled style. Also enables a per-block dark
    # drop-shadow so neon glows survive on bright wallpapers without needing
    # a solid panel behind the playfield.
    block_glow: bool = False


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

NEON = Theme(
    name='neon',
    block_colors=COLORS_NEON,
    # bg_rgb / bg_alpha unused for neon — keeping the floating-on-desktop
    # aesthetic. Per-block shadows in _draw_cell_neon provide local contrast
    # against bright wallpapers without painting a panel.
    bg_rgb=(10, 8, 30),
    bg_alpha=0,
    ghost_alpha=60,
    particle_life_ms=600,
    particle_speed=2.8,
    particle_count=22,
    score_rgb=(255, 80, 220),             # hot magenta
    multiplier_low_rgb=(0, 255, 255),     # cyan at idle
    multiplier_high_rgb=(255, 80, 220),   # magenta at full burn
    text_glow=True,
    block_glow=True,
)


ORDER = ('ambient', 'vivid', 'neon')
_BY_NAME = {AMBIENT.name: AMBIENT, VIVID.name: VIVID, NEON.name: NEON}


def get(name: str) -> Theme:
    return _BY_NAME.get(name, AMBIENT)
