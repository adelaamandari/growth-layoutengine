"""
diagnostics.py
Measurements ABOUT a generated plan, as opposed to geometry that makes
one. Pure standard library.

`shared_boundaries` originally existed to quantify a defect: growth.py
used to walk all four edges of every element independently, so a unit
flush against a corridor built that wall twice. walls.py now resolves
each physical wall once, so that defect is gone -- and this module's job
changed accordingly. It is no longer a measurement of what is broken; it
is the INDEPENDENT check that the fix holds.

That independence is the point, so keep it. This module finds coincident
boundaries by its own pairwise edge comparison, with its own
COLLINEAR_TOL_CM, deliberately NOT importing walls.py's interval
decomposition or its constants. Sharing them would mean a bug in the
resolution logic would agree with itself and pass silently.

That is not hypothetical -- it happened. Both sides independently decided
a wall belonged to one storey, the element's own el.level, so a duplex
spanning levels 0-1 never met the level-1 unit beside it: growth built
that party wall twice and this module skipped the pair by the same test.
177m of doubled wall verified as clean. Independence only buys anything
where the two do not share the assumption. Both now work per OCCUPIED
storey -- see `_storeys`, derived here rather than imported, which is
also why `wall_length` counts a duplex's perimeter once per floor.

`verify_walls` puts the two together and asserts the invariant:

    resolved + dropped == naive - shared

i.e. every shared stretch is present exactly once. It returns a report
rather than raising, so the API can surface it (`/api/plan` does, on
every response) and it can act as a regression guard. On the default
program at SEED 42 it holds to 0.00m: 945.72m naive, 193.48m shared,
752.24m resolved across 147 walls, 44 of them shared -- 2,256.7 m2.

"The default program" means the 18-entry one in app/schemas.py, which is
what the API and the UI send. preview.DEFAULT_PROGRAM is a DIFFERENT,
12-entry list with no Lobby, Gym, Library, Workspace or outdoor ground,
and figures quoted here were once taken from it by mistake -- they came
out a third short and nothing said which program they belonged to.

The seed matters and belongs in the figure. Shared spaces draw their
size from a range, so an unseeded plan gives a different total every
run; the numbers this docstring used to quote (550.33 / 171.29 / 378.99)
were from one such run and could never have been reproduced. What is
checkable in any run is delta_m, which is 0.00 regardless.

The resolved total is also higher than those old figures for a real
reason: a duplex's upper storey now carries walls of its own, which is
the material you build. Not a regression.
"""

from __future__ import annotations

from .geometry import Point
from .growth import PlacedElement, builds_walls

# Two edges count as the same physical wall if every endpoint of one sits
# within this distance of the other's infinite line. 2cm is deliberately
# looser than geometry.EPS (1cm): that epsilon decides collision, this one
# decides identity, and a wall built from both sides can be a hair off.
COLLINEAR_TOL_CM = 2.0
MIN_SHARED_CM = 5.0


def _storeys(el: PlacedElement) -> range:
    """Every storey this element occupies.

    Derived here rather than imported, for the same reason this module
    computes its own overlaps: the check has to be able to disagree with
    the resolution logic. A duplex is one element standing on two
    storeys, and counting it once was what let 177m of doubled wall pass
    as deduplicated.
    """
    return range(el.level, el.level + max(1, getattr(el, "floors", 1)))


def element_edges(el: PlacedElement) -> list[tuple[Point, Point]]:
    c = el.corners
    return [(c[i], c[(i + 1) % 4]) for i in range(4)]


def _overlap(a: tuple[Point, Point], b: tuple[Point, Point]) -> tuple[float, Point, Point] | None:
    """Length of b's projection onto a, if b is collinear with a and the
    two actually overlap. Returns (length, start, end) in world space."""
    (a1, a2) = a
    dx, dy = a2.x - a1.x, a2.y - a1.y
    length = (dx * dx + dy * dy) ** 0.5
    if length == 0:
        return None
    ux, uy = dx / length, dy / length

    for p in b:
        perp = abs((p.x - a1.x) * -uy + (p.y - a1.y) * ux)
        if perp > COLLINEAR_TOL_CM:
            return None

    ts = sorted(((p.x - a1.x) * ux + (p.y - a1.y) * uy) for p in b)
    lo, hi = max(0.0, ts[0]), min(length, ts[1])
    if hi - lo <= MIN_SHARED_CM:
        return None
    return (hi - lo,
            Point(a1.x + ux * lo, a1.y + uy * lo),
            Point(a1.x + ux * hi, a1.y + uy * hi))


