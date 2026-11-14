"""Draw the channel's profile picture, banner and video watermark with code: python channel_art.py

Sizes follow YouTube Help, "Manage your channel branding". The banner's name and tagline stay
inside the area every device shows, and only decoration runs past it.
"""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from studio.config import CHANNEL_NAME, ROOT
from studio.media.thumbnails import AMBER, CREAM, INK, NAVY_BOTTOM, NAVY_TOP, TEAL
from studio.media.visuals import HEAVY, SERIF, _draw_professor, font

OUT = ROOT / "assets" / "channel"
PROFILE = (800, 800)
WATERMARK = (150, 150)
BANNER = (2560, 1440)
# YouTube's safe area is 1235 x 338 at 2048 wide, which is 1544 x 423 at 2560.
SAFE = (508, 509, 2052, 931)
TAGLINE = "You've seen the highlight. Here's what actually happened."
CHALK = (58, 74, 104)


def _badge(base: float, size: float) -> Image.Image:
    """The Professor inside an amber ring, drawn large so shrinking it leaves clean edges."""
    img = Image.new("RGB", (PROFILE[0] * 2, PROFILE[1] * 2), AMBER)
    d = ImageDraw.Draw(img)
    w, h = img.size
    d.ellipse((w * 0.04, h * 0.04, w * 0.96, h * 0.96), fill=NAVY_TOP)
    _draw_professor(d, w / 2, h * base, size)
    return img


def _ring(img: Image.Image) -> Image.Image:
    """Everything past the ring goes, since YouTube crops to a circle anyway."""
    w, h = img.size
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).ellipse((w * 0.04, h * 0.04, w * 0.96, h * 0.96), fill=255)
    return Image.composite(img, Image.new("RGB", img.size, AMBER), mask)


def face() -> Image.Image:
    """Just the Professor, for sizes too small to carry words."""
    return _ring(_badge(1.31, 3.2)).resize(PROFILE, Image.LANCZOS)


def profile() -> Image.Image:
    """The Professor above the channel name, on an amber band that runs into the ring."""
    img = _badge(0.85, 2.0)
    d = ImageDraw.Draw(img)
    w, _ = img.size
    top = 915
    d.rectangle((0, top, w, img.height), fill=AMBER)
    lines = ["THE ATHLETICS", "ARCHIVE"]
    size = 300
    while d.textlength(lines[0], font=font(HEAVY, size)) > w * 0.8:
        size -= 2
    f = font(HEAVY, size)
    for line, y in zip(lines, (top + 170, top + 170 + size * 1.02)):
        d.text((w / 2, y), line, font=f, fill=INK, anchor="mm")
    return _ring(img).resize(PROFILE, Image.LANCZOS)


def watermark() -> Image.Image:
    """The same face at YouTube's watermark size, see-through outside the circle so it sits on any slide."""
    img = face().convert("RGBA")
    mask = Image.new("L", (PROFILE[0] * 2, PROFILE[1] * 2), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, mask.width - 1, mask.height - 1), fill=255)
    img.putalpha(mask.resize(PROFILE, Image.LANCZOS))
    return img.resize(WATERMARK, Image.LANCZOS)


def _rows(d, x0: int, x1: int, base: int, seed: int) -> None:
    """Rising bars: the channel's charts as decoration, with no real numbers to misread."""
    rng = random.Random(seed)
    x = x0
    height = 60
    while x < x1:
        height = min(height + rng.randint(10, 46), 460)
        d.rounded_rectangle((x, base - height, x + 54, base), radius=8, fill=CHALK)
        x += 82


def _marks(d, box: tuple[int, int, int, int], seed: int) -> None:
    """Chalkboard X's and O's, for the film-room feel."""
    rng = random.Random(seed)
    x0, y0, x1, y1 = box
    for _ in range(12):
        x, y, s = rng.uniform(x0, x1), rng.uniform(y0, y1), 26
        if rng.random() < 0.5:
            d.line((x - s, y - s, x + s, y + s), fill=CHALK, width=8)
            d.line((x - s, y + s, x + s, y - s), fill=CHALK, width=8)
        else:
            d.ellipse((x - s, y - s, x + s, y + s), outline=CHALK, width=8)


