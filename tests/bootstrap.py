"""Gemeinsamer Start für alle Test-Suiten – wird von jeder Harness als Erstes importiert.

* ``ROOT``: Repo-Wurzel (Elternordner von ``tests/``), unabhängig vom Arbeitsverzeichnis.
* ``TMP``: temporärer Ordner für alle Testdaten (Red-Config, JSON-Daten, SQLite …),
  wird beim Prozessende gelöscht.
* Red wird mit einer **eigenen** Instanz in ``TMP`` gestartet – die echte Red-Konfiguration
  des Rechners (``config.json`` im Nutzerordner) wird weder gelesen noch verändert.
* Das Repo ist als Paket ``rc`` importierbar: ``from rc.tickets.tickets import Tickets``.
* ``tests/`` liegt auf ``sys.path``, damit sich die Harness-Dateien gegenseitig importieren können.
"""
import atexit
import json
import pathlib
import shutil
import sys
import tempfile
import types
from copy import deepcopy

if not __debug__:
    raise SystemExit("Die Tests prüfen mit assert – bitte nicht mit python -O / PYTHONOPTIMIZE starten.")

TESTS_DIR = pathlib.Path(__file__).resolve().parent
ROOT = TESTS_DIR.parent

if str(TESTS_DIR) not in sys.path:
    sys.path.insert(0, str(TESTS_DIR))

TMP = pathlib.Path(tempfile.mkdtemp(prefix="red-cogs-tests-"))
atexit.register(shutil.rmtree, TMP, ignore_errors=True)

from redbot.core import data_manager  # noqa: E402

INSTANCE = "red_cogs_tests"
if data_manager.basic_config is None:
    data_manager.config_file = TMP / "red-config.json"
    _cfg = deepcopy(data_manager.basic_config_default)
    _cfg.update(DATA_PATH=str(TMP / "red-data"), STORAGE_TYPE="JSON", STORAGE_DETAILS={})
    data_manager.config_file.write_text(json.dumps({INSTANCE: _cfg}), encoding="utf-8")
    data_manager.load_basic_configuration(INSTANCE)

if "rc" not in sys.modules:
    _pkg = types.ModuleType("rc")
    _pkg.__path__ = [str(ROOT)]
    sys.modules["rc"] = _pkg


def cog_dirs():
    """Alle Cog-Ordner im Repo (Ordner mit ``info.json`` und ``__init__.py``)."""
    return sorted(p for p in ROOT.iterdir()
                  if p.is_dir() and (p / "info.json").exists() and (p / "__init__.py").exists())


def tmpdir(prefix):
    """Neuer Unterordner in ``TMP`` (wird mit aufgeräumt)."""
    return pathlib.Path(tempfile.mkdtemp(prefix=prefix, dir=TMP))
