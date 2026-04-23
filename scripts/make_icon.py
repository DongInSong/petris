"""Generate petris.ico — a minimal mint ㄴ-piece on a transparent canvas."""
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = 1024

# Deepened teal (V dropped from ~92% to ~70%) so the icon doesn't glare on
# light-mode taskbars while still reading as the same piece family.
MINT = (64, 176, 156)
MINT_LIGHT = (96, 204, 180)   # head — slightly lighter so the face block pops
EYE = (16, 42, 52)
# Dark outline around each block. Gives edge definition against both
# near-white (taskbar/browser) and near-black (dark taskbar) backgrounds.
OUTLINE = (20, 52, 58)


def _block(draw: ImageDraw.ImageDraw, x: int, y: int, s: int, rgb: tuple,
           face: bool = False) -> None:
    r, g, b = rgb
    ow = max(1, s // 40)
    # Outline first, then inset fill.
    draw.rectangle((x, y, x + s - 1, y + s - 1), fill=OUTLINE + (255,))
    ix0, iy0 = x + ow, y + ow
    ix1, iy1 = x + s - 1 - ow, y + s - 1 - ow
    draw.rectangle((ix0, iy0, ix1, iy1), fill=(r, g, b, 255))
    # Soft 1-step highlight / shadow inside the inset for just enough depth at small sizes.
    edge = max(2, s // 28)
    hi = (min(255, r + 30), min(255, g + 22), min(255, b + 20), 255)
    draw.rectangle((ix0, iy0, ix1, iy0 + edge), fill=hi)
    draw.rectangle((ix0, iy0, ix0 + edge, iy1), fill=hi)
    sh = (max(0, r - 45), max(0, g - 40), max(0, b - 36), 255)
    draw.rectangle((ix0, iy1 - edge, ix1, iy1), fill=sh)
    draw.rectangle((ix1 - edge, iy0, ix1, iy1), fill=sh)
    if face:
        ez = max(4, s // 8)
        ey = y + int(s * 0.38)
        e1 = x + int(s * 0.26)
        e2 = x + int(s * 0.74) - ez
        draw.rectangle((e1, ey, e1 + ez, ey + ez), fill=EYE)
        draw.rectangle((e2, ey, e2 + ez, ey + ez), fill=EYE)


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Four blocks in ㄴ / J shape — 3 across, 1 on top-left.
    bs = int(size * 0.32)
    gap = max(2, size // 180)
    total_w = bs * 3 + gap * 2
    total_h = bs * 2 + gap
    ox = (size - total_w) // 2
    oy = (size - total_h) // 2

    # Bottom row (three blocks)
    row_y = oy + bs + gap
    _block(d, ox, row_y, bs, MINT)
    _block(d, ox + bs + gap, row_y, bs, MINT)
    _block(d, ox + 2 * (bs + gap), row_y, bs, MINT)
    # Head (top of the leftmost column)
    _block(d, ox, oy, bs, MINT_LIGHT, face=True)

    return img


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "petris.ico"
    preview = out.with_suffix(".png")
    base = make_icon(SIZE)
    base.save(preview, "PNG")
    sizes = [256, 128, 64, 48, 32, 24, 16]
    base.resize((256, 256), Image.LANCZOS).save(
        out, format="ICO", sizes=[(s, s) for s in sizes]
    )
    print(f"wrote {out} ({out.stat().st_size} bytes)")
    print(f"wrote {preview} ({preview.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
