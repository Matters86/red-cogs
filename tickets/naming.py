"""Gemeinsame Ticketnamen für Discord und Dashboard; keine Seiteneffekte."""
import re

NAME_PRESETS = {
    "reason_user_num": "{reason}-{user}-{num}",
    "user_reason_num": "{user}-{reason}-{num}",
    "ticket_num": "ticket-{num}",
}
PLACEHOLDERS = {"reason", "user", "display", "num", "id"}
_FIELD = re.compile(r"\{(\w+)\}")
_TRANSLIT = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
MAX_NAME = 90


def _required_length(value):
    slug = re.sub(r"[^a-z0-9\-_]+", "-", value.lower().translate(_TRANSLIT).strip())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return max(len(value), len(slug))


def name_format(conf):
    if conf.get("name_template_mode", "legacy") != "template":
        return "legacy"
    return next((key for key, value in NAME_PRESETS.items() if value == conf.get("name_template")), "custom")


def parse_name_settings(data, conf):
    """Alte/teilweise Formulare dürfen die bisherige Namenswahl nicht zurücksetzen."""
    mode = conf.get("name_template_mode", "legacy")
    template = conf.get("name_template") or "ticket-{num}"
    selected = data.get("name_format")
    if selected is None:
        candidate = str(data.get("name_template") or template).strip()
        if candidate == template:
            return mode, template
        selected = "custom"
    if selected == "legacy":
        return "legacy", template
    if selected in NAME_PRESETS:
        return "template", NAME_PRESETS[selected]
    if selected != "custom":
        raise ValueError("Bitte ein gültiges Format für Ticketnamen wählen.")
    candidate = str(data.get("name_template") or "").strip()
    fields = _FIELD.findall(candidate)
    remaining = _FIELD.sub("", candidate)
    if not candidate or len(candidate) > MAX_NAME or any(ord(c) < 32 for c in candidate):
        raise ValueError("Die Namensvorlage muss 1 bis 90 Zeichen lang sein und darf keine Zeilenumbrüche enthalten.")
    if any(field not in PLACEHOLDERS for field in fields) or "{" in remaining or "}" in remaining:
        raise ValueError("Erlaubte Platzhalter: {reason}, {user}, {display}, {num} und {id}.")
    if "num" not in fields:
        raise ValueError("Bitte {num} für die eindeutige Ticketnummer in der Vorlage verwenden.")
    return "template", candidate


def ticket_base_name(conf, reason, num, member):
    label = str((reason or {}).get("label") or "ticket")
    username = str(getattr(member, "name", None) or getattr(member, "id", "user"))
    template = conf.get("name_template") or "ticket-{num}"
    if conf.get("name_template_mode", "legacy") != "template" and (reason or {}).get("label"):
        template = "{reason}-{num}"
    values = {"reason": label, "user": username,
              "display": str(getattr(member, "display_name", None) or username),
              "num": str(num), "id": str(getattr(member, "id", ""))}

    def fill():
        return _FIELD.sub(lambda match: values.get(match.group(1), match.group(0)), template)

    result = fill()
    # Nummer und feste Bestandteile erhalten; lange Gründe/Namen zuerst kürzen.
    while _required_length(result) > MAX_NAME:
        candidates = [key for key in ("reason", "user", "display") if "{" + key + "}" in template and len(values[key]) > 1]
        if not candidates:
            break
        key = max(candidates, key=lambda item: len(values[item]) * template.count("{" + item + "}"))
        values[key] = values[key][:-1]
        result = fill()
    if _required_length(result) > MAX_NAME:
        # Auch ungewöhnliche Altvorlagen bleiben verwendbar; eine enthaltene Nummer
        # darf durch die Discord-Längenbegrenzung nicht versehentlich verschwinden.
        suffix = "-" + str(num) if "{num}" in template else ""
        prefix = result[:max(0, MAX_NAME - len(suffix))]
        while prefix and _required_length(prefix + suffix) > MAX_NAME:
            prefix = prefix[:-1]
        result = prefix + suffix
    return result or f"ticket-{num}"
