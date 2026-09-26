"""Diagramme als Inline-SVG – ohne externe Bibliotheken, ohne eigenes CSS.

Alle Funktionen sind rein (String rein, String raus) und escapen jeden Text. Farben kommen aus
den CSS-Variablen des WebCore-Themes (``var(--accent)`` …) über ``style``-Attribute – dadurch
passen sie zum Dark-Theme. Die Grafiken skalieren über ``viewBox`` (Breite 100 %), Tooltips
liefern ``<title>``-Elemente (Maus-Hover bzw. langes Tippen).
"""

from __future__ import annotations

import html
import math

W = 520                      # viewBox-Breite (zwei Diagramme nebeneinander ≈ 1:1 auf dem Desktop)
H = 230
PAD_L, PAD_R, PAD_T, PAD_B = 52, 14, 14, 32
FONT = 15

C_ACCENT = "var(--accent,#3ddc97)"
C_DANGER = "var(--danger,#ff6b6b)"
C_INFO = "var(--info,#6cb6ff)"
C_AMBER = "var(--amber,#f5b94a)"
C_GRID = "var(--border,#232b36)"
C_AXIS = "var(--border-2,#2e3845)"
C_TEXT = "var(--muted,#8b97a7)"
C_LABEL = "var(--text,#e6edf3)"


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def fmt_num(value) -> str:
    """Zahl im deutschen Format (Tausenderpunkt, max. 1 Nachkommastelle)."""
    if value is None:
        return "–"
    if isinstance(value, float) and not value.is_integer():
        s = f"{value:,.1f}"
    else:
        s = f"{int(round(value)):,}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def _nice_step(raw: float) -> float:
    if raw <= 0:
        return 1
    exp = math.floor(math.log10(raw))
    base = raw / 10 ** exp
    for m in (1, 2, 2.5, 5, 10):
        if base <= m:
            return m * 10 ** exp
    return 10 ** (exp + 1)


def nice_range(lo: float, hi: float, ticks: int = 4, *, zero: bool = True) -> tuple[float, float, float]:
    """(unten, oben, schritt) mit „runden“ Achsenwerten."""
    if zero:
        lo = min(0.0, lo)
    if hi <= lo:
        hi = lo + (1 if lo == 0 else abs(lo) * 0.1 + 1)
    step = _nice_step((hi - lo) / max(1, ticks))
    if step < 1 and all(float(v).is_integer() for v in (lo, hi)):
        step = 1
    bottom = math.floor(lo / step) * step
    top = math.ceil(hi / step) * step
    if top == bottom:
        top = bottom + step
    return bottom, top, step


def _svg(label: str, body: str, height: int = H) -> str:
    return (
        f"<svg viewBox='0 0 {W} {height}' width='100%' role='img' aria-label='{esc(label)}' "
        "preserveAspectRatio='xMidYMid meet' style='display:block;max-width:100%;height:auto;overflow:visible' "
        f"font-family='inherit' font-size='{FONT}'><title>{esc(label)}</title>{body}</svg>"
    )


def _y_axis(lo, hi, step, y_of, *, absolute: bool = False) -> str:
    out = []
    v = lo
    guard = 0
    while v <= hi + step / 1000 and guard < 50:
        y = y_of(v)
        out.append(f"<line x1='{PAD_L}' x2='{W - PAD_R}' y1='{y:.1f}' y2='{y:.1f}' "
                   f"style='stroke:{C_GRID};stroke-width:1'/>")
        lab = abs(v) if absolute else v
        lab = int(lab) if float(lab).is_integer() else lab
        out.append(f"<text x='{PAD_L - 6}' y='{y + 5:.1f}' text-anchor='end' style='fill:{C_TEXT}'>"
                   f"{esc(fmt_num(lab))}</text>")
        v += step
        guard += 1
    return "".join(out)


def _x_labels(labels: list[str], x_of) -> str:
    n = len(labels)
    if not n:
        return ""
    every = max(1, math.ceil(n / 5))
    out = []
    idx = list(range(0, n, every))
    if n - 1 not in idx and (n - 1) - idx[-1] >= every / 2:
        idx.append(n - 1)
    for i in idx:
        out.append(f"<text x='{x_of(i):.1f}' y='{H - 8}' text-anchor='middle' style='fill:{C_TEXT}'>"
                   f"{esc(labels[i])}</text>")
    return "".join(out)


