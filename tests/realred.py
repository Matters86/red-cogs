"""Smoke-Tests gegen das echte Red 3.5 (Config mit JSON-Treiber, echte commands/pagify).

Lädt jeden Cog-Ordner (mit info.json) als Paket – scheitert ein Import, schlägt die Suite fehl.
"""
import asyncio, importlib, sys, types
import bootstrap


class FakeBot:
    guilds = []
    user = types.SimpleNamespace(id=999)
    owner_ids = {1}
    def get_cog(self, name): return None
    async def cog_disabled_in_guild(self, cog, guild): return False
    async def is_owner(self, u): return getattr(u, "id", None) == 1
    def dispatch(self, *a, **k): pass
    loop = None


async def main():
    bot = FakeBot()
    # 1) Alle Cogs laden (setup-Funktion) – echter Red-Import, Config, Dekoratoren
    failed = []
    dirs = bootstrap.cog_dirs()
    assert len(dirs) >= 17, [d.name for d in dirs]
    for d in dirs:
        try:
            mod = importlib.import_module(f"rc.{d.name}")
            assert callable(getattr(mod, "setup", None)), f"{d.name}: keine setup()-Funktion"
        except Exception as e:
            failed.append((d.name, repr(e)))
    print("Import mit echtem Red:", failed or f"alle {len(dirs)} OK")
    assert not failed, failed

    # 1b) Repo-Regeln: info.json gültig, identifier eindeutig, keine Namenskollision
    import json, pkgutil, re
    import redbot.cogs
    core_cogs = {m.name for m in pkgutil.iter_modules(redbot.cogs.__path__)}
    ids = {}
    for d in dirs:
        info = json.loads((d / "info.json").read_text(encoding="utf-8"))
        assert info.get("name") and info.get("short") and "end_user_data_statement" in info, d.name
        assert d.name not in sys.stdlib_module_names and d.name not in core_cogs, \
            f"Cog-Ordner {d.name!r} heißt wie ein Python-Standardmodul oder Red-Core-Cog"
        for f in d.rglob("*.py"):
            for m in re.finditer(r"(?:identifier=|IDENTIFIER\s*=\s*)(0x[0-9A-Fa-f]+|\d+)", f.read_text(encoding="utf-8")):
                ids.setdefault(int(m.group(1), 0), set()).add(d.name)
    dup = {k: v for k, v in ids.items() if len(v) > 1}
    assert not dup, f"identifier doppelt vergeben: {dup}"
    # CONVENTIONS.md: Tabelle „Vergebene identifier“ muss zum Code passen
    conv = (bootstrap.ROOT / "CONVENTIONS.md").read_text(encoding="utf-8")
    table = {m.group(1): int(m.group(2)) for m in re.finditer(r"^\| (\w+) \| (\d+)", conv, re.M)}
    code = {name: i for i, names in ids.items() for name in names}
    missing = {n: i for n, i in code.items() if table.get(n) != i}
    assert not missing, f"CONVENTIONS.md: identifier fehlen/abweichend: {missing}"
    print(f"info.json gültig, {len(ids)} identifier eindeutig und in CONVENTIONS.md, "
          "keine Namenskollision mit stdlib/Red-Core")

    # 2) pagify mit dem jetzt korrekten Keyword
    from redbot.core.utils.chat_formatting import pagify
    list(pagify("a\nb", delims=["\n"], page_length=1900))
    try:
        list(pagify("a\nb", delimiters=["\n"], page_length=1900))
        raise AssertionError("pagify(delimiters=) ging?! – Red-API geändert")
    except TypeError:
        print("Bestätigt: pagify(delimiters=...) wirft TypeError (alter raid-list-Bug)")
    # Kein Cog darf pagify mit dem falschen Keyword aufrufen
    bad = [str(f.relative_to(bootstrap.ROOT)) for d in bootstrap.cog_dirs() for f in d.rglob("*.py")
           if "delimiters=" in f.read_text(encoding="utf-8")]
    assert not bad, f"pagify(delimiters=...) in {bad}"

    # 3) Instanzen mit echtem Config
    from rc.tickets.tickets import Tickets
    from rc.raidhelper.raidhelper import RaidHelper
    from rc.poll.poll import Poll
    from rc.guard.guard import Guard
    from rc.sticky.sticky import Sticky
    from rc.autorole.autorole import Autorole
    from rc.onlyimagevideo.onlyimagevideo import OnlyImageVideo
    from rc.autoroom.autoroom import AutoRoom
    from rc.organigram.organigram import Organigram
    from rc.changelog.changelog import Changelog
    from rc.commands.commands import Commands
    cogs = {}
    for cls in (Tickets, RaidHelper, Poll, Guard, Sticky, Autorole, OnlyImageVideo, AutoRoom, Organigram, Changelog, Commands):
        cogs[cls.__name__] = cls(bot)
    print("Instanziiert:", ", ".join(cogs))

    g = types.SimpleNamespace(id=4242)
    # raidhelper: parallele IDs eindeutig
    rh = cogs["RaidHelper"]
    ids = await asyncio.gather(*(rh._next_id(g) for _ in range(20)))
    assert len(set(ids)) == 20, ids
    print("raidhelper _next_id: 20 parallele IDs eindeutig")
    # onlyimagevideo-Zähler atomar (echtes get_lock)
    oiv = cogs["OnlyImageVideo"]
    counter = oiv.config.guild(g).deleted_total
    async def inc():
        async with counter.get_lock():
            await counter.set(int(await counter()) + 1)
    await asyncio.gather(*(inc() for _ in range(50)))
    assert await counter() == 50
    print("Zähler unter get_lock: 50/50")
    # tickets: echte Config, Doppel-Schließen
    tk = cogs["Tickets"]
    async with tk.config.guild(g).tickets() as t:
        t["100"] = {"num": 1, "owner_id": 5, "status": "open"}
    calls = []
    async def fake_locked(guild, channel, record, closer, conf):
        await asyncio.sleep(0.02); calls.append(1)
        async with tk.config.guild(guild).tickets() as t:
            t[str(channel.id)]["status"] = "closed"
    tk._close_ticket_locked = fake_locked
    conf = await tk.config.guild(g).all()
    ch = types.SimpleNamespace(id=100)
    res = await asyncio.gather(*(tk._close_ticket(g, ch, {"num": 1}, None, conf) for _ in range(3)))
    assert calls == [1] and sorted(res) == [False, False, True], (calls, res)
    print("tickets: 3x gleichzeitig schließen -> 1x ausgeführt")
    # autorole Job-Guard
    ar = cogs["Autorole"]
    async def slow(guild): await asyncio.sleep(0.02); return (1, 1)
    ar.apply_to_existing = slow
    t1 = ar.start_apply_job(g); t2 = ar.start_apply_job(g)
    assert t1 and t2 is None and await t1 == (1, 1)
    print("autorole: applyall läuft nur einmal parallel")
    # sticky Validierung
    from rc.sticky.validate import validate_sticky
    assert validate_sticky({"mode": "text", "text": "x" * 2001})
    assert validate_sticky({"mode": "embed", "text": "ok", "embed_image": "ftp://x"})
    assert validate_sticky({"mode": "text", "text": "ok", "webhook": True, "webhook_name": "Discord Bot"})
    assert validate_sticky({"mode": "text", "text": "ok"}) is None
    print("sticky: Validierung OK")
    # guard: paralleler Notmodus-Start -> nur einmal
    gd = cogs["Guard"]
    starts = []
    async def fake_start_locked(guild, *, reason_kind, joins):
        if await gd._lockdown_active(guild):
            return False
        await asyncio.sleep(0.02)
        await gd.config.guild(guild).lockdown_until.set(-1)
        starts.append(1); return True
    gd._start_lockdown_locked = fake_start_locked
    r = await asyncio.gather(*(gd._start_lockdown(g) for _ in range(5)))
    assert starts == [1] and r.count(True) == 1
    print("guard: 5 gleichzeitige Notmodus-Starts -> 1 ausgeführt")
    # raidhelper Wiederholung springt in die Zukunft
    from datetime import datetime, timezone
    created = []
    async def fake_create(guild, **kw): created.append(kw["start_ts"]); return {}
    rh.create_event = fake_create
    old = int(datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc).timestamp())
    await rh._spawn_next(g, {"start_ts": old, "recurrence": "weekly", "game": "wow_retail", "title": "x", "deadline_ts": old})
    assert created and created[0] > datetime.now(timezone.utc).timestamp()
    print("raidhelper: Wiederholung nach langer Offline-Zeit -> nächster Termin in der Zukunft")

asyncio.run(main())
