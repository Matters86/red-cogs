"""Native Organigramm-Layouts: Ausgabe, Sicherheit, Schriftlängen und Matrix-Identität."""
import io
from copy import deepcopy
from unittest.mock import patch

import bootstrap
from PIL import Image
from rc.organigram import render as R


def chart(pattern):
    child = R.RNode("child", "Sehr lange Position mit mehreren Wörtern", "#6cb6ff",
                    people=[R.RPerson("Sehr langer Anzeigename zur Lesbarkeitsprüfung", member_id=1),
                            R.RPerson("Gleicher Name", member_id=2)])
    root = R.RNode("root", "Leitung", people=[R.RPerson("Sehr langer Anzeigename zur Lesbarkeitsprüfung", member_id=1)],
                   children=[child, R.RNode("empty", "Unbesetzt", people=[R.RPerson("unbesetzt", vacant=True)])])
    return R.RChart("Layout-Prüfung", pattern, roots=[root], footer="Testserver")


def main():
    assert len(R.PATTERNS) == 8
    images = {}
    for pattern in R.PATTERNS:
        assert (bootstrap.ROOT / "organigram" / "assets" / "previews" / f"{pattern}.png").is_file()
        image = Image.open(io.BytesIO(R.render_chart_png(chart(pattern))))
        assert image.format == "PNG" and image.width > 100 and image.height > 100
        assert image.width * image.height <= R.MAX_PX
        images[pattern] = image
    assert images["horizontal"].width > images["horizontal"].height
    assert images["teamzeilen"].width >= 800
    assert images["matrix"].width > images["liste"].width

    # Jeder neue Renderer muss vor großer Allokation dieselben Bildgrenzen beachten.
    for pattern in ("horizontal", "teamzeilen", "matrix"):
        with patch.object(R, "MAX_PX", 100):
            try:
                R.render_chart_png(chart(pattern))
            except R.ChartTooLarge:
                pass
            else:
                raise AssertionError(f"{pattern}: Bildgrenze nicht geprüft")

    # Matrix verbindet gleiche Discord-ID über Rollen hinweg; Namen allein werden nie verbunden.
    base = chart("matrix")
    single = Image.open(io.BytesIO(R.render_chart_png(base)))
    separate = deepcopy(base)
    separate.roots[0].children[0].people[0].member_id = 99
    distinct = Image.open(io.BytesIO(R.render_chart_png(separate)))
    assert distinct.height == single.height + 46
    text_only = deepcopy(base)
    text_only.roots[0].people[0].member_id = None
    text_only.roots[0].children[0].people[0].member_id = None
    assert Image.open(io.BytesIO(R.render_chart_png(text_only))).height == distinct.height
    print("Acht PNG-Layouts, lange Texte, Größenbremse und Matrix-Identitäten – OK")


if __name__ == "__main__":
    main()
