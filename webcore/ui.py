"""UI-Baukasten für Cog-Dashboards (reine HTML-Helfer, alle Werte werden escaped).

Cogs holen ihn über WebCore – ohne eigenen Import und ohne eigenes CSS::

    ui = request.app["webcore"].ui
    body = ui.tab("einstellungen", "Einstellungen", "bi-sliders", ui.card("Allgemein", ...))

Zusammen mit ``static/webcore.css`` und ``static/webcore.js`` ergibt das:

* **Tabs** – jede ``ui.tab(...)``-Sektion wird automatisch zu einem Reiter; der
  zuletzt gewählte Reiter bleibt pro Seite erhalten (auch nach dem Speichern).
* **Karten** mit Titel, Erklärtext und Aktionen.
* **Formular-Raster**, **Schalter** statt Checkboxen, **Einheiten** an Zahlenfeldern.
* **Mehrfachauswahl als Chips** mit Suche (automatisch für ``<select multiple>``).
* **„Ungespeicherte Änderungen“-Leiste** für Formulare mit ``savebar=True``.
* **Bestätigungsdialog** über ``confirm="Text"`` an Formularen/Buttons.
* **Tabellenfilter** über ``ui.table(..., search=True)``.
"""

from __future__ import annotations

import html
import re

_SLUG_RE = re.compile(r"[^a-z0-9_-]+")


def esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def _attrs(attrs: dict | None) -> str:
    out = []
    for key, val in (attrs or {}).items():
        if val is None or val is False:
            continue
        if val is True:
            out.append(f" {key}")
        else:
            out.append(f" {key}='{esc(val)}'")
    return "".join(out)


# --------------------------------------------------------------------------- #
#  Seitenaufbau
# --------------------------------------------------------------------------- #
def hero(icon: str, title: str, text: str = "", *, actions: str = "") -> str:
    """Seitenkopf: Symbol, (optionale) Überschrift, kurze Erklärung, Aktionen (HTML).

    Der Seitentitel steht bereits in der Kopfzeile – ``title=""`` zeigt nur die Erklärung.
    """
    return (
        "<header class='wc-hero'>"
        f"<div class='wc-hero-icon'><i class='bi {esc(icon)}'></i></div>"
        "<div class='wc-hero-text'>" + (f"<h2>{esc(title)}</h2>" if title else "")
        + (f"<p>{text}</p>" if text else "")
        + "</div>"
        + (f"<div class='wc-hero-actions'>{actions}</div>" if actions else "")
        + "</header>"
    )


def stats(items) -> str:
    """Kennzahlen-Leiste. ``items``: [(label, value, icon, hint|None, tone|None)] – tone: ok/warn/bad/info."""
    cells = []
    for item in items:
        label, value, icon, hint, tone = (list(item) + [None] * 5)[:5]
        cells.append(
            f"<div class='wc-stat{(' ' + esc(tone)) if tone else ''}'>"
            f"<div class='wc-stat-top'><span>{esc(label)}</span>"
            + (f"<i class='bi {esc(icon)}'></i>" if icon else "")
            + f"</div><div class='wc-stat-value'>{value if isinstance(value, Raw) else esc(value)}</div>"
            + (f"<div class='wc-stat-hint'>{esc(hint)}</div>" if hint else "")
            + "</div>"
        )
    return f"<div class='wc-stats'>{''.join(cells)}</div>"


class Raw(str):
    """Markiert bereits sicheres HTML (wird nicht erneut escaped)."""


def tab(key: str, title: str, icon: str, body: str, *, count=None, hidden: bool = False) -> str:
    """Eine Reiter-Sektion. Alle ``tab()``-Sektionen einer Seite werden zur Reiterleiste."""
    key = _SLUG_RE.sub("-", key.lower()).strip("-") or "tab"
    return (
        f"<section class='wc-tab' id='tab-{esc(key)}' data-tab='{esc(key)}' data-title='{esc(title)}' "
        f"data-icon='{esc(icon)}'"
        + (f" data-count='{esc(count)}'" if count not in (None, "") else "")
        + (" data-hidden='1'" if hidden else "")
        + f">{body}</section>"
    )


def card(title: str | None = None, body: str = "", *, desc: str | None = None, actions: str = "",
         icon: str | None = None, cls: str = "", tone: str | None = None) -> str:
    head = ""
    if title or actions:
        head = (
            "<div class='wc-card-head'><div class='wc-card-title'>"
            + (f"<i class='bi {esc(icon)}'></i>" if icon else "")
            + f"<div><h3>{esc(title or '')}</h3>"
            + (f"<p>{desc}</p>" if desc else "")
            + "</div></div>"
            + (f"<div class='wc-card-actions'>{actions}</div>" if actions else "")
            + "</div>"
        )
    tone_cls = f" tone-{esc(tone)}" if tone else ""
    return f"<div class='card-x wc-card{tone_cls}{(' ' + cls) if cls else ''}'>{head}<div class='wc-card-body'>{body}</div></div>"


