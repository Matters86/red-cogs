"""Trusted server-profile configuration; no network, bot, or secret output."""
from dataclasses import dataclass, field
import hmac
import os
import re


PROFILE_ID = re.compile(r"[a-z][a-z0-9_-]{0,31}\Z")
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,95}\Z")
ALLOWED_PROFILES = {"legacy", "dev", "live"}


@dataclass(frozen=True)
class Profile:
    id: str
    label: str
    environment: str
    guild_id: str | None
    enabled: bool
    key: str | None = field(default=None, repr=False)

    def public(self, *, internal=False):
        data = {"id": self.id, "label": self.label, "environment": self.environment}
        if internal:
            data["guild_id"] = self.guild_id
        return data


class Profiles:
    def __init__(self, configured=None, legacy_key=None, *, environ=None):
        environ = os.environ if environ is None else environ
        configured = configured if isinstance(configured, dict) else {}
        self.raw = configured
        profiles = {}
        # The old DB/key remain their own unassigned profile. No implicit Dev/Live.
        records = {"legacy": {"label": "Bestand (unzugeordnet)"}, **configured}
        for profile_id, record in records.items():
            if profile_id not in ALLOWED_PROFILES or not isinstance(record, dict):
                continue
            raw_guild = record.get("guild_id")
            guild_id = str(raw_guild) if isinstance(raw_guild, (str, int)) and not isinstance(raw_guild, bool) else ""
            guild_id = guild_id if guild_id.isdigit() and int(guild_id) > 0 else None
            env = record.get("key_env")
            key = environ.get(env) if isinstance(env, str) and ENV_NAME.fullmatch(env) else None
            if profile_id == "legacy" and not env:
                key = legacy_key
            if not isinstance(key, str) or not key or key == "CHANGE_ME" or len(key) > 4096:
                key = None
            label = record.get("label")
            label = label.strip()[:64] if isinstance(label, str) and label.strip() else profile_id
            environment = profile_id if profile_id in ("dev", "live", "legacy") else "custom"
            profiles[profile_id] = Profile(profile_id, label, environment, guild_id,
                                           record.get("enabled", True) is True, key)
        self.items = profiles

    def for_guild(self, guild_id):
        wanted = str(guild_id)
        return [profile for profile in self.items.values() if profile.enabled and profile.guild_id == wanted]

    def select(self, profile_id, guild_id):
        profile = self.items.get(profile_id) if isinstance(profile_id, str) else None
        if profile and profile.enabled and profile.guild_id is not None and profile.guild_id == str(guild_id):
            return profile
        return None

    def for_bridge(self, key, requested=None):
        if not isinstance(key, str) or not key or len(key) > 4096:
            return None
        matches = [profile for profile in self.items.values() if profile.enabled and profile.key
                   and hmac.compare_digest(key.encode("utf-8"), profile.key.encode("utf-8"))]
        # A duplicate configuration key must never choose whichever profile is first.
        if len(matches) != 1:
            return None
        profile = matches[0]
        if requested is not None and requested != profile.id:
            return None
        # Legacy machine sync remains compatible while human access stays unbound.
        if profile.id != "legacy" and profile.guild_id is None:
            return None
        return profile
