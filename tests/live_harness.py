"""Live-Harness: wie wc_harness, aber Posten funktioniert.

- Fake-Text-/Voice-/Kategorie-Kanäle sind echte Unterklassen von discord.TextChannel/
  VoiceChannel/CategoryChannel (per object.__new__ ohne discord-State angelegt) und bestehen
  damit alle ``isinstance``-Prüfungen der Cogs.
- ``send``/``edit``/``fetch_message``/``delete``/``history``/Webhooks werden in ``LOG``
  aufgezeichnet. Nachrichten werden wie von Discord geprüft (Längen-/Komponenten-Limits,
  leere Nachricht, ungültige Emojis) -> ``discord.HTTPException`` 400 wie in echt.
- ``bot.loop`` existiert (laufende Event-Loop).
- Rechte pro Kanal lassen sich entziehen: ``chan.forbid = {"send", "history", ...}``.

Nutzung:  import live_harness as L; wc, bot, app = await L.make_app()
Server:   python tests/live_harness.py [port]   (X-Test-User-Header wie wc_harness)
wc_harness.py bleibt unverändert – hier wird nur zur Laufzeit ausgetauscht (H.Guild/H.FakeBot).
"""
import asyncio, itertools, struct, types, zlib
import wc_harness as H
import discord

LOG: list[tuple] = []          # (op, channel_id, info-dict)
_ids = itertools.count(7_000_000_000)
_MISSING = object()


def log(op, ch, **info):
    LOG.append((op, getattr(ch, "id", ch), info))


def _resp(status, reason):
    return types.SimpleNamespace(status=status, reason=reason)


def bad_request(msg):
    return discord.HTTPException(_resp(400, "Bad Request"), {"code": 50035, "message": f"Invalid Form Body: {msg}"})


def forbidden():
    return discord.Forbidden(_resp(403, "Forbidden"), {"code": 50013, "message": "Missing Permissions"})


def not_found():
    return discord.NotFound(_resp(404, "Not Found"), {"code": 10008, "message": "Unknown Message"})


# --------------------------------------------------------------------------- #
#  Discord-Validierung (die häufigsten 400er)
# --------------------------------------------------------------------------- #
def _check_emoji(e, where):
    if not e:
        return
    if e.get("id"):
        return
    name = e.get("name") or ""
    # Unicode-Emoji: Discord lehnt Text wie "abc", ":smile:" oder Leerzeichen ab.
    if not name or any(c.isspace() for c in name) or any(c.isascii() and c.isalnum() for c in name.replace("#", "").replace("*", "")) \
            or not any(ord(c) >= 0x2000 for c in name) or len(name) > 16:
        raise bad_request(f"{where}.emoji: Invalid emoji ({name!r})")


def validate_embed(emb: discord.Embed, i=0):
    d = emb.to_dict()
    total = 0
    def chk(val, lim, path, required=False):
        nonlocal total
        if val is None:
            if required:
                raise bad_request(f"embeds.{i}.{path}: required")
            return
        if required and not str(val).strip():
            raise bad_request(f"embeds.{i}.{path}: must not be empty")
        if len(str(val)) > lim:
            raise bad_request(f"embeds.{i}.{path}: Must be {lim} or fewer in length ({len(str(val))})")
        total += len(str(val))
    chk(d.get("title"), 256, "title")
    chk(d.get("description"), 4096, "description")
    fields = d.get("fields") or []
    if len(fields) > 25:
        raise bad_request(f"embeds.{i}.fields: Must be 25 or fewer in length")
    for n, f in enumerate(fields):
        chk(f.get("name"), 256, f"fields.{n}.name", required=True)
        chk(f.get("value"), 1024, f"fields.{n}.value", required=True)
    chk((d.get("footer") or {}).get("text"), 2048, "footer.text")
    chk((d.get("author") or {}).get("name"), 256, "author.name")
    for key in ("image", "thumbnail"):
        url = (d.get(key) or {}).get("url")
        if url and not url.startswith(("http://", "https://", "attachment://")):
            raise bad_request(f"embeds.{i}.{key}.url: Not a well formed URL")
    if total > 6000:
        raise bad_request(f"embeds: total length {total} > 6000")


