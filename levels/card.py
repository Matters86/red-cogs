"""Rangkarte als PNG (Pillow) – reine, blockierende Funktionen.

Aufrufer führen ``render_rank_card`` immer über ``asyncio.to_thread`` aus. Stil und Schriften wie
beim Willkommensbild (welcome/card.py): Archivo + IBM Plex (SIL OFL 1.1) liegen als Kopie in
``assets/fonts``, damit der Cog eigenständig ist; fehlen sie, gibt es Pillows Standardschrift.
"""

from __future__ import annotations

import io
import os
import unicodedata
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 934, 282
AVATAR = 180

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIRS = (os.path.join(_HERE, "assets", "fonts"),)
FONT_HEAD = "Archivo-ExtraBold.ttf"
FONT_NAME = "Archivo-Bold.ttf"
FONT_TEXT = "IBMPlexSans-SemiBold.ttf"

BG1 = (18, 23, 29)
BG2 = (33, 40, 53)
MUTED = (139, 151, 167)
TEXT = (230, 237, 243)
TRACK = (46, 56, 69)


@lru_cache(maxsize=64)
def _font(name: str, size: int):
    for d in _FONT_DIRS:
        path = os.path.normpath(os.path.join(d, name))
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    try:  # Pillow >= 10.1: skalierbare Standardschrift
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def fonts_available() -> bool:
    return any(os.path.isfile(os.path.join(d, FONT_NAME)) for d in _FONT_DIRS)


def clean_text(text: str) -> str:
    """Entfernt Zeichen, die die Schriften nicht darstellen (Emojis, Steuerzeichen, ZWJ …)."""
    out = []
    for ch in unicodedata.normalize("NFC", str(text or "")):
        cat = unicodedata.category(ch)
        if cat in ("So", "Cs", "Co", "Cn", "Cc", "Cf", "Mn", "Sk") or 0xFE00 <= ord(ch) <= 0xFE0F:
            continue
        out.append(ch)
    return " ".join("".join(out).split())


