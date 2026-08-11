"""
facade.py
Clad the building: pick a facade panel for every exterior wall bay and
place it in world space.

WHICH WALLS GET CLAD
Only walls that are EXTERIOR. `walls.resolve_walls` already tells us:
a wall with two owners is between two elements and is internal, a wall
with one owner faces out. That is the whole test -- there is no separate
notion of an envelope, and there does not need to be, because shared-wall
resolution has already computed exactly this.

Outdoor areas build no walls at all (growth.builds_walls), so a garden
never gets a facade, which is correct and needs no special case here.

PANELS TILE A RUN, NOT A WALL
A facade is continuous across the building; it does not restart at every
party wall. So exterior walls are first merged into RUNS -- collinear and
touching -- and the panels tile the run. Each bay then asks which wall it
actually sits on to decide what panel it is, so a run crossing from a
unit to the lobby changes panel where the rooms change while the module
keeps going.

This matters more than it sounds. Tiling each resolved wall on its own
clad 65% of the envelope: `resolve_walls` cuts a wall wherever a
neighbour meets it, so a 12m elevation arrives as four 3m pieces that
each waste most of a 330 panel. Merging first takes it to 73%, and it is
also just what a facade is.

THE MODULE BELONGS TO THE ELEVATION, NOT THE STOREY
One datum per plan LINE, shared by every storey on it. Panels can then
only ever land at line_base + k*pitch, so a panel on level 2 sits exactly
above the one on level 1 and their columns run continuous up the
building.

Tiling each storey independently is the obvious way to write this and it
is wrong: every level centres its own run, the runs are different lengths
because the storeys are different shapes, and the panels come out offset
by a metre or two per floor. Nothing errors -- the facade simply never
stacks, `verify_facade` reports zero stacked pairs, and every column
lands on the middle of the panel below. So the datum is computed across
all levels of the line before any panel is placed.

THE PANEL MODULE IS NOT THE STRUCTURAL BAY, AND CANNOT BE MADE TO BE
Three measured modules, none of them adjustable by this file:

    panel posts     50cm rhythm -- 7 pairs at local x -150..+150
    panel overall   330cm       -- 15cm proud of the end posts each side
    structural bay  360cm       -- surveyed, the Beam A assembly is
                                   360x360 with arms SA.SB.SC out to 180

360 is not a multiple of 50, so no offset makes the panel posts fall on
the column grid in general: 330 and 360 realign only every LCM = 3960cm,
i.e. 12 panels to 11 bays, 39.6m. There is no arrangement to search for.

What IS available is 330 + 30 = 360. `align` chooses between the two
readings of that:

  "run"   the default. Panels butt at 330 and the run is centred on the
          wall. The facade is continuous and self-consistent; it simply
          drifts against the columns.

  "grid"  one panel per structural bay, centred in it, anchored on the
          same entrance origin frame.py anchors the column grid to. Every
          panel joint then lands on a column line by construction, and
          the 30cm left at each column is the column's own zone rather
          than a gap in the cladding.

          Two costs, both real. The bay must be wholly on wall for its
          panel, so short elevations clad less. And a 40cm column in a
          30cm joint laps 5cm onto each neighbouring panel -- the panel
          is 10cm too wide to sit clear between columns. That lap is
          measured and reported (`column_lap_cm`), not silently accepted:
          it is a fixing detail if intended and a clash if not, and this
          file cannot tell which.

`unclad_cm` in the summary is the remainder either way. It is not an
error; it is the honest measure of how much wall this panel set cannot
cover -- and most of what is left is the 170cm corridor ends, which are
narrower than any panel in the set.

HOW A PANEL IS ORIENTED
Each panel's local frame (see facade_import) has +x along the wall, y=0
on the wall centre line with -y pointing OUT, and z up from the panel's
own floor slab. Outward is computed per wall from its single owner: the
direction from the owner's centroid to the wall, which for the convex
rectangles growth.py produces is always the true outward normal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, floor

from .facade_import import load_facades
from .frame import GRID_CM
from .geometry import Point
from .growth import LEVEL_HEIGHT_CM, FloorPlan

# What each panel is for, in Adela's words. `glazing` orders them from
# blank to most open, which is what the selection rules below sort on and
# what the UI legend uses -- it is the single axis all nine sit on.
PANEL_ROLES: dict[str, dict] = {
    "A": {"label": "Solid — upper floor",   "glazing": 0, "use": "residential",
          "note": "Solid facade, upper floor, denser shading."},
    "B": {"label": "Solid — ground floor",  "glazing": 0, "use": "residential",
          "note": "Solid facade at ground level."},
    "C": {"label": "Simple — no shading",   "glazing": 1, "use": "any",
          "note": "No shading needed. Normal and simple; applies to anything."},
    "D": {"label": "One big window",        "glazing": 2, "use": "residential",
          "note": "Open for one big window. Residential units."},
    "E": {"label": "Two windows",           "glazing": 3, "use": "residential",
          "note": "Open for two windows. Residential units."},
    "H": {"label": "One full window",       "glazing": 4, "use": "shared",
          "note": "Open for one full window. Shared spaces."},
    "G": {"label": "Two full windows",      "glazing": 5, "use": "shared",
          "note": "Open for two full windows. Shared spaces."},
    "F": {"label": "Three full windows",    "glazing": 6, "use": "shared",
          "note": "Open for three full windows. Shared spaces."},
    "I": {"label": "Balcony",               "glazing": 3, "use": "residential",
          "note": "Balcony. Projects 116cm, against 70cm for the shading panels."},
}


@dataclass
class FacadePanel:
    """One placed panel."""
    panel: str            # "A".."I"
    cx: float             # centre of the panel on the wall line, world cm
    cy: float
    z0: float             # its floor slab
    angle: float          # radians about vertical; +x local runs this way
    level: int
    wall_id: int
    owner: str            # the element it clads
    rule: str             # why this panel -- surfaced in the UI
    # Outward normal, kept rather than recovered from `angle`: the solar
    # analysis needs it and re-deriving it is where the 180-degree sign
    # error lives.
    nx: float = 0.0
    ny: float = 0.0
    # Set by the solar pass, if one was run: kWh/m2/yr of direct beam on
    # this panel, and that value normalised 0..1 across the building.
    sun_kwh: float = 0.0
    sun_norm: float = 0.0


@dataclass
class Facade:
    panels: list[FacadePanel] = field(default_factory=list)
    # Wall length that no whole panel could cover, in cm. See the module
    # docstring: reported, never stretched away. Split into its two very
    # different causes, because they call for different answers:
    #
    #   too_short_cm  a whole run narrower than one panel. Mostly the
    #                 170cm corridor ends. Needs a NARROWER PANEL TYPE;
    #                 no arrangement of this set will ever cover it.
    #   remainder_cm  what is left over at the ends of runs that were
    #                 clad. Needs a filler piece, or a run length that
    #                 divides by 330.
    unclad_cm: float = 0.0
    too_short_cm: float = 0.0
    remainder_cm: float = 0.0
    clad_cm: float = 0.0
    exterior_cm: float = 0.0
    # Runs too narrow for any panel, as (length_cm, owner label), longest
    # first -- the shopping list for what the set is missing.
    too_short_runs: list = field(default_factory=list)


def _outward(wall, element) -> Point:
    """Unit normal of the wall pointing away from the element it clads."""
    mx = (wall.start.x + wall.end.x) / 2
    my = (wall.start.y + wall.end.y) / 2
    cx = sum(c.x for c in element.corners) / len(element.corners)
    cy = sum(c.y for c in element.corners) / len(element.corners)

    dx, dy = wall.end.x - wall.start.x, wall.end.y - wall.start.y
    n = (-dy, dx)
    length = (n[0] ** 2 + n[1] ** 2) ** 0.5
    if length == 0:
        return Point(0.0, 1.0)
    n = (n[0] / length, n[1] / length)
    # Flip it if it points back into the element.
    if (mx - cx) * n[0] + (my - cy) * n[1] < 0:
        n = (-n[0], -n[1])
    return Point(n[0], n[1])


def _choose(kind: str, level: int, run_rank: int, n: int, i: int) -> tuple[str, str]:
    """
    Pick a panel for bay `i` of `n` on a wall, and say why.

    `run_rank` is how this wall ranks by length among the exterior walls
    of the same element on the same level -- 0 is the element's longest,
    i.e. its principal elevation. That is the only ordering available
    without a site or an orientation, and it is a real one: the longest
    exterior face of a dwelling is its front.

    The rules are Adela's, one per line:

      circulation      C   -- "no need for shading, can apply to anything"
      unit, ground     B   -- "solid facade, ground floor"
      unit, upper      I on the principal elevation's first bay, one
                            balcony per unit per storey; then E/D across
                            the rest of that elevation -- two windows and
                            one big window, alternating so the front is
                            not one repeated panel
                       D/A on secondary elevations, alternating: fewer
                            openings on the flank than on the front, and
                            A is exactly "solid, upper floor, more dense"
      shared space     F/G/H by elevation rank -- three, two and one full
                            window. The most open panel goes on the
                            longest elevation, so a lobby or a gym takes
                            its light on its best face.
    """
    if kind in ("corridor", "core"):
        return "C", "circulation — no shading needed"

    if kind == "communal":
        panel = ("F", "G", "H")[min(run_rank, 2)]
        return panel, f"shared space, elevation {run_rank + 1} by length"

    # residential
    if level == 0:
        return "B", "residential, ground floor — solid"

    if run_rank == 0:
        if i == 0:
            return "I", "residential upper — balcony on the principal elevation"
        return ("E" if i % 2 == 1 else "D"), "residential upper — principal elevation"

    return ("D" if i % 2 == 0 else "A"), f"residential upper — flank elevation {run_rank + 1}"


# Two exterior walls belong to the same run if they are collinear to
# within this, and touch to within it. Matched to walls.COLLINEAR_TOL_CM:
# the walls being merged came out of that same resolution, so anything
# tighter would fail to re-join pieces it had just cut apart.
_RUN_TOL_CM = 2.0
_PARALLEL_EPS = 1e-6


def _lines(walls: list) -> list[dict]:
    """Group exterior walls onto their supporting plan lines.

    Deliberately across ALL storeys: the line is where the facade module
    is anchored, and a level-1 wall standing above a level-0 one is the
    same elevation seen one floor up. Each line carries its walls as
    (t0, t1, wall) in the line's own 1D coordinate.
    """
    lines: list[dict] = []
    for wall in walls:
        dx = wall.end.x - wall.start.x
        dy = wall.end.y - wall.start.y
        length = (dx * dx + dy * dy) ** 0.5
        if length <= 0:
            continue
        ux, uy = dx / length, dy / length
        # One sign convention per direction, or a wall and its reverse
        # land on two different lines and never merge.
        if ux < -_PARALLEL_EPS or (abs(ux) <= _PARALLEL_EPS and uy < 0):
            ux, uy = -ux, -uy

        found = None
        for ln in lines:
            if abs(ln["ux"] * uy - ln["uy"] * ux) > _PARALLEL_EPS:
                continue
            nx, ny = -ln["uy"], ln["ux"]
            off = ((wall.start.x - ln["ox"]) * nx + (wall.start.y - ln["oy"]) * ny)
            if abs(off) <= _RUN_TOL_CM:
                found = ln
                break
        if found is None:
            found = {"ox": wall.start.x, "oy": wall.start.y, "ux": ux, "uy": uy,
                     "items": []}
            lines.append(found)

        def proj(p):
            return ((p.x - found["ox"]) * found["ux"]
                    + (p.y - found["oy"]) * found["uy"])

        t0, t1 = sorted((proj(wall.start), proj(wall.end)))
        found["items"].append((t0, t1, wall))

    for ln in lines:
        # Key on the interval only: two walls can share both endpoints
        # (one directly above the other), and the tuple comparison would
        # then fall through to comparing Wall objects, which is a
        # TypeError rather than a tie-break.
        ln["items"].sort(key=lambda it: (it[0], it[1]))
    return lines


def _merge(intervals: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Collapse touching intervals. A gap wider than the tolerance stays
    a gap -- a facade does not leap across a courtyard."""
    out: list[list[float]] = []
    for t0, t1 in sorted(intervals):
        if out and t0 - out[-1][1] <= _RUN_TOL_CM:
            out[-1][1] = max(out[-1][1], t1)
        else:
            out.append([t0, t1])
    return [(a, b) for a, b in out]