def validate_view(view):
    if view is None:
        return
    rows = view.to_components()
    if len(rows) > 5:
        raise bad_request("components: max 5 rows")
    seen = set()
    for r, row in enumerate(rows):
        comps = row.get("components", [])
        if not comps or len(comps) > 5:
            raise bad_request(f"components.{r}: 1-5 components")
        if any(c["type"] != 2 for c in comps) and len(comps) > 1:
            raise bad_request(f"components.{r}: select menu must be alone in a row")
        for c, comp in enumerate(comps):
            where = f"components.{r}.components.{c}"
            cid = comp.get("custom_id")
            if cid is not None:
                if len(cid) > 100:
                    raise bad_request(f"{where}.custom_id: max 100")
                if cid in seen:
                    raise bad_request(f"{where}.custom_id: duplicate {cid!r}")
                seen.add(cid)
            if comp["type"] == 2:
                if not comp.get("label") and not comp.get("emoji"):
                    raise bad_request(f"{where}: button needs label or emoji")
                if len(comp.get("label") or "") > 80:
                    raise bad_request(f"{where}.label: max 80")
                _check_emoji(comp.get("emoji"), where)
            elif comp["type"] == 3:
                opts = comp.get("options") or []
                if not 1 <= len(opts) <= 25:
                    raise bad_request(f"{where}.options: 1-25")
                if len(comp.get("placeholder") or "") > 150:
                    raise bad_request(f"{where}.placeholder: max 150")
                mn, mx = comp.get("min_values", 1), comp.get("max_values", 1)
                if not (0 <= mn <= mx <= len(opts)) or mx < 1:
                    raise bad_request(f"{where}: min/max_values invalid ({mn}/{mx}, {len(opts)} options)")
                vals = set()
                for o, opt in enumerate(opts):
                    for k in ("label", "value"):
                        if not 1 <= len(opt.get(k) or "") <= 100:
                            raise bad_request(f"{where}.options.{o}.{k}: 1-100")
                    if len(opt.get("description") or "") > 100:
                        raise bad_request(f"{where}.options.{o}.description: max 100")
                    if opt["value"] in vals:
                        raise bad_request(f"{where}.options.{o}.value: duplicate")
                    vals.add(opt["value"])
                    _check_emoji(opt.get("emoji"), f"{where}.options.{o}")


def validate_message(content, embeds, view, files):
    if content is not None and len(str(content)) > 2000:
        raise bad_request(f"content: Must be 2000 or fewer in length ({len(str(content))})")
    if len(embeds) > 10:
        raise bad_request("embeds: max 10")
    for i, e in enumerate(embeds):
        validate_embed(e, i)
    validate_view(view)
    if not (content and str(content).strip()) and not embeds and not files:
        raise discord.HTTPException(_resp(400, "Bad Request"), {"code": 50006, "message": "Cannot send an empty message"})


# --------------------------------------------------------------------------- #
#  Nachrichten, Webhooks
# --------------------------------------------------------------------------- #
class FakeMessage:
    def __init__(self, channel, author, content=None, embeds=(), view=None, attachments=(), webhook_id=None):
        self.id = next(_ids); self.channel = channel; self.guild = channel.guild; self.author = author
        self.content = content or ""; self.embeds = list(embeds); self.view = view
        self.attachments = list(attachments); self.webhook_id = webhook_id; self.deleted = False

    @property
    def embed(self):
        return self.embeds[0] if self.embeds else None

    @property
    def jump_url(self):
        return f"https://discord.com/channels/{self.guild.id}/{self.channel.id}/{self.id}"

    async def edit(self, *, content=_MISSING, embed=_MISSING, embeds=_MISSING, view=_MISSING,
                   attachments=_MISSING, **kw):
        ch = self.channel
        if "edit" in ch.forbid:
            raise forbidden()
        if self.author is not ch.guild._bot_user and self.webhook_id is None:
            raise discord.Forbidden(_resp(403, "Forbidden"), {"code": 50005, "message": "Cannot edit a message authored by another user"})
        new_content = self.content if content is _MISSING else (content or "")
        new_embeds = self.embeds if embed is _MISSING and embeds is _MISSING else (
            list(embeds or []) if embeds is not _MISSING else ([embed] if embed else []))
        new_view = self.view if view is _MISSING else view
        new_att = self.attachments if attachments is _MISSING else [getattr(a, "filename", "file") for a in attachments]
        validate_message(new_content, new_embeds, new_view, new_att)
        self.content, self.embeds, self.view, self.attachments = new_content, new_embeds, new_view, new_att
        log("edit", ch, message=self.id, content=new_content, embeds=len(new_embeds), attachments=new_att)
        return self

    async def delete(self, *, delay=None):
        ch = self.channel
        if self.deleted or self.id not in ch._messages:
            raise not_found()
        if "delete" in ch.forbid:
            raise forbidden()
        ch._messages.pop(self.id, None); self.deleted = True
        log("delete", ch, message=self.id)


