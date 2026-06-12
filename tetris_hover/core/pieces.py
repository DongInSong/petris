"""Piece definitions, SRS rotation states, and wall kick tables."""
from typing import Dict, List, Tuple

Mino = Tuple[int, int]  # (dx, dy) within piece bounding box

KINDS = ('I', 'O', 'T', 'S', 'Z', 'J', 'L')

# Minos per rotation state 0, 1 (R), 2, 3 (L). (dx, dy) with y down.
SHAPES: Dict[str, List[List[Mino]]] = {
    'I': [
        [(0, 1), (1, 1), (2, 1), (3, 1)],
        [(2, 0), (2, 1), (2, 2), (2, 3)],
        [(0, 2), (1, 2), (2, 2), (3, 2)],
        [(1, 0), (1, 1), (1, 2), (1, 3)],
    ],
    'O': [
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (2, 1)],
    ],
    'T': [
        [(1, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (1, 2)],
        [(1, 0), (0, 1), (1, 1), (1, 2)],
    ],
    'S': [
        [(1, 0), (2, 0), (0, 1), (1, 1)],
        [(1, 0), (1, 1), (2, 1), (2, 2)],
        [(1, 1), (2, 1), (0, 2), (1, 2)],
        [(0, 0), (0, 1), (1, 1), (1, 2)],
    ],
    'Z': [
        [(0, 0), (1, 0), (1, 1), (2, 1)],
        [(2, 0), (1, 1), (2, 1), (1, 2)],
        [(0, 1), (1, 1), (1, 2), (2, 2)],
        [(1, 0), (0, 1), (1, 1), (0, 2)],
    ],
    'J': [
        [(0, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (2, 0), (1, 1), (1, 2)],
        [(0, 1), (1, 1), (2, 1), (2, 2)],
        [(1, 0), (1, 1), (0, 2), (1, 2)],
    ],
    'L': [
        [(2, 0), (0, 1), (1, 1), (2, 1)],
        [(1, 0), (1, 1), (1, 2), (2, 2)],
        [(0, 1), (1, 1), (2, 1), (0, 2)],
        [(0, 0), (1, 0), (1, 1), (1, 2)],
    ],
}

# SRS wall kick tables. Keys: (from_rot, to_rot). Values: list of (dx, dy) tests.
# Original SRS uses y-up; these are converted to y-down (dy sign flipped).
KICKS_JLSTZ: Dict[Tuple[int, int], List[Mino]] = {
    (0, 1): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (1, 0): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (1, 2): [(0, 0), (1, 0), (1, 1), (0, -2), (1, -2)],
    (2, 1): [(0, 0), (-1, 0), (-1, -1), (0, 2), (-1, 2)],
    (2, 3): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
    (3, 2): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (3, 0): [(0, 0), (-1, 0), (-1, 1), (0, -2), (-1, -2)],
    (0, 3): [(0, 0), (1, 0), (1, -1), (0, 2), (1, 2)],
}

KICKS_I: Dict[Tuple[int, int], List[Mino]] = {
    (0, 1): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    (1, 0): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    (1, 2): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
    (2, 1): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    (2, 3): [(0, 0), (2, 0), (-1, 0), (2, -1), (-1, 2)],
    (3, 2): [(0, 0), (-2, 0), (1, 0), (-2, 1), (1, -2)],
    (3, 0): [(0, 0), (1, 0), (-2, 0), (1, 2), (-2, -1)],
    (0, 3): [(0, 0), (-1, 0), (2, 0), (-1, -2), (2, 1)],
}


def get_kicks(kind: str, from_rot: int, to_rot: int) -> List[Mino]:
    if kind == 'O':
        return [(0, 0)]
    table = KICKS_I if kind == 'I' else KICKS_JLSTZ
    return table[(from_rot, to_rot)]


# Candy-arcade palette (vivid theme): guideline hues, pulled off the pure
# 240-primaries toward richer sweets — these sit under a gloss gradient, so
# slightly deeper bases keep the candy from washing out.
COLORS_VIVID: Dict[str, Tuple[int, int, int]] = {
    'I': (0, 196, 255),     # bubblegum cyan
    'O': (255, 204, 0),     # lemon drop
    'T': (186, 64, 255),    # grape
    'S': (54, 214, 80),     # lime candy
    'Z': (255, 70, 92),     # strawberry
    'J': (64, 110, 255),    # blue raspberry
    'L': (255, 144, 32),    # orange cream
}

# Low-saturation pastel (ambient theme)
COLORS_AMBIENT: Dict[str, Tuple[int, int, int]] = {
    'I': (160, 210, 220),
    'O': (225, 215, 160),
    'T': (200, 170, 220),
    'S': (170, 215, 180),
    'Z': (220, 170, 175),
    'J': (175, 185, 220),
    'L': (220, 195, 165),
}

# Saturated neon/cyberpunk palette: cyan + magenta dominate, hot lime + electric
# blue accents. Designed to glow on the dark backdrop, not blend with desktop.
COLORS_NEON: Dict[str, Tuple[int, int, int]] = {
    'I': (0, 255, 255),
    'O': (255, 235, 80),
    'T': (255, 60, 200),
    'S': (80, 255, 100),
    'Z': (255, 60, 100),
    'J': (80, 130, 255),
    'L': (255, 130, 30),
}

# Frosted-ice palette (aurora theme): cool and luminous but with enough
# body that the translucent glass doesn't wash out over light wallpapers.
COLORS_AURORA: Dict[str, Tuple[int, int, int]] = {
    'I': (88, 196, 240),    # glacier cyan
    'O': (235, 210, 130),   # low-sun gold
    'T': (168, 122, 244),   # auroral violet
    'S': (104, 224, 164),   # polar mint
    'Z': (244, 116, 158),   # arctic rose
    'J': (116, 148, 246),   # twilight periwinkle
    'L': (246, 166, 104),   # horizon peach
}

# Game Boy DMG palette (retro theme): every piece is LCD ink. Three shades
# only so the board stays authentically monochrome; pieces read by shape.
COLORS_RETRO: Dict[str, Tuple[int, int, int]] = {
    'I': (15, 56, 15),      # darkest ink
    'O': (15, 56, 15),
    'T': (15, 56, 15),
    'S': (48, 98, 48),      # mid ink
    'Z': (48, 98, 48),
    'J': (27, 76, 27),      # deep ink
    'L': (27, 76, 27),
}

BOARD_W = 10
BOARD_H = 20
BUFFER = 4
TOTAL_H = BOARD_H + BUFFER

SPAWN_COL = 3
SPAWN_ROW = 2