def callout(text: str, *, tone: str = "info", icon: str | None = None) -> str:
    icons = {"info": "bi-info-circle", "ok": "bi-check-circle", "warn": "bi-exclamation-triangle", "bad": "bi-x-octagon"}
    return (
        f"<div class='wc-callout {esc(tone)}'><i class='bi {esc(icon or icons.get(tone, 'bi-info-circle'))}'></i>"
        f"<div>{text}</div></div>"
    )


def empty(icon: str, title: str, text: str = "", *, action: str = "") -> str:
    return (
        f"<div class='wc-empty'><i class='bi {esc(icon)}'></i><div>{esc(title)}</div>"
        + (f"<small>{text}</small>" if text else "")
        + (f"<div style='margin-top:12px'>{action}</div>" if action else "")
        + "</div>"
    )


def badge(text: str, tone: str = "muted") -> str:
    return f"<span class='wc-pill {esc(tone)}'>{esc(text)}</span>"


def columns(*blocks: str, cols: int = 2) -> str:
    return f"<div class='wc-cols cols-{int(cols)}'>{''.join(blocks)}</div>"


# --------------------------------------------------------------------------- #
#  Formulare
# --------------------------------------------------------------------------- #
def form(action: str, body: str, *, csrf: str, hidden: dict | None = None, savebar: bool = False,
         confirm: str | None = None, id: str | None = None, cls: str = "", method: str = "post",
         enctype: str | None = None) -> str:
    """POST-Formular inkl. CSRF-Token. ``savebar=True`` zeigt bei Änderungen die Speicherleiste.
    Für Datei-Uploads ``enctype="multipart/form-data"`` setzen."""
    fields = [f"<input type='hidden' name='csrf_token' value='{esc(csrf)}'>"] if method == "post" else []
    fields += [f"<input type='hidden' name='{esc(k)}' value='{esc(v)}'>" for k, v in (hidden or {}).items() if v is not None]
    attrs = {"id": id, "enctype": enctype, "data-wc-savebar": "1" if savebar else None, "data-confirm": confirm}
    return (
        f"<form class='wc-form{(' ' + cls) if cls else ''}' method='{method}' action='{esc(action)}'{_attrs(attrs)}>"
        + "".join(fields) + body + "</form>"
    )


def grid(*fields: str, cols: int = 2) -> str:
    return f"<div class='wc-grid cols-{int(cols)}'>{''.join(fields)}</div>"


def field(label: str, control: str, *, help: str | None = None, wide: bool = False) -> str:
    return (
        f"<div class='wc-field{' wide' if wide else ''}'><label class='wc-label'>{esc(label)}</label>"
        f"{control}" + (f"<div class='wc-help'>{help}</div>" if help else "") + "</div>"
    )


def switch(name: str, label: str, checked, *, desc: str | None = None, value: str | None = None) -> str:
    val = f" value='{esc(value)}'" if value is not None else ""
    return (
        "<label class='wc-switch'>"
        f"<input type='checkbox' name='{esc(name)}'{val}{' checked' if checked else ''}>"
        "<span class='wc-switch-ui' aria-hidden='true'></span>"
        f"<span class='wc-switch-text'><b>{esc(label)}</b>"
        + (f"<small>{desc}</small>" if desc else "")
        + "</span></label>"
    )


def switches(*items: str) -> str:
    """Gruppe von ``switch(...)``-Schaltern untereinander."""
    return f"<div class='wc-switches'>{''.join(items)}</div>"


def divider() -> str:
    return "<div class='wc-divider'></div>"


def color_input(name: str, value="#5865f2") -> str:
    """Farbwähler (Hex)."""
    return f"<input class='wc-input wc-color' type='color' name='{esc(name)}' value='{esc(value or '#5865f2')}'>"


def text_input(name: str, value="", *, placeholder: str = "", type: str = "text", attrs: dict | None = None) -> str:
    return (
        f"<input class='wc-input' type='{esc(type)}' name='{esc(name)}' value='{esc(value)}'"
        f" placeholder='{esc(placeholder)}'{_attrs(attrs)}>"
    )


def number(name: str, value, *, min=None, max=None, unit: str | None = None, step=None,
           placeholder: str | None = None, attrs: dict | None = None) -> str:
    attrs = {"min": min, "max": max, "step": step, "placeholder": placeholder, **(attrs or {})}
    inp = f"<input class='wc-input' type='number' name='{esc(name)}' value='{esc(value)}'{_attrs(attrs)}>"
    if unit:
        return f"<div class='wc-input-group'>{inp}<span class='wc-unit'>{esc(unit)}</span></div>"
    return inp