class FakePartial:
    def __init__(self, channel, mid): self.channel = channel; self.id = mid
    async def delete(self, *, delay=None):
        msg = self.channel._messages.get(self.id)
        if msg is None:
            raise not_found()
        await msg.delete()


class FakeWebhook:
    def __init__(self, channel, name, user):
        self.id = next(_ids); self.channel = channel; self.name = name; self.user = user
        self.channel_id = channel.id

    async def send(self, content=None, *, embed=None, embeds=None, username=None, avatar_url=None,
                   allowed_mentions=None, wait=False, **kw):
        embeds = list(embeds or ([embed] if embed else []))
        validate_message(content, embeds, None, [])
        author = types.SimpleNamespace(id=self.id, name=username or self.name, bot=True)
        msg = FakeMessage(self.channel, author, content, embeds, webhook_id=self.id)
        self.channel._messages[msg.id] = msg
        log("webhook_send", self.channel, message=msg.id, content=content, embeds=len(embeds), username=username)
        return msg if wait else None

    async def delete_message(self, mid):
        msg = self.channel._messages.get(int(mid))
        if msg is None or msg.webhook_id != self.id:
            raise not_found()
        self.channel._messages.pop(msg.id); msg.deleted = True
        log("webhook_delete", self.channel, message=msg.id)


# --------------------------------------------------------------------------- #
#  Kanäle (echte Unterklassen)
# --------------------------------------------------------------------------- #
class _SendMixin:
    async def send(self, content=None, *, embed=None, embeds=None, file=None, files=None, view=None,
                   allowed_mentions=None, reference=None, **kw):
        if "send" in self.forbid:
            raise forbidden()
        embeds = list(embeds or ([embed] if embed else []))
        files = list(files or ([file] if file else []))
        names = [getattr(f, "filename", "file") for f in files]
        validate_message(content, embeds, view, names)
        msg = FakeMessage(self, self.guild._bot_user, content, embeds, view, names)
        self._messages[msg.id] = msg
        log("send", self, message=msg.id, content=content, embeds=len(embeds), view=bool(view), files=names)
        return msg

    async def fetch_message(self, mid):
        if "history" in self.forbid:
            raise forbidden()
        msg = self._messages.get(int(mid))
        if msg is None:
            raise not_found()
        log("fetch", self, message=int(mid))
        return msg

    def get_partial_message(self, mid):
        return FakePartial(self, int(mid))

    async def history(self, *, limit=100, oldest_first=False, **kw):
        if "history" in self.forbid:
            raise forbidden()
        msgs = sorted(self._messages.values(), key=lambda m: m.id, reverse=not oldest_first)
        log("history", self, limit=limit)
        for m in msgs[:limit] if limit else msgs:
            yield m

    def permissions_for(self, obj):
        p = discord.Permissions.all()
        if "send" in self.forbid:
            p.send_messages = False
        if "webhooks" in self.forbid:
            p.manage_webhooks = False
        return p

    async def edit(self, *, reason=None, **kw):
        if "edit_channel" in self.forbid:
            raise forbidden()
        for k, v in kw.items():
            setattr(self, k, v)
        log("channel_edit", self, **{k: v for k, v in kw.items()})
        return self

    async def delete(self, *, reason=None):
        log("channel_delete", self)
        self.guild._remove_channel(self)


def _init_common(obj, guild, cid, name, category, pos):
    obj.id = cid; obj.name = name; obj.guild = guild; obj._state = None
    obj.category_id = category.id if category is not None else None
    obj.position = pos; obj.nsfw = False; obj._overwrites = []
    obj.forbid = set(); obj._messages = {}


class FakeText(_SendMixin, discord.TextChannel):
    members = None  # Property von discord überschreiben -> Instanzattribut

    @classmethod
    def make(cls, guild, cid, name, category=None, pos=0):
        o = object.__new__(cls)
        _init_common(o, guild, cid, name, category, pos)
        o.topic = None; o.slowmode_delay = 0; o._type = discord.ChannelType.text.value
        o.last_message_id = None; o.default_auto_archive_duration = 1440
        o.default_thread_slowmode_delay = 0; o.members = []
        o._webhooks = []
        return o

    async def webhooks(self):
        if "webhooks" in self.forbid:
            raise forbidden()
        return list(self._webhooks)

    async def create_webhook(self, *, name, avatar=None, reason=None):
        if "webhooks" in self.forbid:
            raise forbidden()
        wh = FakeWebhook(self, name, self.guild._bot_user)
        self._webhooks.append(wh)
        log("webhook_create", self, name=name)
        return wh