def empty_chart(label: str, text: str = "Noch keine Daten") -> str:
    return _svg(label, f"<text x='{W / 2}' y='{H / 2}' text-anchor='middle' style='fill:{C_TEXT}'>{esc(text)}</text>")


def line_chart(labels: list[str], values: list, *, label: str, unit: str = "", tips: list[str] | None = None,
               color: str = C_ACCENT) -> str:
    """Linie (``None`` = Lücke). ``labels`` = x-Beschriftung, ``tips`` = Tooltip je Punkt."""
    known = [v for v in values if v is not None]
    if not known:
        return empty_chart(label)
    lo, hi, step = nice_range(min(known), max(known), zero=False)
    n = len(values)
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B

    def x_of(i):
        return PAD_L + (plot_w * (i + 0.5) / n)

    def y_of(v):
        return PAD_T + plot_h * (1 - (v - lo) / (hi - lo))

    segs, cur = [], []
    for i, v in enumerate(values):
        if v is None:
            if cur:
                segs.append(cur)
            cur = []
        else:
            cur.append((x_of(i), y_of(v)))
    if cur:
        segs.append(cur)
    body = [_y_axis(lo, hi, step, y_of)]
    for seg in segs:
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in seg)
        area = f"{seg[0][0]:.1f},{PAD_T + plot_h:.1f} {pts} {seg[-1][0]:.1f},{PAD_T + plot_h:.1f}"
        body.append(f"<polygon points='{area}' style='fill:{color};fill-opacity:.10;stroke:none'/>")
        body.append(f"<polyline points='{pts}' style='fill:none;stroke:{color};stroke-width:2.5;"
                    "stroke-linejoin:round;stroke-linecap:round'/>")
    dot = n <= 31
    for i, v in enumerate(values):
        if v is None:
            continue
        tip = tips[i] if tips else f"{labels[i]}: {fmt_num(v)}{(' ' + unit) if unit else ''}"
        # Unsichtbare, breite Trefferfläche je Tag für den Tooltip; kleiner Punkt bei wenigen Tagen.
        body.append(
            f"<g><title>{esc(tip)}</title>"
            f"<rect x='{x_of(i) - plot_w / n / 2:.1f}' y='{PAD_T}' width='{plot_w / n:.1f}' height='{plot_h}' "
            "style='fill:transparent'/>"
            + (f"<circle cx='{x_of(i):.1f}' cy='{y_of(v):.1f}' r='3' style='fill:{color}'/>" if dot else "")
            + "</g>"
        )
    body.append(_x_labels(labels, x_of))
    return _svg(label, "".join(body))


def bar_chart(labels: list[str], values: list, *, label: str, unit: str = "", tips: list[str] | None = None,
              color: str = C_INFO) -> str:
    """Senkrechte Balken je Tag."""
    if not values or not any(values):
        return empty_chart(label)
    lo, hi, step = nice_range(0, max(values))
    n = len(values)
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    slot = plot_w / n
    bw = max(1.0, slot * 0.72)

    def x_of(i):
        return PAD_L + slot * (i + 0.5)

    def y_of(v):
        return PAD_T + plot_h * (1 - (v - lo) / (hi - lo))

    body = [_y_axis(lo, hi, step, y_of)]
    for i, v in enumerate(values):
        tip = tips[i] if tips else f"{labels[i]}: {fmt_num(v)}{(' ' + unit) if unit else ''}"
        y = y_of(v)
        body.append(
            f"<g><title>{esc(tip)}</title>"
            f"<rect x='{x_of(i) - slot / 2:.1f}' y='{PAD_T}' width='{slot:.1f}' height='{plot_h}' style='fill:transparent'/>"
            + (f"<rect x='{x_of(i) - bw / 2:.1f}' y='{y:.1f}' width='{bw:.1f}' height='{PAD_T + plot_h - y:.1f}' "
               f"rx='{min(3, bw / 3):.1f}' style='fill:{color}'/>" if v else "")
            + "</g>"
        )
    body.append(f"<line x1='{PAD_L}' x2='{W - PAD_R}' y1='{y_of(0):.1f}' y2='{y_of(0):.1f}' "
                f"style='stroke:{C_AXIS};stroke-width:1.5'/>")
    body.append(_x_labels(labels, x_of))
    return _svg(label, "".join(body))


