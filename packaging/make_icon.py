"""Regenerate the app icon (packaging/icon.icns, icon.ico, icon.png). macOS only: uses the
system New York font. Run with Pillow installed: python packaging/make_icon.py"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SIZE = 1024
INK, PAPER, MARK, RULE = (24, 32, 44), (243, 245, 248), (255, 226, 90), (221, 226, 233)


def draw() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = 100  # macOS icon grid: artwork inset from the canvas edge
    d.rounded_rectangle((pad, pad, SIZE - pad, SIZE - pad), radius=185, fill=PAPER, outline=RULE, width=6)
    font = ImageFont.truetype("/System/Library/Fonts/NewYork.ttf", 760)
    try:
        font.set_variation_by_name("Bold")
    except (OSError, ValueError):
        pass
    text = "v"
    l, t, r, b = d.textbbox((0, 0), text, font=font)
    x = (SIZE - (r - l)) / 2 - l
    y = (SIZE - (b - t)) / 2 - t - 10
    # Highlighter across the lower part of the letter, the same mark as the UI headwords.
    top = y + t + (b - t) * 0.50
    d.rectangle((x + l - 60, top, x + r + 60, y + b + 10), fill=MARK)
    d.text((x, y), text, font=font, fill=INK)
    return img

if __name__ == "__main__":
    icon = draw()
    icon.save(HERE / "icon.png")
    icon.save(HERE / "icon.icns")
    icon.save(HERE / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("wrote icon.png, icon.icns, icon.ico")
