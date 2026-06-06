"""Spiel-Templates für den RaidHelper-Cog.

Ein **Spiel** ist reine Datenbeschreibung – keine Logik. Die gesamte Anmelde-,
Roster- und Embed-Logik im Cog liest nur diese Tabellen. Ein weiteres Spiel
hinzuzufügen heißt deshalb: einen Block in ``GAMES`` ergänzen, fertig.

Aufbau eines Spiels::

    "<spiel_id>": {
        "label": "Anzeigename",
        "roles": { "<rolle_id>": {"label": "...", "emoji": "..."} , ... },
        "role_order": ["tank", "healer", ...],   # Reihenfolge im Roster
        "classes": {
            "<klasse_id>": {
                "label": "Anzeigename",
                "color": 0xRRGGBB,               # Klassenfarbe (Spec-Tag/Embed)
                "emoji": "<:name:id>" | None,     # optionales Custom-Emoji
                "specs": { "<spec_id>": {"label": "...", "role": "<rolle_id>"}, ... },
            }, ...
        },
        "class_order": ["krieger", ...],          # Reihenfolge der Klassen-Buttons
    }

Die Rolle einer Anmeldung ergibt sich **immer** aus der gewählten Spec
(``specs[spec]["role"]``), nicht aus der Klasse.
"""

from __future__ import annotations

# Standard-Rollen, die alle WoW-Templates teilen (Reihenfolge = Roster-Anzeige).
_WOW_ROLES: dict[str, dict[str, str]] = {
    "tank": {"label": "Tanks", "emoji": "🛡️"},
    "healer": {"label": "Heiler", "emoji": "✚"},
    "mdps": {"label": "Nahkampf", "emoji": "⚔️"},
    "rdps": {"label": "Fernkampf", "emoji": "🏹"},
}
_WOW_ROLE_ORDER = ["tank", "healer", "mdps", "rdps"]

# Offizielle WoW-Klassenfarben.
_COLORS = {
    "krieger": 0xC79C6E,
    "paladin": 0xF58CBA,
    "jaeger": 0xABD473,
    "schurke": 0xFFF569,
    "priester": 0xFFFFFF,
    "todesritter": 0xC41F3B,
    "schamane": 0x0070DE,
    "magier": 0x69CCF0,
    "hexenmeister": 0x9482C9,
    "moench": 0x00FF96,
    "druide": 0xFF7D0A,
    "daemonenjaeger": 0xA330C9,
    "rufer": 0x33937F,
}


def _spec(label: str, role: str) -> dict[str, str]:
    return {"label": label, "role": role}


def _cls(key: str, label: str, specs: dict[str, dict[str, str]]) -> dict:
    return {"label": label, "color": _COLORS[key], "emoji": None, "specs": specs}


# --------------------------------------------------------------------------- #
#  WoW – Retail (aktuelle Erweiterung): 13 Klassen
# --------------------------------------------------------------------------- #
_WOW_RETAIL_CLASSES: dict[str, dict] = {
    "krieger": _cls("krieger", "Krieger", {
        "waffen": _spec("Waffen", "mdps"),
        "furor": _spec("Furor", "mdps"),
        "schutz": _spec("Schutz", "tank"),
    }),
    "paladin": _cls("paladin", "Paladin", {
        "heilig": _spec("Heilig", "healer"),
        "schutz": _spec("Schutz", "tank"),
        "vergeltung": _spec("Vergeltung", "mdps"),
    }),
    "jaeger": _cls("jaeger", "Jäger", {
        "tierherrschaft": _spec("Tierherrschaft", "rdps"),
        "treffsicherheit": _spec("Treffsicherheit", "rdps"),
        "ueberleben": _spec("Überleben", "mdps"),
    }),
    "schurke": _cls("schurke", "Schurke", {
        "meucheln": _spec("Meucheln", "mdps"),
        "gesetzlosigkeit": _spec("Gesetzlosigkeit", "mdps"),
        "taeuschung": _spec("Täuschung", "mdps"),
    }),
    "priester": _cls("priester", "Priester", {
        "disziplin": _spec("Disziplin", "healer"),
        "heilig": _spec("Heilig", "healer"),
        "schatten": _spec("Schatten", "rdps"),
    }),
    "todesritter": _cls("todesritter", "Todesritter", {
        "blut": _spec("Blut", "tank"),
        "frost": _spec("Frost", "mdps"),
        "unheilig": _spec("Unheilig", "mdps"),
    }),
    "schamane": _cls("schamane", "Schamane", {
        "elementar": _spec("Elementar", "rdps"),
        "verstaerkung": _spec("Verstärkung", "mdps"),
        "wiederherstellung": _spec("Wiederherstellung", "healer"),
    }),
    "magier": _cls("magier", "Magier", {
        "arkan": _spec("Arkan", "rdps"),
        "feuer": _spec("Feuer", "rdps"),
        "frost": _spec("Frost", "rdps"),
    }),
    "hexenmeister": _cls("hexenmeister", "Hexenmeister", {
        "gebrechen": _spec("Gebrechen", "rdps"),
        "daemonologie": _spec("Dämonologie", "rdps"),
        "zerstoerung": _spec("Zerstörung", "rdps"),
    }),
    "moench": _cls("moench", "Mönch", {
        "braumeister": _spec("Braumeister", "tank"),
        "nebelwirker": _spec("Nebelwirker", "healer"),
        "windlaeufer": _spec("Windläufer", "mdps"),
    }),
    "druide": _cls("druide", "Druide", {
        "gleichgewicht": _spec("Gleichgewicht", "rdps"),
        "wildheit": _spec("Wildheit", "mdps"),
        "waechter": _spec("Wächter", "tank"),
        "wiederherstellung": _spec("Wiederherstellung", "healer"),
    }),
    "daemonenjaeger": _cls("daemonenjaeger", "Dämonenjäger", {
        "verwuestung": _spec("Verwüstung", "mdps"),
        "rachsucht": _spec("Rachsucht", "tank"),
        "verschlinger": _spec("Verschlinger", "rdps"),
    }),
    "rufer": _cls("rufer", "Rufer", {
        "verheerung": _spec("Verheerung", "rdps"),
        "bewahrung": _spec("Bewahrung", "healer"),
        "erweckung": _spec("Erweckung", "rdps"),
    }),
}
_WOW_RETAIL_ORDER = [
    "krieger", "paladin", "jaeger", "schurke", "priester", "todesritter",
    "schamane", "magier", "hexenmeister", "moench", "druide",
    "daemonenjaeger", "rufer",
]