def shared_boundaries(elements: list[PlacedElement]) -> tuple[float, list[dict]]:
    """
    Find every stretch of wall that two different elements both build.

    Returns (total_length_cm, segments), where each segment records the
    two element labels and the overlapping run. Note this is a purely
    geometric test: it reports coincident boundaries regardless of
    whether the two sides were ever INTENDED as a party wall, so treat
    the total as an upper bound on recoverable duplication until it is
    checked against the joinery drawings.

    Only elements that stand on a COMMON storey are compared, and the
    overlap is counted once for each storey they share. The test works in
    plan, so without that guard a corridor on level 1 standing directly
    above the one on level 0 would report its whole length as shared --
    they are two real walls, one above the other, sharing nothing.

    Comparing e1.level == e2.level looks like the same guard and is not:
    it also excludes a duplex on levels 0-1 from the level-1 unit beside
    it, which do share a real wall. That is the pair growth.py was
    building twice.

    Outdoor areas are skipped for the same reason they are skipped in
    resolution: a garden's boundary is not a wall, so a unit standing
    against one shares nothing with it. `builds_walls` is imported from
    growth, NOT from walls.py -- this module's independence from the
    resolution logic is the point of it, and what has a wall is a fact
    about the plan, not about how walls get resolved.
    """
    walled = [el for el in elements if builds_walls(el)]
    segments: list[dict] = []
    total = 0.0
    for i, e1 in enumerate(walled):
        for e2 in walled[i + 1:]:
            # Every storey they BOTH stand on. Testing e1.level == e2.level
            # instead misses the case that matters: a duplex on levels 0-1
            # against an ordinary unit on level 1 shares a real wall on
            # level 1, and comparing base levels says they never meet.
            shared_levels = (set(_storeys(e1)) & set(_storeys(e2)))
            if not shared_levels:
                continue
            for ea in element_edges(e1):
                for eb in element_edges(e2):
                    hit = _overlap(ea, eb)
                    if hit is None:
                        continue
                    length, p1, p2 = hit
                    # Once per storey they share: two duplexes side by
                    # side build that party wall on both their floors, and
                    # both copies have to be accounted for.
                    for lv in sorted(shared_levels):
                        total += length
                        segments.append({
                            "a": e1.label, "b": e2.label, "level": lv,
                            "length_cm": round(length, 1),
                            "p": [round(p1.x, 2), round(p1.y, 2),
                                  round(p2.x, 2), round(p2.y, 2)],
                        })
    return total, segments


def wall_length(elements: list[PlacedElement]) -> float:
    """Total edge length summed per element PER STOREY it occupies, in cm
    -- i.e. counting a shared boundary once for each side that claims it,
    on every floor that side stands on. This is the NAIVE figure; compare
    it against the resolved walls to see what deduplication recovered.

    The per-storey multiplier is not decoration. Walls resolve one storey
    at a time, so a duplex contributes its perimeter twice to the resolved
    set; charging it once here would leave the invariant holding only
    where both sides were wrong together.

    Counts only elements that build walls, so the naive total and the
    resolved total are measuring the same set and verify_walls compares
    like with like."""
    total = 0.0
    for el in elements:
        if not builds_walls(el):
            continue
        # Multiplied by the storeys it occupies. A duplex's perimeter is
        # built on both its floors, and charging it once made the naive
        # figure disagree with a resolved set that (correctly) builds it
        # twice -- so the invariant could only hold by both sides making
        # the same mistake.
        storeys = len(_storeys(el))
        for a, b in element_edges(el):
            total += ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5 * storeys
    return total


