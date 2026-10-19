"""Draw a flow figure from a short description, and check every edge against the code.

    python docs/tools/flow.py docs/flows/ask.yaml        # writes docs/flows/ask.svg.html
    python docs/tools/flow.py --check docs/flows/*.yaml  # checks only; exit 1 on a miss

A box is a real file on a grid (lane = row, col = column). An edge says how it shows in code:
  import  the source imports the target module
  calls   the source contains `text`
  http    the source contains `text` and the target route file declares it
  queue   both files contain `text`
An edge that cannot be seen is drawn dashed, labelled "assumed", and fails --check unless the
YAML marks it `assumed: true`.

Edge layout: `via` [[col, row], …] bends it (x.5 / y.5 are the gaps between boxes); `exit` and
`enter` shift where it leaves or meets a box; `reverse` flips the arrow; `label_at` places the
label by hand.
"""

import html
import re
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]

#: One grid for every flow, so all figures look alike.
LANE_X, BOX_X0, COL_W, BOX_W, BOX_H, ROW_H, TOP = 104, 116, 190, 150, 44, 80, 16
#: How far an arrow head stops short of the box it points at.
HEAD = 4

Point = tuple[float, float]

ARROW_HEAD = (
    '<defs><marker id="fa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
    'markerHeight="6" orient="auto-start-reverse">'
    '<path d="M 0 0 L 10 5 L 0 10 z" fill="currentColor"/></marker></defs>'
)
EDGE_STYLE = (
    '<g stroke="var(--ink-faint)" stroke-width="1.3" fill="none" color="var(--ink-faint)" '
    'marker-end="url(#fa)">'
)


def read(path: str) -> str:
    f = ROOT / path
    return f.read_text() if f.is_file() else ""


def module_of(path: str) -> str:
    """`src/mycel/services/chat.py` → `mycel.services.chat`; "" outside the package."""
    parts = Path(path).with_suffix("").parts
    return ".".join(parts[parts.index("mycel") :]) if "mycel" in parts else ""


def imports(source: str, module: str) -> bool:
    head, _, tail = module.rpartition(".")
    m, h = re.escape(module), re.escape(head)
    return bool(
        re.search(rf"from {m} import|import {m}\b|from {h} import [^\n]*\b{tail}\b", source)
    )


def seen(edge: dict[str, Any], boxes: dict[str, Any]) -> bool:
    """Whether the code shows this edge."""
    a, b = read(boxes[edge["from"]]["file"]), read(boxes[edge["to"]]["file"])
    kind, text = edge.get("kind", "import"), edge.get("text", "")
    if kind == "import":
        module = module_of(boxes[edge["to"]]["file"])
        return bool(module) and imports(a, module)
    if kind == "calls":
        return text in a
    if kind == "http":
        return text in a and text.strip('"').split("{")[0].rstrip("/") in b
    if kind == "queue":
        return text in a and text in b
    return False


def check(spec: dict[str, Any]) -> list[str]:
    """Every missing file, every edge the code does not show, every layout clash."""
    boxes = {b["id"]: b for b in spec["boxes"]}
    misses = [
        f"box {b['id']}: no file {b['file']}"
        for b in spec["boxes"]
        if not (ROOT / b["file"]).exists()
    ]
    for e in spec["edges"]:
        e["_seen"] = seen(e, boxes)
        if not e["_seen"] and not e.get("assumed"):
            misses.append(
                f"edge {e['from']}→{e['to']} ({e.get('kind', 'import')}): not seen in code"
            )
    return misses + layout_misses(spec)


def X(c: float) -> float:
    """Grid column → x of its centre."""
    return BOX_X0 + c * COL_W + BOX_W / 2


def Y(r: float) -> float:
    """Grid row → y of its centre."""
    return TOP + r * ROW_H + BOX_H / 2


def toward(p: Point, q: Point, by: float) -> Point:
    """`p` moved `by` units toward `q` along their shared axis."""
    (px, py), (qx, qy) = p, q
    sign = lambda d: (d > 0) - (d < 0)  # noqa: E731
    return px + by * sign(qx - px), py + by * sign(qy - py)


def on_edge(box: dict[str, Any], centre: Point, toward_pt: Point) -> Point:
    """Where a line from the box's anchor toward `toward_pt` leaves the box."""
    (x, y), (tx, ty) = centre, toward_pt
    if y == ty:
        return (box["x"] + BOX_W if tx > x else box["x"]), y
    return x, (box["y"] + BOX_H if ty > y else box["y"])


