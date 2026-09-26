"""Harness für welcome + warns: live_harness (echter WebCore, Fake-Discord mit echten Kanal-Unterklassen)
+ die beiden neuen Cogs. Rollen-Rechte: Support (Lena, 11) = Bearbeiten, Moderator (Tom, 12) = Ansehen.
Start: python tests/wl_harness.py [port]   (mit Beispieldaten)
"""
import live_harness as L
import discord
H = L.H

SENT_DMS = []


def _dm_sender(member):
    async def send(content=None, *, embed=None, embeds=None, file=None, allowed_mentions=None, **kw):
        if getattr(member, "dm_closed", False):
            raise L.forbidden()
        embeds = list(embeds or ([embed] if embed else []))
        L.validate_message(content, embeds, None, [file] if file else [])
        SENT_DMS.append((member.id, content, embeds))
        return None
    return send


def patch_members(bot):
    import datetime
    for g in bot.guilds:
        g.owner_id = 1
        g.owner = g.get_member(1)
        for m in g.members:
            if getattr(m, "_wl_patched", False):
                continue
            m._wl_patched = True
            m.send = _dm_sender(m)
            m.created_at = datetime.datetime(2023, 5, 1, tzinfo=datetime.timezone.utc)
            m.guild_permissions = discord.Permissions.none() if m.id != 1 else discord.Permissions.all()
        if g.me is not None:
            g.me.guild_permissions = discord.Permissions.all()


async def make_app():
    wc, bot, app = await L.make_app()
    patch_members(bot)
    from rc.welcome.welcome import Welcome
    classes = [Welcome]
    try:
        from rc.warns.warns import Warns
        classes.append(Warns)
    except ImportError:
        pass
    for cls in classes:
        c = cls(bot); bot._cogs[cls.__name__] = c; c._register_dashboard(wc)
    await wc.config.role_perms.set({"1000": {"1101": {"welcome": "edit", "warnings": "edit"},
                                             "1102": {"welcome": "view", "warnings": "view"}}})
    return wc, bot, app


async def seed(bot):
    g = bot.guilds[0]
    wl = bot._cogs["Welcome"].config.guild(g)
    await wl.welcome_enabled.set(True); await wl.welcome_channel.set(g.text_channels[0].id)
    await wl.welcome_mode.set("embed"); await wl.card_enabled.set(True)
    await wl.leave_enabled.set(True)   # ohne Kanal -> Hinweis
    wa = bot._cogs.get("Warns")
    if wa is None:
        return
    await wa.config.guild(g).mod_roles.set([1102]); await wa.config.guild(g).log_channel.set(g.text_channels[3].id)
    await wa.config.guild(g).timeout_at.set(3); await wa.config.guild(g).kick_at.set(6)
    async def timeout(self, until, reason=None): pass
    H.Member.timeout = timeout
    tom, kai, mia, lena = (g.get_member(i) for i in (12, 13, 14, 11))
    await wa.add_warning(g, kai, tom, "Spam im allgemeinen Chat", 1)
    await wa.add_warning(g, mia, tom, "Beleidigung im Voice-Channel", 2)
    await wa.add_warning(g, kai, tom, "Werbung per DM an Mitglieder – trotz Hinweis in den Regeln", 2)
    await wa.add_warning(g, lena, g.get_member(1), "Falscher Kanal", 1)
    await wa.revoke(g, 4, g.get_member(1))
    await wa.add_warning(g, kai, g.get_member(1), "Test <script>alert(1)</script>", 1)


async def make_demo():
    wc, bot, app = await make_app()
    await seed(bot)
    return wc, bot, app


if __name__ == "__main__":
    H.main(make_demo)
