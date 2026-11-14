"""Draw Game Day Brain's channel art: python game_day_brain_art.py

The look is the hub's command center (the owner's choice, 2026-11-09): a glowing cyan brain on deep navy.
The brain and mascot pictures were drawn by FLUX.1 schnell on this Mac (assets/game-day-brain/art).
Sizes follow YouTube Help, "Manage your channel branding": the banner's words stay inside the area
every device shows, and only decoration runs past it.
"""
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from studio.config import ROOT
from studio.media.visuals import font

OUT = ROOT / "assets" / "game-day-brain"
ART = OUT / "art"
PROFILE = (800, 800)
WATERMARK = (150, 150)
BANNER = (2560, 1440)
SAFE = (508, 509, 2052, 931)  # YouTube's 1546 x 423 area at 2560 wide
NAVY, DEEP = (4, 14, 30), (1, 6, 14)
CYAN, CYAN_DIM, WHITE, RED = (62, 231, 255), (20, 110, 150), (232, 251, 255), (224, 49, 43)
WIDE = ("/System/Library/Fonts/Avenir Next.ttc", ("Heavy", "Bold"))
BODY = ("/System/Library/Fonts/Avenir Next.ttc", ("Medium", "Regular"))
TAGLINE = "What sports really do to your brain and body"


def _glow(layer: Image.Image, radius: int, strength: float = 1.6) -> Image.Image:
    """A bright copy of the layer, blurred, for a neon halo behind it."""
    halo = layer.filter(ImageFilter.GaussianBlur(radius))
    return Image.eval(halo, lambda p: min(255, int(p * strength)))


