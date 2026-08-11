"""
preview.py
2D SVG preview of a generated FloorPlan -- pure standard library, no
matplotlib, no Rhino. Writes a plain .svg you can open in any browser.

The point of this module is to make the component system VISIBLE. The
element fills (corridor/core/unit/communal) are deliberately recessive
neutrals; the saturated colour is spent entirely on the wall components,
because those are the actual subject of the project and are otherwise
invisible in any numeric output.

Component encoding:
  SA / SB / SC  -> line colour (three CVD-validated hues)
  N             -> a node marker, not a fourth hue

N is drawn as a marker rather than a colour on purpose. It keeps the
categorical palette inside three slots (four hues cannot clear the
colourblind-separation floor when every pair can appear adjacent, which
is the case in a plan drawing), and it matches what N structurally IS --
the node/corner where members meet, not another length of edge.

Usage:
    from growth_engine import generate_floorplan
    from growth_engine.preview import save_svg

    plan = generate_floorplan(program=[...], seed=42)
    save_svg(plan, "plan.svg")

or from the command line:

    python -m growth_engine.preview --seed 42 --out plan.svg
"""

from __future__ import annotations

from .growth import FloorPlan, generate_floorplan
from .geometry import Point, normalize
from .catalog import get_unit

# --- palette -------------------------------------------------------
# Wall components: categorical slots 1-3, validated all-pairs in both
# light and dark mode (worst CVD dE 9.2 light / 9.4 dark, worst
# normal-vision dE 24.0 light / 20.9 dark).
COMPONENT_STROKE = {
    "SA": "#2a78d6",  # blue
    "SB": "#eb6834",  # orange
    "SC": "#1baf7a",  # aqua
}
NODE_STROKE = "#0b0b0b"
NODE_FILL = "#fcfcfb"

# Element fills: recessive warm neutrals. These must NOT compete with
# the component colours -- they are context, not data.
#
# Outdoor is the one exception, and deliberately so: it is the only fill
# carrying a categorical distinction rather than a shade of "interior",
# so it reads green. It is desaturated well below the SC aqua (#1baf7a)
# it sits nearest, so it stays background against the components while
# still being unmistakably not-a-room.
KIND_FILL = {
    "corridor": "#e8e6df",
    "core": "#d6d2c6",
    "stairs": "#c9c4b4",
    "unit": "#faf9f5",
    "communal": "#f0ece1",
    "outdoor": "#dfeacd",
}
KIND_EDGE = "rgba(11,11,11,0.10)"
OUTDOOR_EDGE = "rgba(74,110,52,0.45)"

SURFACE = "#fcfcfb"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
ROOM_STROKE = "#c3c2b7"

FONT = 'system-ui, -apple-system, "Segoe UI", sans-serif'


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _bounds(plan: FloorPlan) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for el in plan.elements:
        for c in el.corners:
            xs.append(c.x)
            ys.append(c.y)
    return min(xs), min(ys), max(xs), max(ys)


def _unit_room_polys(el) -> list[tuple[str, list[tuple[float, float]]]]:
    """Map a placed unit's real rooms into world coordinates, using the
    same local frame massing.generate_room_massing uses: c1 is the local
    origin, c1->c2 is local +x (corridor frontage), c1->c4 is local +y
    (into the unit's depth)."""
    try:
        unit = get_unit(el.label)
    except KeyError:
        return []
    if not unit.has_real_rooms:
        return []
    c1, c2, c3, c4 = el.corners
    along = normalize(Point(c2.x - c1.x, c2.y - c1.y))
    out = normalize(Point(c4.x - c1.x, c4.y - c1.y))
    polys = []
    for room in unit.rooms:
        pts = []
        for rx, ry in ((room.x_min, room.y_min), (room.x_max, room.y_min),
                       (room.x_max, room.y_max), (room.x_min, room.y_max)):
            p = c1 + along.scaled(rx) + out.scaled(ry)
            pts.append((p.x, p.y))
        polys.append((room.name, pts))
    return polys


