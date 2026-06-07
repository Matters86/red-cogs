"""Bild-Renderer für den Organigram-Cog.

Erzeugt PNG-Bilder eines Organigramms in fünf Mustern, im Look des
WebCore-Dashboards (dunkel, Akzentgrün, Archivo + IBM Plex). Das Modul ist
bewusst **frei von discord.py** – es bekommt ein aufgelöstes Datenmodell
(``RChart`` mit ``RNode``/``RPerson``) und gibt ``bytes`` zurück. Die
Discord-spezifische Auflösung (Rollen → Mitglieder, Avatare laden) passiert im
Cog.

Gerendert wird intern in doppelter Auflösung (Supersampling) und am Ende sauber
herunterskaliert – das ergibt glatte Kanten bei Linien, Kästen und Avataren.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass, field

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

# --------------------------------------------------------------------------- #
#  Theme (1:1 aus webcore/base.html)
# --------------------------------------------------------------------------- #
BG = (13, 16, 20)          # --bg     #0d1014
PANEL = (21, 26, 33)       # --panel  #151a21
PANEL2 = (27, 33, 43)      # --panel-2#1b212b
BORDER = (37, 44, 55)      # --border #252c37
TEXT = (230, 237, 243)     # --text   #e6edf3
MUTED = (139, 151, 167)    # --muted  #8b97a7
ACCENT = (61, 220, 151)    # --accent #3ddc97

_FONT_DIR = os.path.join(os.path.dirname(__file__), "assets", "fonts")

# Logische Schriftgrößen (werden intern mit SCALE multipliziert).
SCALE = 2

# Wie viele Personen je Knoten maximal gezeigt werden (Rest -> "+N weitere").
MAX_PEOPLE = 7

PATTERNS = {
    "baum": "Baum (oben nach unten)",
    "abteilungen": "Abteilungen (Spalten)",
    "pyramide": "Pyramide (Ebenen)",
    "liste": "Kompaktliste",
    "karten": "Karten",
}


# --------------------------------------------------------------------------- #
#  Datenmodell
# --------------------------------------------------------------------------- #
@dataclass
class RPerson:
    name: str
    avatar_png: bytes | None = None
    vacant: bool = False


@dataclass
class RNode:
    id: str
    label: str
    color: str = "#3ddc97"
    emoji: str = ""
    people: list[RPerson] = field(default_factory=list)
    children: list["RNode"] = field(default_factory=list)
    # vom Layout gefüllt:
    depth: int = 0
    x: float = 0.0
    y: float = 0.0


@dataclass
class RChart:
    title: str
    pattern: str = "baum"
    accent: str = "#3ddc97"
    show_avatars: bool = True
    roots: list[RNode] = field(default_factory=list)
    footer: str = ""


# --------------------------------------------------------------------------- #
#  Hilfen
# --------------------------------------------------------------------------- #
def _hex(value: str | None, fallback=ACCENT) -> tuple[int, int, int]:
    if not value:
        return fallback
    v = value.strip().lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))
    except (ValueError, IndexError):
        return fallback


def _mix(c1, c2, t: float) -> tuple[int, int, int]:
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def _iter_nodes(nodes: list[RNode]):
    for n in nodes:
        yield n
        yield from _iter_nodes(n.children)


# --------------------------------------------------------------------------- #
#  Renderer
# --------------------------------------------------------------------------- #
class _Renderer:
    """Hält Fonts/Skalierung und zeichnet über skalierende Primitive."""

    # Logische Maße
    PAD = 14
    CARD_W = 244
    H_GAP = 26          # horizontaler Abstand zwischen Geschwister-Teilbäumen
    V_GAP = 58          # vertikaler Abstand zwischen Ebenen (Platz für Linien)
    MARGIN = 40
    MAX_PEOPLE = 7
    AV = 22             # Avatar-Durchmesser (logisch)
    LINE_H = 22         # Zeilenhöhe Namen

    def __init__(self, chart: RChart):
        self.chart = chart
        self.S = SCALE
        self._fcache: dict[tuple, ImageFont.FreeTypeFont] = {}

    # ---- Fonts -------------------------------------------------------- #
    def _font(self, key: str, size: int, *, draw: bool) -> ImageFont.FreeTypeFont:
        px = size * (self.S if draw else 1)
        ck = (key, px)
        if ck in self._fcache:
            return self._fcache[ck]
        files = {
            "display": "Archivo-ExtraBold.ttf",
            "displayb": "Archivo-Bold.ttf",
            "label": "IBMPlexSans-SemiBold.ttf",
            "body": "IBMPlexSans-Regular.ttf",
            "mono": "IBMPlexMono-Medium.ttf",
        }
        fallbacks = {
            "display": "DejaVuSans-Bold.ttf",
            "displayb": "DejaVuSans-Bold.ttf",
            "label": "DejaVuSans-Bold.ttf",
            "body": "DejaVuSans.ttf",
            "mono": "DejaVuSansMono.ttf",
        }
        path = os.path.join(_FONT_DIR, files[key])
        try:
            font = ImageFont.truetype(path, px)
        except OSError:
            for base in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts"):
                fp = os.path.join(base, fallbacks[key])
                if os.path.exists(fp):
                    font = ImageFont.truetype(fp, px)
                    break
            else:
                font = ImageFont.load_default()
        self._fcache[ck] = font
        return font

    # ---- Messung (logisch) ------------------------------------------- #
    def _measure(self, text: str, key: str, size: int) -> tuple[int, int]:
        f = self._font(key, size, draw=False)
        l, t, r, b = f.getbbox(text or "x")
        return (r - l, b - t)

    def _wrap(self, text: str, key: str, size: int, max_w: int) -> list[str]:
        words = (text or "").split()
        if not words:
            return [""]
        lines, cur = [], words[0]
        for w in words[1:]:
            if self._measure(cur + " " + w, key, size)[0] <= max_w:
                cur += " " + w
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        # Harte Umbrüche für überlange Einzelwörter
        out = []
        for ln in lines:
            while self._measure(ln, key, size)[0] > max_w and len(ln) > 1:
                cut = len(ln)
                while cut > 1 and self._measure(ln[:cut] + "…", key, size)[0] > max_w:
                    cut -= 1
                out.append(ln[:cut] + "…")
                ln = ln[cut:]
            out.append(ln)
        return out

    def _ellipsize(self, text: str, key: str, size: int, max_w: int) -> str:
        if self._measure(text, key, size)[0] <= max_w:
            return text
        s = text
        while s and self._measure(s + "…", key, size)[0] > max_w:
            s = s[:-1]
        return (s + "…") if s else "…"

    # ---- skalierende Zeichenprimitive -------------------------------- #
    def _s(self, *vals):
        return [v * self.S for v in vals]

    def _rrect(self, box, radius, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = self._s(*box)
        self.d.rounded_rectangle(
            [x0, y0, x1, y1], radius=radius * self.S, fill=fill,
            outline=outline, width=max(1, width * self.S),
        )

    def _line(self, pts, fill, width=1):
        sp = [(x * self.S, y * self.S) for x, y in pts]
        self.d.line(sp, fill=fill, width=max(1, width * self.S), joint="curve")

    def _ellipse(self, box, fill=None, outline=None, width=1):
        x0, y0, x1, y1 = self._s(*box)
        self.d.ellipse([x0, y0, x1, y1], fill=fill, outline=outline,
                       width=max(1, width * self.S))

    def _text(self, xy, text, key, size, fill, anchor="la"):
        x, y = self._s(*xy)
        self.d.text((x, y), text, font=self._font(key, size, draw=True),
                    fill=fill, anchor=anchor)

    # ---- Avatar ------------------------------------------------------- #
    def _avatar(self, person: RPerson, d_px: int, ring: tuple[int, int, int]):
        """Liefert ein RGBA-Image (Größe d_px*S) mit kreisförmigem Avatar + Ring."""
        size = d_px * self.S
        out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        inner = size - 4 * self.S  # Platz für Ring
        if person.avatar_png and not person.vacant:
            try:
                av = Image.open(io.BytesIO(person.avatar_png)).convert("RGBA")
                av = ImageOps.fit(av, (inner, inner), Image.LANCZOS)
            except Exception:
                av = None
        else:
            av = None
        if av is None:
            # Platzhalter: gefüllter Kreis + Initiale (oder Strich bei vacant)
            av = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
            ad = ImageDraw.Draw(av)
            base = _mix(ring, PANEL, 0.55) if not person.vacant else PANEL2
            ad.ellipse([0, 0, inner - 1, inner - 1], fill=base)
            ch = "?" if person.vacant else (person.name.strip()[:1].upper() or "?")
            f = self._font("label", max(9, d_px // 2), draw=True)
            ad.text((inner / 2, inner / 2), ch, font=f, fill=TEXT, anchor="mm")
        # Kreis-Maske
        mask = Image.new("L", (inner, inner), 0)
        ImageDraw.Draw(mask).ellipse([0, 0, inner - 1, inner - 1], fill=255)
        out.paste(av, (2 * self.S, 2 * self.S), mask)
        # Ring
        rd = ImageDraw.Draw(out)
        rw = max(1, (2 if not person.vacant else 1) * self.S)
        rd.ellipse([rw, rw, size - rw - 1, size - rw - 1], outline=ring, width=rw)
        return out

    def _paste(self, img: Image.Image, xy):
        x, y = self._s(*xy)
        self.base.paste(img, (int(x), int(y)), img)

    # ================================================================== #
    #  Karten-Maß / -Zeichnung (für baum, abteilungen, pyramide)
    # ================================================================== #
    def _card_height(self, node: RNode, w: int) -> int:
        inner = w - 2 * self.PAD
        h = self.PAD + 5  # Top-Strip
        # Label (umbrochen, max 2 Zeilen)
        lab_lines = self._wrap(node.label or "—", "label", 13, inner)[:2]
        h += len(lab_lines) * 19
        # Personen
        ppl = node.people[: self.MAX_PEOPLE]
        overflow = max(0, len(node.people) - self.MAX_PEOPLE)
        if ppl:
            h += 8  # Abstand nach Label
            row = (self.AV + 6) if self.chart.show_avatars else self.LINE_H
            h += len(ppl) * row
            if overflow:
                h += self.LINE_H
        h += self.PAD
        return h

    def _draw_card(self, node: RNode, x: float, y: float, w: int) -> int:
        col = _hex(node.color, _hex(self.chart.accent))
        h = self._card_height(node, w)
        inner = w - 2 * self.PAD
        # Panel
        self._rrect((x, y, x + w, y + h), 13, fill=PANEL, outline=BORDER, width=1)
        # Akzent-Streifen oben
        self._rrect((x + self.PAD, y + 8, x + w - self.PAD, y + 11), 2, fill=col)
        cy = y + 16
        # Label
        for ln in self._wrap(node.label or "—", "label", 13, inner)[:2]:
            self._text((x + self.PAD, cy), ln, "label", 13, TEXT)
            cy += 19
        # Personen
        ppl = node.people[: self.MAX_PEOPLE]
        overflow = max(0, len(node.people) - self.MAX_PEOPLE)
        if ppl:
            cy += 8
            for p in ppl:
                if self.chart.show_avatars:
                    av = self._avatar(p, self.AV, col)
                    self._paste(av, (x + self.PAD, cy))
                    tx = x + self.PAD + self.AV + 8
                    name = self._ellipsize(
                        p.name, "body", 12, inner - self.AV - 8)
                    fill = MUTED if p.vacant else TEXT
                    self._text((tx, cy + self.AV / 2), name, "body", 12,
                               fill, anchor="lm")
                    cy += self.AV + 6
                else:
                    self._ellipse((x + self.PAD + 1, cy + 7,
                                   x + self.PAD + 7, cy + 13), fill=col)
                    name = self._ellipsize(p.name, "body", 12, inner - 14)
                    fill = MUTED if p.vacant else TEXT
                    self._text((x + self.PAD + 14, cy + 3), name, "body", 12, fill)
                    cy += self.LINE_H
            if overflow:
                self._text((x + self.PAD + (self.AV + 8 if self.chart.show_avatars else 14),
                            cy + 2), f"+{overflow} weitere", "body", 11, MUTED)
        return h

    # ================================================================== #
    #  Hintergrund + Rahmen (Titel/Footer)
    # ================================================================== #
    def _canvas(self, w: int, h: int) -> tuple[int, int]:
        """Erzeugt base/draw inkl. Titelhöhe oben und Footer unten.
        Gibt (content_x0, content_y0) zurück."""
        accent = _hex(self.chart.accent)
        w = int(round(w))
        h = int(round(h))
        title_h = 64
        footer_h = 34 if self.chart.footer else 12
        total_w = w + 2 * self.MARGIN
        total_h = h + title_h + footer_h + self.MARGIN
        # Mindestbreite, damit Titel/Footer nie abgeschnitten werden.
        title_w = self._measure(self.chart.title or "Organigramm", "display", 24)[0]
        need = self.MARGIN + 20 + title_w + self.MARGIN
        if self.chart.footer:
            need = max(need, self.MARGIN + self._measure(self.chart.footer, "mono", 11)[0] + self.MARGIN)
        total_w = max(total_w, need)
        self.W, self.H = total_w, total_h

        self.base = Image.new("RGB", (total_w * self.S, total_h * self.S), BG)
        # Sanfter radialer Glow oben rechts (wie im Web)
        glow = Image.new("RGBA", self.base.size, (0, 0, 0, 0))
        gd = ImageDraw.Draw(glow)
        gr = int(total_w * 0.9) * self.S
        gx, gy = int(total_w * 1.02) * self.S, int(-total_h * 0.1) * self.S
        gd.ellipse([gx - gr, gy - gr, gx + gr, gy + gr],
                   fill=(accent[0], accent[1], accent[2], 26))
        glow = glow.filter(ImageFilter.GaussianBlur(120 * self.S // 2))
        self.base = Image.alpha_composite(self.base.convert("RGBA"), glow).convert("RGB")
        self.d = ImageDraw.Draw(self.base)

        # Titel + Akzentpunkt
        self._ellipse((self.MARGIN, self.MARGIN + 6, self.MARGIN + 11,
                       self.MARGIN + 17), fill=accent)
        self._text((self.MARGIN + 20, self.MARGIN + 2),
                   self.chart.title or "Organigramm", "display", 24, TEXT)
        # Footer
        if self.chart.footer:
            self._text((self.MARGIN, total_h - footer_h + 4),
                       self.chart.footer, "mono", 11, MUTED)
        return self.MARGIN, self.MARGIN + title_h

    def _finish(self) -> bytes:
        img = self.base.resize((self.W, self.H), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    # ================================================================== #
    #  Muster: BAUM
    # ================================================================== #
    def _layout_tree(self, roots: list[RNode]):
        # Tiefe setzen
        def set_depth(n, d):
            n.depth = d
            for c in n.children:
                set_depth(c, d + 1)
        for r in roots:
            set_depth(r, 0)

        # X packen (Leaves links→rechts, Eltern zentriert)
        cursor = [0.0]

        def assign_x(n):
            if not n.children:
                n.x = cursor[0] + self.CARD_W / 2
                cursor[0] += self.CARD_W + self.H_GAP
            else:
                for c in n.children:
                    assign_x(c)
                n.x = (n.children[0].x + n.children[-1].x) / 2
        for r in roots:
            assign_x(r)

        # Reihenhöhen je Tiefe
        max_depth = max((n.depth for n in _iter_nodes(roots)), default=0)
        row_h = [0] * (max_depth + 1)
        for n in _iter_nodes(roots):
            row_h[n.depth] = max(row_h[n.depth], self._card_height(n, self.CARD_W))
        row_top = [0] * (max_depth + 1)
        acc = 0
        for d in range(max_depth + 1):
            row_top[d] = acc
            acc += row_h[d] + self.V_GAP
        content_h = acc - self.V_GAP
        content_w = cursor[0] - self.H_GAP
        for n in _iter_nodes(roots):
            n.y = row_top[n.depth]
        return content_w, content_h, row_h

    def render_tree(self) -> bytes:
        roots = self.chart.roots
        content_w, content_h, row_h = self._layout_tree(roots)
        ox, oy = self._canvas(max(content_w, 280), content_h)

        line_col = _mix(BORDER, MUTED, 0.35)
        # Verbindungslinien
        for n in _iter_nodes(roots):
            if not n.children:
                continue
            ph = self._card_height(n, self.CARD_W)
            px = ox + n.x
            py = oy + n.y + ph
            bus_y = py + self.V_GAP / 2
            self._line([(px, py), (px, bus_y)], line_col, 2)
            xs = [ox + c.x for c in n.children]
            self._line([(min(xs), bus_y), (max(xs), bus_y)], line_col, 2)
            for c in n.children:
                cx = ox + c.x
                self._line([(cx, bus_y), (cx, oy + c.y)], line_col, 2)
        # Karten
        for n in _iter_nodes(roots):
            self._draw_card(n, ox + n.x - self.CARD_W / 2, oy + n.y, self.CARD_W)
        return self._finish()

    # ================================================================== #
    #  Muster: ABTEILUNGEN (Spalten)
    # ================================================================== #
    def render_columns(self) -> bytes:
        roots = self.chart.roots
        # "Abteilungen" = erste Ebene unter dem/den Wurzelknoten.
        if len(roots) == 1 and roots[0].children:
            head = roots[0]
            columns = roots[0].children
        else:
            head = None
            columns = roots

        COL_W = 270
        ROW = 30          # Zeilenhöhe einer Position in der Spalte
        IND = 18          # Einrückung je Ebene

        def col_flat(node, depth, acc):
            acc.append((node, depth))
            for c in node.children:
                col_flat(c, depth + 1, acc)
            return acc

        col_items = [col_flat(c, 0, []) for c in columns]

        def people_lines(node):
            n = len(node.people[: self.MAX_PEOPLE])
            return n + (1 if len(node.people) > self.MAX_PEOPLE else 0)

        def col_height(items):
            h = self.PAD
            for node, depth in items:
                h += ROW
                pl = people_lines(node)
                row = (self.AV + 6) if self.chart.show_avatars else self.LINE_H
                h += pl * row + (6 if pl else 0)
            return h + self.PAD

        col_h = [col_height(it) for it in col_items]
        content_h = (max(col_h) if col_h else 80)
        head_h = self._card_height(head, COL_W) + 24 if head else 0
        n_cols = max(1, len(columns))
        content_w = n_cols * COL_W + (n_cols - 1) * self.H_GAP
        ox, oy = self._canvas(max(content_w, 280), content_h + head_h)

        # Kopf
        oy2 = oy
        if head:
            self._draw_card(head, ox + content_w / 2 - COL_W / 2, oy, COL_W)
            oy2 = oy + head_h

        line_col = _mix(BORDER, MUTED, 0.3)
        for ci, items in enumerate(col_items):
            cx = ox + ci * (COL_W + self.H_GAP)
            # Spalten-Panel
            self._rrect((cx, oy2, cx + COL_W, oy2 + content_h), 13,
                        fill=PANEL, outline=BORDER, width=1)
            cy = oy2 + self.PAD
            for idx, (node, depth) in enumerate(items):
                col = _hex(node.color, _hex(self.chart.accent))
                lx = cx + self.PAD + depth * IND
                # Einrück-Leitlinie
                if depth > 0:
                    self._line([(cx + self.PAD + (depth - 1) * IND + 6, cy - 4),
                                (cx + self.PAD + (depth - 1) * IND + 6, cy + 12),
                                (lx - 4, cy + 12)], line_col, 1)
                # Marker + Label
                head_style = "label" if depth == 0 else "body"
                self._ellipse((lx, cy + 4, lx + 8, cy + 12), fill=col)
                label = self._ellipsize(node.label or "—", head_style, 13 if depth == 0 else 12,
                                        COL_W - (lx - cx) - self.PAD - 14)
                self._text((lx + 14, cy + 1), label, head_style,
                           13 if depth == 0 else 12, TEXT)
                cy += ROW
                # Personen
                ppl = node.people[: self.MAX_PEOPLE]
                overflow = max(0, len(node.people) - self.MAX_PEOPLE)
                for p in ppl:
                    if self.chart.show_avatars:
                        av = self._avatar(p, self.AV, col)
                        self._paste(av, (lx + 14, cy))
                        name = self._ellipsize(p.name, "body", 12,
                                               COL_W - (lx - cx) - self.PAD - 14 - self.AV - 8)
                        self._text((lx + 14 + self.AV + 8, cy + self.AV / 2),
                                   name, "body", 12, MUTED if p.vacant else TEXT, anchor="lm")
                        cy += self.AV + 6
                    else:
                        name = self._ellipsize(p.name, "body", 12,
                                               COL_W - (lx - cx) - self.PAD - 18)
                        self._text((lx + 18, cy), name, "body", 12,
                                   MUTED if p.vacant else TEXT)
                        cy += self.LINE_H
                if overflow:
                    self._text((lx + 14, cy), f"+{overflow} weitere", "body", 11, MUTED)
                    cy += self.LINE_H
                if ppl or overflow:
                    cy += 6
        return self._finish()

    # ================================================================== #
    #  Muster: PYRAMIDE (Ebenen)
    # ================================================================== #
    def render_tiers(self) -> bytes:
        roots = self.chart.roots

        def set_depth(n, d):
            n.depth = d
            for c in n.children:
                set_depth(c, d + 1)
        for r in roots:
            set_depth(r, 0)

        levels: dict[int, list[RNode]] = {}
        for n in _iter_nodes(roots):
            levels.setdefault(n.depth, []).append(n)
        max_depth = max(levels) if levels else 0

        CARD_W = 220
        # Reihenhöhe je Ebene
        row_h = {}
        row_w = {}
        for d, nodes in levels.items():
            row_h[d] = max(self._card_height(n, CARD_W) for n in nodes)
            row_w[d] = len(nodes) * CARD_W + (len(nodes) - 1) * self.H_GAP
        content_w = max(row_w.values()) if row_w else 280
        content_h = sum(row_h.values()) + max_depth * self.V_GAP
        ox, oy = self._canvas(max(content_w, 280), content_h)

        # Positionen berechnen (zentriert je Ebene)
        pos: dict[str, tuple[float, float, int]] = {}
        y = oy
        for d in range(max_depth + 1):
            nodes = levels.get(d, [])
            rw = row_w.get(d, 0)
            x = ox + (content_w - rw) / 2
            # Bandtrenner
            if d > 0:
                self._line([(ox, y - self.V_GAP / 2), (ox + content_w, y - self.V_GAP / 2)],
                           _mix(BORDER, BG, 0.2), 1)
            self._text((ox + content_w, y - self.V_GAP / 2 - 14 if d > 0 else y - 16),
                       f"Ebene {d + 1}", "mono", 10, _mix(MUTED, BG, 0.25), anchor="ra")
            for n in nodes:
                pos[n.id] = (x + CARD_W / 2, y, d)
                x += CARD_W + self.H_GAP
            y += row_h.get(d, 0) + self.V_GAP

        # Verbindungslinien (Kind -> Elternmitte)
        line_col = _mix(BORDER, MUTED, 0.25)
        for n in _iter_nodes(roots):
            for c in n.children:
                if n.id in pos and c.id in pos:
                    px, py, _ = pos[n.id]
                    cx, cy, _ = pos[c.id]
                    py_b = py + row_h[pos[n.id][2]]
                    self._line([(px, py_b), (px, (py_b + cy) / 2),
                                (cx, (py_b + cy) / 2), (cx, cy)], line_col, 1)
        # Karten
        for n in _iter_nodes(roots):
            if n.id in pos:
                cx, cy, _ = pos[n.id]
                self._draw_card(n, cx - CARD_W / 2, cy, CARD_W)
        return self._finish()

    # ================================================================== #
    #  Muster: KOMPAKTLISTE (Bild)
    # ================================================================== #
    def render_list(self) -> bytes:
        roots = self.chart.roots
        lines: list[tuple[str, str, tuple, bool]] = []  # (prefix, text, color, is_label)

        def walk(node, prefix, is_last, is_root):
            col = _hex(node.color, _hex(self.chart.accent))
            if is_root:
                branch = ""
                child_prefix = ""
            else:
                branch = prefix + ("└─ " if is_last else "├─ ")
                child_prefix = prefix + ("   " if is_last else "│  ")
            emoji = ""  # Emoji nur in Embed/Text-Modus (Bild-Fonts haben keine Emoji-Glyphen)
            lines.append((branch, f"{emoji}{node.label or '—'}", col, True))
            ppl = node.people[: self.MAX_PEOPLE]
            overflow = max(0, len(node.people) - self.MAX_PEOPLE)
            for i, p in enumerate(ppl):
                lines.append((child_prefix + "   • ", p.name, col, False))
            if overflow:
                lines.append((child_prefix + "   • ", f"+{overflow} weitere", MUTED, False))
            for i, c in enumerate(node.children):
                walk(c, child_prefix, i == len(node.children) - 1, False)

        for r in roots:
            walk(r, "", True, True)

        LH = 24
        # Breite messen
        max_w = 280
        for prefix, text, _c, _lbl in lines:
            w = self._measure(prefix, "mono", 13)[0] + self._measure(text, "label", 13)[0] + 8
            max_w = max(max_w, w)
        content_h = len(lines) * LH + self.PAD
        ox, oy = self._canvas(max_w + 2 * self.PAD, content_h)

        # Panel
        self._rrect((ox, oy, ox + max_w + 2 * self.PAD, oy + content_h), 13,
                    fill=PANEL, outline=BORDER, width=1)
        y = oy + self.PAD
        for prefix, text, col, is_label in lines:
            self._text((ox + self.PAD, y), prefix, "mono", 13, _mix(BORDER, MUTED, 0.55))
            px = ox + self.PAD + self._measure(prefix, "mono", 13)[0]
            if is_label:
                self._ellipse((px, y + 5, px + 7, y + 12), fill=col)
                self._text((px + 12, y), text, "label", 13, TEXT)
            else:
                self._text((px, y), text, "body", 13, MUTED)
            y += LH
        return self._finish()

    # ================================================================== #
    #  Muster: KARTEN
    # ================================================================== #
    def render_cards(self) -> bytes:
        roots = self.chart.roots
        # Personen sammeln (mit Positions-Label + Farbe)
        cards: list[tuple[RPerson, str, tuple]] = []
        for n in _iter_nodes(roots):
            col = _hex(n.color, _hex(self.chart.accent))
            if n.people:
                for p in n.people:
                    cards.append((p, n.label or "—", col))
            # Knoten ohne Personen erscheinen nicht als Karte (nur Positionen mit Leuten/vacant)
        if not cards:
            cards = [(RPerson(name="—", vacant=True), "Keine Einträge", _hex(self.chart.accent))]

        CARD_W = 200
        CARD_H = 92
        GAP = 16
        # Spaltenzahl an Zielbreite (~5 Karten) ausrichten
        cols = max(1, min(5, len(cards)))
        rows = (len(cards) + cols - 1) // cols
        content_w = cols * CARD_W + (cols - 1) * GAP
        content_h = rows * CARD_H + (rows - 1) * GAP
        ox, oy = self._canvas(max(content_w, 280), content_h)

        AVD = 46
        for i, (p, role, col) in enumerate(cards):
            r, c = divmod(i, cols)
            x = ox + c * (CARD_W + GAP)
            y = oy + r * (CARD_H + GAP)
            self._rrect((x, y, x + CARD_W, y + CARD_H), 13, fill=PANEL,
                        outline=BORDER, width=1)
            self._rrect((x, y, x + 4, y + CARD_H), 0, fill=col)  # Farbkante links
            av = self._avatar(p, AVD, col)
            self._paste(av, (x + 14, y + (CARD_H - AVD) / 2))
            tx = x + 14 + AVD + 12
            tw = CARD_W - (14 + AVD + 12) - 12
            name = self._ellipsize(p.name, "label", 14, tw)
            self._text((tx, y + CARD_H / 2 - 12), name, "label", 14,
                       MUTED if p.vacant else TEXT)
            self._text((tx, y + CARD_H / 2 + 8),
                       self._ellipsize(role, "body", 11, tw), "body", 11, MUTED)
        return self._finish()

    # ---- Dispatch ----------------------------------------------------- #
    def render(self) -> bytes:
        fn = {
            "baum": self.render_tree,
            "abteilungen": self.render_columns,
            "pyramide": self.render_tiers,
            "liste": self.render_list,
            "karten": self.render_cards,
        }.get(self.chart.pattern, self.render_tree)
        return fn()


# --------------------------------------------------------------------------- #
#  Öffentliche API
# --------------------------------------------------------------------------- #
def render_chart_png(chart: RChart) -> bytes:
    """Rendert das Organigramm im in ``chart.pattern`` gewählten Muster zu PNG-Bytes."""
    return _Renderer(chart).render()


def build_text_tree(chart: RChart) -> str:
    """Reiner Text-Baum (für den Codeblock-Modus in Discord)."""
    out: list[str] = []
    if chart.title:
        out.append(chart.title)
        out.append("")

    def walk(node: RNode, prefix: str, is_last: bool, is_root: bool):
        if is_root:
            branch, child_prefix = "", ""
        else:
            branch = prefix + ("└─ " if is_last else "├─ ")
            child_prefix = prefix + ("   " if is_last else "│  ")
        emoji = (node.emoji + " ") if node.emoji else ""
        out.append(f"{branch}{emoji}{node.label or '—'}")
        ppl = node.people[: _Renderer.MAX_PEOPLE]
        overflow = max(0, len(node.people) - _Renderer.MAX_PEOPLE)
        for p in ppl:
            out.append(f"{child_prefix}   • {p.name}")
        if overflow:
            out.append(f"{child_prefix}   • +{overflow} weitere")
        for i, c in enumerate(node.children):
            walk(c, child_prefix, i == len(node.children) - 1, False)

    for r in chart.roots:
        walk(r, "", True, True)
    return "\n".join(out)
