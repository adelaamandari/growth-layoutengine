"""
diagnostics.py
Measurements ABOUT a generated plan, as opposed to geometry that makes
one. Pure standard library.

`shared_boundaries` exists because of a real gap between the design and
the implementation: PROJECT_SUMMARY states that a `shared_walls` entry
means two rooms share ONE physical built wall -- "built once, referenced
by both, never duplicated" -- but growth.py currently walks all four
edges of every element independently. Where a unit sits flush against a
corridor, both build that wall. This module quantifies how much.

Two consequences, both real:
  1. Any material take-off double-counts the shared length.
  2. The two copies do not share breakpoints. A corridor edge walks its
     nine components across the corridor's whole length; the unit's edge
     walks nine across the unit's width. So the two faces of one
     physical wall disagree about where the members land.
"""

from __future__ import annotations

from .geometry import Point
from .growth import PlacedElement

# Two edges count as the same physical wall if every endpoint of one sits
# within this distance of the other's infinite line. 2cm is deliberately
# looser than geometry.EPS (1cm): that epsilon decides collision, this one
# decides identity, and a wall built from both sides can be a hair off.
COLLINEAR_TOL_CM = 2.0
MIN_SHARED_CM = 5.0


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
    """
    segments: list[dict] = []
    total = 0.0
    for i, e1 in enumerate(elements):
        for e2 in elements[i + 1:]:
            for ea in element_edges(e1):
                for eb in element_edges(e2):
                    hit = _overlap(ea, eb)
                    if hit is None:
                        continue
                    length, p1, p2 = hit
                    total += length
                    segments.append({
                        "a": e1.label, "b": e2.label,
                        "length_cm": round(length, 1),
                        "p": [round(p1.x, 2), round(p1.y, 2),
                              round(p2.x, 2), round(p2.y, 2)],
                    })
    return total, segments


def wall_length(elements: list[PlacedElement]) -> float:
    """Total edge length summed per element, in cm -- i.e. counting a
    shared boundary once for each side that claims it. This is the
    NAIVE figure; compare it against the resolved walls to see what
    deduplication recovered."""
    total = 0.0
    for el in elements:
        for a, b in element_edges(el):
            total += ((b.x - a.x) ** 2 + (b.y - a.y) ** 2) ** 0.5
    return total


def verify_walls(plan, tol_cm: float = 1.0) -> dict:
    """
    Check that the resolved wall set really is deduplicated.

    The invariant: total resolved wall length must equal the naive
    per-element total minus the shared length, i.e. every shared stretch
    is present exactly once. Returns a report rather than raising, so it
    can be surfaced in the API and used as a regression guard.
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

    return {
        "naive_length_m": round(naive / 100, 2),
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