def render_svg(plan: FloorPlan, out_width_px: float = 1700.0,
               padding_px: float = 56.0, show_walls: bool = True,
               show_rooms: bool = True, show_labels: bool = True,
               title: str = "Generated floor plan") -> str:
    """Render a FloorPlan to an SVG document string."""
    min_x, min_y, max_x, max_y = _bounds(plan)
    world_w = max_x - min_x
    world_h = max_y - min_y
    if world_w <= 0 or world_h <= 0:
        raise ValueError("plan has no extent -- nothing to draw")

    legend_h = 92.0
    s = (out_width_px - 2 * padding_px) / world_w
    out_height_px = world_h * s + 2 * padding_px + legend_h

    def px(x: float, y: float) -> tuple[float, float]:
        # world y is up, SVG y is down -- flip so north stays up.
        return ((x - min_x) * s + padding_px,
                (max_y - y) * s + padding_px)

    o: list[str] = []
    add = o.append
    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{out_width_px:.0f}" '
        f'height="{out_height_px:.0f}" viewBox="0 0 {out_width_px:.0f} '
        f'{out_height_px:.0f}" font-family=\'{FONT}\'>')
    add(f'<rect width="100%" height="100%" fill="{SURFACE}"/>')

    # --- element fills ---------------------------------------------
    add('<g id="elements">')
    for el in plan.elements:
        pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (px(c.x, c.y) for c in el.corners))
        fill = KIND_FILL.get(el.kind, "#eeeeee")
        # An outdoor area has no wall components drawn on it, so its own
        # outline is the only edge it gets -- it carries the weight the
        # SA/SB/SC strokes carry on a room.
        edge = OUTDOOR_EDGE if el.kind == "outdoor" else KIND_EDGE
        add(f'<polygon points="{pts}" fill="{fill}" stroke="{edge}" stroke-width="1"/>')
    add('</g>')

    # --- real room subdivisions ------------------------------------
    if show_rooms:
        add('<g id="rooms" fill="none" stroke-dasharray="3 3">')
        for el in plan.elements:
            if el.kind != "unit":
                continue
            for _name, poly in _unit_room_polys(el):
                pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in (px(x, y) for x, y in poly))
                add(f'<polygon points="{pts}" stroke="{ROOM_STROKE}" stroke-width="1"/>')
        add('</g>')

    # --- wall components -------------------------------------------
    # Drawn from plan.walls, not per element: each physical wall is
    # built once, so a shared boundary is stroked once here too.
    if show_walls:
        add('<g id="walls" stroke-linecap="round">')
        for wall in plan.walls:
            for w in wall.segments:
                if w.component == "N":
                    continue
                x1, y1 = px(w.start.x, w.start.y)
                x2, y2 = px(w.end.x, w.end.y)
                col = COMPONENT_STROKE.get(w.component, INK_MUTED)
                add(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                    f'stroke="{col}" stroke-width="2.5"/>')
        add('</g>')
        # nodes on top, as markers rather than a fourth hue
        add('<g id="nodes">')
        for wall in plan.walls:
            for w in wall.segments:
                if w.component != "N":
                    continue
                mx = (w.start.x + w.end.x) / 2
                my = (w.start.y + w.end.y) / 2
                cx, cy = px(mx, my)
                add(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="3.2" fill="{NODE_FILL}" '
                    f'stroke="{NODE_STROKE}" stroke-width="1.4"/>')
        add('</g>')

    # --- labels ----------------------------------------------------
    if show_labels:
        add(f'<g id="labels" fill="{INK_PRIMARY}" font-size="12" text-anchor="middle">')
        for el in plan.elements:
            cx = sum(c.x for c in el.corners) / len(el.corners)
            cy = sum(c.y for c in el.corners) / len(el.corners)
            tx, ty = px(cx, cy)
            add(f'<text x="{tx:.1f}" y="{ty:.1f}" paint-order="stroke" '
                f'stroke="{SURFACE}" stroke-width="3">{_esc(el.label)}</text>')
        add('</g>')

    # --- legend, scale bar, north --------------------------------------
    ly = out_height_px - legend_h + 30
    lx = padding_px
    add(f'<g id="legend" font-size="12" fill="{INK_SECONDARY}">')
    for comp in ("SA", "SB", "SC"):
        add(f'<line x1="{lx:.0f}" y1="{ly:.0f}" x2="{lx + 26:.0f}" y2="{ly:.0f}" '
            f'stroke="{COMPONENT_STROKE[comp]}" stroke-width="2.5" stroke-linecap="round"/>')
        add(f'<text x="{lx + 33:.0f}" y="{ly + 4:.0f}">{comp}</text>')
        lx += 74
    add(f'<circle cx="{lx + 13:.0f}" cy="{ly:.0f}" r="3.2" fill="{NODE_FILL}" '
        f'stroke="{NODE_STROKE}" stroke-width="1.4"/>')
    add(f'<text x="{lx + 33:.0f}" y="{ly + 4:.0f}">N (node)</text>')

    # scale bar -- a round 10m
    bar_world = 1000.0
    bar_px = bar_world * s
    bx = out_width_px - padding_px - bar_px
    add(f'<line x1="{bx:.1f}" y1="{ly:.0f}" x2="{bx + bar_px:.1f}" y2="{ly:.0f}" '
        f'stroke="{INK_PRIMARY}" stroke-width="2"/>')
    add(f'<line x1="{bx:.1f}" y1="{ly - 4:.0f}" x2="{bx:.1f}" y2="{ly + 4:.0f}" stroke="{INK_PRIMARY}" stroke-width="2"/>')
    add(f'<line x1="{bx + bar_px:.1f}" y1="{ly - 4:.0f}" x2="{bx + bar_px:.1f}" y2="{ly + 4:.0f}" stroke="{INK_PRIMARY}" stroke-width="2"/>')
    add(f'<text x="{bx + bar_px / 2:.1f}" y="{ly + 18:.0f}" text-anchor="middle">10 m</text>')
    add('</g>')

    add(f'<text x="{padding_px:.0f}" y="{padding_px - 22:.0f}" font-size="15" '
        f'font-weight="600" fill="{INK_PRIMARY}">{_esc(title)}</text>')
    add(f'<text x="{out_width_px - padding_px:.0f}" y="{padding_px - 22:.0f}" '
        f'font-size="12" text-anchor="end" fill="{INK_MUTED}">'
        f'{world_w / 100:.1f} x {world_h / 100:.1f} m</text>')
    add('</svg>')
    return "\n".join(o)


