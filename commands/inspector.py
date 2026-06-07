"""Befehls-Introspektion und Rechte-Engine für den Commands-Cog.

Komplett dependency-frei: es werden ausschließlich discord.py-/Red-Bordmittel
verwendet (keine zusätzliche pip-Abhängigkeit).

Stufen-Modell (die vier Dashboard-Spalten):

    Jeder  <  Mod  <  Admin  <  Owner(= Bot-Owner)

Die geforderte Mindeststufe je Befehl stammt aus Reds ``PrivilegeLevel``.
Zusätzlich geforderte Discord-Rechte (``user_perms``, z. B. „Server verwalten")
lassen sich nicht sauber auf eine Stufe abbilden und werden deshalb getrennt als
Badge ausgewiesen. Die *exakte* Antwort „darf Mitglied X diesen Befehl?" liefert
die Mitglieds-Prüfung (``evaluate_member``).

Bewusst NICHT modelliert (im Dashboard nur als Hinweis ausgewiesen):
* Einzelregeln der Permissions-Cog (allow/deny pro Befehl/Server),
* befehlseigene ``checks`` (beliebige Funktionen),
* kanal-spezifische Rechte-Overrides.
Die In-Discord-Eigenprüfung (``[p]meinebefehle`` ohne Ziel) nutzt dagegen Reds
``can_run`` und ist damit vollständig – inklusive Permissions-Cog-Regeln.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from redbot.core import commands

try:  # Importpfad ist stabil, wir bleiben aber defensiv.
    from redbot.core.commands.requires import PrivilegeLevel
except Exception:  # pragma: no cover - nur falls Red sich umstrukturiert
    PrivilegeLevel = None


# Spaltenreihenfolge / -beschriftung.
TIER_LABELS = ["Jeder", "Mod", "Admin", "Owner"]
T_EVERYONE, T_MOD, T_ADMIN, T_OWNER = 0, 1, 2, 3

# Häufige Discord-Rechte mit deutschem Label (Fallback: aufgehübschter Name).
PERM_DE = {
    "administrator": "Administrator",
    "manage_guild": "Server verwalten",
    "manage_channels": "Kanäle verwalten",
    "manage_messages": "Nachrichten verwalten",
    "manage_roles": "Rollen verwalten",
    "manage_nicknames": "Nicknamen verwalten",
    "manage_webhooks": "Webhooks verwalten",
    "manage_threads": "Threads verwalten",
    "manage_emojis": "Emojis verwalten",
    "manage_emojis_and_stickers": "Emojis/Sticker verwalten",
    "manage_events": "Events verwalten",
    "kick_members": "Mitglieder kicken",
    "ban_members": "Mitglieder bannen",
    "moderate_members": "Mitglieder moderieren",
    "mute_members": "Mitglieder stummschalten",
    "deafen_members": "Mitglieder taub schalten",
    "move_members": "Mitglieder verschieben",
    "mention_everyone": "@everyone erwähnen",
    "view_audit_log": "Audit-Log ansehen",
    "view_guild_insights": "Server-Insights",
    "create_instant_invite": "Einladungen erstellen",
}


def _pl(name: str):
    """Holt ein PrivilegeLevel-Mitglied defensiv (oder None)."""
    return getattr(PrivilegeLevel, name, None) if PrivilegeLevel is not None else None


def perm_label(name: str) -> str:
    return PERM_DE.get(name, name.replace("_", " ").title())


def _required_tier(priv) -> int:
    """Reds PrivilegeLevel -> Spaltenindex, ab dem ein ✓ steht."""
    none_pl = _pl("NONE")
    if priv is None or priv == none_pl:
        return T_EVERYONE
    if priv == _pl("MOD"):
        return T_MOD
    if priv == _pl("ADMIN"):
        return T_ADMIN
    # GUILD_OWNER und BOT_OWNER -> nur Owner-Spalte.
    return T_OWNER


def _short_doc(cmd) -> str:
    try:
        text = (cmd.short_doc or "").strip()
        if text:
            return text
    except Exception:
        pass
    raw = (getattr(cmd, "help", "") or "").strip()
    return raw.split("\n", 1)[0] if raw else ""


def _perm_names(user_perms) -> list:
    """Liste der gesetzten Permission-Namen aus einem discord.Permissions-Objekt."""
    if not user_perms:
        return []
    out = []
    try:
        for name, value in user_perms:
            if value:
                out.append(name)
    except Exception:
        return []
    return out


@dataclass
class CmdInfo:
    qualified_name: str
    name: str
    cog: str
    short: str
    signature: str
    aliases: list
    hidden: bool          # discord.py-eigenes hidden-Flag des Befehls
    enabled: bool
    is_group: bool
    depth: int            # 0 = Top-Level, 1 = Subbefehl, ...
    required_tier: int
    guild_owner_only: bool
    perms: list           # discord-Permission-Namen (intern)
    custom_checks: int    # Anzahl befehlseigener checks (nicht Reds requires)
    req_priv: object = None            # echtes PrivilegeLevel (für exakte Prüfung)
    is_hidden_cfg: bool = False        # vom Owner per Dashboard/Befehl ausgeblendet
    verdict: Optional[bool] = None     # Ergebnis der Mitglieds-Prüfung
    verdict_note: str = ""

    @property
    def allowed_tiers(self) -> list:
        """[Jeder, Mod, Admin, Owner] -> True, wenn die Stufe das Privileg erfüllt."""
        return [idx >= self.required_tier for idx in range(4)]

    @property
    def perm_labels(self) -> list:
        return [perm_label(p) for p in self.perms]


def build_command_info(cmd) -> CmdInfo:
    req = getattr(cmd, "requires", None)
    priv = getattr(req, "privilege_level", None) if req is not None else None
    user_perms = getattr(req, "user_perms", None) if req is not None else None
    try:
        custom = len(cmd.checks or [])
    except Exception:
        custom = 0
    return CmdInfo(
        qualified_name=cmd.qualified_name,
        name=cmd.name,
        cog=cmd.cog_name or "",
        short=_short_doc(cmd),
        signature=(cmd.signature or "").strip(),
        aliases=list(getattr(cmd, "aliases", []) or []),
        hidden=bool(getattr(cmd, "hidden", False)),
        enabled=bool(getattr(cmd, "enabled", True)),
        is_group=isinstance(cmd, commands.Group),
        depth=cmd.qualified_name.count(" "),
        required_tier=_required_tier(priv),
        guild_owner_only=(priv is not None and priv == _pl("GUILD_OWNER")),
        perms=_perm_names(user_perms),
        custom_checks=custom,
        req_priv=priv,
    )


def walk_all_commands(bot) -> list:
    """Alle Befehle inklusive Subbefehle (defensiv, gibt eine Liste zurück)."""
    try:
        return list(bot.walk_commands())
    except Exception:
        out = []
        for cmd in bot.commands:
            out.append(cmd)
            if isinstance(cmd, commands.Group):
                try:
                    out.extend(cmd.walk_commands())
                except Exception:
                    pass
        return out


def cog_names(bot) -> list:
    names = {c for c in (cmd.cog_name for cmd in walk_all_commands(bot)) if c}
    return sorted(names, key=str.lower)


async def member_privilege_level(bot, member):
    """Reds PrivilegeLevel für ein Mitglied (BOT_OWNER … NONE) oder None."""
    if PrivilegeLevel is None:
        return None
    if member.id in getattr(bot, "owner_ids", set()):
        return _pl("BOT_OWNER")
    guild = getattr(member, "guild", None)
    if guild is not None and member.id == guild.owner_id:
        return _pl("GUILD_OWNER")
    role_ids = {r.id for r in getattr(member, "roles", [])}
    gid = guild.id if guild is not None else 0
    try:
        admin_ids = set(await bot.get_admin_role_ids(gid))
    except Exception:
        admin_ids = set()
    if role_ids & admin_ids:
        return _pl("ADMIN")
    try:
        mod_ids = set(await bot.get_mod_role_ids(gid))
    except Exception:
        mod_ids = set()
    if role_ids & mod_ids:
        return _pl("MOD")
    return _pl("NONE")


async def member_is_mod_or_higher(bot, member) -> bool:
    """True, wenn das Mitglied mindestens Mod-Stufe hat (für Fremd-Prüfung)."""
    priv = await member_privilege_level(bot, member)
    mod = _pl("MOD")
    return priv is not None and mod is not None and priv >= mod


def _member_has_perms(member, perm_names) -> bool:
    if not perm_names:
        return True
    gp = getattr(member, "guild_permissions", None)
    if gp is None:
        return False
    if getattr(gp, "administrator", False):
        return True
    return all(getattr(gp, p, False) for p in perm_names)


def evaluate_member(info: CmdInfo, member, member_priv):
    """Darf das Mitglied den Befehl ausführen? -> (bool, Hinweis-Text).

    Bildet Reds ``Requires.verify`` vereinfacht ab: Bot-Owner darf alles; sonst
    genügt es, *eine* der gesetzten Anforderungen (Mindeststufe ODER geforderte
    Rechte) zu erfüllen. Befehlseigene checks/Permissions-Regeln werden als
    Hinweis ausgewiesen, nicht ausgewertet.
    """
    if not info.enabled:
        return False, "deaktiviert"
    if PrivilegeLevel is not None and member_priv == _pl("BOT_OWNER"):
        return True, ""

    gates = []
    req = info.req_priv
    none_pl = _pl("NONE")
    if PrivilegeLevel is not None and req is not None and req != none_pl:
        gates.append(member_priv is not None and member_priv >= req)
    if info.perms:
        gates.append(_member_has_perms(member, info.perms))

    base = True if not gates else any(gates)
    note = "zzgl. Befehlsprüfung" if (base and info.custom_checks) else ""
    return base, note
