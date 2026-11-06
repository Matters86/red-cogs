"""Lesbare Organigramm-Seiten: vollständige Struktur und vollständige Personenlisten."""
from dataclasses import dataclass, field

from .render import RChart, RPerson, _Renderer, _hex, TEXT, MUTED, PANEL, BORDER

MIN_PAGE_SIZE, MAX_PAGE_SIZE, DEFAULT_PAGE_SIZE = 5, 50, 20
MAX_PAGES = 500
MAX_EXPORT_BYTES = 64 * 1024 * 1024


class PagesTooLarge(ValueError):
    pass


@dataclass
class ChartPage:
    title: str
    kind: str
    path: str = ""
    color: str = "#3ddc97"
    people: list[RPerson] = field(default_factory=list)
    positions: list[tuple[str, int, int]] = field(default_factory=list)


def page_size(value):
    try:
        return max(MIN_PAGE_SIZE, min(MAX_PAGE_SIZE, int(value)))
    except (ValueError, TypeError):
        return DEFAULT_PAGE_SIZE


def plan_pages(chart: RChart, size=DEFAULT_PAGE_SIZE) -> list[ChartPage]:
    """Stabile Vorreihenfolge; dieselben Identitäten/Zuordnungen wie alle anderen Ausgaben."""
    size = page_size(size)
    nodes = []

    def collect(node, path, depth):
        full_path = path + [node.label or "Ohne Bezeichnung"]
        people = [person for person in node.people if not person.vacant]
        nodes.append((node, full_path, depth, people))
        for child in node.children:
            collect(child, full_path, depth + 1)

    for root in chart.roots:
        collect(root, [], 0)
    total = (len(nodes) + size - 1) // size + sum(max(1, (len(people) + size - 1) // size)
                                               for _, _, _, people in nodes)
    if total > MAX_PAGES:
        raise PagesTooLarge(f"Das Organigramm benötigt {total} Seiten; erlaubt sind höchstens {MAX_PAGES}. "
                            "Erhöhe Personen/Positionen je Seite oder teile es in mehrere Organigramme.")
    result = []
    for offset in range(0, len(nodes), size):
        result.append(ChartPage("Hierarchieübersicht", "overview", positions=[
            (" › ".join(path), depth, len(people)) for _, path, depth, people in nodes[offset:offset + size]
        ]))
    for node, path, _, people in nodes:
        for offset in range(0, max(1, len(people)), size):
            part = offset // size + 1
            parts = max(1, (len(people) + size - 1) // size)
            title = node.label or "Ohne Bezeichnung"
            if parts > 1:
                title += f" · Teil {part}/{parts}"
            result.append(ChartPage(title, "people", path=" › ".join(path), color=node.color,
                                    people=people[offset:offset + size]))
    return result or [ChartPage("Hierarchieübersicht", "overview")]


def render_page(chart: RChart, page: ChartPage, index: int, total: int) -> bytes:
    """Breite 900px, Namen/Positionspfade werden vollständig umbrochen statt gekürzt."""
    renderer = _Renderer(RChart(chart.title, accent=chart.accent, show_avatars=chart.show_avatars,
                               footer=f"{chart.footer} · Seite {index + 1}/{total}"))
    width = 820
    subtitle = renderer._wrap(page.title, "label", 18, width - 28)
    path_lines = renderer._wrap(page.path, "body", 12, width - 28) if page.path else []
    header_h = 20 + len(subtitle) * 25 + len(path_lines) * 18 + 16
    rows = []
    if page.kind == "overview":
        for path, depth, count in page.positions:
            lines = renderer._wrap(path, "label", 14, width - 120)
            rows.append((lines, max(60, 24 + len(lines) * 21), depth, count))
    else:
        for person in page.people:
            lines = renderer._wrap(person.name, "body", 15, width - 95)
            rows.append((lines, max(56, 22 + len(lines) * 22), person, None))
    height = header_h + sum(row[1] + 8 for row in rows) + (64 if not rows else 0)
    ox, oy = renderer._canvas(width, height)
    y = oy
    for line in subtitle:
        renderer._text((ox + 14, y), line, "label", 18, TEXT)
        y += 25
    for line in path_lines:
        renderer._text((ox + 14, y), line, "body", 12, MUTED)
        y += 18
    y = oy + header_h
    if not rows:
        renderer._text((ox + 14, y + 12), "Keine Personen zugeordnet" if page.kind == "people" else "Keine Positionen",
                       "body", 15, MUTED)
    for lines, row_h, item, count in rows:
        renderer._rrect((ox, y, ox + width, y + row_h), 9, fill=PANEL, outline=BORDER)
        if page.kind == "overview":
            for row, line in enumerate(lines):
                renderer._text((ox + 14, y + 12 + row * 21), line, "label", 14, TEXT)
            renderer._text((ox + width - 96, y + 18), f"{count} Personen", "body", 11, MUTED)
        else:
            tx = ox + 16
            if chart.show_avatars:
                renderer._paste(renderer._avatar(item, 32, _hex(page.color)), (tx, y + (row_h - 32) / 2))
                tx += 48
            for row, line in enumerate(lines):
                renderer._text((tx, y + 12 + row * 22), line, "body", 15, TEXT)
        y += row_h + 8
    return renderer._finish()
