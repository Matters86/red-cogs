"""Öffentliche Live-Sitzungen für stabile Erkennungszeit und einmalige Benachrichtigung."""


def reconcile(conf, snapshots, role_status, now):
    entries = dict(conf.get("notification_state") or {})
    observed = {}
    sources = conf.get("sources") or {}
    for origin, snapshot in snapshots.items():
        if snapshot is None:
            continue
        for key, streams in snapshot.items():
            if origin != "discord" and (key not in sources or not sources[key].get("enabled", True)):
                continue
            for stream in streams:
                url = stream.get("url")
                if not url:
                    continue
                # Plattform-IDs sind genauer als eine Discord-Präsenz derselben URL.
                if url not in observed or not key.startswith("discord:"):
                    observed[url] = stream
    for url, entry in list(entries.items()):
        source_id = entry.get("source_id", "")
        if source_id.startswith("discord:"):
            authoritative = (role_status.get("ready") and role_status.get("role_name")
                             and role_status.get("members", 0) > 0
                             and entry.get("watch_role_id") == conf.get("watched_role_id"))
            live = {s.get("url") for streams in (snapshots.get("discord") or {}).values() for s in streams}
        else:
            snapshot = snapshots.get(entry.get("provider"))
            authoritative = snapshot is not None and source_id in snapshot
            live = {s.get("url") for s in (snapshot or {}).get(source_id, [])}
        # Discord besitzt keine Broadcast-ID. Kurze Präsenz-Aussetzer gehören
        # deshalb noch zur selben Sitzung. API-IDs bleiben auch nach Offline
        # gemerkt: Erst eine neue Broadcast-ID darf erneut benachrichtigen.
        role_ended = (source_id.startswith("discord:") and authoritative and url not in live
                      and now - entry.get("last_seen", now) >= 300)
        if role_ended or (url not in observed and now - entry.get("last_seen", now) > 7 * 86400):
            entries.pop(url, None)
    records = conf.get("state") or {}
    for url, stream in observed.items():
        entry = entries.get(url)
        role_stream = stream["source_key"].startswith("discord:")
        if (entry is not None and not role_stream and entry.get("stream_id") != "live"
                and entry.get("stream_id") != stream["id"]):
            entry = None
        if entry is None:
            previous = next((r for r in records.values() if r.get("stream", {}).get("url") == url
                             and (role_stream or r.get("stream", {}).get("id") == stream["id"])), {})
            entry = {"source_id": stream["source_key"], "provider": stream["provider"],
                     "stream_id": stream["id"], "first_seen": previous.get("first_seen") or previous.get("pending_since") or now,
                     "announced": bool(previous.get("message_id") or previous.get("announced")),
                     "watch_role_id": conf.get("watched_role_id") if role_stream else None}
            entries[url] = entry
        elif not role_stream:
            entry.update(source_id=stream["source_key"], provider=stream["provider"], stream_id=stream["id"])
        else:
            # Dieselbe URL kann nach Entfernen/Pausieren einer API-Quelle über
            # die Rolle weiterlaufen. Die letzte bekannte API-ID bleibt erhalten.
            entry.update(source_id=stream["source_key"], watch_role_id=conf.get("watched_role_id"))
        entry["last_seen"] = now
    return entries
