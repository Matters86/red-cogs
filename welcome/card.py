"""Begrüßungskarte als PNG (Pillow) – reine, blockierende Funktionen.

Aufrufer führen ``render_card`` / ``prepare_background`` immer über
``asyncio.to_thread`` aus. Schriften liegen in ``assets/fonts`` (Archivo + IBM Plex,
SIL OFL 1.1 – dieselben wie beim Organigram); fehlen sie, gibt es Pillows
Standardschrift.
"""

from __future__ import annotations

import io
import os
import unicodedata
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

W, H = 1000, 400                 # Kartengröße (Discord zeigt ~ 400–550 px breit)
AVATAR = 176                     # Avatar-Durchmesser
MAX_BG_BYTES = 8 * 1024 * 1024  # Download-Limit für Hintergrundbilder (Bild-URL)
MAX_BG_SIDE = 6000
MIN_BG_W, MIN_BG_H = 300, 120
ALLOWED_FORMATS = {"PNG": "PNG", "JPEG": "JPEG", "WEBP": "WebP", "GIF": "GIF"}

_HERE = os.path.dirname(os.path.abspath(__file__))
_FONT_DIRS = (
    os.path.join(_HERE, "assets", "fonts"),
    os.path.join(_HERE, "..", "organigram", "assets", "fonts"),
)
FONT_HEAD = "Archivo-ExtraBold.ttf"
FONT_NAME = "Archivo-Bold.ttf"
FONT_TEXT = "IBMPlexSans-SemiBold.ttf"


class BackgroundError(ValueError):
    """Hintergrundbild ist ungültig/nicht ladbar (Text = deutsche Begründung)."""


# --------------------------------------------------------------------------- #
#  Schriften
# --------------------------------------------------------------------------- #
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
    except TypeError:  # ältere Pillow-Versionen
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


def _text_w(draw, text, font, spacing=0) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return (box[2] - box[0]) + spacing * max(0, len(text) - 1)


def _fit(draw, text, name, size, min_size, max_w):
    """Schriftgröße verkleinern, bis ``text`` passt; sonst mit „…“ kürzen."""
    s = size
    while s > min_size and _text_w(draw, text, _font(name, s)) > max_w:
        s -= 2
    font = _font(name, s)
    if _text_w(draw, text, font) <= max_w:
        return text, font
    while text and _text_w(draw, text + "…", font) > max_w:
        text = text[:-1]
    return (text.rstrip() + "…") if text else "…", font


# --------------------------------------------------------------------------- #
#  Farben / Hintergrund
# --------------------------------------------------------------------------- #
def hex_rgb(value: str, default=(61, 220, 151)) -> tuple[int, int, int]:
    v = str(value or "").strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except (ValueError, IndexError):
        return default


def _gradient(c1, c2) -> Image.Image:
    """Diagonaler Verlauf von ``c1`` (oben links) nach ``c2`` (unten rechts)."""
    horiz = Image.linear_gradient("L").rotate(90, expand=True).transpose(Image.FLIP_LEFT_RIGHT).resize((W, H))
    vert = Image.linear_gradient("L").resize((W, H))
    mask = Image.blend(horiz, vert, 0.35)
    return Image.composite(Image.new("RGB", (W, H), c2), Image.new("RGB", (W, H), c1), mask)


def _cover(img: Image.Image, size=(W, H)) -> Image.Image:
    return ImageOps.fit(img, size, method=Image.LANCZOS, centering=(0.5, 0.5))


def prepare_background(data: bytes, max_bytes: int = MAX_BG_BYTES) -> bytes:
    """Prüft ein (heruntergeladenes) Bild und liefert es als PNG in Kartengröße.

    Wirft ``BackgroundError`` mit einer deutschen Begründung.
    """
    if not data:
        raise BackgroundError("Die Datei ist leer.")
    if len(data) > max_bytes:
        raise BackgroundError(f"Die Datei ist zu groß ({len(data) // 1024} KB, max. {max_bytes // 1024} KB).")
    try:
        img = Image.open(io.BytesIO(data))
        fmt = (img.format or "").upper()
    except Exception:  # noqa: BLE001 – alles, was Pillow nicht als Bild erkennt
        raise BackgroundError("Die Datei ist kein unterstütztes Bild (PNG, JPEG, WebP oder GIF).") from None
    if fmt not in ALLOWED_FORMATS:
        raise BackgroundError(f"Format {fmt or 'unbekannt'} wird nicht unterstützt (PNG, JPEG, WebP oder GIF).")
    w, h = img.size
    if w > MAX_BG_SIDE or h > MAX_BG_SIDE:
        raise BackgroundError(f"Das Bild ist zu groß ({w}×{h} px, max. {MAX_BG_SIDE} px je Seite).")
    if w < MIN_BG_W or h < MIN_BG_H:
        raise BackgroundError(f"Das Bild ist zu klein ({w}×{h} px, mind. {MIN_BG_W}×{MIN_BG_H} px).")
    try:
        img.seek(0)
        img.load()
        img = ImageOps.exif_transpose(img) if fmt in ("JPEG", "WEBP") else img
        img = img.convert("RGB")
    except Exception:  # noqa: BLE001 – kaputte/abgeschnittene Datei, Decompression-Bomb …
        raise BackgroundError("Das Bild ist beschädigt und lässt sich nicht lesen.") from None
    out = io.BytesIO()
    _cover(img).save(out, "PNG", optimize=False, compress_level=6)
    return out.getvalue()


