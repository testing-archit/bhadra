"""Draws the notetaker's camera avatar: a friendly Charcha speech-bubble face
on the night-glow background, idle and speaking. Re-run after a design change:

    python make_avatar.py      # writes assets/avatar_idle.png, assets/avatar_speaking.png
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, S = 640, 360, 3  # drawn at 3x, then downscaled for smooth edges
NIGHT = (14, 12, 31)
CREAM = (250, 247, 241)
INK = (29, 26, 59)
GENDA = (240, 160, 32)
VIOLET = (139, 124, 255)
GULABI = (240, 107, 180)
OUT = Path(__file__).parent / "assets"


def glow(size, box, color, radius, alpha):
    """A soft colour pool: an ellipse in `box`, blurred inside a full-size
    transparent layer so it fades out with no hard edges."""
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse(box, fill=(*color, alpha))
    return layer.filter(ImageFilter.GaussianBlur(radius))


def frame(speaking: bool) -> Image.Image:
    w, h = W * S, H * S
    img = Image.new("RGBA", (w, h), (*NIGHT, 255))
    img.alpha_composite(glow((w, h), (-w // 6, -h // 2, int(w * 0.7), int(h * 0.55)), VIOLET, 220, 120))
    img.alpha_composite(glow((w, h), (int(w * 0.5), int(h * 0.25), int(w * 1.2), int(h * 1.3)), GULABI, 220, 90))
    cx, cy = w // 2, int(h * 0.44)
    d = ImageDraw.Draw(img)
    if speaking:
        for r, a in ((330, 60), (280, 110)):
            ring = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((cx - r, cy - r, cx + r, cy + r), outline=(*GENDA, a), width=18)
            img.alpha_composite(ring.filter(ImageFilter.GaussianBlur(4)))
    # Bubble face with a tail.
    bw, bh = 420, 330
    d.rounded_rectangle((cx - bw // 2, cy - bh // 2, cx + bw // 2, cy + bh // 2), radius=150, fill=CREAM)
    d.polygon([(cx - 120, cy + bh // 2 - 30), (cx - 30, cy + bh // 2 - 10), (cx - 160, cy + bh // 2 + 90)], fill=CREAM)
    # Bindi, eyes, mouth.
    d.ellipse((cx - 22, cy - 120, cx + 22, cy - 76), fill=GENDA)
    for ex in (cx - 78, cx + 78):
        d.ellipse((ex - 22, cy - 40, ex + 22, cy + 10), fill=INK)
        d.ellipse((ex - 8, cy - 30, ex + 4, cy - 18), fill=CREAM)
    if speaking:
        d.ellipse((cx - 46, cy + 40, cx + 46, cy + 110), fill=INK)
        d.ellipse((cx - 26, cy + 78, cx + 26, cy + 104), fill=(232, 96, 110))
    else:
        d.arc((cx - 70, cy + 10, cx + 70, cy + 100), start=20, end=160, fill=INK, width=16)
    # Name tag.
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Kohinoor.ttc", 54, index=4)
    except OSError:
        font = ImageFont.load_default()
    label = "Charcha · AI notetaker"
    tw = d.textlength(label, font=font)
    tag = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(tag).rounded_rectangle((cx - tw / 2 - 36, h - 150, cx + tw / 2 + 36, h - 60), radius=45, fill=(255, 255, 255, 36))
    img.alpha_composite(tag)
    d = ImageDraw.Draw(img)
    d.text((cx - tw / 2, h - 142), label, font=font, fill=CREAM)
    return img.resize((W, H), Image.LANCZOS).convert("RGB")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    frame(False).save(OUT / "avatar_idle.png", optimize=True)
    frame(True).save(OUT / "avatar_speaking.png", optimize=True)
    print("wrote", OUT / "avatar_idle.png", OUT / "avatar_speaking.png")