def diverging_chart(labels: list[str], ups: list, downs: list, *, label: str, tips: list[str] | None = None,
                    up_color: str = C_ACCENT, down_color: str = C_DANGER) -> str:
    """Balken nach oben (z. B. Beitritte) und nach unten (Abgänge) um eine Null-Linie."""
    if not any(ups) and not any(downs):
        return empty_chart(label)
    top = max(ups) if ups else 0
    bottom = -max(downs) if downs else 0
    lo, hi, step = nice_range(bottom, max(top, 1))
    n = len(labels)
    plot_w = W - PAD_L - PAD_R
    plot_h = H - PAD_T - PAD_B
    slot = plot_w / n
    bw = max(1.0, slot * 0.72)

    def x_of(i):
        return PAD_L + slot * (i + 0.5)

    def y_of(v):
        return PAD_T + plot_h * (1 - (v - lo) / (hi - lo))

    zero = y_of(0)
    body = [_y_axis(lo, hi, step, y_of, absolute=True)]   # Abgänge nach unten, Beschriftung ohne Minus
    for i in range(n):
        up, down = ups[i], downs[i]
        tip = tips[i] if tips else f"{labels[i]}: +{up} / −{down}"
        part = (f"<g><title>{esc(tip)}</title>"
                f"<rect x='{x_of(i) - slot / 2:.1f}' y='{PAD_T}' width='{slot:.1f}' height='{plot_h}' "
                "style='fill:transparent'/>")
        if up:
            y = y_of(up)
            part += (f"<rect x='{x_of(i) - bw / 2:.1f}' y='{y:.1f}' width='{bw:.1f}' height='{zero - y:.1f}' "
                     f"style='fill:{up_color}'/>")
        if down:
            y = y_of(-down)
            part += (f"<rect x='{x_of(i) - bw / 2:.1f}' y='{zero:.1f}' width='{bw:.1f}' height='{y - zero:.1f}' "
                     f"style='fill:{down_color}'/>")
        body.append(part + "</g>")
    body.append(f"<line x1='{PAD_L}' x2='{W - PAD_R}' y1='{zero:.1f}' y2='{zero:.1f}' "
                f"style='stroke:{C_AXIS};stroke-width:1.5'/>")
    body.append(_x_labels(labels, x_of))
    return _svg(label, "".join(body))


def hbar_chart(items: list[tuple[str, float]], *, label: str, unit: str = "", color: str = C_ACCENT,
               value_fmt=None) -> str:
    """Horizontale Balken (Top-Liste). ``items`` = [(Name, Wert)], bereits sortiert."""
    items = [(n, v) for n, v in items if v]
    if not items:
        return empty_chart(label)
    row = 34
    top_pad = 6
    height = top_pad * 2 + row * len(items)
    name_w = 170
    val_w = 76
    plot_w = W - name_w - val_w - 12
    vmax = max(v for _, v in items) or 1
    fmt = value_fmt or fmt_num
    body = []
    for i, (name, v) in enumerate(items):
        y = top_pad + i * row
        short = name if len(name) <= 18 else name[:17] + "…"
        w = max(2.0, plot_w * v / vmax)
        tip = f"{name}: {fmt(v)}{(' ' + unit) if unit else ''}"
        body.append(
            f"<g><title>{esc(tip)}</title>"
            f"<rect x='0' y='{y}' width='{W}' height='{row}' style='fill:transparent'/>"
            f"<text x='{name_w - 8}' y='{y + row / 2 + 5:.1f}' text-anchor='end' style='fill:{C_LABEL}'>{esc(short)}</text>"
            f"<rect x='{name_w}' y='{y + 5}' width='{plot_w:.1f}' height='{row - 10}' rx='4' style='fill:{C_GRID}'/>"
            f"<rect x='{name_w}' y='{y + 5}' width='{w:.1f}' height='{row - 10}' rx='4' style='fill:{color}'/>"
            f"<text x='{name_w + plot_w + 8:.1f}' y='{y + row / 2 + 5:.1f}' style='fill:{C_TEXT}'>{esc(fmt(v))}</text>"
            "</g>"
        )
    return _svg(label, "".join(body), height=height)