def banner() -> Image.Image:
    w, h = BANNER
    img = Image.new("RGB", BANNER)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line((0, y, w, y), fill=tuple(int(a + (b - a) * t) for a, b in zip(NAVY_TOP, NAVY_BOTTOM)))
    glow = Image.new("L", BANNER, 0)
    ImageDraw.Draw(glow).ellipse((w * 0.2, h * 0.2, w * 0.8, h * 0.8), fill=70)
    img.paste((70, 92, 150), (0, 0), glow.filter(ImageFilter.GaussianBlur(170)))
    d = ImageDraw.Draw(img)

    # Decoration lives outside the safe area: TVs and desktops show it, phones crop it away.
    x0, y0, x1, y1 = SAFE
    desk = y1 + 4
    _rows(d, 40, x0 - 70, desk, 3)
    _marks(d, (x1 + 90, y0 - 60, w - 60, desk - 60), 5)
    _marks(d, (60, 60, w - 60, y0 - 90), 8)

    # The Professor stands behind the desk, inside the safe area.
    s = 0.62
    cx = x1 - 215
    _draw_professor(d, cx, desk + 26 * s, s)
    d.rectangle((0, desk, w, h), fill=INK)
    d.rectangle((0, desk, w, desk + 10), fill=AMBER)
    _marks(d, (60, desk + 70, w - 60, h - 60), 11)  # only TVs show this far down

    # The name, as large as fits beside him, then the promise.
    x0 += 40  # breathing room where phones crop
    room = cx - 215 - x0
    size = 200
    while d.textlength(CHANNEL_NAME.upper(), font=font(HEAVY, size)) > room:
        size -= 2
    title_y = y0 + 58
    d.text((x0 + 8, title_y + 6), CHANNEL_NAME.upper(), font=font(HEAVY, size), fill=INK)
    d.text((x0, title_y), CHANNEL_NAME.upper(), font=font(HEAVY, size), fill=CREAM)
    line_y = title_y + size + 26
    d.rectangle((x0, line_y, x0 + 150, line_y + 10), fill=AMBER)
    tag = size
    while d.textlength(TAGLINE, font=font(SERIF, tag)) > room:
        tag -= 1
    d.text((x0, line_y + 40), TAGLINE, font=font(SERIF, tag), fill=TEAL)
    return img


def checks(profile_img: Image.Image, banner_img: Image.Image, out: Path) -> Path:
    """How both look on real surfaces: the tiny circle, then the banner on TV, desktop and phone."""
    sheet = Image.new("RGB", (1600, 1260), (30, 30, 34))
    x = 20
    for size in (176, 98, 48):
        tile = profile_img.resize((size, size), Image.LANCZOS)
        mask = Image.new("L", (size * 4, size * 4), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size * 4, size * 4), fill=255)
        sheet.paste(tile, (x, 20), mask.resize((size, size), Image.LANCZOS))
        x += size + 24
    mark = watermark()
    for shade, offset in (((245, 245, 245), 0), ((13, 18, 27), 170)):  # on light and on dark slides
        back = Image.new("RGB", (150, 150), shade)
        back.paste(mark, (0, 0), mark)
        sheet.paste(back, (x + offset, 20))
    sheet.paste(banner_img.resize((800, 450), Image.LANCZOS), (20, 220))  # TV: the whole image
    desktop = banner_img.crop((0, 508, 2560, 932))
    sheet.paste(desktop.resize((1560, int(1560 * 424 / 2560)), Image.LANCZOS), (20, 690))
    phone = banner_img.crop(SAFE)
    sheet.paste(phone.resize((1000, int(1000 * 422 / 1544)), Image.LANCZOS), (20, 970))
    sheet.save(out)
    return out


if __name__ == "__main__":
    import sys

    OUT.mkdir(parents=True, exist_ok=True)
    p, b = profile(), banner()
    watermark().save(OUT / "watermark.png", optimize=True)
    p.save(OUT / "profile.png", optimize=True)
    b.save(OUT / "banner.png", optimize=True)
    checks(p, b, Path(sys.argv[1]) if len(sys.argv) > 1 else OUT / "checks.png")
    for name in ("profile.png", "banner.png", "watermark.png"):
        print(name, round((OUT / name).stat().st_size / 1_000_000, 2), "MB")
