"""Rollen-Panels für den Autorole-Cog.

Ein *Panel* ist eine vom Bot gepostete Nachricht mit **Buttons** oder einem
**Dropdown (Select-Menü)** darunter, über die sich Mitglieder selbst Rollen
geben/nehmen. Verhalten ist **pro Panel** einstellbar:

* ``style``  – ``buttons`` oder ``select``
* ``mode``   – ``toggle`` (Klick gibt/entfernt) oder ``add`` (nur vergeben)
* ``unique`` – ``True`` = nur **eine** Rolle aus diesem Panel gleichzeitig

Dieses Modul enthält nur **reine Helfer** (Komponenten bauen, custom_id parsen,
Rollen-Differenz berechnen). Alle Seiteneffekte (Config, Nachrichten posten,
Interaktionen beantworten) liegen im Cog selbst.

Persistenz: Die Komponenten tragen stabile ``custom_id``s und bleiben dadurch an
der Nachricht erhalten – auch nach einem Bot-Neustart. Geklickt wird über den
``on_interaction``-Listener im Cog ausgewertet (kein erneutes Registrieren nötig).
"""

from __future__ import annotations

import secrets

import discord

# Eindeutiges Präfix (andere Cogs nutzen "tickets:", "rh:", "poll:").
PANEL_PREFIX = "arp:"

MAX_ROLES = 25                 # Discord: max. 25 Buttons (5×5) bzw. 25 Select-Optionen
STYLES = ("buttons", "select")
MODES = ("toggle", "add")
DEFAULT_COLOR = 0x3DDC97       # Theme-Akzent

BUTTON_STYLES: dict[str, discord.ButtonStyle] = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}
DEFAULT_BUTTON_STYLE = "secondary"


def new_panel_id() -> str:
    """Kurze, eindeutige Panel-ID (8 Hex-Zeichen, kollisionsarm)."""
    return secrets.token_hex(4)


def new_panel(name: str) -> dict:
    """Erzeugt ein leeres Panel mit sinnvollen Standardwerten."""
    return {
        "id": new_panel_id(),
        "name": name.strip()[:100] or "Panel",
        "channel_id": None,
        "message_id": None,
        "style": "buttons",
        "mode": "toggle",
        "unique": False,
        "use_embed": True,
        "title": "Rollen",
        "color": "",
        "text": "Klicke unten, um dir Rollen zu geben oder wieder zu entfernen.",
        "roles": [],   # [{role_id, label, emoji, style, description}]
    }


def _emoji(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        return discord.PartialEmoji.from_str(value)
    except Exception:  # noqa: BLE001
        return None


def parse_color(value) -> discord.Color:
    raw = (value or "").strip().lstrip("#")
    if len(raw) == 6:
        try:
            return discord.Color(int(raw, 16))
        except ValueError:
            pass
    return discord.Color(DEFAULT_COLOR)


def parse_custom_id(custom_id: str):
    """``arp:btn:<pid>:<role_id>`` / ``arp:sel:<pid>`` -> (kind, pid, role_id|None) | None."""
    if not custom_id.startswith(PANEL_PREFIX):
        return None
    parts = custom_id[len(PANEL_PREFIX):].split(":")
    if parts and parts[0] == "btn" and len(parts) == 3 and parts[2].isdigit():
        return "btn", parts[1], int(parts[2])
    if parts and parts[0] == "sel" and len(parts) == 2:
        return "sel", parts[1], None
    return None


# --------------------------------------------------------------------------- #
#  Nachricht + Komponenten bauen
# --------------------------------------------------------------------------- #
def message_kwargs(panel: dict) -> dict:
    """Liefert ``content``/``embed`` für ``send``/``edit`` (jeweils einer ist None)."""
    text = (panel.get("text") or "").strip()
    if panel.get("use_embed"):
        title = (panel.get("title") or "").strip()
        if not title and not text:
            text = "Wähle unten deine Rollen."
        embed = discord.Embed(
            title=title or None,
            description=text or None,
            color=parse_color(panel.get("color")),
        )
        return {"content": None, "embed": embed}
    # Reiner Text – nie leer senden (sonst API-Fehler).
    return {"content": text or "\u200b", "embed": None}


def build_view(panel: dict) -> discord.ui.View:
    """Baut eine (nicht ablaufende) View mit Buttons oder einem Select."""
    view = discord.ui.View(timeout=None)
    roles = list(panel.get("roles", []))[:MAX_ROLES]
    pid = panel["id"]

    if panel.get("style") == "select":
        options = []
        for r in roles:
            options.append(
                discord.SelectOption(
                    label=(r.get("label") or "Rolle")[:100],
                    value=str(r["role_id"]),
                    description=((r.get("description") or "").strip()[:100] or None),
                    emoji=_emoji(r.get("emoji")),
                )
            )
        if not options:
            return view
        unique = bool(panel.get("unique"))
        view.add_item(
            discord.ui.Select(
                custom_id=f"{PANEL_PREFIX}sel:{pid}",
                placeholder=((panel.get("title") or "Rollen auswählen")[:150]),
                min_values=0,
                max_values=1 if unique else len(options),
                options=options,
            )
        )
        return view

    # Buttons (max. 5 pro Reihe)
    for i, r in enumerate(roles):
        emoji = _emoji(r.get("emoji"))
        label = (r.get("label") or "").strip()[:80]
        if not label and emoji is None:
            label = "Rolle"
        view.add_item(
            discord.ui.Button(
                label=label or None,
                emoji=emoji,
                style=BUTTON_STYLES.get(r.get("style"), discord.ButtonStyle.secondary),
                custom_id=f"{PANEL_PREFIX}btn:{pid}:{r['role_id']}",
                row=i // 5,
            )
        )
    return view


# --------------------------------------------------------------------------- #
#  Reine Rollen-Differenz-Logik (ohne Discord/Config – gut testbar)
# --------------------------------------------------------------------------- #
def compute_button(member_ids: set[int], target: int, panel_ids: list[int],
                   mode: str, unique: bool) -> tuple[set[int], set[int]]:
    """Gibt (hinzufügen, entfernen) für einen Button-Klick zurück."""
    has = target in member_ids
    if unique:
        others = {rid for rid in panel_ids if rid != target} & member_ids
        if mode == "toggle" and has:
            return set(), {target}                     # abschalten
        return (set() if has else {target}), others     # auf target setzen
    if mode == "add":
        return (set() if has else {target}), set()
    # toggle (Standard)
    return (set() if has else {target}), ({target} if has else set())


def compute_select(member_ids: set[int], chosen: set[int], panel_ids: list[int],
                   mode: str, unique: bool) -> tuple[set[int], set[int]]:
    """Gibt (hinzufügen, entfernen) für eine Select-Auswahl zurück."""
    managed = set(panel_ids)
    desired = set(chosen) & managed
    if mode == "add" and not unique:
        return (desired - member_ids), set()
    # toggle bzw. unique: Auswahl = gewünschter Endzustand innerhalb des Panels
    add = desired - member_ids
    remove = (managed & member_ids) - desired
    return add, remove
