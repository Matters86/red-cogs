"""Kurzlebige Formularentwürfe: getrennt nach Sitzung, Server und Formular."""
import time

TTL = 3600
MAX_DRAFTS = 200


def _key(request, guild_id, form):
    return (request.get("webcore_csrf", ""), str(guild_id), str(form))


def remember(cog, request, guild_id, form, values):
    drafts = cog.__dict__.setdefault("_ux_drafts", {})
    now = time.monotonic()
    for key in [key for key, (stamp, _) in drafts.items() if now - stamp > TTL]:
        drafts.pop(key, None)
    while len(drafts) >= MAX_DRAFTS:
        drafts.pop(next(iter(drafts)))
    drafts[_key(request, guild_id, form)] = (now, dict(values))


def restore(cog, request, guild_id, form):
    item = cog.__dict__.get("_ux_drafts", {}).get(_key(request, guild_id, form))
    return dict(item[1]) if item and time.monotonic() - item[0] <= TTL else {}


def discard(cog, request, guild_id, form):
    cog.__dict__.get("_ux_drafts", {}).pop(_key(request, guild_id, form), None)