class FakeVoice(_SendMixin, discord.VoiceChannel):
    members = None

    @classmethod
    def make(cls, guild, cid, name, category=None, pos=0):
        o = object.__new__(cls)
        _init_common(o, guild, cid, name, category, pos)
        o.bitrate = 64000; o.user_limit = 0; o.rtc_region = None; o.video_quality_mode = discord.VideoQualityMode.auto
        o.last_message_id = None; o.slowmode_delay = 0; o.status = None
        o._type = discord.ChannelType.voice.value
        o.members = []
        return o


class FakeCategory(discord.CategoryChannel):
    channels = None; text_channels = None; voice_channels = None

    @classmethod
    def make(cls, guild, cid, name, pos=0):
        o = object.__new__(cls)
        _init_common(o, guild, cid, name, None, pos)
        o.channels = []; o.text_channels = []; o.voice_channels = []
        return o

    async def edit(self, **kw):
        log("channel_edit", self, **kw)


# --------------------------------------------------------------------------- #
#  Welt
# --------------------------------------------------------------------------- #
def _png(w=4, h=4, rgb=(61, 220, 151)):
    raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
    def chunk(t, d): return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + \
        chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class FakeAsset:
    def __init__(self, uid): self.key = f"a{uid}"; self.url = f"https://cdn.discordapp.com/avatars/{uid}/a.png"
    async def read(self): return _png()
    def __str__(self): return self.url


BOT_USER = types.SimpleNamespace(id=999, name="Matters Bot", bot=True, display_name="Matters Bot",
                                 mention="<@999>", display_avatar=FakeAsset(999))


# Rollen vergleichbar machen (discord.Role vergleicht über die Position) + Member.top_role
def _pos(r): return (r.position, r.id)
H.Role.__lt__ = lambda a, b: _pos(a) < _pos(b)
H.Role.__le__ = lambda a, b: _pos(a) <= _pos(b)
H.Role.__gt__ = lambda a, b: _pos(a) > _pos(b)
H.Role.__ge__ = lambda a, b: _pos(a) >= _pos(b)
H.Role.__hash__ = lambda r: hash(r.id)
H.Member.top_role = property(lambda m: max(m.roles, key=_pos))


class LiveGuild(H.Guild):
    def __init__(self, gid, name):
        super().__init__(gid, name)
        self._bot_user = BOT_USER
        cat = FakeCategory.make(self, gid + 90, "Support")
        self.categories = [cat]
        self.text_channels = [FakeText.make(self, gid + i, n, cat, i)
                              for i, n in enumerate(["allgemein", "support", "ankündigungen", "logs"], 1)]
        self.voice_channels = [FakeVoice.make(self, gid + 50, "Lobby", None, 50)]
        cat.text_channels = list(self.text_channels); cat.channels = list(self.text_channels)
        bot_role = H.Role(self, gid + 999, "Matters Bot", 20, 0x5865F2); bot_role.managed = True
        self.roles.append(bot_role)
        me = H.Member(self, 999, "Matters Bot", [bot_role], admin=True); me.bot = True
        me.display_avatar = FakeAsset(999); me.avatar = me.display_avatar
        self.me = me
        self.threads = []

    def _remove_channel(self, ch):
        for lst in (self.text_channels, self.voice_channels, self.categories):
            if ch in lst:
                lst.remove(ch)

    async def create_text_channel(self, name, *, topic=None, category=None, reason=None, **kw):
        ch = FakeText.make(self, next(_ids), name, category, 99)
        ch.topic = topic
        self.text_channels.append(ch)
        log("channel_create", ch, name=name, topic=topic)
        return ch


class LiveBot(H.FakeBot):
    def __init__(self, guilds):
        super().__init__(guilds)
        self.loop = asyncio.get_running_loop()
        self.user = BOT_USER
        for g in guilds:
            for m in g.members:
                m.display_avatar = FakeAsset(m.id); m.avatar = m.display_avatar

    def get_channel(self, cid):
        for g in self.guilds:
            c = g.get_channel(cid)
            if c is not None:
                return c
        return None


H.Guild = LiveGuild
H.FakeBot = LiveBot


async def make_app():
    return await H.make_app()


if __name__ == "__main__":
    H.main(make_app)