# --------------------------------------------------------------------------- #
#  WoW – Classic (Vanilla): 9 Klassen, kein Todesritter/Mönch/DH/Rufer
# --------------------------------------------------------------------------- #
_WOW_CLASSIC_CLASSES: dict[str, dict] = {
    "krieger": _cls("krieger", "Krieger", {
        "waffen": _spec("Waffen", "mdps"),
        "furor": _spec("Furor", "mdps"),
        "schutz": _spec("Schutz", "tank"),
    }),
    "paladin": _cls("paladin", "Paladin", {
        "heilig": _spec("Heilig", "healer"),
        "schutz": _spec("Schutz", "tank"),
        "vergeltung": _spec("Vergeltung", "mdps"),
    }),
    "jaeger": _cls("jaeger", "Jäger", {
        "tierherrschaft": _spec("Tierherrschaft", "rdps"),
        "treffsicherheit": _spec("Treffsicherheit", "rdps"),
        "ueberleben": _spec("Überleben", "rdps"),
    }),
    "schurke": _cls("schurke", "Schurke", {
        "meucheln": _spec("Meucheln", "mdps"),
        "kampf": _spec("Kampf", "mdps"),
        "taeuschung": _spec("Täuschung", "mdps"),
    }),
    "priester": _cls("priester", "Priester", {
        "disziplin": _spec("Disziplin", "healer"),
        "heilig": _spec("Heilig", "healer"),
        "schatten": _spec("Schatten", "rdps"),
    }),
    "schamane": _cls("schamane", "Schamane", {
        "elementar": _spec("Elementar", "rdps"),
        "verstaerkung": _spec("Verstärkung", "mdps"),
        "wiederherstellung": _spec("Wiederherstellung", "healer"),
    }),
    "magier": _cls("magier", "Magier", {
        "arkan": _spec("Arkan", "rdps"),
        "feuer": _spec("Feuer", "rdps"),
        "frost": _spec("Frost", "rdps"),
    }),
    "hexenmeister": _cls("hexenmeister", "Hexenmeister", {
        "gebrechen": _spec("Gebrechen", "rdps"),
        "daemonologie": _spec("Dämonologie", "rdps"),
        "zerstoerung": _spec("Zerstörung", "rdps"),
    }),
    "druide": _cls("druide", "Druide", {
        "gleichgewicht": _spec("Gleichgewicht", "rdps"),
        "wildheit": _spec("Wildheit", "mdps"),
        "wiederherstellung": _spec("Wiederherstellung", "healer"),
    }),
}
_WOW_CLASSIC_ORDER = [
    "krieger", "paladin", "jaeger", "schurke", "priester",
    "schamane", "magier", "hexenmeister", "druide",
]


