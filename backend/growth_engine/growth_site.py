"""
growth_site.py
The site-driven growth strategy: perimeter blocks around a courtyard,
laid out on the grids the plot's own edges give.

HOW THIS DIFFERS FROM growth.py
The branch strategy grows a cross: an entrance somewhere inside the
plot, a spine running south, a core, three orthogonal arms, and rooms
hung off them. It is a building that happens to be on a site.

This one starts at the STREET. The entrance sits on a real frontage --
Deptford Church Street, the main road -- and the building lines the
edges of the plot with the middle left open. That is what Adela's two
option sketches show, and it is the ordinary way a London block is made.

Both strategies are kept. A lot of verified behaviour depends on the
branch strategy's output shape (shared-wall resolution, stacking, frame,
facade), and having the two side by side on the same program and seed is
worth more than picking one.

THE TWO GRIDS
site_grid reads the axes off the edges and finds that the plot offers two
families, not three: the street frontages agree with each other to within
a degree, and Crossfield's diagonal is 35 degrees off. Each frontage band
is laid out on ITS OWN family, so the building follows the street it
fronts. Where two families meet there is a seam, and the seam is where
this will look worst -- it is marked in the plan view for that reason.

Consequence worth stating: elements on the diagonal family are ROTATED
about 32 degrees off cardinal. The engine has always produced
axis-aligned rectangles, and several things downstream take a bounding
box where they used to be able to assume the box WAS the shape. massing
and the 3D views handle the real corners; frame.py still works off
bounding boxes and therefore DEGRADES on the diagonal band -- its columns
land on the bounding box rather than the rotated footprint. That is a
known limit, not a silent one.

WHY THE OUTER FACE GOES ON THE FRONTAGE
Units carry surveyed depths from 4.2 to 8.2 m. A corridor at a fixed
offset would leave the shallow ones short of the street, which is the one
thing a perimeter block cannot do. So each unit's OUTER face sits on the
frontage line and it extends inward by its own depth; the corridor runs
behind the deepest of them. Shallow units leave a pocket behind, and the
residual pass picks those up as green -- the layout corrects itself
rather than needing every unit to be the same size.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .catalog import get_unit
from .geometry import Point, polygon_contains, polygons_overlap
from .growth import (
    CORRIDOR_WIDTH_CM,
    CORE_SIZE_CM,
    LEVEL_HEIGHT_CM,
    MAX_LEVELS,
    OUTDOOR_HEIGHT_CM,
    RESIDENTIAL_KEYS,
    FloorPlan,
    PlacedElement,
    _assign_growth_steps,
    _resolve_walls_per_level,
)
from .shared_spaces import get_shared, is_outdoor
from .site_grid import build_field, extract_axes, grid_families
from .walls import walls_by_owner

CORRIDOR_HALF = CORRIDOR_WIDTH_CM / 2

# How far along a frontage to step when a bay is blocked, and the
# smallest gap worth trying to fill. Both in cm.
STEP_CM = 90.0

# A band is abandoned once this many consecutive bays fail -- it has run
# off the end of the frontage or into the neighbouring band.
MAX_BAND_MISSES = 6

# Smallest leftover worth calling a garden. 60 m2, in cm2 because that is
# what the engine measures in -- and written as a product rather than a
# literal, because 60 m2 is 600_000 cm2 and getting that wrong by a
# factor of ten silently swallows every green area but the largest.
MIN_GREEN_CM2 = 60.0 * 100.0 * 100.0


@dataclass
class SiteContext:
    """Everything the strategy needs to know about the plot."""
    boundary: list[Point]          # cm, entrance at origin
    boundary_m: list[tuple]        # m, site frame
    origin_m: tuple[float, float]
    families: list
    axes: list


def build_context(site, inset_m: float = 6.0, names=None) -> SiteContext:
    b_m = site.boundary(inset_m)
    axes = extract_axes(b_m, names)
    fams = grid_families(axes)
    return SiteContext(
        boundary=[Point(x, y) for x, y in site.boundary_cm(inset_m)],
        boundary_m=b_m,
        origin_m=site.origin_m,
        families=fams,
        axes=axes,
    )


def _to_cm(ctx: SiteContext, x_m: float, y_m: float) -> Point:
    ox, oy = ctx.origin_m
    return Point((x_m - ox) * 100.0, (y_m - oy) * 100.0)


def _family_of_edge(ctx: SiteContext, edge_index: int) -> int:
    for fi, fam in enumerate(ctx.families):
        if any(a.edge_index == edge_index for a in fam.axes):
            return fi
    return 0


def _rect(a: Point, b: Point, u: Point, n: Point, along: float, deep: float):
    """Rectangle from a start point, `along` the frontage and `deep` in."""
    p0 = a
    p1 = Point(a.x + u.x * along, a.y + u.y * along)
    p2 = Point(p1.x + n.x * deep, p1.y + n.y * deep)
    p3 = Point(p0.x + n.x * deep, p0.y + n.y * deep)
    return [p0, p1, p2, p3]


def _free(occupied, level, floors, corners) -> bool:
    for lv in range(level, level + floors):
        if any(polygons_overlap(corners, ex) for ex in occupied.get(lv, [])):
            return False
    return True


def _claim(occupied, level, floors, corners) -> None:
    for lv in range(level, level + floors):
        occupied.setdefault(lv, []).append(corners)


def _place(elements, occupied, boundary, kind, label, corners,
           level, height_cm=LEVEL_HEIGHT_CM) -> bool:
    floors = max(1, int(round(height_cm / LEVEL_HEIGHT_CM)))
    if not polygon_contains(corners, boundary):
        return False
    if not _free(occupied, level, floors, corners):
        return False
    _claim(occupied, level, floors, corners)
    elements.append(PlacedElement(kind, label, corners,
                                  height_cm=height_cm, level=level))
    return True


def _frontages(ctx: SiteContext, entrance_edge: int) -> list[int]:
    """Edge indices, the entrance frontage first.

    Order matters: bands are laid in sequence and the first one gets the
    space where two bands would overlap at a corner. Putting the entrance
    frontage first means the main road gets the continuous elevation and
    the side streets butt into it, which is the right way round.
    """
    n = len(ctx.boundary_m)
    return [entrance_edge] + [i for i in range(n) if i != entrance_edge]


def _edge_frame(ctx: SiteContext, edge: int):
    """(start, direction, inward normal, length) of one frontage, in cm."""
    n = len(ctx.boundary_m)
    a = _to_cm(ctx, *ctx.boundary_m[edge])
    b = _to_cm(ctx, *ctx.boundary_m[(edge + 1) % n])
    dx, dy = b.x - a.x, b.y - a.y
    length = math.hypot(dx, dy)
    u = Point(dx / length, dy / length)
    # Inward normal: toward the plot's centroid, measured rather than
    # assumed, because the boundary's winding is not guaranteed.
    cx = sum(p.x for p in ctx.boundary) / len(ctx.boundary)
    cy = sum(p.y for p in ctx.boundary) / len(ctx.boundary)
    nrm = Point(-u.y, u.x)
    mid = Point((a.x + b.x) / 2, (a.y + b.y) / 2)
    if (cx - mid.x) * nrm.x + (cy - mid.y) * nrm.y < 0:
        nrm = Point(-nrm.x, -nrm.y)
    return a, u, nrm, length


def generate_site_floorplan(program: list[str], site, seed: int | None = None,
                            inset_m: float = 6.0, entrance_edge: int = 1,
                            resolution_cm: float = 90.0,
                            max_levels: int = MAX_LEVELS,
                            street_names=None) -> FloorPlan:
    """
    Grow a perimeter block on a real plot.

    entrance_edge indexes the site boundary; 1 is Deptford Church Street,
    the main road, which is where Adela's sketches enter from.

    The seed varies where the entrance sits along that frontage, which
    band each storey starts from, and which residual regions become
    garden rather than playground. Two seeds on one program give two
    genuinely different blocks rather than the same block jittered.
    """
    if seed is not None:
        random.seed(seed)

    ctx = build_context(site, inset_m, street_names)
    boundary = ctx.boundary

    outdoor_keys = [k for k in program if is_outdoor(k)]
    built = [k for k in program if not is_outdoor(k)]

    elements: list[PlacedElement] = []
    occupied: dict[int, list] = {}
    counts: dict[str, int] = {}

    # --- the entrance, on the street -------------------------------
    ent_a, ent_u, ent_n, ent_len = _edge_frame(ctx, entrance_edge)
    # Somewhere along the middle two-thirds: hard against a corner is
    # never where a front door goes.
    t = ent_len * (0.2 + 0.6 * random.random())
    entrance = Point(ent_a.x + ent_u.x * t, ent_a.y + ent_u.y * t)

    # Deepest residential unit in the program sets every band's depth --
    # see the module docstring on why the outer face leads.
    depths = [get_unit(k).depth_cm for k in built if k in RESIDENTIAL_KEYS]
    band_depth = max(depths) if depths else 600.0

    # Lobby just inside the entrance, and the core behind it.
    lobby_w, lobby_d = 900.0, band_depth
    lobby = _rect(Point(entrance.x - ent_u.x * lobby_w / 2,
                        entrance.y - ent_u.y * lobby_w / 2),
                  None, ent_u, ent_n, lobby_w, lobby_d)
    _place(elements, occupied, boundary, "communal", "Lobby", lobby, 0)
    core_at = Point(entrance.x + ent_n.x * (band_depth + CORRIDOR_HALF),
                    entrance.y + ent_n.y * (band_depth + CORRIDOR_HALF))

    qi = 0
    level = 0
    empty_streak = 0
    corridors: list[tuple[int, int, float, float]] = []

    while qi < len(built) and level < max_levels:
        # The core is the stair: on every storey the building reaches.
        core = _rect(Point(core_at.x - ent_u.x * CORE_SIZE_CM / 2
                           - ent_n.x * CORE_SIZE_CM / 2,
                           core_at.y - ent_u.y * CORE_SIZE_CM / 2
                           - ent_n.y * CORE_SIZE_CM / 2),
                     None, ent_u, ent_n, CORE_SIZE_CM, CORE_SIZE_CM)
        _place(elements, occupied, boundary, "core", "Core", core, level)

        placed_here = False
        for edge in _frontages(ctx, entrance_edge):
            if qi >= len(built):
                break
            a, u, nrm, length = _edge_frame(ctx, edge)
            misses = 0
            offset = 0.0
            reach_start = offset

            while qi < len(built) and offset < length and misses < MAX_BAND_MISSES:
                key = built[qi]
                residential = key in RESIDENTIAL_KEYS

                if residential:
                    unit = get_unit(key)
                    w, d, h = unit.width_cm, unit.depth_cm, unit.height_cm
                else:
                    spec = get_shared(key)
                    w = random.uniform(*spec.frontage_cm)
                    d = min(band_depth, random.uniform(*spec.depth_cm))
                    h = LEVEL_HEIGHT_CM

                start = Point(a.x + u.x * offset, a.y + u.y * offset)
                corners = _rect(start, None, u, nrm, w, d)
                kind = "unit" if residential else "communal"

                if _place(elements, occupied, boundary, kind, key, corners,
                          level, height_cm=h):
                    counts[key] = counts.get(key, 0) + 1
                    qi += 1
                    offset += w
                    placed_here = True
                    misses = 0
                else:
                    offset += STEP_CM
                    misses += 1

            if offset > reach_start:
                corridors.append((edge, level, reach_start, offset))

        if placed_here:
            empty_streak = 0
        else:
            empty_streak += 1
            if empty_streak > 1:
                break
        level += 1

    # --- the corridor behind each band -----------------------------
    # Emitted after the fact, like the branch strategy's: a band's length
    # is not known until the units on it have been placed.
    for edge, lv, t0, t1 in corridors:
        a, u, nrm, _length = _edge_frame(ctx, edge)
        start = Point(a.x + u.x * t0 + nrm.x * band_depth,
                      a.y + u.y * t0 + nrm.y * band_depth)
        span = t1 - t0
        while span > CORRIDOR_WIDTH_CM:
            corners = _rect(start, None, u, nrm, span, CORRIDOR_WIDTH_CM)
            if _place(elements, occupied, boundary, "corridor", "Corridor",
                      corners, lv):
                break
            span -= STEP_CM

    # --- everything left over becomes green ------------------------
    if outdoor_keys:
        _fill_residual(elements, occupied, ctx, outdoor_keys, counts,
                       resolution_cm)

    walls, dropped_cm, dropped_count = _resolve_walls_per_level(elements)
    for el, ids in zip(elements, walls_by_owner(walls, len(elements))):
        el.wall_ids = ids
    _assign_growth_steps(elements)

    off_site = [f"{el.label} (L{el.level})" for el in elements
                if not polygon_contains(el.corners, boundary)]

    return FloorPlan(
        elements=elements, entrance=entrance, core_position=core_at,
        unit_counts=counts, walls=walls,
        dropped_wall_cm=dropped_cm, dropped_wall_count=dropped_count,
        level_count=max((el.level + el.floors for el in elements), default=1),
        boundary=boundary, off_site=off_site,
    )


def _fill_residual(elements, occupied, ctx: SiteContext, keys, counts,
                   resolution_cm: float) -> None:
    """
    Whatever the building did not take becomes green.

    This is Adela's decision, and it is the one that makes the diagonal
    edge cheap: green areas build no walls, carry no frame and are not
    floor area, so they can take any shape the leftover makes without a
    single new joint. The acute corner of the triangle, which an
    orthogonal grid can never reach, becomes landscape -- which is
    exactly what both her sketches do.

    Cells are merged into maximal rectangles rather than emitted one by
    one: 90cm cells would otherwise put thousands of elements in the
    plan. The result is a STEPPED edge at 90cm, which at this scale reads
    as following the diagonal. True polygons are the next increment and
    need N-corner support in massing and the 3D views.
    """
    res_m = resolution_cm / 100.0
    field = build_field(ctx.boundary_m, ctx.families, res_m)

    free = {}
    for c in field.cells:
        p = _to_cm(ctx, c.x, c.y)
        cell = [Point(p.x - resolution_cm / 2, p.y - resolution_cm / 2),
                Point(p.x + resolution_cm / 2, p.y - resolution_cm / 2),
                Point(p.x + resolution_cm / 2, p.y + resolution_cm / 2),
                Point(p.x - resolution_cm / 2, p.y + resolution_cm / 2)]
        if _free(occupied, 0, 1, cell) and polygon_contains(cell, ctx.boundary):
            free[(c.ix, c.iy)] = p

    if not free:
        return

    # Greedy maximal rectangles: take the largest block of free cells
    # anywhere, emit it, remove it, repeat. Cheap and good enough -- this
    # is landscape, not a take-off.
    order = 0
    while free:
        best = _largest_rect(free)
        if best is None:
            break
        (i0, j0, w, h) = best
        pts = [free[(i0, j0)], free[(i0 + w - 1, j0)],
               free[(i0 + w - 1, j0 + h - 1)], free[(i0, j0 + h - 1)]]
        x0 = min(p.x for p in pts) - resolution_cm / 2
        x1 = max(p.x for p in pts) + resolution_cm / 2
        y0 = min(p.y for p in pts) - resolution_cm / 2
        y1 = max(p.y for p in pts) + resolution_cm / 2
        corners = [Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1)]

        for i in range(i0, i0 + w):
            for j in range(j0, j0 + h):
                free.pop((i, j), None)

        # Too small to be a garden -- it is a gap, and naming one would be
        # generous. Dropped rather than emitted as litter.
        if (x1 - x0) * (y1 - y0) < MIN_GREEN_CM2:
            continue

        key = keys[order % len(keys)]
        order += 1
        if _place(elements, occupied, ctx.boundary, "outdoor", key, corners,
                  0, height_cm=OUTDOOR_HEIGHT_CM):
            counts[key] = counts.get(key, 0) + 1


def _largest_rect(free: dict) -> tuple | None:
    """Largest all-free axis-aligned block of cells, by area.

    Largest-rectangle-in-histogram, row by row, with a monotonic stack:
    O(cells) per call. The obvious nested-loop version -- for every cell,
    grow every width and height -- is O(cells x w x h), which on a 90cm
    field of a few thousand cells took seconds per call and this is
    called once per green area.
    """
    if not free:
        return None
    js = [j for (_i, j) in free]
    i_lo = min(i for (i, _j) in free)
    i_hi = max(i for (i, _j) in free)
    j_lo, j_hi = min(js), max(js)
    width = i_hi - i_lo + 1

    heights = [0] * (width + 1)      # trailing 0 flushes the stack
    best = None

    for j in range(j_lo, j_hi + 1):
        for k in range(width):
            heights[k] = heights[k] + 1 if (i_lo + k, j) in free else 0

        stack: list[int] = []
        for k in range(width + 1):
            while stack and heights[stack[-1]] >= heights[k]:
                h = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                w = k - left
                if h and w:
                    area = w * h
                    if best is None or area > best[0]:
                        # j is the BOTTOM row of the run, so the block
                        # starts h-1 rows above it.
                        best = (area, i_lo + left, j - h + 1, w, h)
            stack.append(k)

    return None if best is None else (best[1], best[2], best[3], best[4])
