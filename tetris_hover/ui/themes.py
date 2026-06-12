"""Theme presets.

    ambient — pastel, low-key; the default. Beveled blocks, square particles.
    vivid   — arcade candy: glossy rounded blocks, confetti bursts.
    neon    — cyberpunk glow: lit-tube blocks, velocity sparks.
    aurora  — frosted glass: translucent icy blocks, drifting orbs.
    retro   — Game Boy LCD: pea-green panel, monochrome blocks, pixel dust.

Visual identity per theme is carried by four style switches consumed by
BoardView/EffectLayer: block_style, ghost_style, particle_style, panel.
"""
from dataclasses import dataclass
from typing import Dict, Tuple

from ..core.pieces import (
    COLORS_AMBIENT,
    COLORS_AURORA,
    COLORS_NEON,
    COLORS_RETRO,
    COLORS_VIVID,
)


RGB = Tuple[int, int, int]


@dataclass(frozen=True)
class Theme:
    name: str
    block_colors: Dict[str, RGB]
    bg_alpha: int  # panel alpha when panel=True (unused otherwise)
    bg_rgb: RGB
    ghost_alpha: int
    particle_life_ms: int
    particle_speed: float
    particle_count: int
    # Score / multiplier overlay styling. Defaults match ambient; neon
    # overrides text_glow=True to render a colored halo around a lit core.
    score_rgb: RGB = (255, 255, 255)
    multiplier_low_rgb: RGB = (120, 230, 255)   # at multiplier ≈ 1.0
    multiplier_high_rgb: RGB = (255, 160, 60)   # at multiplier ≈ 8.0
    text_outline_rgb: RGB = (0, 0, 0)
    text_glow: bool = False
    # Block rendering style: 'bevel' (flat fill + 2px bevel edges),
    # 'candy' (glossy rounded gradient), 'neon' (dark tube + bloom),
    # 'glass' (translucent frosted), 'lcd' (solid monochrome pixel).
    block_style: str = 'bevel'
    # Ghost piece: 'fill' (faint solid) or 'outline' (hollow frame).
    ghost_style: str = 'fill'
    # Particle shape: 'square', 'confetti', 'spark', 'orb'.
    particle_style: str = 'square'
    # Paint a rounded backdrop panel (bg_rgb @ bg_alpha) behind the playfield.
    # Only retro uses it — every other theme floats on the desktop.
    panel: bool = False


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
    bg_alpha=0,
    bg_rgb=(10, 10, 20),
    ghost_alpha=80,
    particle_life_ms=620,
    particle_speed=3.2,
    particle_count=26,
    score_rgb=(255, 226, 92),              # arcade marquee yellow
    multiplier_low_rgb=(110, 210, 255),
    multiplier_high_rgb=(255, 92, 160),
    text_outline_rgb=(30, 16, 40),
    block_style='candy',
    ghost_style='outline',
    particle_style='confetti',
)

NEON = Theme(
    name='neon',
    block_colors=COLORS_NEON,
    # bg unused — floating-on-desktop aesthetic. Per-block shadow halos in
    # the renderer provide local contrast against bright wallpapers.
    bg_rgb=(10, 8, 30),
    bg_alpha=0,
    ghost_alpha=110,
    particle_life_ms=480,
    particle_speed=3.6,
    particle_count=20,
    score_rgb=(255, 80, 220),             # hot magenta
    multiplier_low_rgb=(0, 255, 255),     # cyan at idle
    multiplier_high_rgb=(255, 80, 220),   # magenta at full burn
    text_glow=True,
    block_style='neon',
    ghost_style='outline',
    particle_style='spark',
)

AURORA = Theme(
    name='aurora',
    block_colors=COLORS_AURORA,
    bg_alpha=0,
    bg_rgb=(16, 24, 40),
    ghost_alpha=110,
    particle_life_ms=950,
    particle_speed=1.0,
    particle_count=14,
    score_rgb=(235, 245, 255),            # moonlight white
    multiplier_low_rgb=(150, 220, 255),
    multiplier_high_rgb=(255, 170, 220),
    text_outline_rgb=(20, 40, 70),
    block_style='glass',
    ghost_style='outline',
    particle_style='orb',
)

RETRO = Theme(
    name='retro',
    block_colors=COLORS_RETRO,
    # The pale LCD panel is the theme — blocks sit on it like a real DMG.
    bg_rgb=(154, 187, 27),
    bg_alpha=216,
    ghost_alpha=44,
    particle_life_ms=420,
    particle_speed=1.6,
    particle_count=8,
    score_rgb=(15, 56, 15),               # darkest LCD ink
    multiplier_low_rgb=(48, 98, 48),
    multiplier_high_rgb=(15, 56, 15),
    text_outline_rgb=(154, 187, 27),
    block_style='lcd',
    ghost_style='fill',
    particle_style='square',
    panel=True,
)


ORDER = ('ambient', 'vivid', 'neon', 'aurora', 'retro')
_BY_NAME = {t.name: t for t in (AMBIENT, VIVID, NEON, AURORA, RETRO)}


def get(name: str) -> Theme:
    return _BY_NAME.get(name, AMBIENT)