def build_facade(plan: FloorPlan, pitch_cm: float | None = None,
                 align: str = "run", grid_cm: float = GRID_CM) -> Facade:
    """
    Clad every exterior wall of a plan.

    pitch_cm defaults to the bundled catalog's panel width. Passing it
    explicitly is for trying a different module, not for making an
    awkward run come out even.

    align is "run" (panels butt, run centred on the wall) or "grid" (one
    panel per structural bay, joints on the column lines). See the module
    docstring for what each costs.
    """
    cat = load_facades()
    panel_w = (cat or {}).get("panel_width_cm", 330.0)
    if pitch_cm is None:
        pitch_cm = panel_w

    # In grid mode the panel keeps its own width but the SPACING becomes
    # the structural bay, so the two stop being the same number. Every
    # length below is therefore explicit about which it means: `step` is
    # centre to centre, `panel_w` is what a panel actually covers.
    on_grid = align == "grid"
    step = grid_cm if on_grid else pitch_cm

    exterior = []
    exterior_cm = 0.0
    for wall in plan.walls:
        if len(wall.owners) != 1:
            continue  # shared, i.e. internal
        if wall.owners[0] >= len(plan.elements):
            continue
        exterior.append(wall)
        exterior_cm += wall.length_cm

    # Each element ranks its own exterior walls longest-first, so a bay
    # can ask "is the wall behind me this element's principal elevation?"
    # even though the RUN it belongs to may cross several elements.
    # Keyed by wall id and sorted by (-length, id) so the ranking is
    # stable rather than depending on resolve_walls' emission order.
    rank_of: dict[int, int] = {}
    by_owner: dict[int, list] = {}
    for wall in exterior:
        by_owner.setdefault(wall.owners[0], []).append(wall)
    for walls in by_owner.values():
        for rank, wall in enumerate(sorted(walls, key=lambda w: (-w.length_cm, w.id))):
            rank_of[wall.id] = rank

    out = Facade(exterior_cm=exterior_cm)

    for ln in _lines(exterior):
        items = ln["items"]

        # ONE datum for the whole line, across every storey on it. This
        # is what makes the facade stack -- see the module docstring.
        # Centred on the line's full extent so the leftover splits at the
        # two ends rather than piling up at one.
        lo = min(t0 for t0, _t1, _w in items)
        hi = max(t1 for _t0, t1, _w in items)
        n_line = int((hi - lo) // step)
        if n_line < 1:
            # Nothing on this line is wide enough for a panel. Charge it
            # per storey so a 170cm corridor end standing on four floors
            # is counted four times, which is what it costs.
            for t0, t1, wall in items:
                out.unclad_cm += t1 - t0
                out.too_short_cm += t1 - t0
                out.too_short_runs.append(
                    (round(t1 - t0, 1), plan.elements[wall.owners[0]].label))
            continue

        if on_grid:
            # Anchor on the SAME origin frame.py anchors the column grid
            # to -- the entrance -- projected onto this line's direction.
            # growth.py only ever builds axis-aligned rectangles, so the
            # line direction is (+-1,0) or (0,+-1) and this projection is
            # exact rather than an approximation.
            g = ln["ux"] * plan.entrance.x + ln["uy"] * plan.entrance.y
            origin_t = g - (ln["ux"] * ln["ox"] + ln["uy"] * ln["oy"])
            # First bay whose panel could touch this line's extent.
            k0 = floor((lo - origin_t) / step)
            base = origin_t + k0 * step
            n_line = int((hi - base) // step) + 1
        else:
            base = lo + ((hi - lo) - n_line * step) / 2

        # Per storey, which stretches of this line actually exist.
        #
        # EVERY storey an owner occupies, not just the one it is based
        # on. A duplex is one element with floors=2, and growth.py groups
        # walls by el.level alone, so its upper storey has no wall of its
        # own -- clad from the wall set as-is, a 3Bed's second floor came
        # out bare. On a four-storey plan that left 90 panels on level 0,
        # 66 on level 1, 7 on level 2 and none on level 3: a facade that
        # stopped two floors below the highest room.
        #
        # Straight off wall.level now. This used to expand each wall
        # across its owners' storeys, because walls were grouped by base
        # level and a duplex's upper floor had none of its own -- the
        # facade stopped two storeys below the highest room. That gap is
        # closed at the source: walls resolve per occupied storey, so a
        # duplex has a real level-1 wall to clad.
        by_level: dict[int, list] = {}
        for t0, t1, wall in items:
            by_level.setdefault(wall.level, []).append((t0, t1, wall))

        for level in sorted(by_level):
            here = by_level[level]
            spans = _merge([(t0, t1) for t0, t1, _w in here])
            placed = 0

            for k in range(n_line):
                # The panel sits centred in its bay. In "run" mode the
                # bay IS the panel, so a and b are its edges; in "grid"
                # mode the bay is 30cm wider and the panel is inset 15cm
                # at each column line.
                t = base + (k + 0.5) * step
                a = t - panel_w / 2
                b = t + panel_w / 2
                # The whole PANEL has to be on real wall. Testing only
                # the midpoint would hang panels off the end of a short
                # storey, where the elevation steps back.
                if not any(s0 - _RUN_TOL_CM <= a and b <= s1 + _RUN_TOL_CM
                           for s0, s1 in spans):
                    continue

                # Which wall is this bay on? The run may cross several
                # elements, and the panel is chosen by what is behind it,
                # not by where the run started.
                hit = next((it for it in here if it[0] <= t <= it[1]), None)
                if hit is None:
                    hit = min(here, key=lambda it: min(abs(t - it[0]), abs(t - it[1])))
                wall = hit[2]
                el = plan.elements[wall.owners[0]]

                normal = _outward(wall, el)
                # Rotation about +z that carries the panel's local axes
                # onto the wall. Derived from the ONE constraint that
                # matters: local -y must land on the outward normal, so
                # local +y lands on -normal. Under R(a), local +y goes to
                # (-sin a, cos a), so sin a = n.x and cos a = -n.y.
                #
                # Worth deriving rather than guessing: the sign error here
                # is 180 degrees, which points every balcony and every
                # shading fin INTO the building it is cladding, and from
                # most camera angles that still looks like a facade.
                angle = atan2(normal.x, -normal.y)

                panel, rule = _choose(el.kind, level, rank_of.get(wall.id, 0),
                                      n_line, k)
                out.panels.append(FacadePanel(
                    panel=panel,
                    cx=ln["ox"] + ln["ux"] * t,
                    cy=ln["oy"] + ln["uy"] * t,
                    z0=level * LEVEL_HEIGHT_CM,
                    angle=angle,
                    level=level,
                    wall_id=wall.id,
                    owner=el.label,
                    rule=rule,
                    nx=normal.x, ny=normal.y,
                ))
                placed += 1

            level_len = sum(s1 - s0 for s0, s1 in spans)
            # A panel covers its own width, never the bay spacing -- in
            # grid mode those differ by 30cm and charging the spacing
            # would claim cladding on the column line.
            out.clad_cm += placed * panel_w
            out.unclad_cm += level_len - placed * panel_w
            if placed:
                out.remainder_cm += level_len - placed * panel_w
            else:
                out.too_short_cm += level_len
                out.too_short_runs.append(
                    (round(level_len, 1), plan.elements[here[0][2].owners[0]].label))

    return out


def verify_facade(facade: Facade, pitch_cm: float | None = None,
                  step_cm: float | None = None) -> dict:
    """
    Check that the panels actually meet each other, rather than assuming
    it because the arithmetic looked right.

    Two joints have to hold, and they fail in different ways:

      VERTICAL   a panel's column is 300 tall and a storey is 300, so a
                 panel directly above another must start exactly where it
                 ends. This is the one that was broken: panel D was
                 modelled 10cm low, so every D hung below its slab with a
                 10cm gap at the head. facade_import now takes the datum
                 from the column zone, which fixes it at the source --
                 this checks the fix holds.

      HORIZONTAL panels tile at their own width, so neighbours in a run
                 share an edge exactly. A gap here means the pitch and
                 the panel width have drifted apart.

    Returns a report rather than raising, so the API can surface it.
    """
    cat = load_facades() or {}
    if pitch_cm is None:
        pitch_cm = cat.get("panel_width_cm", 330.0)
    # Centre-to-centre spacing, which is the panel width in "run" mode
    # and the structural bay in "grid" mode. Passing the wrong one makes
    # every joint look like a gap.
    if step_cm is None:
        step_cm = pitch_cm
    panels_meta = cat.get("panels", {})

    bad_column = sorted({
        k for k, p in panels_meta.items()
        if abs(p.get("column_z0", 0.0)) > 0.5
        or abs(p.get("column_z1", 0.0) - LEVEL_HEIGHT_CM) > 0.5
    })

    # Vertical: group by (wall line position, level) and look for a panel
    # one storey up at the same plan position.
    at = {}
    for p in facade.panels:
        at[(round(p.cx, 1), round(p.cy, 1), p.level)] = p
    stacked = gaps = 0
    for (x, y, lv), _p in at.items():
        if (x, y, lv + 1) in at:
            stacked += 1
            # Column runs 0..300 on a 300 storey, so the panel above
            # starts exactly where this one's column ends. Any panel
            # whose column is not 0..300 breaks that, which is what
            # bad_column catches; here we only need the z spacing.
            below = at[(x, y, lv)]
            above = at[(x, y, lv + 1)]
            if abs((above.z0 - below.z0) - LEVEL_HEIGHT_CM) > 0.5:
                gaps += 1

    # Horizontal: neighbours in a run are pitch apart, centre to centre.
    #
    # Grouped by the actual LINE, not just by angle: two parallel
    # elevations on opposite sides of the building share an angle, and
    # keying on that alone compares panels that were never neighbours and
    # reports a phantom gap between them. The line is fixed by the angle
    # plus the distance along the normal.
    by_line: dict[tuple, list] = {}
    for p in facade.panels:
        offset = p.cx * p.nx + p.cy * p.ny
        by_line.setdefault((p.level, round(p.angle, 3), round(offset, 1)), []).append(p)
    adjacent = seams = 0
    for group in by_line.values():
        group.sort(key=lambda p: (p.cx, p.cy))
        for a, b in zip(group, group[1:]):
            d = ((b.cx - a.cx) ** 2 + (b.cy - a.cy) ** 2) ** 0.5
            if d > step_cm * 1.5:
                continue  # different runs on the same line, not neighbours
            adjacent += 1
            if abs(d - step_cm) > 0.5:
                seams += 1

    return {
        "panel_width_cm": pitch_cm,
        "storey_cm": LEVEL_HEIGHT_CM,
        "misaligned_types": bad_column,
        "stacked_pairs": stacked,
        "vertical_gaps": gaps,
        "adjacent_pairs": adjacent,
        "horizontal_gaps": seams,
        "connected": not bad_column and gaps == 0 and seams == 0,
    }


def column_alignment(facade: Facade, plan: FloorPlan,
                     grid_cm: float = GRID_CM) -> dict:
    """
    How close each panel joint lands to a structural column line.

    Measured, not assumed. `build_facade(align="grid")` should come out
    at zero offset for every joint; the default "run" mode should come
    out scattered, and this is what shows by how much.

    The grid is the one frame.py uses: anchored on the entrance, 360cm.
    """
    cat = load_facades() or {}
    panel_w = cat.get("panel_width_cm", 330.0)
    ex, ey = plan.entrance.x, plan.entrance.y

    # Measured on the panel CENTRE against the centre of a structural
    # bay, not on the panel edge against a column line. In grid mode the
    # edge is deliberately (bay - panel)/2 short of the column, so
    # measuring the edge reports that inset as an error when it is the
    # detail working exactly as intended.
    offsets = []
    for p in facade.panels:
        ux, uy = -p.ny, p.nx           # along the wall
        t = ux * (p.cx - ex) + uy * (p.cy - ey)
        d = abs(t - (round(t / grid_cm - 0.5) + 0.5) * grid_cm)
        offsets.append(min(d, grid_cm - d))

    if not offsets:
        return {"grid_cm": grid_cm, "panels": 0}
    centred = sum(1 for d in offsets if d <= 2.0)
    clear = (grid_cm - panel_w) / 2
    return {
        "grid_cm": grid_cm,
        "panel_width_cm": panel_w,
        "panels": len(offsets),
        "in_bay": centred,
        "in_bay_pct": round(100 * centred / len(offsets), 1),
        "mean_offset_cm": round(sum(offsets) / len(offsets), 1),
        "max_offset_cm": round(max(offsets), 1),
        # Gap left at each column line by one-panel-per-bay, and how far
        # a 40cm column reaches into the panels on either side of it.
        # The lap is a fixing detail if intended and a clash if not, and
        # this module cannot tell which -- so it reports the number.
        "clear_to_column_cm": round(clear, 1),
        "column_lap_cm": round(20.0 - clear, 1),
    }


def facade_summary(facade: Facade) -> dict:
    counts: dict[str, int] = {}
    levels: dict[str, int] = {}
    for p in facade.panels:
        counts[p.panel] = counts.get(p.panel, 0) + 1
        levels[str(p.level)] = levels.get(str(p.level), 0) + 1
    widest = sorted(facade.too_short_runs, reverse=True)[:6]
    return {
        "panel_count": len(facade.panels),
        "counts": counts,
        "by_level": levels,
        "exterior_length_m": round(facade.exterior_cm / 100, 1),
        "clad_length_m": round(facade.clad_cm / 100, 1),
        "unclad_length_m": round(facade.unclad_cm / 100, 1),
        "too_short_length_m": round(facade.too_short_cm / 100, 1),
        "too_short_count": len(facade.too_short_runs),
        # The widest run no panel fits, i.e. how narrow a new panel type
        # would have to be to start closing the gap.
        "widest_too_short_cm": max((r[0] for r in facade.too_short_runs), default=0.0),
        "too_short_examples": [{"length_cm": r[0], "owner": r[1]} for r in widest],
        "remainder_length_m": round(facade.remainder_cm / 100, 1),
        "clad_pct": (round(100 * facade.clad_cm / facade.exterior_cm, 1)
                     if facade.exterior_cm else 0.0),
    }