def hex_rgb(value: str, default=(61, 220, 151)) -> tuple[int, int, int]:
    v = str(value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except (ValueError, IndexError):
        return default


def _text_w(draw, text, font) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _fit(draw, text, name, size, min_size, max_w):
    s = size
    while s > min_size and _text_w(draw, text, _font(name, s)) > max_w:
        s -= 2
    font = _font(name, s)
    if _text_w(draw, text, font) <= max_w:
        return text, font
    while text and _text_w(draw, text + "…", font) > max_w:
        text = text[:-1]
    return (text.rstrip() + "…") if text else "…", font


def _load_avatar(data: bytes | None):
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.seek(0)
        return img.convert("RGBA")
    except Exception:  # noqa: BLE001 – unlesbares Avatarbild -> Platzhalter
        return None


def _round(img: Image.Image, size: int) -> Image.Image:
    img = ImageOps.fit(img, (size, size), method=Image.LANCZOS)
    big = Image.new("L", (size * 4, size * 4), 0)
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=255)
    mask = big.resize((size, size), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _circle(size: int, fill) -> Image.Image:
    big = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    ImageDraw.Draw(big).ellipse((0, 0, size * 4 - 1, size * 4 - 1), fill=fill)
    return big.resize((size, size), Image.LANCZOS)


def _num(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def render_rank_card(*, name: str, level: int, rank: int | None, xp_into: int, xp_needed: int, total_xp: int,
                     server: str = "", avatar: bytes | None = None, accent: str = "#3ddc97",
                     labels: dict | None = None) -> bytes:
    """Rendert die Rangkarte (``W``×``H``) und gibt PNG-Bytes zurück.

    ``labels``: übersetzte Beschriftungen ``level``, ``rank``, ``xp`` (mit {into}/{needed}), ``total`` (mit {total}).
    """
    lb = {"level": "LEVEL", "rank": "RANG", "xp": "{into} / {needed} XP", "total": "{total} XP gesamt"}
    lb.update(labels or {})
    acc = hex_rgb(accent)
    # Hintergrund: dunkler Verlauf + weicher Akzent-Schein
    grad = Image.linear_gradient("L").rotate(90, expand=True).resize((W, H))
    card = Image.composite(Image.new("RGB", (W, H), BG2), Image.new("RGB", (W, H), BG1), grad).convert("RGBA")
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-140, -160, 360, 340), fill=(*acc, 70))
    ImageDraw.Draw(glow).ellipse((700, 170, 1060, 470), fill=(*acc, 30))
    card.alpha_composite(glow.filter(ImageFilter.GaussianBlur(60)))

    # Avatar mit Akzent-Ring
    ax, ay = 42, (H - AVATAR) // 2
    card.alpha_composite(_circle(AVATAR + 12, (*acc, 255)), (ax - 6, ay - 6))
    av = _load_avatar(avatar)
    if av is not None:
        card.alpha_composite(_round(av, AVATAR), (ax, ay))
    else:
        card.alpha_composite(_circle(AVATAR, (20, 24, 32, 255)), (ax, ay))
        d0 = ImageDraw.Draw(card)
        d0.text((ax + AVATAR // 2, ay + AVATAR // 2), (clean_text(name) or "?")[0].upper(),
                font=_font(FONT_NAME, 84), fill=(*TEXT, 255), anchor="mm")

    d = ImageDraw.Draw(card)
    left = ax + AVATAR + 40          # 262
    right = W - 40

    # Rang / Level rechts oben: kleine Beschriftung + große Zahl
    f_lab = _font(FONT_TEXT, 20)
    f_big = _font(FONT_HEAD, 46)
    x = right
    parts = [(lb["level"], str(int(level)), acc)]
    parts.append((lb["rank"], f"#{rank}" if rank else "–", TEXT))
    for label, value, color in parts:
        vw = _text_w(d, value, f_big)
        d.text((x - vw, 30), value, font=f_big, fill=(*color, 255))
        x -= vw + 10
        lw = _text_w(d, label, f_lab)
        d.text((x - lw, 52), label, font=f_lab, fill=(*MUTED, 255))
        x -= lw + 28
    stats_left = x

    # Name (links, bis vor die Kennzahlen)
    nm, fn = _fit(d, clean_text(name) or "?", FONT_NAME, 40, 22, max(120, stats_left - left - 10))
    d.text((left, 104), nm, font=fn, fill=(*TEXT, 255), anchor="ls")
    srv, fs = _fit(d, clean_text(server), FONT_TEXT, 20, 14, right - left)
    if srv:
        d.text((left, 136), srv, font=fs, fill=(*MUTED, 255), anchor="ls")

    # Fortschrittsbalken
    bar_y, bar_h = 176, 34
    d.rounded_rectangle((left, bar_y, right, bar_y + bar_h), radius=bar_h // 2, fill=(*TRACK, 255))
    ratio = 0.0 if xp_needed <= 0 else max(0.0, min(1.0, xp_into / xp_needed))
    if ratio > 0:
        fill_w = max(bar_h, int((right - left) * ratio))
        d.rounded_rectangle((left, bar_y, left + fill_w, bar_y + bar_h), radius=bar_h // 2, fill=(*acc, 255))
    f_small = _font(FONT_TEXT, 20)
    xp_txt = lb["xp"].format(into=_num(xp_into), needed=_num(xp_needed))
    d.text((right, bar_y - 10), xp_txt, font=f_small, fill=(*TEXT, 255), anchor="rs")
    d.text((left, bar_y + bar_h + 30), lb["total"].format(total=_num(total_xp)), font=f_small,
           fill=(*MUTED, 255), anchor="ls")

    out = io.BytesIO()
    card.convert("RGB").save(out, "PNG", compress_level=6)
    return out.getvalue()
