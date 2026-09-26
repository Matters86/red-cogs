"""``python -m tests`` (aus der Repo-Wurzel) = ``python tests/run_all.py``."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from run_all import main  # noqa: E402

sys.exit(main())
