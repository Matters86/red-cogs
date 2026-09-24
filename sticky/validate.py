"""Reine Prüf-Logik für Sticky-Datensätze (ohne discord-Abhängigkeit, separat testbar)."""

from __future__ import annotations

# Discord-Limits: Nachrichtentext 2000, Embed-Beschreibung 4096 Zeichen.
TEXT_MAX = 2000
EMBED_TEXT_MAX = 4096


def validate_sticky(entry: dict) -> str | None:
    """Prüft einen Sticky-Datensatz gegen Discord-Limits. Rückgabe: Fehlertext (deutsch) oder None."""
    text = entry.get("text") or ""
    if entry.get("mode") == "embed":
        if len(text) > EMBED_TEXT_MAX:
            return f"Embed-Text zu lang (max. {EMBED_TEXT_MAX} Zeichen)"
        if len(entry.get("embed_title") or "") > 256:
            return "Embed-Titel zu lang (max. 256 Zeichen)"
        if len(entry.get("embed_footer") or "") > 2048:
            return "Embed-Footer zu lang (max. 2048 Zeichen)"
        img = (entry.get("embed_image") or "").strip()
        if img and not img.lower().startswith(("http://", "https://")):
            return "Bild-URL muss mit http:// oder https:// beginnen"
    elif len(text) > TEXT_MAX:
        return f"Text zu lang (max. {TEXT_MAX} Zeichen)"
    if entry.get("webhook"):
        name = (entry.get("webhook_name") or "").strip()
        if len(name) > 80:
            return "Webhook-Name zu lang (max. 80 Zeichen)"
        if name and any(bad in name.lower() for bad in ("discord", "clyde")):
            return "Webhook-Name darf „discord“/„clyde“ nicht enthalten (Discord lehnt das ab)"
        avatar = (entry.get("webhook_avatar") or "").strip()
        if avatar and not avatar.lower().startswith(("http://", "https://")):
            return "Avatar-URL muss mit http:// oder https:// beginnen"
    return None