def route(e: dict[str, Any], a: dict[str, Any], b: dict[str, Any]) -> list[Point]:
    """The polyline from box a to box b, square corners only."""
    start = (a["col"] + e.get("exit", 0), a["row"])
    stop = (b["col"] + e.get("enter", 0), b["row"])
    via = [tuple(v) for v in e.get("via", [])]
    if not via and start[0] != stop[0] and start[1] != stop[1]:
        # down to the gap just before the target row, across, then into the target
        gap = stop[1] - 0.5 if stop[1] > start[1] else stop[1] + 0.5
        via = [(start[0], gap), (stop[0], gap)]
    grid = [start, *via, stop]
    pts = [(X(c), Y(r)) for c, r in grid]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
        if x1 != x2 and y1 != y2:
            raise ValueError(f"edge {e['from']}→{e['to']}: a diagonal segment; add `via` points")
    start = on_edge(a, pts[0], pts[1])
    end = on_edge(b, pts[-1], pts[-2])
    pts = [start, *pts[1:-1], end]
    if e.get("reverse"):
        pts.reverse()
    pts[-1] = toward(pts[-1], pts[-2], HEAD)
    return pts


def label_spot(e: dict[str, Any], pts: list[Point]) -> Point:
    """Beside the longest segment, unless the YAML places it."""
    if "label_at" in e:
        c, r = e["label_at"]
        return X(c), Y(r) + 3
    segs = list(zip(pts, pts[1:], strict=False))
    if len(segs) == 1 and pts[0][1] == pts[1][1]:
        return min(pts[0][0], pts[1][0]) + 3, pts[0][1] + BOX_H / 2 + 11
    (x1, y1), (x2, y2) = max(segs, key=lambda s: abs(s[0][0] - s[1][0]) + abs(s[0][1] - s[1][1]))
    if y1 == y2:
        return min(x1, x2) + 8, y1 - 4
    return x1 + 8, ((y1 + y2) / 2 + 3 if len(segs) == 1 else min(y1, y2) + 22)


def text(
    x: float,
    y: float,
    body: str,
    *,
    mono: bool = True,
    size: float = 9,
    fill: str = "var(--ink-faint)",
    extra: str = "",
) -> str:
    font = "var(--mono)" if mono else "var(--sans)"
    where = f'x="{x:.0f}" y="{y:.0f}"'
    look = f'font-family="{font}" font-size="{size}" fill="{fill}"{extra}'
    return f"<text {where} {look}>{html.escape(body)}</text>"


def box_svg(b: dict[str, Any]) -> str:
    fill, stroke, color = (
        ("var(--gold-wash)", "var(--gold)", "var(--gold)")
        if b.get("hot")
        else ("var(--surface)", "var(--line)", "var(--ink)")
    )
    tip = html.escape(b["file"].replace("src/mycel/", "") + "\n" + b.get("tip", b["role"]))
    return (
        f'<a href="vscode://file{ROOT / b["file"]}" class="hv" '
        f'data-path="{b["file"]}" data-tip="{tip}">'
        f'<rect x="{b["x"]:.0f}" y="{b["y"]:.0f}" width="{BOX_W}" height="{BOX_H}" rx="2" '
        f'fill="{fill}" stroke="{stroke}"/>'
        + text(b["x"] + 10, b["y"] + 18, b["label"], size=11, fill=color)
        + text(b["x"] + 10, b["y"] + 34, b["role"], mono=False, size=9.5, fill="var(--ink-soft)")
        + "</a>"
    )


def edge_label(e: dict[str, Any], x: float, y: float) -> str:
    out = ""
    if e.get("step"):
        out += f'<circle cx="{x + 6:.0f}" cy="{y - 3:.0f}" r="8" fill="var(--accent)"/>'
        out += text(
            x + 6, y + 0.5, str(e["step"]), size=9.5, fill="#fff", extra=' text-anchor="middle"'
        )
        x += 18
    return out + text(x, y, e.get("label", "") + ("" if e["_seen"] else " · assumed"))


LABEL_H, CHAR_W = 11, 5.6


def label_box(e: dict[str, Any], x: float, y: float) -> tuple[float, float, float, float]:
    """The area a label covers: (x1, y1, x2, y2)."""
    lead = 18 if e.get("step") else 0
    w = lead + CHAR_W * len(e.get("label", "") + ("" if e["_seen"] else " · assumed"))
    return x, y - LABEL_H + 2, x + w, y + 3


