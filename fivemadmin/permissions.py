"""Exact role grants for the existing panel capabilities; no runtime side effects."""
import hashlib
import json

PERMISSION_CATALOG = [
    {"id": "view_players", "group": "Spieler", "label": "Spieler anzeigen und suchen"},
    {"id": "view_inventory", "group": "Spieler", "label": "Inventar einsehen"},
    {"id": "teleport", "group": "Spieler", "label": "Teleport zu Spielern oder Koordinaten"},
    {"id": "heal", "group": "Spieler", "label": "Heilen"},
    {"id": "revive", "group": "Spieler", "label": "Wiederbeleben"},
    {"id": "message", "group": "Spieler", "label": "Private Nachricht senden"},
    {"id": "kick", "group": "Moderation", "label": "Vom Server entfernen (Kick)"},
    {"id": "ban", "group": "Moderation", "label": "Sperren verwalten und aufheben"},
    {"id": "notes", "group": "Moderation", "label": "Spielerakten und Notizen"},
    {"id": "setjob", "group": "Moderation", "label": "Job und Gang ändern"},
    {"id": "car_to_garage", "group": "Fahrzeuge", "label": "Fahrzeugliste und einzelnes Einparken"},
    {"id": "park_all", "group": "Fahrzeuge", "label": "Alle geeigneten Fahrzeuge einparken"},
    {"id": "support_vehicles", "group": "Support", "label": "Fahrzeugakte und Fahrzeugsuche"},
    {"id": "support_cases", "group": "Support", "label": "Supportfälle, Übergaben und Fotos"},
    {"id": "support_diagnostics", "group": "Support", "label": "Supportdiagnose"},
    {"id": "money", "group": "Wirtschaft", "label": "Geld geben und entfernen"},
    {"id": "items", "group": "Wirtschaft", "label": "Gegenstände geben und entfernen"},
    {"id": "view_stats", "group": "Wirtschaft", "label": "Wirtschaftsstatistik einsehen"},
    {"id": "announce", "group": "Server", "label": "Serveransagen senden"},
    {"id": "server_status", "group": "Server", "label": "Serverstatus und Diagnose"},
    {"id": "view_logs", "group": "Protokolle", "label": "Ereignisse einsehen"},
    {"id": "audit", "group": "Protokolle", "label": "Aktionsprotokoll und Audit einsehen"},
]
PERMISSION_IDS = frozenset(row["id"] for row in PERMISSION_CATALOG)


def validate_permissions(value):
    if (not isinstance(value, list) or len(value) > len(PERMISSION_IDS)
            or any(not isinstance(key, str) or key not in PERMISSION_IDS for key in value)
            or len(set(value)) != len(value)):
        raise ValueError("Ungültige oder doppelte Funktionsrechte.")
    return sorted(value)


def role_permissions(value, presets):
    if isinstance(value, str):
        return set(presets.get(value, ()))
    if isinstance(value, dict) and set(value) == {"permissions"}:
        try:
            return set(validate_permissions(value["permissions"]))
        except ValueError:
            pass
    return set()


def role_revision(guild_id, role_id, value):
    payload = json.dumps([str(guild_id), str(role_id), value],
                         ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
