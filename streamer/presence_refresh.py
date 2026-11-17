"""Explizite Gateway-Präsenzabfragen mit kurzlebigen Snapshots im Arbeitsspeicher.

``query_members(..., presences=True)`` kann aktuelle Aktivitäten liefern, ohne
bestehende Memberobjekte im discord.py-Cache zu ersetzen. Deshalb werden nur
deren Aktivitäten hier übernommen. Rollenmitgliedschaft bleibt Sache des
normalen Guild-Caches. Keine dieser Daten wird in Config oder Dateien abgelegt.
"""
from __future__ import annotations

import asyncio


FORCE_INTERVAL = 30
BACKGROUND_INTERVAL = 60
MAX_AGE = 120
QUERY_TIMEOUT = 20
BATCH_SIZE = 100


class PresenceRefresh:
    def __init__(self, bot, clock):
        self.bot = bot
        self._clock = clock
        self._states = {}
        self._locks = {}
        self._generations = {}
        self._epoch = 0

    @staticmethod
    def _gid(guild):
        return int(guild.id)

    def enabled(self, guild):
        return bool(self._states.get(self._gid(guild), {}).get("enabled"))

    def checkpoint(self, guild):
        """Eine vor asynchronen Config-Zugriffen erfasste Rollen-Generation."""
        return self._epoch, self._generations.get(self._gid(guild), 0)

    def status(self, guild):
        state = self._states.get(self._gid(guild))
        if not state or not state["enabled"]:
            return ""
        if state["warning"]:
            return state["warning"]
        if state["last_success"] is None:
            return "Der Discord-Status wird noch neu geladen. Vorhandene Meldungen bleiben erhalten."
        if self._clock() - state["last_success"] > MAX_AGE:
            return "Der zuletzt geladene Discord-Status ist veraltet. Vorhandene Meldungen bleiben bis zur nächsten sicheren Prüfung erhalten."
        return ""

    def activities(self, member):
        state = self._states.get(self._gid(member.guild))
        if state and state["enabled"] and any(r.id == state["role_id"] for r in member.roles):
            snapshot = state["snapshots"].get(member.id)
            if snapshot is not None:
                return snapshot
        return tuple(getattr(member, "activities", ()) or ())

    def invalidate(self, guild):
        gid = self._gid(guild)
        self._generations[gid] = self._generations.get(gid, 0) + 1
        self._states.pop(gid, None)

    def observe(self, member):
        """Ein neuer Gateway-Event ist aktueller als eine bereits laufende Abfrage."""
        state = self._states.get(self._gid(member.guild))
        if not state or not state["enabled"]:
            return
        if not any(r.id == state["role_id"] for r in member.roles):
            self.remove(member)
            return
        state["versions"][member.id] = state["versions"].get(member.id, 0) + 1
        state["snapshots"][member.id] = tuple(getattr(member, "activities", ()) or ())

    def remove(self, member):
        state = self._states.get(self._gid(member.guild))
        if state and (member.id in state["snapshots"] or member.id in state["versions"]):
            state["snapshots"].pop(member.id, None)
            state["versions"][member.id] = state["versions"].get(member.id, 0) + 1

    def clear(self):
        self._epoch += 1
        self._states.clear()
        self._generations.clear()
        self._locks.clear()

    def _current(self, gid, state, token):
        return (self._states.get(gid) is state
                and token == (self._epoch, self._generations.get(gid, 0)))

    def _fail(self, gid, state, token, message):
        if self._current(gid, state, token):
            state["warning"] = message
            state["retry_at"] = self._clock() + BACKGROUND_INTERVAL
        return {"ok": False, "message": message}

    def _unavailable(self, guild):
        intents = getattr(self.bot, "intents", None)
        if not getattr(intents, "members", False) or not getattr(intents, "presences", False):
            return "Discord-Status kann nicht geladen werden: Presence Intent und Server Members Intent müssen aktiviert sein."
        if not getattr(self.bot, "is_ready", lambda: False)() or getattr(guild, "unavailable", False):
            return "Discord ist noch nicht verbunden. Der Status kann gerade nicht neu geladen werden."
        if not getattr(guild, "chunked", False):
            return "Die Mitgliederliste ist noch nicht vollständig geladen. Bitte den Discord-Status später erneut prüfen."
        return ""

    async def refresh(self, guild, role, *, force=False, checkpoint=None):
        """Aktuelle Rollen-Präsenzen abfragen; Fehler sind niemals Offline-Beweise."""
        gid = self._gid(guild)
        if (role is None or getattr(getattr(role, "guild", None), "id", None) != guild.id
                or role.is_default() or guild.get_role(role.id) is None):
            return {"ok": False, "message": "Bitte zuerst eine gültige Rolle dieses Servers für die Beobachtung auswählen."}
        lock = self._locks.setdefault(gid, asyncio.Lock())
        async with lock:
            if checkpoint is not None and checkpoint != self.checkpoint(guild):
                return {"ok": False, "message": "Die Rollen-Einstellung wurde während der Prüfung geändert. Bitte erneut prüfen."}
            state = self._states.get(gid)
            if state and state["role_id"] != role.id:
                self.invalidate(guild)
                state = None
            if not state and not force:
                return {"ok": True, "message": "Der Discord-Status wurde noch nicht ausdrücklich neu geladen."}
            if state is None:
                state = {"enabled": True, "role_id": role.id, "snapshots": {}, "versions": {},
                         "last_attempt": None, "last_success": None, "retry_at": 0, "warning": ""}
                self._states[gid] = state
            token = (self._epoch, self._generations.get(gid, 0))
            now = self._clock()
            if now < state["retry_at"]:
                return {"ok": False, "message": state["warning"] or "Bitte kurz warten und die Prüfung erneut starten."}
            unavailable = self._unavailable(guild)
            if unavailable:
                state["last_attempt"] = now
                return self._fail(gid, state, token, unavailable)
            interval = FORCE_INTERVAL if force else BACKGROUND_INTERVAL
            if state["last_attempt"] is not None and now - state["last_attempt"] < interval:
                warning = self.status(guild)
                return {"ok": not bool(warning), "message": warning or "Der Discord-Status wurde gerade geprüft; vorhandene Daten werden verwendet."}
            state["last_attempt"] = now
            requested = [m.id for m in role.members if not getattr(m, "bot", False)]
            # Auch die allererste Abfrage kann von Rollen-/Presence-Events
            # überholt werden, bevor für die ID ein Snapshot existiert.
            for uid in requested:
                state["versions"].setdefault(uid, 0)
            versions = dict(state["versions"])

            async def query():
                received = {}
                for offset in range(0, len(requested), BATCH_SIZE):
                    part = requested[offset:offset + BATCH_SIZE]
                    members = await guild.query_members(user_ids=part, presences=True, cache=False, limit=BATCH_SIZE)
                    if not isinstance(members, (tuple, list)):
                        raise ValueError("invalid response")
                    for member in members:
                        if (getattr(getattr(member, "guild", None), "id", None) != guild.id
                                or member.id not in part or member.id in received):
                            raise ValueError("invalid member")
                        activities = getattr(member, "activities", None)
                        if not isinstance(activities, (tuple, list)):
                            raise ValueError("invalid activities")
                        received[member.id] = tuple(activities)
                return received

            try:
                received = await asyncio.wait_for(query(), timeout=QUERY_TIMEOUT)
            except asyncio.CancelledError:
                self._fail(gid, state, token, "Die Discord-Status-Abfrage wurde abgebrochen. Vorhandene Meldungen bleiben bis zur nächsten Prüfung erhalten.")
                raise
            except Exception:
                return self._fail(gid, state, token,
                                  "Der Discord-Status konnte nicht vollständig neu geladen werden. Vorhandene Meldungen bleiben erhalten; die Prüfung wird wiederholt.")
            if not self._current(gid, state, token):
                return {"ok": False, "message": "Die Rollen-Einstellung wurde während der Prüfung geändert. Bitte erneut prüfen."}
            if guild.get_role(role.id) is None:
                return self._fail(gid, state, token, "Die beobachtete Rolle existiert nicht mehr.")
            current_ids = {m.id for m in role.members if not getattr(m, "bot", False)}
            if current_ids - received.keys():
                return self._fail(gid, state, token,
                                  "Discord hat nicht alle Rollenmitglieder zurückgemeldet. Vorhandene Meldungen bleiben bis zur vollständigen Prüfung erhalten.")
            merged = {uid: value for uid, value in state["snapshots"].items() if uid in current_ids}
            for uid in current_ids:
                if state["versions"].get(uid, 0) == versions.get(uid, 0):
                    merged[uid] = received[uid]
            state.update(snapshots=merged,
                         versions={uid: version for uid, version in state["versions"].items() if uid in current_ids},
                         last_success=self._clock(), retry_at=0, warning="")
            noun = "Rollenmitglied" if len(current_ids) == 1 else "Rollenmitglieder"
            return {"ok": True, "message": f"Discord-Status für {len(current_ids)} {noun} neu geladen."}
