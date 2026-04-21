"""Generate petris.ico — a minimal mint ㄴ-piece on a transparent canvas."""
from pathlib import Path

from PIL import Image, ImageDraw


SIZE = 1024

# Tetris-flavored mint (close to the I-piece cyan family but warmer).
MINT = (94, 234, 212)
MINT_LIGHT = (140, 244, 224)  # head — slightly lighter so the face block pops
EYE = (14, 40, 50)


def _block(draw: ImageDraw.ImageDraw, x: int, y: int, s: int, rgb: tuple,
           face: bool = False) -> None:
    r, g, b = rgb
    draw.rectangle((x, y, x + s - 1, y + s - 1), fill=(r, g, b, 255))
    # Soft 1-step highlight / shadow for just enough depth at small sizes.
    edge = max(3, s // 24)
    hi = (min(255, r + 28), min(255, g + 20), min(255, b + 18), 255)
    draw.rectangle((x, y, x + s - 1, y + edge), fill=hi)
    draw.rectangle((x, y, x + edge, y + s - 1), fill=hi)
    sh = (max(0, r - 60), max(0, g - 60), max(0, b - 60), 255)
    draw.rectangle((x, y + s - edge, x + s - 1, y + s - 1), fill=sh)
    draw.rectangle((x + s - edge, y, x + s - 1, y + s - 1), fill=sh)
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