def textarea(name: str, value="", *, rows: int = 3, placeholder: str = "", mono: bool = False) -> str:
    return (
        f"<textarea class='wc-input{' mono' if mono else ''}' name='{esc(name)}' rows='{int(rows)}'"
        f" placeholder='{esc(placeholder)}'>{esc(value)}</textarea>"
    )


def select(name: str, items, selected=None, *, none_label: str | None = None, multiple: bool = False,
           placeholder: str | None = None, autosubmit: bool = False, attrs: dict | None = None) -> str:
    """``items``: [(value, label)] oder [(value, label, color_hex)] – Farbe erscheint als Punkt in den Chips."""
    if isinstance(selected, (list, tuple, set)):
        sel = {str(s) for s in selected if s is not None}
    else:
        sel = {str(selected)} if selected not in (None, "") else set()
    opts = []
    if none_label is not None and not multiple:
        opts.append(f"<option value=''{'' if sel else ' selected'}>{esc(none_label)}</option>")
    for item in items:
        value, label = item[0], item[1]
        color = item[2] if len(item) > 2 else None
        data = f" data-color='{esc(color)}'" if color else ""
        opts.append(
            f"<option value='{esc(value)}'{data}{' selected' if str(value) in sel else ''}>{esc(label)}</option>"
        )
    attrs = {
        "multiple": multiple,
        "data-placeholder": placeholder,
        "onchange": "this.form.submit()" if autosubmit else None,
        **(attrs or {}),
    }
    return f"<select class='wc-input' name='{esc(name)}'{_attrs(attrs)}>{''.join(opts)}</select>"


def button(label: str, *, icon: str | None = None, kind: str = "accent", type: str = "submit",
           name: str | None = None, value: str | None = None, confirm: str | None = None,
           href: str | None = None, small: bool = False, attrs: dict | None = None) -> str:
    cls = {"accent": "btn-accent", "ghost": "btn-ghost", "danger": "btn-danger"}.get(kind, "btn-accent")
    if small:
        cls += " btn-sm"
    inner = (f"<i class='bi {esc(icon)}'></i>" if icon else "") + (f"<span>{esc(label)}</span>" if label else "")
    if href:
        return f"<a class='{cls}' href='{esc(href)}'{_attrs(attrs)}>{inner}</a>"
    all_attrs = {"type": type, "name": name, "value": value, "data-confirm": confirm}
    all_attrs.update(attrs or {})
    return f"<button class='{cls}'{_attrs(all_attrs)}>{inner}</button>"


def actions(*buttons: str, align: str = "start") -> str:
    return f"<div class='wc-form-actions {esc(align)}'>{''.join(buttons)}</div>"


def save_row(label: str = "Speichern", *, extra: str = "") -> str:
    return actions(button(label, icon="bi-check2"), extra)


# --------------------------------------------------------------------------- #
#  Tabellen
# --------------------------------------------------------------------------- #
def table(headers, rows, *, empty_text: str = "Keine Einträge.", search: bool = False,
          search_placeholder: str = "Suchen …", id: str | None = None) -> str:
    """``headers``: [str] (Präfix '>' = rechtsbündig); ``rows``: fertige ``<tr>…</tr>``-Strings."""
    ths = "".join(
        f"<th class='right'>{esc(h[1:])}</th>" if h.startswith(">") else f"<th>{esc(h)}</th>" for h in headers
    )
    body = "".join(rows) or f"<tr class='wc-empty-row'><td colspan='{len(headers)}'>{esc(empty_text)}</td></tr>"
    tid = id or f"t{abs(hash(''.join(headers))) % 10**6}"
    tools = (
        f"<div class='wc-table-tools'><div class='wc-search'><i class='bi bi-search'></i>"
        f"<input type='search' data-wc-filter='#{esc(tid)}' placeholder='{esc(search_placeholder)}'></div></div>"
        if search else ""
    )
    return (
        f"{tools}<div class='wc-scroll'><table class='table wc-table' id='{esc(tid)}'>"
        f"<thead><tr>{ths}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def row(*cells: str, attrs: dict | None = None) -> str:
    """Tabellenzeile aus fertigen Zellen-Inhalten (HTML). Präfix '>' im Inhalt = rechtsbündig."""
    tds = []
    for c in cells:
        c = str(c)
        if c.startswith(">"):
            tds.append(f"<td class='right'>{c[1:]}</td>")
        else:
            tds.append(f"<td>{c}</td>")
    return f"<tr{_attrs(attrs)}>{''.join(tds)}</tr>"
