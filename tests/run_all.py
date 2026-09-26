"""Startet alle Test-Suiten nacheinander, jede in einem eigenen Python-Prozess.

    python tests/run_all.py            # alle Suiten
    python -m tests                    # dasselbe (aus der Repo-Wurzel)
    python tests/run_all.py wc pr      # nur Suiten, deren Name so beginnt
    python tests/run_all.py -v         # Ausgabe jeder Suite zeigen (sonst nur bei Fehlern)

Vorab wird geprüft, dass jede Test-Datei hier eingetragen ist, jeder Cog von mindestens einer
Test-Datei importiert wird und alle Cog-Anforderungen (info.json) in tests/requirements.txt stehen.
Exit-Code 0 nur, wenn alles grün ist.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

TESTS_DIR = pathlib.Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent
TIMEOUT = 300  # Sekunden je Suite

# (Datei ohne .py, was sie prüft) – Reihenfolge = Ausführungsreihenfolge
SUITES = [
    ("realred", "Echtes Red: alle Cogs importierbar, Repo-Regeln (identifier, Namen), Config-Locks/Nebenläufigkeit"),
    ("wc_test", "WebCore: Login, Server-Wechsler, Rollen-Rechte-Matrix, Nur-Ansicht, Selbst-Hochstufung, Audit-Log"),
    ("wcm_test", "WebCore: Mitglieder-Bereich /me, öffentliche API (CORS, Rate-Limit), Audit-Kanal, Befehle"),
    ("vis_test", "WebCore: visible()-Callback blendet Mitglieder-Seiten je Server aus"),
    ("live_test", "Posten aus den Dashboards mit Discord-Limits (tickets, poll, raidhelper, sticky, changelog, autorole, organigram, guard, autoroom)"),
    ("rc_functest", "raidhelper: Events im Dashboard anlegen/bearbeiten, Validierung, Rechte, raid-Befehle"),
    ("rm_functest", "raidhelper: Mitgliederseite /me/raids (Sichtbarkeit, Anmelden, Ablehnungen)"),
    ("pr_test", "poll + autorole: Mitgliederseiten /me/umfragen und /me/rollen"),
    ("tc_functest", "tickets + changelog: „Meine Tickets“ und öffentliche Changelog-API"),
    ("tw_functest", "twitchlive: gemockte Twitch-API, Live-Meldungen, Live-Rolle, Befehle, Dashboard"),
    ("wl_test_welcome", "welcome: Beitritt/Verlassen, Willkommensbild, DM, Befehle, Dashboard"),
    ("wl_test_warns", "warns: Punkte, Verfall, Maßnahmen mit Hierarchie-Schutz, Befehle, Dashboard"),
    ("fivem_functest", "fivemadmin: WebCore-Seite, Panel-Rechte, keine Secrets im HTML"),
    ("fx_test", "tickets + raidhelper + twitchlive: Datenlöschung, „Neu posten“, öffentliche APIs raids/twitch"),
    ("ws_test", "WebCore: Bot-Status, Fehlerprotokoll (Handler, Maskierung, kein Doppel-Handler), Sichern & Wiederherstellen, Audit-Tabelle"),
    ("st_test", "serverstats: Zählung, Puffer/Flush, Voice-Zeit, Aufbewahrung, keine Personendaten, SVG-Diagramme, CSV, Befehle, Dashboard-Rechte"),
    ("lv_test", "levels: XP/Cooldown/Kurve, Voice-XP, Level-Up-Meldung, Belohnungen, Rangkarte, Rangliste, Befehle, Dashboard, /me/level, Datenlöschung"),
    ("gv_test", "giveaways: Teilnahme-Regeln, persistente Buttons, faire Auslosung, Downtime-Nachholen, Reroll/Ende/Abbruch, Rechte, Dashboard, /me/gewinnspiele"),
    ("sc_test", "scheduler: nächster Termin (alle Typen, Sommerzeit, Monatsende), Downtime-Regel, Auto-Pause, allowed_mentions, Dashboard, Befehle"),
    ("op_test", "WebCore: Stufe „Bedienen“ (operate_forms, POST-Prüfung, visible_guilds, Oberfläche/JS-Sperre), Rollen-Vorlagen, Befehle, Sicherung"),
    ("opa_test", "Bedienen/Tagesgeschäft: tickets (Schließen), warns, guard, fivemadmin, welcome (Test ohne Speichern), sticky, changelog; autorole/levels/serverstats ohne Bedienen"),
    ("opb_test", "Bedienen/Tagesgeschäft: raidhelper, poll, giveaways, scheduler, twitchlive, organigram; autoroom/onlyimagevideo/commands/example ohne Bedienen"),
]

# Dateien in tests/, die keine Suite sind
HELPERS = {"__main__", "run_all", "bootstrap", "tc_seed"}


def check_registry():
    """Jede *test*-Datei muss in SUITES stehen; jeder Cog muss in einer Test-Datei vorkommen."""
    problems = []
    names = {n for n, _ in SUITES}
    for f in sorted(TESTS_DIR.glob("*.py")):
        stem = f.stem
        if stem in HELPERS or stem.endswith("_harness"):
            continue
        if stem not in names:
            problems.append(f"tests/{f.name} ist keine Harness und nicht in run_all.SUITES eingetragen")
    for name in names:
        if not (TESTS_DIR / f"{name}.py").exists():
            problems.append(f"Suite {name} fehlt (tests/{name}.py)")
    reqs = {line.split("#")[0].strip().split(">")[0].split("<")[0].split("=")[0].strip().lower()
            for line in (TESTS_DIR / "requirements.txt").read_text(encoding="utf-8").splitlines()}
    for info in sorted(ROOT.glob("*/info.json")):
        for req in json.loads(info.read_text(encoding="utf-8")).get("requirements", []):
            name = req.split(">")[0].split("<")[0].split("=")[0].split("[")[0].strip().lower()
            if name not in reqs and name != "aiohttp":  # aiohttp kommt mit Red
                problems.append(f"{info.parent.name}: Anforderung {req!r} fehlt in tests/requirements.txt")
    sources = "\n".join(f.read_text(encoding="utf-8") for f in TESTS_DIR.glob("*.py") if f.stem != "realred")
    for d in sorted(ROOT.iterdir()):
        if (d / "info.json").exists() and (d / "__init__.py").exists() and f"rc.{d.name}" not in sources:
            problems.append(f"Cog {d.name}: keine Test-Datei importiert rc.{d.name}")
    return problems


def run_suite(name, cwd, verbose):
    env = {k: v for k, v in os.environ.items() if k != "PYTHONOPTIMIZE"}  # assert muss aktiv sein
    env["PYTHONUNBUFFERED"] = "1"
    env.setdefault("PYTHONIOENCODING", "utf-8")
    t0 = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, str(TESTS_DIR / f"{name}.py")], cwd=cwd, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=TIMEOUT)
        code, out = proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        code, out = "Timeout", (exc.stdout or b"") + f"\n>>> abgebrochen nach {TIMEOUT} s\n".encode()
    return code, time.monotonic() - t0, out.decode("utf-8", "replace")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    verbose = "-v" in argv
    wanted = [a for a in argv if not a.startswith("-")]
    suites = [(n, d) for n, d in SUITES if not wanted or any(n.startswith(w) for w in wanted)]
    if not suites:
        print(f"Keine Suite passt zu {wanted}. Vorhanden: {', '.join(n for n, _ in SUITES)}")
        return 2
    gha = os.environ.get("GITHUB_ACTIONS") == "true"

    print(f"red-cogs Tests – {len(suites)} Suite(n), Python {sys.version.split()[0]}\n", flush=True)
    problems = check_registry() if not wanted else []
    for p in problems:
        print(f"[FAIL] Registry: {p}")
        if gha:
            print(f"::error title=tests/run_all::{p}")

    results = []
    t_all = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="red-cogs-run-") as cwd:
        for name, desc in suites:
            code, secs, out = run_suite(name, cwd, verbose)
            ok = code == 0
            results.append((name, ok, secs))
            print(f"[{' OK ' if ok else 'FAIL'}] {name:<16} {secs:6.1f} s  {desc}", flush=True)
            if verbose or not ok:
                lines = out.rstrip().splitlines()
                shown = lines if verbose else lines[-80:]
                if gha:
                    print(f"::group::Ausgabe {name}")
                elif not verbose and len(lines) > len(shown):
                    print(f"    … {len(lines) - len(shown)} Zeilen ausgelassen …")
                for line in shown:
                    print("    " + line)
                if gha:
                    print("::endgroup::")
                if not ok:
                    print(f"    -> Exit-Code {code}", flush=True)
                    if gha:
                        print(f"::error title=Test-Suite {name}::Exit-Code {code} – siehe Ausgabe oben")

    failed = [n for n, ok, _ in results if not ok]
    total = time.monotonic() - t_all
    print(f"\nErgebnis: {len(results) - len(failed)}/{len(results)} Suiten bestanden in {total:.1f} s"
          + (f" – fehlgeschlagen: {', '.join(failed)}" if failed else ""))
    if problems:
        print(f"Registry-Probleme: {len(problems)}")
    return 1 if failed or problems else 0


if __name__ == "__main__":
    sys.exit(main())