def _load_avatar(data: bytes | None) -> Image.Image | None:
    if not data:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.seek(0)
        return img.convert("RGBA")
    except Exception:  # noqa: BLE001 – unlesbares Avatarbild -> Karte ohne Avatar
        return None


def _round(img: Image.Image, size: int) -> Image.Image:
    """Quadratisch zuschneiden und mit geglätteter Kreismaske versehen."""
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


# --------------------------------------------------------------------------- #
#  Karte
# --------------------------------------------------------------------------- #
def render_card(*, name: str, member_line: str, server: str, headline: str,
                avatar: bytes | None = None, background: bytes | None = None,
                color1: str = "#1b2a4a", color2: str = "#3ddc97", text_color: str = "#ffffff",
                fallback_name: str = "Neues Mitglied") -> bytes:
    """Rendert die Begrüßungskarte und gibt PNG-Bytes zurück (``W``×``H``)."""
    txt = hex_rgb(text_color, (255, 255, 255))
    base = None
    if background:
        try:
            base = _cover(Image.open(io.BytesIO(background)).convert("RGB"))
            # Abdunkeln, damit Text auf jedem Foto lesbar bleibt.
            base = Image.blend(base, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
        except Exception:  # noqa: BLE001 – defekte Datei -> Farbverlauf
            base = None
    if base is None:
        base = _gradient(hex_rgb(color1, (27, 42, 74)), hex_rgb(color2, (61, 220, 151)))
        # dezente Deko-Kreise
        deco = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        dd = ImageDraw.Draw(deco)
        dd.ellipse((-120, 220, 260, 600), fill=(255, 255, 255, 18))
        dd.ellipse((780, -160, 1160, 220), fill=(255, 255, 255, 22))
        dd.ellipse((860, 250, 1060, 450), fill=(255, 255, 255, 12))
        base = Image.alpha_composite(base.convert("RGBA"), deco).convert("RGB")
    card = base.convert("RGBA")

    # Avatar mit Ring (oder Platzhalter ohne Avatar)
    ax, ay = (W - AVATAR) // 2, 28
    ring = AVATAR + 12
    card.alpha_composite(_circle(ring, (*txt, 235)), (ax - 6, ay - 6))
    av = _load_avatar(avatar)
    if av is not None:
        card.alpha_composite(_round(av, AVATAR), (ax, ay))
    else:
        card.alpha_composite(_circle(AVATAR, (20, 24, 32, 255)), (ax, ay))
        initial = (clean_text(name) or "?")[0].upper()
        d0 = ImageDraw.Draw(card)
        f0 = _font(FONT_NAME, 84)
        d0.text((W // 2, ay + AVATAR // 2), initial, font=f0, fill=(*txt, 255), anchor="mm")

    # Texte (mit weichem Schatten)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ds = ImageDraw.Draw(shadow)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dl = ImageDraw.Draw(layer)
    max_w = W - 80

    head = clean_text(headline).upper()[:40]
    fh = _font(FONT_HEAD, 26)
    spacing = 6
    hw = _text_w(dl, head, fh, spacing)
    x = (W - hw) // 2
    for ch in head:
        ds.text((x + 1, 228 + 2), ch, font=fh, fill=(0, 0, 0, 150))
        dl.text((x, 228), ch, font=fh, fill=(*txt, 215))
        x += _text_w(dl, ch, fh) + spacing

    nm, fn = _fit(dl, clean_text(name) or fallback_name, FONT_NAME, 54, 28, max_w)
    ds.text((W // 2 + 2, 292 + 3), nm, font=fn, fill=(0, 0, 0, 170), anchor="mm")
    dl.text((W // 2, 292), nm, font=fn, fill=(*txt, 255), anchor="mm")

    sub = " · ".join(p for p in (clean_text(member_line), clean_text(server)) if p)
    sb, fs = _fit(dl, sub, FONT_TEXT, 26, 16, max_w)
    ds.text((W // 2 + 1, 350 + 2), sb, font=fs, fill=(0, 0, 0, 150), anchor="mm")
    dl.text((W // 2, 350), sb, font=fs, fill=(*txt, 225), anchor="mm")

    card.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(3)))
    card.alpha_composite(layer)
    out = io.BytesIO()
    card.convert("RGB").save(out, "PNG", compress_level=6)
    return out.getvalue()
