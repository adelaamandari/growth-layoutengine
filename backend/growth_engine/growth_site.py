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
from .geometry import Point, polygon_area, polygon_contains, polygons_overlap
from .growth import (
    CORRIDOR_WIDTH_CM,
    generate_floorplan,
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

# A band walks its WHOLE frontage. There used to be a miss counter here
# that abandoned a band after six failed bays, and it was quietly wrong:
# an acute corner has to be walked past before the plot is deep enough
# for anything, and on this triangle the Coffey frontage does not admit
# its first bay until 12.6 m in -- fourteen probes. The band gave up at
# 5.4 m and that whole elevation stayed empty, which read as a layout
# choice rather than a constant that was too small.
#
# No counter is needed: `offset` only increases and is bounded by the
# frontage length, so the walk terminates on its own.

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

        # All frontages grow TOGETHER, one bay each in turn, rather than
        # the first band running until the program is exhausted. Taking
        # them one at a time gave the entrance frontage everything and
        # left the others bare, which is not a perimeter block -- it is
        # one terrace and two empty streets.
        bands = [{"edge": e, "offset": 0.0, "t0": None, "t1": 0.0, "done": False}
                 for e in _frontages(ctx, entrance_edge)]
        placed_here = False

        while qi < len(built) and any(not b["done"] for b in bands):
            for band in bands:
                if qi >= len(built):
                    break
                if band["done"]:
                    continue

                a, u, nrm, length = _edge_frame(ctx, band["edge"])
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
                kind = "unit" if residential else "communal"

                # Walk the rest of this frontage looking for a bay. The
                # walk is bounded by the frontage itself; nothing else
                # needs to stop it.
                offset = band["offset"]
                placed = False
                while offset + w <= length:
                    start = Point(a.x + u.x * offset, a.y + u.y * offset)
                    corners = _rect(start, None, u, nrm, w, d)
                    if _place(elements, occupied, boundary, kind, key,
                              corners, level, height_cm=h):
                        counts[key] = counts.get(key, 0) + 1
                        qi += 1
                        band["offset"] = offset + w
                        band["t0"] = offset if band["t0"] is None else band["t0"]
                        band["t1"] = offset + w
                        placed = placed_here = True
                        break
                    offset += STEP_CM

                if not placed:
                    band["done"] = True

        for band in bands:
            if band["t0"] is not None:
                corridors.append((band["edge"], level, band["t0"], band["t1"]))

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


def generate_spine_floorplan(program: list[str], site, seed: int | None = None,
                             inset_m: float = 6.0, entrance_edge: int = 1,
                             resolution_cm: float = 90.0,
                             grid_family: int | None = None,
                             max_branch_cm: float = 4000.0,
                             branch_depth: int = 2,
                             street_names=None) -> FloorPlan:
    """
    The SPINE, turned onto a site grid.

    This is not a third morphology -- it is growth.py's own logic
    (entrance, entry run, core, three orthogonal arms, rooms hung off
    them) with two things changed:

      the frame is ROTATED onto one of the grid families the site's
        edges give, so the whole armature runs with the street instead
        of with the page;
      the entrance sits on a real frontage rather than at an interior
        origin, so the building is entered from the street.

    Everything else is the branch strategy exactly as verified -- the
    stacking rule, shared-wall resolution, the boundary constraint. That
    is the point of doing it this way: the spine reads the way Adela's
    option 2 sketch does, and none of the growth logic had to be
    reinvented to get it, only re-based.

    Whatever the building does not take becomes green, the same residual
    pass the perimeter strategy uses.

    The seed varies where on the frontage the entrance sits AND which
    grid family the building takes, weighted by how much frontage backs
    each. So a randomize can hand back a street-aligned scheme or one
    turned onto the Crossfield diagonal -- a real design variable rather
    than a jitter.
    """
    if seed is not None:
        random.seed(seed)

    ctx = build_context(site, inset_m, street_names)

    # THE SPINE RUNS ALONG THE LONGEST EDGE, NOT INTO THE SITE.
    #
    # It used to enter perpendicular to a frontage, which on this plot
    # meant driving across the SHORT edge -- 62.9 m of Deptford Church
    # Street -- and hitting the far boundary almost immediately. The
    # branches had nowhere to run, so the program stacked instead of
    # spreading: 654 m2 of ground over three storeys where the plot
    # comfortably holds more on one or two.
    #
    # Running the spine along the longest edge uses the triangle's
    # LENGTH. The two side arms then reach across its width, which is
    # the wide direction, and the plan spreads the way the plot is
    # actually shaped.
    if grid_family is None:
        # THE LONGEST EDGE, deterministically -- `extract_axes` returns
        # them longest first. Not the biggest grid FAMILY: Coffey and
        # Deptford Church sum to more support between them, but neither
        # is as long as Crossfield on its own, and a spine needs one
        # continuous run. Summed support is the wrong measure here.
        #
        # Deliberately not a weighted draw either. The longest edge is
        # the plot's own long axis and that is the whole point of running
        # the spine along it; letting a seed sometimes pick a shorter one
        # just produces the cramped plan this was meant to fix. Variety
        # comes from which END the entrance takes and where along it,
        # which changes the plan without giving up the long axis.
        spine_axis = ctx.axes[0]
    else:
        fam = ctx.families[min(grid_family, len(ctx.families) - 1)]
        spine_axis = fam.axes[0]

    spine_edge = spine_axis.edge_index
    a, edge_u, edge_n, length = _edge_frame(ctx, spine_edge)

    # Which end to start from. Both ends give genuinely different plans
    # on a triangle, because one is the acute corner.
    from_start = random.random() < 0.5
    run = edge_u if from_start else Point(-edge_u.x, -edge_u.y)

    # growth.py runs its entry corridor along -v, so v is the reverse of
    # the spine, and u -- the direction the side arms take -- is across
    # the plot.
    v_ax = Point(-run.x, -run.y)
    u_ax = Point(-v_ax.y, v_ax.x)

    # Stood off the edge far enough that units can hang on the STREET
    # side of the spine as well as the inward side. growth.py loads both
    # sides of every run, and a spine hard against the boundary wastes
    # one of them.
    setback = max(d for d in
                  [get_unit(k).depth_cm for k in program
                   if k in RESIDENTIAL_KEYS] or [600.0]) + CORRIDOR_HALF
    base = a if from_start else Point(a.x + edge_u.x * length,
                                      a.y + edge_u.y * length)

    def _entrance_at(d: float) -> Point:
        return Point(base.x + run.x * d + edge_n.x * setback,
                     base.y + run.y * d + edge_n.y * setback)

    def _inside(p: Point) -> bool:
        # A box the width of the entry corridor, since that is what has
        # to fit -- testing the bare point would put the door inside and
        # the corridor through the boundary.
        h = CORRIDOR_HALF
        return polygon_contains(
            [Point(p.x - h, p.y - h), Point(p.x + h, p.y - h),
             Point(p.x + h, p.y + h), Point(p.x - h, p.y + h)],
            ctx.boundary)

    # Walk along the edge until the setback point is actually ON the
    # plot. Near an acute corner the plot is narrower than the setback,
    # so offsetting inward crosses straight out through the far edge --
    # the entrance, the entry run and every core stacked above it then
    # land outside, and nothing downstream can reject them because the
    # armature is placed before any containment test runs.
    along = length * (0.10 + 0.15 * random.random())
    entrance = _entrance_at(along)
    while not _inside(entrance) and along < length:
        along += STEP_CM
        entrance = _entrance_at(along)

    built = [k for k in program if not is_outdoor(k)]
    outdoor_keys = [k for k in program if is_outdoor(k)] or ["Garden"]

    # max_branch_cm is much larger than the branch strategy's 1200. That
    # cap exists to stop an UNCONSTRAINED plan sprawling, and here the
    # site already does the containing -- the two do different jobs, as
    # growth.py's own docstring says. Left at 1200 the spine stacked to
    # 13 storeys on a plot that comfortably holds the program across two
    # or three, because it hit the cap long before it hit the boundary.
    # branch_depth 2 by default here: the tertiary runs are what make a
    # spine on a deep plot reach past one unit either side of its arms.
    plan = generate_floorplan(built, seed=seed, boundary=ctx.boundary,
                              entrance=entrance, axes=(u_ax, v_ax),
                              max_branch_cm=max_branch_cm,
                              branch_depth=branch_depth)

    # Residual -> green. Appending is safe: outdoor elements build no
    # walls, so the resolved wall set and every existing element's
    # wall_ids stay valid. Growth steps are reassigned because the new
    # elements would otherwise all claim step 0.
    occupied: dict[int, list] = {}
    for el in plan.elements:
        for lv in range(el.level, el.level + el.floors):
            occupied.setdefault(lv, []).append(el.corners)
    _fill_residual(plan.elements, occupied, ctx, outdoor_keys,
                   plan.unit_counts, resolution_cm)
    _assign_growth_steps(plan.elements)
    plan.off_site = [f"{el.label} (L{el.level})" for el in plan.elements
                     if not polygon_contains(el.corners, ctx.boundary)]
    return plan


def _fill_residual(elements, occupied, ctx: SiteContext, keys, counts,
                   resolution_cm: float) -> None:
    """
    Whatever the building did not take becomes green.

    This is Adela's decision, and it is the one that makes the diagonal
    cheap: green areas build no walls, carry no frame and are not floor
    area, so leftover shape costs nothing and no new joint is needed. The
    acute corner an orthogonal grid can never reach becomes landscape.

    Each connected region of free cells becomes ONE polygon, traced round
    its own outline. It used to be carved into maximal rectangles, which
    was cheap and looked like it: a garden arrived as four or five boxes
    stacked into an approximate L, with seams through the middle of what
    is one piece of ground. A region is one thing and is now drawn as one
    thing, following the diagonal in 90cm steps.

    Green polygons may be NON-CONVEX, which nothing else in the engine
    is. That is safe precisely because they build nothing: walls, frame
    and floor area all skip them via growth.builds_walls, and the only
    consumers are the plan drawing, the extrusion and the area, all of
    which handle any simple polygon. The overlap test does NOT -- it is
    SAT, which assumes convex -- so regions are not overlap-tested
    against each other. They cannot overlap: they are disjoint sets of
    cells that were each checked free before the region was formed.
    """
    res_m = resolution_cm / 100.0
    field = build_field(ctx.boundary_m, ctx.families, res_m)

    free: dict[tuple[int, int], Point] = {}
    for c in field.cells:
        p = _to_cm(ctx, c.x, c.y)
        half = resolution_cm / 2
        cell = [Point(p.x - half, p.y - half), Point(p.x + half, p.y - half),
                Point(p.x + half, p.y + half), Point(p.x - half, p.y + half)]
        if _free(occupied, 0, 1, cell) and polygon_contains(cell, ctx.boundary):
            free[(c.ix, c.iy)] = p

    if not free:
        return

    # Cell lattice -> world. Cell (i, j) spans [i, i+1] x [j, j+1] in
    # lattice units; anchor off a known cell centre so the mapping is
    # exact rather than reconstructed from the field's bounds.
    (i0, j0), p0 = next(iter(free.items()))
    ox = p0.x - (i0 + 0.5) * resolution_cm
    oy = p0.y - (j0 + 0.5) * resolution_cm

    order = 0
    for region in _regions(free):
        loop = _trace_outline(region, ox, oy, resolution_cm)
        if len(loop) < 3:
            continue
        if polygon_area(loop) < MIN_GREEN_CM2:
            # Too small to be a garden -- it is a gap, and naming one
            # would be generous.
            continue
        key = keys[order % len(keys)]
        order += 1
        _claim(occupied, 0, 1, loop)
        elements.append(PlacedElement("outdoor", key, loop,
                                      height_cm=OUTDOOR_HEIGHT_CM, level=0))
        counts[key] = counts.get(key, 0) + 1


def _regions(free: dict) -> list[set]:
    """Connected components of free cells, four-connectivity."""
    seen: set = set()
    out = []
    for cell in free:
        if cell in seen:
            continue
        stack = [cell]
        seen.add(cell)
        comp = set()
        while stack:
            i, j = stack.pop()
            comp.add((i, j))
            for n in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                if n in free and n not in seen:
                    seen.add(n)
                    stack.append(n)
        out.append(comp)
    return sorted(out, key=len, reverse=True)


def _trace_outline(region: set, ox: float, oy: float, res: float) -> list[Point]:
    """The outline of a set of cells, as one polygon.

    Every cell side with no neighbour behind it is a boundary edge,
    emitted DIRECTED so the region stays on one hand; chaining them then
    has no ambiguity at a corner where four cells meet diagonally. Runs
    of collinear edges collapse, so a straight 20m side is two points
    rather than twenty-two.

    Only the outer loop is kept. A region with a hole in it would need
    the inner loop as well, and a PlacedElement has one ring.
    """
    edges: dict[tuple, tuple] = {}
    for (i, j) in region:
        if (i, j - 1) not in region:
            edges[(i, j)] = (i + 1, j)
        if (i + 1, j) not in region:
            edges[(i + 1, j)] = (i + 1, j + 1)
        if (i, j + 1) not in region:
            edges[(i + 1, j + 1)] = (i, j + 1)
        if (i - 1, j) not in region:
            edges[(i, j + 1)] = (i, j)
    if not edges:
        return []

    start = min(edges)
    loop = [start]
    cur = edges[start]
    while cur != start and cur in edges:
        loop.append(cur)
        cur = edges.pop(cur) if False else edges[cur]
        if len(loop) > 4 * len(region) + 8:
            break                       # malformed; bail rather than spin

    pts = [Point(ox + i * res, oy + j * res) for i, j in loop]

    # Collapse the staircase. Tracing a diagonal edge on a 90cm lattice
    # gives a step at every cell -- one region came out with 322 corners,
    # which is the raster, not the shape. Simplified to within one cell,
    # a run of steps becomes the diagonal it was approximating, which is
    # both what the ground actually is and what Adela drew.
    return _simplify(pts, res)


def _simplify(pts: list[Point], tol: float) -> list[Point]:
    """Ramer-Douglas-Peucker on a closed ring."""
    if len(pts) < 4:
        return pts

    def _rdp(seq: list[Point]) -> list[Point]:
        if len(seq) < 3:
            return seq
        a, b = seq[0], seq[-1]
        dx, dy = b.x - a.x, b.y - a.y
        span = math.hypot(dx, dy)
        worst, idx = -1.0, 0
        for k in range(1, len(seq) - 1):
            p = seq[k]
            if span < 1e-9:
                d = math.hypot(p.x - a.x, p.y - a.y)
            else:
                d = abs(dx * (a.y - p.y) - dy * (a.x - p.x)) / span
            if d > worst:
                worst, idx = d, k
        if worst <= tol:
            return [a, b]
        return _rdp(seq[:idx + 1])[:-1] + _rdp(seq[idx:])

    # Split the ring at two far-apart points so RDP has open chains to
    # work on -- run on a closed loop it would collapse the whole thing
    # to its two endpoints.
    half = len(pts) // 2
    out = _rdp(pts[:half + 1])[:-1] + _rdp(pts[half:] + [pts[0]])[:-1]
    return out if len(out) >= 3 else pts