# --------------------------------------------------------------------------- #
#  WoW – WotLK/Cata-Klassensatz: 10 Klassen (Classic + Todesritter)
# --------------------------------------------------------------------------- #
_WOW_WOTLK_CLASSES: dict[str, dict] = {
    **{k: _WOW_CLASSIC_CLASSES[k] for k in _WOW_CLASSIC_ORDER},
    "todesritter": _cls("todesritter", "Todesritter", {
        "blut": _spec("Blut", "tank"),
        "frost": _spec("Frost", "mdps"),
        "unheilig": _spec("Unheilig", "mdps"),
    }),
    # Wächter (Bär) kommt in WotLK als Tank-Variante der Wildheit dazu.
    "druide": _cls("druide", "Druide", {
        "gleichgewicht": _spec("Gleichgewicht", "rdps"),
        "wildheit": _spec("Wildheit", "mdps"),
        "waechter": _spec("Wächter", "tank"),
        "wiederherstellung": _spec("Wiederherstellung", "healer"),
    }),
}
_WOW_WOTLK_ORDER = [
    "krieger", "paladin", "todesritter", "jaeger", "schurke", "priester",
    "schamane", "magier", "hexenmeister", "druide",
]


# --------------------------------------------------------------------------- #
#  Registrierte Spiele
# --------------------------------------------------------------------------- #
GAMES: dict[str, dict] = {
    "wow_retail": {
        "label": "WoW – Retail",
        "roles": _WOW_ROLES,
        "role_order": _WOW_ROLE_ORDER,
        "classes": _WOW_RETAIL_CLASSES,
        "class_order": _WOW_RETAIL_ORDER,
    },
    "wow_classic": {
        "label": "WoW – Classic (Vanilla)",
        "roles": _WOW_ROLES,
        "role_order": _WOW_ROLE_ORDER,
        "classes": _WOW_CLASSIC_CLASSES,
        "class_order": _WOW_CLASSIC_ORDER,
    },
    "wow_wotlk": {
        "label": "WoW – WotLK/Cata",
        "roles": _WOW_ROLES,
        "role_order": _WOW_ROLE_ORDER,
        "classes": _WOW_WOTLK_CLASSES,
        "class_order": _WOW_WOTLK_ORDER,
    },
}

DEFAULT_GAME = "wow_retail"


# --------------------------------------------------------------------------- #
#  Zugriffshelfer (vom Cog/Dashboard genutzt – nie direkt auf GAMES zugreifen)
# --------------------------------------------------------------------------- #
def list_games() -> list[tuple[str, str]]:
    """[(spiel_id, label), …] in definierter Reihenfolge."""
    return [(gid, g["label"]) for gid, g in GAMES.items()]


def get_game(game_id: str | None) -> dict | None:
    return GAMES.get(game_id or DEFAULT_GAME)


def game_label(game_id: str | None) -> str:
    g = get_game(game_id)
    return g["label"] if g else (game_id or "?")


def role_order(game_id: str) -> list[str]:
    g = get_game(game_id)
    return list(g["role_order"]) if g else []


def role_meta(game_id: str, role_id: str) -> dict[str, str]:
    g = get_game(game_id)
    if not g:
        return {"label": role_id, "emoji": ""}
    return g["roles"].get(role_id, {"label": role_id, "emoji": ""})


def class_order(game_id: str) -> list[str]:
    g = get_game(game_id)
    return list(g["class_order"]) if g else []


def get_class(game_id: str, class_id: str) -> dict | None:
    g = get_game(game_id)
    return g["classes"].get(class_id) if g else None


def class_label(game_id: str, class_id: str) -> str:
    c = get_class(game_id, class_id)
    return c["label"] if c else class_id


def class_color(game_id: str, class_id: str) -> int:
    c = get_class(game_id, class_id)
    return c["color"] if c else 0x99AAB5


def get_spec(game_id: str, class_id: str, spec_id: str | None) -> dict | None:
    c = get_class(game_id, class_id)
    if not c or spec_id is None:
        return None
    return c["specs"].get(spec_id)


def spec_label(game_id: str, class_id: str, spec_id: str | None) -> str:
    s = get_spec(game_id, class_id, spec_id)
    return s["label"] if s else (spec_id or "")


def spec_role(game_id: str, class_id: str, spec_id: str | None) -> str | None:
    """Die Rolle (tank/healer/mdps/rdps), die zu Klasse+Spec gehört."""
    s = get_spec(game_id, class_id, spec_id)
    if s:
        return s["role"]
    # Fallback: erste Spec der Klasse.
    c = get_class(game_id, class_id)
    if c and c["specs"]:
        return next(iter(c["specs"].values()))["role"]
    return None


def specs_of(game_id: str, class_id: str) -> list[tuple[str, str, str]]:
    """[(spec_id, label, role), …] für die Spec-Auswahl einer Klasse."""
    c = get_class(game_id, class_id)
    if not c:
        return []
    return [(sid, s["label"], s["role"]) for sid, s in c["specs"].items()]


def default_spec(game_id: str, class_id: str) -> str | None:
    c = get_class(game_id, class_id)
    if not c or not c["specs"]:
        return None
    return next(iter(c["specs"].keys()))


def is_valid(game_id: str, class_id: str | None = None, spec_id: str | None = None) -> bool:
    g = get_game(game_id)
    if not g:
        return False
    if class_id is None:
        return True
    c = g["classes"].get(class_id)
    if c is None:
        return False
    if spec_id is None:
        return True
    return spec_id in c["specs"]