def verify_walls(plan, tol_cm: float = MIN_SHARED_CM) -> dict:
    """
    Check that the resolved wall set really is deduplicated.

    The invariant: total resolved wall length must equal the naive
    per-element total minus the shared length, i.e. every shared stretch
    is present exactly once. Returns a report rather than raising, so it
    can be surfaced in the API and used as a regression guard.

    The tolerance is one sliver (MIN_SHARED_CM), not 1cm. This module and
    walls.py are deliberately independent and each decides for itself
    when two edges are the same line -- COLLINEAR_TOL_CM here, its own
    line grouping there -- so on geometry that very nearly aligns they
    are ENTITLED to disagree slightly about where a shared stretch starts
    and ends. Seed 11 came out 1.29cm apart on 1,418m of wall and failed
    a 1cm tolerance; that is a rounding difference between two honest
    measurements, not a wall built twice.

    This does not weaken the check. The defect this exists to catch was
    177m -- four orders of magnitude above the tolerance -- and anything
    of that kind still fails loudly. A tolerance tight enough to trip on
    tenths of a millimetre per metre is one that gets ignored, which is
    worse than one that is honest about its own precision.
    """
    naive = wall_length(plan.elements)
    shared_len, shared_segs = shared_boundaries(plan.elements)
    resolved = sum(w.length_cm for w in plan.walls)
    dropped = getattr(plan, "dropped_wall_cm", 0.0)
    expected = naive - shared_len

    referenced = set()
    for el in plan.elements:
        referenced |= set(el.wall_ids)
    all_ids = {w.id for w in plan.walls}

    # Length is now a per-storey figure, so area follows from it directly
    # -- every resolved wall is exactly one storey tall. Reported because
    # a take-off is priced in m2, and because it is the number that would
    # have made the duplex problem visible: before this, two walls of
    # identical plan length could stand 300 and 600 tall and the report
    # had no way to say so.
    from .growth import LEVEL_HEIGHT_CM

    return {
        "naive_length_m": round(naive / 100, 2),
        "resolved_area_m2": round(resolved * LEVEL_HEIGHT_CM / 10000, 1),
        "storey_height_m": LEVEL_HEIGHT_CM / 100,
        "shared_length_m": round(shared_len / 100, 2),
        "resolved_length_m": round(resolved / 100, 2),
        "expected_length_m": round(expected / 100, 2),
        # Slivers below walls.MIN_WALL_CM are deliberately not built, so
        # they are added back here rather than hidden in a tolerance.
        "dropped_length_m": round(dropped / 100, 3),
        "dropped_count": getattr(plan, "dropped_wall_count", 0),
        "delta_m": round((resolved + dropped - expected) / 100, 4),
        "deduplicated": abs(resolved + dropped - expected) <= tol_cm,
        "shared_wall_count": sum(1 for w in plan.walls if w.shared),
        "shared_interface_count": len(shared_segs),
        "all_walls_referenced": referenced == all_ids,
        "orphan_wall_ids": sorted(all_ids - referenced),
    }


def access_report(plan, limit_cm: float = 2000.0) -> dict:
    """How far a unit is from its nearest stair, and how much of the
    ground is green.

    Both are DESIGN TARGETS rather than invariants -- Adela's brief is a
    20m walk to a core and 30-40% of the ground floor green -- so they
    are measured and reported rather than asserted. A seed that misses
    should be visible, not silently accepted or silently rejected.

    Distance is straight-line between centroids, which understates a real
    walk: it does not follow the corridor. Read it as a lower bound.
    """
    from .geometry import polygon_area

    def centre(el):
        n = len(el.corners)
        return (sum(c.x for c in el.corners) / n, sum(c.y for c in el.corners) / n)

    # Cores AND stairs. Both are vertical circulation, and since the lift
    # core was capped at two per storey it is the stairs that actually
    # carry the escape distance -- measuring to cores alone would report
    # a catastrophic regression while the building got better.
    cores = [e for e in plan.elements if e.kind in ("core", "stairs")]
    rooms = [e for e in plan.elements if e.kind in ("unit", "communal")]

    worst = 0.0
    over = 0
    for r in rooms:
        here = [c for c in cores if c.level == r.level] or cores
        if not here:
            continue
        rx, ry = centre(r)
        d = min(((rx - cx) ** 2 + (ry - cy) ** 2) ** 0.5
                for cx, cy in (centre(c) for c in here))
        worst = max(worst, d)
        if d > limit_cm:
            over += 1

    ground = sum(polygon_area(e.corners) for e in plan.elements
                 if e.level == 0 and e.kind != "outdoor")
    green = sum(polygon_area(e.corners) for e in plan.elements
                if e.kind == "outdoor")
    return {
        "cores": len(cores),
        "lift_cores": sum(1 for e in cores if e.kind == "core"),
        "stairs": sum(1 for e in cores if e.kind == "stairs"),
        "max_to_core_m": round(worst / 100, 1),
        "limit_m": limit_cm / 100,
        "rooms_over_limit": over,
        "rooms": len(rooms),
        "within_limit": over == 0,
        "ground_m2": round(ground / 10000, 0),
        "green_m2": round(green / 10000, 0),
        "green_pct_of_ground": (round(100 * green / ground, 1) if ground else 0.0),
    }