def overlaps(a: tuple[float, ...], b: tuple[float, ...]) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def place_labels(
    spec: dict[str, Any], boxes: dict[str, Any], routes: list[list[Point]]
) -> list[Point]:
    """A spot per label: the default, else the first nearby spot clear of boxes and labels."""
    rect = [(b["x"], b["y"], b["x"] + BOX_W, b["y"] + BOX_H) for b in boxes.values()]
    taken: list[tuple[float, float, float, float]] = []
    spots = []
    for e, pts in zip(spec["edges"], routes, strict=True):
        x0, y0 = label_spot(e, pts)
        tries = (
            [(x0, y0)]
            if "label_at" in e
            else [
                (x0 + dx, y0 + dy)
                for dy in (0, 12, -12, 24, -24, 36)
                for dx in (0, 30, -30, 60, -60, 90)
            ]
        )
        for x, y in tries:
            lb = label_box(e, x, y)
            if not any(overlaps(lb, r) for r in rect) and not any(overlaps(lb, t) for t in taken):
                break
        else:
            x, y = x0, y0
        taken.append(label_box(e, x, y))
        spots.append((x, y))
    return spots


def layout_misses(spec: dict[str, Any]) -> list[str]:
    """Edges through an unrelated box, labels over a box or another label."""
    lanes = spec["lanes"]
    boxes = {b["id"]: b for b in spec["boxes"]}
    for b in spec["boxes"]:
        b["row"] = lanes.index(b["lane"])
        b["x"], b["y"] = X(b["col"]) - BOX_W / 2, Y(b["row"]) - BOX_H / 2
    rect = {i: (b["x"], b["y"], b["x"] + BOX_W, b["y"] + BOX_H) for i, b in boxes.items()}
    misses, placed = [], []
    routes = [route(e, boxes[e["from"]], boxes[e["to"]]) for e in spec["edges"]]
    spots = place_labels(spec, boxes, routes)
    for e, pts, spot in zip(spec["edges"], routes, spots, strict=True):
        name = f"{e['from']}→{e['to']}"
        for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
            seg = (min(x1, x2) - 0.5, min(y1, y2) - 0.5, max(x1, x2) + 0.5, max(y1, y2) + 0.5)
            for i, r in rect.items():
                if i not in (e["from"], e["to"]) and overlaps(
                    seg, (r[0] + 1, r[1] + 1, r[2] - 1, r[3] - 1)
                ):
                    misses.append(f"edge {name} crosses box {i}")
        lb = label_box(e, *spot)
        for i, r in rect.items():
            if overlaps(lb, r):
                misses.append(f"label of {name} sits on box {i}")
        for other, ob in placed:
            if overlaps(lb, ob):
                misses.append(f"label of {name} sits on label of {other}")
        placed.append((name, lb))
    return sorted(set(misses))


def draw(spec: dict[str, Any]) -> str:
    """The figure as one inline SVG."""
    lanes = spec["lanes"]
    boxes = {b["id"]: b for b in spec["boxes"]}
    for b in spec["boxes"]:
        b["row"] = lanes.index(b["lane"])
        b["x"], b["y"] = X(b["col"]) - BOX_W / 2, Y(b["row"]) - BOX_H / 2
    width = max(b["x"] for b in spec["boxes"]) + BOX_W + 16
    height = TOP + len(lanes) * ROW_H

    paths, labels = [], []
    routes = [route(e, boxes[e["from"]], boxes[e["to"]]) for e in spec["edges"]]
    for e, pts, spot in zip(spec["edges"], routes, place_labels(spec, boxes, routes), strict=True):
        dash = "" if e["_seen"] else ' stroke-dasharray="4 3"'
        paths.append('<path d="M ' + " L ".join(f"{x:.0f} {y:.0f}" for x, y in pts) + f'"{dash}/>')
        labels.append(edge_label(e, *spot))

    lane_names = "".join(
        text(LANE_X, Y(i) + 3, lane.upper(), extra=' text-anchor="end" letter-spacing="1.2"')
        for i, lane in enumerate(lanes)
    )
    return (
        f'<svg class="diagram" viewBox="0 0 {width:.0f} {height:.0f}" role="img" '
        f'aria-label="{html.escape(spec["title"])}">'
        + ARROW_HEAD
        + lane_names
        + "".join(box_svg(b) for b in spec["boxes"])
        + EDGE_STYLE
        + "".join(paths)
        + "</g>"
        + "".join(labels)
        + "</svg>"
    )


def main(argv: list[str]) -> int:
    only_check = "--check" in argv
    failed = False
    for path in [a for a in argv if not a.startswith("--")]:
        spec = yaml.safe_load(Path(path).read_text())
        misses = check(spec)
        for miss in misses:
            print(f"{path}: {miss}")
        failed |= bool(misses)
        if not only_check:
            out = Path(path).with_suffix(".svg.html")
            out.write_text(draw(spec) + "\n")
            counts = f"{len(spec['boxes'])} boxes, {len(spec['edges'])} edges"
            print(f"{path} → {out.name}: {counts}, {len(misses)} misses")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
