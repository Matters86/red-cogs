"""Testdaten für tc_harness: Ticket-Panels/-Tickets/-Transcripts und Changelog-Einträge (Server 1000)."""
import tc_harness as T

TRICKY_TITLE = '<script>alert(1)</script> & "Quotes" ]]> \x07Ende'


async def seed(bot, tk, cl, *, entries=12):
    g = bot.guilds[0]
    gc = tk.config.guild(g)
    await gc.support_roles.set([1101]); await gc.ping_roles.set([1102]); await gc.owner_role.set(1104)
    await gc.category_open.set(g.id + 90); await gc.log_channel.set(g.id + 4)
    panels = [
        {"id": "pa", "channel_id": g.id + 2, "message_id": None, "title": "Support",
         "description": "Klick unten, um ein Ticket zu öffnen.", "mode": "button", "button_label": "🎟️ Ticket",
         "placeholder": "Grund …", "reasons": [], "modal_questions": [], "lang": None},
        {"id": "pb", "channel_id": g.id + 2, "message_id": None, "title": "Bewerbung & Bugs",
         "description": "Wähle einen Grund.", "mode": "dropdown", "button_label": "🎟️ Ticket", "placeholder": "Grund …",
         "reasons": [{"id": "r1", "label": "Bewerbung", "emoji": "📝", "description": "Bewirb dich fürs Team",
                      "support_roles": [1103]},
                     {"id": "r2", "label": "<b>Bug</b> melden", "emoji": "🐞", "description": "Fehler im Spiel"},
                     {"id": "r3", "label": "Entbannung", "emoji": "<:custom:123>", "description": None}],
         "modal_questions": [{"label": "Worum geht es?", "placeholder": "Kurz beschreiben", "required": True,
                              "style": "short"},
                             {"label": "Details", "placeholder": "Alles Wichtige", "required": False, "style": "long"}],
         "lang": None},
        {"id": "ph", "channel_id": g.id + 8, "message_id": None, "title": "Team-intern", "description": "",
         "mode": "button", "button_label": "Intern", "placeholder": "", "reasons": [], "modal_questions": [], "lang": None},
        {"id": "pn", "channel_id": g.id + 2, "message_id": None, "title": "Nicht gepostet", "description": "",
         "mode": "button", "button_label": "X", "placeholder": "", "reasons": [], "modal_questions": [], "lang": None},
    ]
    for p in panels[:3]:
        p["message_id"] = await tk.post_panel(g, p)
    await gc.panels.set(panels)
    await gc.max_open.set(1)

    kai, nina = g.get_member(13), g.get_member(15)
    pa, pb = panels[0], panels[1]
    # Kai: 1 geschlossenes (Transcript) + 1 offenes Ticket
    r = await tk.open_ticket(g, kai, pb, pb["reasons"][0], {"Worum geht es?": "Bewerbung als Mod", "Details": ""})
    await r.target.send("Hallo <b>Team</b> & co")
    rec = (await gc.tickets())[str(r.target.id)]
    await tk._close_ticket(g, r.target, rec, g.get_member(11), await gc.all())
    await tk.open_ticket(g, kai, pa, None, {})
    # Nina: 1 geschlossenes Ticket (Kai hinzugefügt) + 1 offenes
    r = await tk.open_ticket(g, nina, pb, pb["reasons"][1], {"Worum geht es?": "Absturz <script>x</script>"})
    await r.target.send("<script>alert('xss')</script> geheim von Nina")
    async with gc.tickets() as tickets:
        tickets[str(r.target.id)]["members"] = [13]
        tickets[str(r.target.id)]["claimed_by"] = 11
    rec = (await gc.tickets())[str(r.target.id)]
    await tk._close_ticket(g, r.target, rec, g.get_member(11), await gc.all())
    r = await tk.open_ticket(g, nina, pa, None, {})
    async with gc.tickets() as tickets:
        tickets[str(r.target.id)]["claimed_by"] = 11

    # Changelog
    cc = cl.config.guild(g)
    await cc.channel_id.set(g.id + 3)
    for i in range(entries):
        rec = []
        inter = T.Inter(rec, g, g.get_member(1 if i % 2 else 11))
        title = TRICKY_TITLE if i == entries - 1 else f"Update {i + 1}"
        await cl.handle_modal_submit(
            inter, title=title, neu=f"Neues Auto {i}\n- Zweiter Punkt & <mehr>", geaendert="• Preise angepasst" if i % 3 else "",
            fixes="Absturz behoben" if i % 2 else "", hinweis="Server-Neustart um 20 Uhr" if i == entries - 1 else "",
            category_emoji="🚗", category_label="Fahrzeuge", lang="de")
    return panels
