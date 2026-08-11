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
from .geometry import (
    Point, point_in_polygon, polygon_area, polygon_contains, polygons_overlap,
)
from .growth import (
    STRUCTURAL_GRID_CM,
    CORRIDOR_WIDTH_CM,
    ENTRY_CORRIDOR_BAYS_CM,
    generate_floorplan,
    CORE_DEPTH_CM,
    CORE_RUN_CM,
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

# How much of a region's ground a clean convex shape must still cover to
# be worth taking. Below this the simplification is costing more garden
# than the tidier outline is worth, and the region is drawn as it is.
MIN_HULL_KEEP = 0.40

# A garden needs WIDTH, not just area. The largest-area rectangle inside
# a ribbon is a long thin verge -- 27m x 3m cleared the 60m2 floor and
# drew as a line against the site edge. Effective width is area divided
# by longest extent, which is orientation-independent and so works for
# the rotated hulls as well as the axis-aligned rectangles.
MIN_GREEN_WIDTH_CM = 500.0


def _too_thin(poly) -> bool:
    if len(poly) < 3:
        return True
    xs = [p.x for p in poly]
    ys = [p.y for p in poly]
    longest = max(max(xs) - min(xs), max(ys) - min(ys))
    if longest <= 0:
        return True
    return polygon_area(poly) / longest < MIN_GREEN_WIDTH_CM


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
                            program_repeat: int = 1,
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
    # Repeating the program is how the plot gets FILLED. One pass of an
    # 18-entry brief uses about a quarter of this site; growth stops when
    # it runs out of program, not when it runs out of room, so asking for
    # more is the only way to see the site's real capacity.
    built = [k for k in program if not is_outdoor(k)] * max(1, program_repeat)

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
        core = _rect(Point(core_at.x - ent_u.x * CORE_RUN_CM / 2
                           - ent_n.x * CORE_DEPTH_CM / 2,
                           core_at.y - ent_u.y * CORE_RUN_CM / 2
                           - ent_n.y * CORE_DEPTH_CM / 2),
                     None, ent_u, ent_n, CORE_RUN_CM, CORE_DEPTH_CM)
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


def _grow_spine_once(program: list[str], site, seed: int | None = None,
                             inset_m: float = 6.0, entrance_edge: int = 1,
                             resolution_cm: float = 90.0,
                             grid_family: int | None = None,
                             max_branch_cm: float = 4000.0,
                             branch_depth: int = 2,
                             program_repeat: int = 1,
                             # 8m, not the 1600 it was. That 1600 halved a
                             # count of 25-28 stairs that were 170 squares;
                             # a core is now a real 3.6x7.2m room with a
                             # lift and a stair in it, so the same pitch
                             # yields 12 -- still about half the original,
                             # which is what was asked for, but now because
                             # each one is a building's worth of core
                             # rather than because the pitch starves them.
                             # At 1600 with the new size the worst walk ran
                             # to 43.4m against a 20m target.
                             core_pitch_cm: float = 800.0,
                             courtyard_ratio: float = 0.16,
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

    # Repeating the program is how the plot gets FILLED. One pass of an
    # 18-entry brief uses about a quarter of this site; growth stops when
    # it runs out of program, not when it runs out of room, so asking for
    # more is the only way to see the site's real capacity.
    built = [k for k in program if not is_outdoor(k)] * max(1, program_repeat)
    outdoor_keys = [k for k in program if is_outdoor(k)] or ["Garden"]

    # max_branch_cm is much larger than the branch strategy's 1200. That
    # cap exists to stop an UNCONSTRAINED plan sprawling, and here the
    # site already does the containing -- the two do different jobs, as
    # growth.py's own docstring says. Left at 1200 the spine stacked to
    # 13 storeys on a plot that comfortably holds the program across two
    # or three, because it hit the cap long before it hit the boundary.
    # branch_depth 2 by default here: the tertiary runs are what make a
    # spine on a deep plot reach past one unit either side of its arms.
    # COURTYARDS, reserved before growth rather than carved out after.
    # Filling the plot solid and then calling the leftover "green" gives
    # a perimeter of scraps; a courtyard has to be decided first and
    # built around. Sized as a share of the developable area, laid on the
    # plan's own axes so they sit square to the building.
    courtyards = _courtyards(ctx, u_ax, v_ax, entrance, courtyard_ratio)

    plan = generate_floorplan(built, seed=seed, boundary=ctx.boundary,
                              entrance=entrance, axes=(u_ax, v_ax),
                              core_pitch_cm=core_pitch_cm,
                              reserved=courtyards,
                              max_branch_cm=max_branch_cm,
                              branch_depth=branch_depth,
                              entry_run_cm=max(ENTRY_CORRIDOR_BAYS_CM, ENTRY_INSET_CM))

    # Residual -> green. Appending is safe: outdoor elements build no
    # walls, so the resolved wall set and every existing element's
    # wall_ids stay valid. Growth steps are reassigned because the new
    # elements would otherwise all claim step 0.
    occupied: dict[int, list] = {}
    for el in plan.elements:
        for lv in range(el.level, el.level + el.floors):
            occupied.setdefault(lv, []).append(el.corners)

    # Courtyards ARE emitted, and they are what makes the green total
    # predictable. Leaving them to the residual pass looked cleaner and
    # was not: only about a fifth of free ground survives that pass --
    # convex, at least 60m2, at least 5m wide -- so green swung between
    # 7% and 53% depending on how awkwardly the leftovers fell. A
    # reserved court is green by construction.
    #
    # The label counter is SHARED with the residual pass, so Garden and
    # Playground alternate across courts and traced pieces alike instead
    # of one label collecting all the courts.
    order = 0
    for block in courtyards:
        key = outdoor_keys[order % len(outdoor_keys)]
        order += 1
        plan.elements.append(PlacedElement("outdoor", key, block,
                                           height_cm=OUTDOOR_HEIGHT_CM,
                                           level=0))
        plan.unit_counts[key] = plan.unit_counts.get(key, 0) + 1
        occupied.setdefault(0, []).append(block)

    _fill_residual(plan.elements, occupied, ctx, outdoor_keys,
                   plan.unit_counts, resolution_cm, start_order=order)
    _assign_growth_steps(plan.elements)
    plan.off_site = [f"{el.label} (L{el.level})" for el in plan.elements
                     if not polygon_contains(el.corners, ctx.boundary)]
    return plan


def _fill_residual(elements, occupied, ctx: SiteContext, keys, counts,
                   resolution_cm: float, start_order: int = 0) -> None:
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

    order = start_order
    for region in _regions(free):
        # ONE REGION, SEVERAL CLEAN PIECES.
        #
        # Drawing a region as a single polygon forces a choice between a
        # shape that is clean and one that is true: on a dense plan the
        # residual is a ribbon threading between buildings, and its
        # honest outline runs to 150 corners while its convex hull covers
        # half a block of housing.
        #
        # Neither is necessary. The region is cut into a few convex
        # pieces instead -- the largest clean shape that fits, then the
        # largest that fits what is left, and so on. Each is a garden you
        # could set out with a tape, and together they keep the ground.
        for piece in _convex_pieces(region, ox, oy, resolution_cm,
                                    ctx.boundary):
            if polygon_area(piece) < MIN_GREEN_CM2 or _too_thin(piece):
                continue     # a gap or a verge, not a garden
            key = keys[order % len(keys)]
            order += 1
            _claim(occupied, 0, 1, piece)
            elements.append(PlacedElement("outdoor", key, piece,
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

    return pts


def _courtyards(ctx: SiteContext, u: Point, v: Point, entrance: Point,
                ratio: float) -> list[list[Point]]:
    """A few open blocks in the body of the plot, reserved before growth.

    Placed along the spine and to either side of it, on the plan's own
    axes so they read as courtyards rather than as gaps. Only those that
    land wholly inside the boundary are kept, so the acute end of a
    triangle simply does not get one.
    """
    area = polygon_area(ctx.boundary)
    if ratio <= 0 or area <= 0:
        return []
    target = area * ratio
    # Two or three courts rather than one big void: a single block that
    # size would cut the plan in half.
    count = 3
    side = math.sqrt(target / count)
    side = max(1200.0, min(side, 2600.0))

    out = []
    for k in range(count):
        along = (k + 1) * (side * 2.2)
        for across in (-1.0, 1.0):
            c = Point(entrance.x - v.x * along + u.x * across * side * 1.15,
                      entrance.y - v.y * along + u.y * across * side * 1.15)
            # A TRAPEZOID, not a square. The two ends are drawn at
            # different widths, so a reserved court reads as a shaped
            # piece of ground rather than a stamped tile -- and, because
            # the labels are handed out from one counter shared with the
            # residual pass, Playground gets these as often as Garden
            # does. Emitting identical squares was what made Playground a
            # permanently rectangular label.
            half = side / 2
            near = half * random.uniform(0.62, 1.0)
            far = half * random.uniform(0.62, 1.0)
            block = [
                Point(c.x - u.x * near - v.x * half, c.y - u.y * near - v.y * half),
                Point(c.x + u.x * near - v.x * half, c.y + u.y * near - v.y * half),
                Point(c.x + u.x * far + v.x * half, c.y + u.y * far + v.y * half),
                Point(c.x - u.x * far + v.x * half, c.y - u.y * far + v.y * half),
            ]
            if polygon_contains(block, ctx.boundary):
                out.append(block)
        if len(out) >= count:
            break
    return out[:count]


def _convex_pieces(region: set, ox: float, oy: float, res: float,
                   boundary, max_pieces: int = 9) -> list[list[Point]]:
    """Cover a region with a few clean convex shapes.

    Greedy: take the best convex shape that fits, remove the cells it
    covers, repeat on what is left. Capped, because past a handful of
    pieces this stops being a set of gardens and becomes confetti -- the
    remainder is then left undrawn rather than shattered.
    """
    out: list[list[Point]] = []
    remaining = set(region)
    for _ in range(max_pieces):
        if len(remaining) < 4:
            break
        best = None
        for sub in _regions({c: None for c in remaining}):
            shape = _clean_shape(sub, ox, oy, res, boundary)
            if len(shape) >= 3 and polygon_area(shape) > (
                    0 if best is None else polygon_area(best)):
                best = shape
        if best is None or polygon_area(best) < MIN_GREEN_CM2                 or _too_thin(best):
            break
        out.append(best)
        remaining = {c for c in remaining
                     if not point_in_polygon(
                         Point(ox + (c[0] + 0.5) * res,
                               oy + (c[1] + 0.5) * res), best)}
    return out


def _clean_shape(region: set, ox: float, oy: float, res: float,
                 boundary) -> list[Point]:
    """A clean CONVEX shape for this region -- a trapezoid where the
    ground allows one.

    Tracing the region gives its true outline, which on a dense plan
    means a 150-corner ribbon threading between buildings. That is
    accurate and unreadable, and it is not what a garden is drawn as.

    So the shape is the region's convex HULL instead, simplified to a
    handful of corners. A hull can of course cover ground that belongs to
    a building, so the region is ERODED -- shrunk by a ring of cells at a
    time -- until its hull lands entirely on free ground. Open regions
    keep almost all their area and come out as quadrilaterals; a region
    threaded between buildings gives up area until what is left is a
    shape you could actually lay out.

    The trade is real and it is bounded. Eroding until a hull fits can
    throw away most of the garden -- on one test it took 750 m2 of green
    down to 300. So a hull is only accepted while it still holds
    MIN_HULL_KEEP of the ground it stands on; past that the region is
    better drawn as it really is. A clean shape is worth some area, not
    half of it.
    """
    have = len(region) * res * res
    for erosion in range(0, 5):
        cells = _erode(region, erosion)
        if len(cells) < 4:
            break
        pts = []
        for (i, j) in cells:
            for di, dj in ((0, 0), (1, 0), (1, 1), (0, 1)):
                pts.append(Point(ox + (i + di) * res, oy + (j + dj) * res))
        hull = _convex_hull(pts)
        hull = _simplify(hull, res * 1.2)
        if len(hull) < 3:
            continue
        if polygon_area(hull) < have * MIN_HULL_KEEP:
            break                        # eroding costs more than it buys
        if _on_free_ground(hull, region, ox, oy, res) and                 polygon_contains(hull, boundary):
            return hull

    # No hull fits -- this region is a ribbon threading between
    # buildings, and its convex hull would cover half a block of housing.
    # Fall back to the largest RECTANGLE that fits inside it: still a
    # clean four-sided shape you could set out with a tape, never the
    # 150-corner outline, and guaranteed to lie on free ground because it
    # is built out of free cells rather than fitted around them.
    return _largest_rect(region, ox, oy, res)


def _largest_rect(region: set, ox: float, oy: float, res: float) -> list[Point]:
    """Largest all-free rectangle inside the region, as a polygon.

    Largest-rectangle-in-histogram row by row with a monotonic stack:
    O(cells). The obvious nested version -- grow every width and height
    from every cell -- is O(cells x w x h) and took seconds per call.
    """
    if not region:
        return []
    i_lo = min(i for i, _ in region)
    i_hi = max(i for i, _ in region)
    j_lo = min(j for _, j in region)
    j_hi = max(j for _, j in region)
    width = i_hi - i_lo + 1

    heights = [0] * (width + 1)
    best = None
    for j in range(j_lo, j_hi + 1):
        for k in range(width):
            heights[k] = heights[k] + 1 if (i_lo + k, j) in region else 0
        stack: list[int] = []
        for k in range(width + 1):
            while stack and heights[stack[-1]] >= heights[k]:
                h = heights[stack.pop()]
                left = stack[-1] + 1 if stack else 0
                w = k - left
                if h and w and (best is None or w * h > best[0]):
                    # j is the BOTTOM row of the run, so the block starts
                    # h-1 rows above it.
                    best = (w * h, i_lo + left, j - h + 1, w, h)
            stack.append(k)
    if best is None:
        return []
    _a, i0, j0, w, h = best
    x0, y0 = ox + i0 * res, oy + j0 * res
    x1, y1 = x0 + w * res, y0 + h * res
    return [Point(x0, y0), Point(x1, y0), Point(x1, y1), Point(x0, y1)]


def _erode(region: set, rings: int) -> set:
    """Drop `rings` layers of cells from the region's edge."""
    out = set(region)
    for _ in range(rings):
        out = {(i, j) for (i, j) in out
               if all((i + di, j + dj) in out
                      for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)))}
        if not out:
            break
    return out


def _convex_hull(pts: list[Point]) -> list[Point]:
    """Andrew's monotone chain."""
    uniq = sorted({(round(p.x, 3), round(p.y, 3)) for p in pts})
    if len(uniq) < 3:
        return [Point(x, y) for x, y in uniq]

    def half(seq):
        out: list[tuple] = []
        for q in seq:
            while len(out) >= 2:
                (ax, ay), (bx, by) = out[-2], out[-1]
                if (bx - ax) * (q[1] - ay) - (by - ay) * (q[0] - ax) <= 0:
                    out.pop()
                else:
                    break
            out.append(q)
        return out

    lower = half(uniq)
    upper = half(list(reversed(uniq)))
    return [Point(x, y) for x, y in lower[:-1] + upper[:-1]]


def _on_free_ground(poly: list[Point], region: set, ox: float, oy: float,
                    res: float) -> bool:
    """Does this polygon cover only cells that belong to the region?

    Sampled rather than solved. The polygon may be non-convex, so the
    usual convex overlap test does not apply -- and this is the question
    that actually matters: a simplified outline is acceptable exactly
    when it has not swallowed ground that belongs to a building.
    """
    xs = [p.x for p in poly]
    ys = [p.y for p in poly]
    step = res / 2
    y = min(ys) + step / 2
    while y < max(ys):
        x = min(xs) + step / 2
        while x < max(xs):
            if point_in_polygon(Point(x, y), poly):
                cell = (int((x - ox) // res), int((y - oy) // res))
                if cell not in region:
                    return False
            x += step
        y += step
    return True


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


# The brief: green should be this share of the ground floor.
GREEN_TARGET = (0.30, 0.40)

# How far in from the entrance the first core sits, and so how long the
# entry corridor is.
#
# This used to be `length * 0.3` -- a third of the spine edge, which on
# the 109.8m Crossfield edge is 32.9m of corridor built before anything
# else. Nothing ever hangs off it: _make_branches starts its three arms
# at the CORE, so the entrance-to-core run is circulation with no units
# on either side for its whole length. Adela flagged it on sight.
#
# It cannot simply be deleted, and that is worth recording because the
# reason is not obvious. The three arms leave the core along -v, -u and
# +u -- there is no arm back toward the street -- so wherever the core
# lands is the street-side edge of the building. Put it two bays in and
# the whole plan crowds one end of a 110m plot: ground area falls to
# 902m2, the far tip is never reached, and the leftover shows up as
# green at 80% of the ground floor. The long run was centring the
# armature, not serving the door.
#
# 16m is where that stops paying. Swept at 3.4/8/12/16/20/26/32.9m over
# 8 seeds, it gives more building than the value it replaces and a
# shorter worst walk to a stair, for half the corridor. Measured, not
# derived: the response is noisy enough that 18m tests worse than both
# its neighbours, so read it as the middle of a broad flat optimum
# rather than a sharp one.
#
# Set to SIX WHOLE BAYS (21.6m) rather than 16m, which buys something
# exact. frame.py anchors the structural
# grid on the entrance and runs the entry corridor down -v, so the main
# core lands at node (0, -entry_run/360) -- a whole number of bays puts
# it exactly ON a node and guarantees the building's principal stair a
# column. At 16m it fell 1.6m short of one and its floor drew
# unsupported, along with a Lobby 5m from anything.
#
# Six bays rather than four or five, over 8 seeds with cores unsnapped:
#
#     entry   bays   max->core avg / worst   over 1 bay   worst gap   green
#     14.4m   4.00        22.7 / 34.4            0         2.69 m      5/8
#     16.0m   4.44        18.2 / 21.4            2         5.00 m      6/8
#     18.0m   5.00        19.9 / 30.0            0         3.35 m      2/8
#     21.6m   6.00        18.2 / 26.9            0         2.46 m      7/8
#
# The honest cost, stated because access_report will show it: the WORST
# walk to a stair goes 21.4m -> 26.9m against Adela's 20m target. What
# it buys is no unsupported element anywhere and the best green of the
# four. 16m keeps the shortest walk and is the value to go back to if
# the walk matters more than the floating plate.
ENTRY_INSET_CM = 6 * STRUCTURAL_GRID_CM


def generate_spine_floorplan(program, site, seed=None, inset_m: float = 6.0,
                             entrance_edge: int = 1,
                             resolution_cm: float = 90.0,
                             grid_family: int | None = None,
                             max_branch_cm: float = 4000.0,
                             branch_depth: int = 2,
                             program_repeat: int = 1,
                             core_pitch_cm: float = 800.0,
                             courtyard_ratio: float = 0.16,
                             street_names=None,
                             attempts: int = 4) -> FloorPlan:
    """
    Grow a spine plan whose green lands in the brief's 30-40% band.

    Green is what is LEFT of the ground once the building has taken what
    it needs, and leftovers are chaotic: on one sweep the same settings
    gave anything from 14% to 64% depending only on where the entrance
    fell. No single courtyard_ratio fixes that, because the ratio is an
    input and the green share is an outcome.

    So it is closed as a loop instead. Grow, measure, adjust the reserved
    courtyard area toward the miss, and grow again -- a few passes, then
    keep the best attempt whether or not it landed. Bounded and cheap
    (each pass is a couple of seconds), and it turns a target that was
    being reported into one that is usually met.

    The result is still REPORTED rather than promised: diagnostics
    .access_report gives the achieved share, and a plan that could not
    reach the band says so instead of pretending.
    """
    from .diagnostics import access_report

    lo, hi = GREEN_TARGET
    ratio = courtyard_ratio
    best = None
    best_miss = None
    # Layout seed, which usually stays put. See the pinned-lever comment
    # below for the one case that moves it.
    layout_seed = seed
    pinned = False

    for attempt in range(max(1, attempts)):
        plan = _grow_spine_once(
            program, site, seed=layout_seed, inset_m=inset_m,
            entrance_edge=entrance_edge, resolution_cm=resolution_cm,
            grid_family=grid_family, max_branch_cm=max_branch_cm,
            branch_depth=branch_depth, program_repeat=program_repeat,
            core_pitch_cm=core_pitch_cm, courtyard_ratio=ratio,
            street_names=street_names)
        share = access_report(plan)["green_pct_of_ground"] / 100.0

        miss = 0.0 if lo <= share <= hi else min(abs(share - lo), abs(share - hi))
        if best_miss is None or miss < best_miss:
            best, best_miss = plan, miss
        if miss == 0.0:
            return plan

        # Reserved ground is the lever: short on green, reserve more.
        # Clamped because past about a third of the plot the courts stop
        # being courtyards and start being the site.
        target = (lo + hi) / 2
        ratio = max(0.04, min(0.34, ratio + (target - share) * 0.45))

        # Green above the band with the reserve already slammed to its
        # floor means the lever is spent: the excess is NOT courtyard, it
        # is ground the building never reached, and reserving less cannot
        # give any of it back. Pulling harder just rebuilds the identical
        # plan, and the loop burns its budget confirming its own answer.
        # Seed 42 did exactly that -- 81% green, four times.
        if share > hi and ratio <= 0.0401:
            pinned = True

        # So move the layout instead. WHERE the entrance falls along the
        # frontage and which end the spine starts from is what swings
        # green from 14% to 64% in the first place, and both are drawn
        # from the seed. Perturbing it deterministically keeps the
        # contract -- same inputs, same plan, every time -- while giving
        # the loop a second thing to vary. Each remaining attempt gets
        # its own layout at the default reserve, rather than one alternate
        # layout and then two more passes at a floor already known to
        # fail. On seed 42 that is 81.3% -> 42.2%, and 831 -> 1199m2 of
        # building; still outside the band, and access_report still says
        # so rather than pretending otherwise.
        if pinned:
            layout_seed = (seed or 0) + (attempt + 1) * 7919
            ratio = courtyard_ratio

    return best