def save_svg(plan: FloorPlan, path: str, **kwargs) -> str:
    svg = render_svg(plan, **kwargs)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)
    return path


def plan_to_dict(plan: FloorPlan) -> dict:
    """JSON-serialisable dump of a plan, including wall components and
    real room subdivisions -- for feeding a web viewer."""
    return {
        "entrance": [plan.entrance.x, plan.entrance.y],
        "core": [plan.core_position.x, plan.core_position.y],
        "unit_counts": plan.unit_counts,
        # Walls live at plan level because each is built once and may be
        # referenced by two elements. Elements carry wall_ids into this.
        "walls": [
            {
                "id": wall.id,
                "owners": list(wall.owners),
                "owner_labels": [plan.elements[i].label for i in wall.owners],
                "shared": wall.shared,
                "length_cm": round(wall.length_cm, 1),
                "segments": [
                    {"c": s.component,
                     "p": [round(s.start.x, 1), round(s.start.y, 1),
                           round(s.end.x, 1), round(s.end.y, 1)]}
                    for s in wall.segments
                ],
            }
            for wall in plan.walls
        ],
        "elements": [
            {
                "kind": el.kind,
                "label": el.label,
                "height_cm": el.height_cm,
                "corners": [[c.x, c.y] for c in el.corners],
                "wall_ids": list(el.wall_ids),
                "rooms": [
                    {"name": n, "poly": [[round(x, 1), round(y, 1)] for x, y in poly]}
                    for n, poly in _unit_room_polys(el)
                ],
            }
            for el in plan.elements
        ],
    }


DEFAULT_PROGRAM = [
    "Studio_A", "Studio_B", "1Bed_A", "1Bed_B", "SK", "2Bed_A",
    "2Bed_B", "SL", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
]


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Render a generated floor plan to SVG.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", default="plan.svg")
    ap.add_argument("--width", type=float, default=1700.0, help="output width in px")
    ap.add_argument("--program", nargs="*", default=DEFAULT_PROGRAM)
    ap.add_argument("--no-walls", action="store_true")
    ap.add_argument("--no-rooms", action="store_true")
    ap.add_argument("--no-labels", action="store_true")
    args = ap.parse_args(argv)

    plan = generate_floorplan(program=args.program, seed=args.seed)
    save_svg(plan, args.out, out_width_px=args.width,
             show_walls=not args.no_walls, show_rooms=not args.no_rooms,
             show_labels=not args.no_labels,
             title=f"Generated floor plan - seed {args.seed}")
    placed = sum(plan.unit_counts.values())
    missing = [p for p in args.program if p not in plan.unit_counts]
    print(f"wrote {args.out}  ({placed}/{len(args.program)} placed)")
    if missing:
        print(f"  NOT placed: {missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
