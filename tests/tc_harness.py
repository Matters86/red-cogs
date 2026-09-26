"""tc_harness – Tickets + Changelog: echter WebCore mit Mein-Bereich + öffentlicher API.

Basis: live_harness.py (Fake-Kanäle bestehen isinstance-Prüfungen, send/edit in L.LOG, Discord-Limits)
und das Login-/Portal-Muster aus wcm_harness.py (X-Test-User-Header, 1 = Owner).
Zusätzlich:
* Nutzer 15 „Nina“ (normales Mitglied auf 1000), 21 „Ben“ (nur 2000)
* Kanal #team-intern (1008), den normale Mitglieder NICHT sehen (Panel dort ist für sie unsichtbar)
* Member.add_roles/remove_roles (Inhaber-Rolle) werden in ROLE_LOG aufgezeichnet
Nutzung:  import tc_harness as T; wc, bot, app, tk, cl = await T.make_app()
Server:   python tests/tc_harness.py [port]   (mit Beispieldaten aus tc_seed.py)
"""
import live_harness as L   # patcht wc_harness (LiveGuild/LiveBot)
H = L.H
import discord

ROLE_LOG = []


async def _add_roles(self, *roles, reason=None):
    ROLE_LOG.append(("add", self.id, [r.id for r in roles]))
    for r in roles:
        if r not in self.roles:
            self.roles.append(r)


async def _remove_roles(self, *roles, reason=None):
    ROLE_LOG.append(("remove", self.id, [r.id for r in roles]))
    self.roles = [r for r in self.roles if r not in roles]

H.Member.add_roles = _add_roles
H.Member.remove_roles = _remove_roles
H.Member.__str__ = lambda m: m.name
# Transcripts brauchen created_at an Nachrichten (live_harness hat es nicht)
from datetime import datetime as _dt, timezone as _tz
L.FakeMessage.created_at = property(lambda m: _dt(2026, 9, 25, 12, 0, tzinfo=_tz.utc))


async def _chan_edit(self, *, reason=None, **kw):
    """Wie live_harness, aber ``category``/``overwrites`` (Ticket schließen/archivieren) werden verstanden."""
    if "edit_channel" in self.forbid:
        raise L.forbidden()
    if "category" in kw:
        cat = kw.pop("category")
        self.category_id = cat.id if cat is not None else None
    if "overwrites" in kw:
        self._tc_overwrites = {getattr(k, "id", k): v for k, v in kw.pop("overwrites").items()}
    for k, v in kw.items():
        setattr(self, k, v)
    L.log("channel_edit", self, **{k: str(v) for k, v in kw.items()},
          category=self.category_id, overwrites=sorted(getattr(self, "_tc_overwrites", {})))
    return self
L._SendMixin.edit = _chan_edit


def _overwrites_for(self, obj):
    return discord.PermissionOverwrite()


async def _set_permissions(self, target, *, overwrite=None, reason=None, **kw):
    L.log("set_permissions", self, target=getattr(target, "id", None), overwrite=str(overwrite))
L.FakeText.overwrites_for = _overwrites_for
L.FakeText.set_permissions = _set_permissions


def build_world():
    guilds = H.build_world()
    g1, g2 = guilds
    g1.members.append(H.Member(g1, 15, "Nina", []))
    g2.members.append(H.Member(g2, 21, "Ben", []))
    hidden = L.FakeText.make(g1, g1.id + 8, "team-intern", g1.categories[0], 8)

    def perms(obj):
        p = discord.Permissions.all()
        if not getattr(getattr(obj, "guild_permissions", None), "administrator", False) and getattr(obj, "id", 0) != 999:
            p.view_channel = False
        return p
    hidden.permissions_for = perms
    g1.text_channels.append(hidden)
    return guilds


async def make_bot():
    guilds = build_world()
    return H.FakeBot(guilds)


async def make_app():
    bot = await make_bot()
    wc = await H.make_webcore(bot)   # redirect http: Sitzungscookie ohne Secure (Tests über http)
    # Erst NACH dem Start: öffentliche Adresse für die Changelog-Karte (Cookie-Flag bleibt ohne Secure)
    await wc.config.redirect_uri.set("https://dash.example.org/callback")
    from rc.tickets.tickets import Tickets
    from rc.changelog.changelog import Changelog
    tk = Tickets(bot); bot._cogs["Tickets"] = tk; tk._register_dashboard(wc)
    cl = Changelog(bot); bot._cogs["Changelog"] = cl; cl._register_dashboard(wc)
    await wc.config.member_portal.set({"1000": True})
    return wc, bot, wc.app, tk, cl


# --------------------------------------------------------------------------- #
#  Fake-Interactions (Buttons/Modals) – zeichnen alle Antworten auf
# --------------------------------------------------------------------------- #
class Resp:
    def __init__(self, rec):
        self.rec = rec; self._done = False; self.modal = None

    def is_done(self):
        return self._done

    async def send_message(self, content=None, *, ephemeral=False, view=None, **kw):
        self._done = True; self.rec.append(["send_message", content, ephemeral, bool(view)])

    async def send_modal(self, modal):
        self._done = True; self.modal = modal
        self.rec.append(["modal", modal.title, [[c.label, c.required, str(c.style), c.max_length, c.placeholder]
                                                for c in modal.children]])

    async def defer(self, **kw):
        self._done = True; self.rec.append(["defer", sorted(kw.items())])

    async def edit_message(self, **kw):
        self._done = True; self.rec.append(["edit_message", kw.get("content")])


class Followup:
    def __init__(self, rec): self.rec = rec

    async def send(self, content=None, *, ephemeral=False, **kw):
        self.rec.append(["followup", content, ephemeral])


class Inter:
    def __init__(self, rec, guild, user, channel=None, custom_id="", values=None):
        self.type = discord.InteractionType.component
        self.data = {"custom_id": custom_id, **({"values": values} if values else {})}
        self.guild = guild; self.user = user; self.channel = channel
        self.response = Resp(rec); self.followup = Followup(rec)


async def make_demo():
    wc, bot, app, tk, cl = await make_app()
    import tc_seed
    await tc_seed.seed(bot, tk, cl)
    return wc, bot, app, tk, cl


if __name__ == "__main__":
    H.main(make_demo)