def _hud_ring(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, width: int, ticks: int = 72) -> None:
    """A thin glowing ring with tick marks and two bright arcs, like the hub's gauges."""
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=CYAN_DIM, width=max(width // 2, 1))
    for k in range(ticks):
        a = 2 * math.pi * k / ticks
        inner = r - (width * 3 if k % 6 == 0 else width * 1.6)
        d.line((cx + math.cos(a) * inner, cy + math.sin(a) * inner, cx + math.cos(a) * r, cy + math.sin(a) * r), fill=CYAN_DIM, width=max(width // 2, 1))
    d.arc((cx - r, cy - r, cx + r, cy + r), 200, 290, fill=CYAN, width=width)
    d.arc((cx - r, cy - r, cx + r, cy + r), 20, 110, fill=CYAN, width=width)


def _circle(img: Image.Image) -> Image.Image:
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, img.width - 1, img.height - 1), fill=255)
    out = Image.new("RGBA", img.size, (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def profile_holo() -> Image.Image:
    """The glowing brain over its platform, framed by a gauge ring. No words: it shows at 98 px."""
    s = 1600  # drawn large, then shrunk for clean edges
    img = Image.new("RGB", (s, s), DEEP)
    brain = Image.open(ART / "holo-brain.png").convert("RGB").resize((int(s * 0.98), int(s * 0.98)), Image.LANCZOS)
    img.paste(brain, (int(s * 0.01), int(s * 0.06)))
    ring = Image.new("RGB", (s, s), (0, 0, 0))
    _hud_ring(ImageDraw.Draw(ring), s / 2, s / 2, s * 0.47, 10)
    img = Image.composite(Image.new("RGB", (s, s), CYAN), img, _glow(ring.convert("L"), 14, 1.2).point(lambda p: p // 3))
    img.paste(ring, (0, 0), ring.convert("L"))
    return _circle(img.resize(PROFILE, Image.LANCZOS))


def profile_mascot() -> Image.Image:
    """The other option: the videos' mascot, tapping his temple, inside a cyan gauge ring."""
    s = 1600
    img = Image.new("RGB", (s, s), (255, 255, 255))
    face = Image.open(ART / "mascot-idea.png").convert("RGB").resize((int(s * 1.08), int(s * 1.08)), Image.LANCZOS)
    img.paste(face, (int(-s * 0.04), int(s * 0.02)))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, s - 1, s - 1), outline=NAVY, width=int(s * 0.045))  # covers the drawing right to the edge, so nothing leaks past the ring
    _hud_ring(d, s / 2, s / 2, s * 0.46, 10)
    return _circle(img.resize(PROFILE, Image.LANCZOS))


def watermark() -> Image.Image:
    """The video watermark: the brain alone, on a transparent background."""
    return profile_holo().resize(WATERMARK, Image.LANCZOS)


def _spaced(d, xy, text, f, spacing, fill, anchor_center=True):
    """Text with wide letter spacing, centered on x."""
    widths = [d.textlength(ch, font=f) for ch in text]
    total = sum(widths) + spacing * (len(text) - 1)
    x, y = xy
    x = x - total / 2 if anchor_center else x
    for ch, w in zip(text, widths):
        d.text((x, y), ch, font=f, fill=fill)
        x += w + spacing
    return total


def banner() -> Image.Image:
    w, h = BANNER
    img = Image.new("RGB", BANNER, DEEP)
    d = ImageDraw.Draw(img)
    for y in range(h):  # a cyan dawn rising behind the middle
        t = abs(y - h / 2) / (h / 2)
        d.line((0, y, w, y), fill=tuple(int(a + (b - a) * t) for a, b in zip((6, 34, 60), DEEP)))
    for x in range(0, w, 64):  # the hub's grid
        d.line((x, 0, x, h), fill=(10, 34, 54))
    for y in range(0, h, 64):
        d.line((0, y, w, y), fill=(10, 34, 54))
    rng = random.Random(4)
    for _ in range(260):  # sparks, mostly outside the safe area
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        r = rng.choice([1, 1, 2, 3])
        d.ellipse((x - r, y - r, x + r, y + r), fill=(150, 236, 255) if r > 1 else (60, 140, 170))
    cx, cy = SAFE[0] + 300, (SAFE[1] + SAFE[3]) / 2
    halo = Image.new("L", BANNER, 0)
    ImageDraw.Draw(halo).ellipse((cx - 340, cy - 340, cx + 340, cy + 340), fill=120)
    img = Image.composite(Image.new("RGB", BANNER, (14, 120, 170)), img, halo.filter(ImageFilter.GaussianBlur(120)))
    brain = Image.open(ART / "holo-brain.png").convert("RGB").resize((520, 520), Image.LANCZOS)
    box = (int(cx - 260), int(cy - 250), int(cx + 260), int(cy + 270))
    img.paste(ImageChops.lighter(img.crop(box), brain), box[:2])  # light only: the picture's black background disappears
    d = ImageDraw.Draw(img)
    _hud_ring(d, cx, cy, 300, 6, 96)
    d.ellipse((cx - 420, cy - 110, cx + 420, cy + 110), outline=(26, 120, 160), width=3)  # an orbit through the ring

    # The name and tagline, glowing, right of the brain and inside the safe area.
    text = Image.new("L", BANNER, 0)
    td = ImageDraw.Draw(text)
    left = cx + 360
    title_font = font(WIDE, 150)
    span = SAFE[2] - 30 - left
    while td.textlength("GAME DAY BRAIN", font=title_font) + 18 * 13 > span:
        title_font = font(WIDE, title_font.size - 4)
    _spaced(td, (left, cy - 150), "GAME DAY BRAIN", title_font, 18, 255, anchor_center=False)
    glow = _glow(text, 22, 2.2)
    img = Image.composite(Image.new("RGB", BANNER, CYAN), img, glow)
    img.paste(Image.new("RGB", BANNER, WHITE), (0, 0), text)
    d = ImageDraw.Draw(img)
    d.line((left, cy + 34, SAFE[2] - 30, cy + 34), fill=CYAN, width=3)
    d.rectangle((left, cy + 28, left + 140, cy + 40), fill=CYAN)
    for words, kind, size, y, color in ((TAGLINE.upper(), BODY, 44, cy + 64, (170, 225, 245)), ("NEW EXPLAINERS FOR FANS AND PLAYERS", WIDE, 30, cy + 128, CYAN)):
        f = font(kind, size)
        while d.textlength(words, font=f) > span:  # every word stays inside the area phones show
            f = font(kind, f.size - 2)
        d.text((left, y), words, font=f, fill=color)
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    profile_holo().save(OUT / "profile.png", optimize=True)
    profile_mascot().save(OUT / "profile-mascot.png", optimize=True)
    watermark().save(OUT / "watermark.png", optimize=True)
    banner().save(OUT / "banner.png", optimize=True)
    print(f"Wrote the profile pictures, watermark and banner to {OUT}")


if __name__ == "__main__":
    main()
