"""Erzeugt schlanke, eigenständige HTML-Transcripts eines Ticket-Kanals.

Bewusst ohne externe Abhängigkeit (kein chat-exporter): Das Ergebnis ist ein
in sich geschlossenes HTML-Dokument im Dark-Theme, das WebCore direkt als
eigene Seite ausliefern kann.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

import discord

_PAGE = """<!DOCTYPE html>
<html lang="de" data-bs-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Transcript · {title}</title>
<style>
  :root{{--bg:#0d1014;--panel:#151a21;--panel-2:#1b212b;--border:#252c37;
    --text:#e6edf3;--muted:#8b97a7;--accent:#3ddc97;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--text);
    font-family:"IBM Plex Sans",system-ui,sans-serif;padding:24px;}}
  .wrap{{max-width:860px;margin:0 auto}}
  .head{{background:var(--panel);border:1px solid var(--border);border-radius:14px;
    padding:20px 22px;margin-bottom:18px}}
  .head h1{{margin:0 0 8px;font-size:1.4rem}}
  .meta{{color:var(--muted);font-size:.88rem;line-height:1.6}}
  .msg{{display:flex;gap:12px;padding:10px 14px;border-radius:10px}}
  .msg:hover{{background:var(--panel)}}
  .av{{width:38px;height:38px;border-radius:50%;background:var(--panel-2);
    flex:0 0 38px;display:flex;align-items:center;justify-content:center;
    color:var(--accent);font-weight:700;font-size:.95rem}}
  .body{{flex:1;min-width:0}}
  .name{{font-weight:600}}
  .time{{color:var(--muted);font-size:.75rem;margin-left:8px}}
  .content{{white-space:pre-wrap;word-wrap:break-word;margin-top:2px}}
  .att{{color:var(--accent);font-size:.85rem}}
  .embed{{border-left:3px solid var(--accent);background:var(--panel-2);
    border-radius:6px;padding:8px 12px;margin-top:6px;font-size:.9rem}}
  .empty{{color:var(--muted);padding:20px}}
</style>
</head>
<body>
<div class="wrap">
  <div class="head">
    <h1>{title}</h1>
    <div class="meta">{meta}</div>
  </div>
  {messages}
</div>
</body>
</html>"""


def _initials(name: str) -> str:
    parts = [p for p in name.split() if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def _fmt_time(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y %H:%M UTC")


async def build_transcript(channel: discord.abc.Messageable, meta: dict) -> str:
    """Liest die Historie und gibt ein vollständiges HTML-Dokument zurück.

    ``meta`` darf u. a. ``num``, ``owner``, ``reason``, ``opened``, ``closed``,
    ``closed_by`` enthalten (alles optional, nur für den Kopf).
    """
    rows: list[str] = []
    try:
        async for message in channel.history(limit=2000, oldest_first=True):
            author = message.author
            name = html.escape(getattr(author, "display_name", str(author)))
            avatar_initials = html.escape(_initials(getattr(author, "display_name", "?")))
            time = _fmt_time(message.created_at)
            content = html.escape(message.content or "")

            extras = ""
            for att in message.attachments:
                extras += f"<div class='att'>📎 {html.escape(att.filename)}</div>"
            for emb in message.embeds:
                title = html.escape(emb.title or "")
                desc = html.escape(emb.description or "")
                if title or desc:
                    extras += f"<div class='embed'><b>{title}</b><br>{desc}</div>"

            rows.append(
                "<div class='msg'>"
                f"<div class='av'>{avatar_initials}</div>"
                "<div class='body'>"
                f"<span class='name'>{name}</span><span class='time'>{time}</span>"
                f"<div class='content'>{content}</div>{extras}"
                "</div></div>"
            )
    except discord.HTTPException:
        rows.append("<div class='empty'>Historie konnte nicht vollständig gelesen werden.</div>")

    title = html.escape(f"Ticket #{meta.get('num', '?')} – {meta.get('channel_name', '')}")
    meta_lines = []
    if meta.get("owner"):
        meta_lines.append(f"Inhaber: {html.escape(str(meta['owner']))}")
    if meta.get("reason"):
        meta_lines.append(f"Grund: {html.escape(str(meta['reason']))}")
    if meta.get("opened"):
        meta_lines.append(f"Geöffnet: {html.escape(str(meta['opened']))}")
    if meta.get("closed"):
        meta_lines.append(f"Geschlossen: {html.escape(str(meta['closed']))}")
    if meta.get("closed_by"):
        meta_lines.append(f"Geschlossen von: {html.escape(str(meta['closed_by']))}")
    meta_html = " &middot; ".join(meta_lines) or "—"

    messages_html = "".join(rows) or "<div class='empty'>Keine Nachrichten.</div>"
    return _PAGE.format(title=title, meta=meta_html, messages=messages_html)
