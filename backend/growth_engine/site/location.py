"""
site/location.py
The real site: a named place, its coordinates, and its boundary.

WHY THIS EXISTS
Until now the engine had no site. Growth started at an origin, north was
whatever +y happened to mean, and solar.py took a latitude as a
parameter with a placeholder default. None of that is wrong on its own,
but it means the sun study was about a building in general rather than
about this building here.

THE DEPTFORD SITE
The triangle bounded by Coffey Street, Deptford Church Street and
Crossfield Street, London SE8 -- the plot at 51.479058, -0.023964.

The boundary is NOT traced off a screenshot. The three corners are the
real OSM intersection nodes of those three streets, which is why they
come out exact: each pair of streets SHARES a node, so the corner is a
single coordinate rather than two lines almost meeting. `fetch_boundary`
below regenerates it, and prints the same numbers.

    Crossfield x Coffey      NW corner
    Coffey     x Church      NE corner
    Crossfield x Church      S corner

WHAT THE POLYGON IS, PRECISELY
Street CENTRELINES, not the developable plot. The kerb-to-boundary
setback is real and this does not know it, so `boundary(inset_m=...)`
offsets every edge inward by a uniform distance -- 6m by default, roughly
half a street width. The centreline area is 4,588 m2; at a 6m inset it is
2,798 m2. That is a big drop, and it is right: a triangle loses area to a
setback much faster than a rectangle does, because all three edges come
in at once and the corners are acute.

Use the inset polygon for anything about what fits; the centreline one is
what OSM actually says.

NORTH IS REAL NOW
Engine +y is north and +x is east, which is the convention
osm_site_finder already builds its local frame on. The site's own axes
sit about 4 degrees off cardinal: Coffey Street runs at bearing 87
degrees, Deptford Church Street at 176. So a building laid out on the
engine's axes is very nearly street-aligned already, and `ROTATION_DEG`
is the correction if you want it exact.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

M_TO_CM = 100.0


@dataclass(frozen=True)
class SiteLocation:
    name: str
    address: str
    lat: float
    lon: float
    # Boundary in metres, east/north from (lat, lon). Winding is not
    # assumed -- `boundary()` works it out, because getting it backwards
    # offsets the setback OUTWARD and quietly grows the site.
    boundary_m: tuple[tuple[float, float], ...]
    # Where the engine's origin -- the entrance, which growth.py seeds
    # everything from -- sits in that frame.
    origin_m: tuple[float, float] = (0.0, 0.0)
    # Rotation of the building's axes relative to true north, degrees
    # clockwise. Zero means the engine's +y IS north.
    rotation_deg: float = 0.0
    source: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def area_m2(self) -> float:
        return _area(self.boundary_m)

    def boundary(self, inset_m: float = 0.0) -> list[tuple[float, float]]:
        """The boundary in metres, with every edge offset inward by
        `inset_m`.

        A true edge offset -- each edge is pushed along its own inward
        normal and the new vertices are the intersections of adjacent
        offset lines. NOT a scale about the centroid, which is the
        tempting one-liner and is wrong for anything but a regular
        polygon: on this scalene triangle it over-shrinks by about 400m2,
        because the centroid is not the incentre.
        """
        if inset_m <= 0:
            return list(self.boundary_m)
        return _offset_polygon(list(self.boundary_m), inset_m)

    def boundary_cm(self, inset_m: float = 0.0) -> list[tuple[float, float]]:
        """The boundary in the engine's own frame: centimetres, relative
        to the entrance rather than to the site coordinate origin."""
        ox, oy = self.origin_m
        return [((x - ox) * M_TO_CM, (y - oy) * M_TO_CM)
                for x, y in self.boundary(inset_m)]


def _area(poly) -> float:
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


def _signed_area(poly) -> float:
    s = 0.0
    for i in range(len(poly)):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % len(poly)]
        s += x0 * y1 - x1 * y0
    return s / 2


def _offset_polygon(poly, inset: float):
    """Push every edge of a convex polygon inward by `inset`.

    Each edge becomes a line offset along its inward normal; each new
    vertex is where two adjacent offset lines cross. Winding is measured
    rather than assumed -- with the sign the wrong way round the setback
    offsets outward, which grows the site instead of shrinking it and
    looks entirely plausible on screen.
    """
    n = len(poly)
    inward = 1.0 if _signed_area(poly) > 0 else -1.0

    lines = []
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = math.hypot(ex, ey)
        if L == 0:
            continue
        # Left normal of the edge, flipped to point into the polygon.
        nx, ny = -ey / L * inward, ex / L * inward
        lines.append((nx, ny, nx * ax + ny * ay + inset))

    out = []
    m = len(lines)
    for i in range(m):
        a1, b1, c1 = lines[i - 1]
        a2, b2, c2 = lines[i]
        det = a1 * b2 - a2 * b1
        if abs(det) < 1e-9:
            out.append(poly[i])           # parallel edges: nothing to cross
            continue
        out.append(((c1 * b2 - c2 * b1) / det, (a1 * c2 - a2 * c1) / det))

    # An inset larger than the inscribed circle collapses the polygon
    # past its own centre. Tested by half-planes, NOT by a winding flip:
    # offsetting a triangle past its inradius is a negative homothety
    # about the incentre, which is a 180-degree rotation and therefore
    # PRESERVES winding. A sign check passes it happily and hands back a
    # small inverted triangle with a plausible positive area.
    for px, py in out:
        if any(a * px + b * py < c - 1e-6 for a, b, c in lines):
            cx = sum(p[0] for p in poly) / n
            cy = sum(p[1] for p in poly) / n
            return [(cx, cy)] * n
    return out


# --- the site ------------------------------------------------------
# Corners are the OSM intersection nodes, in metres east/north of
# 51.479058, -0.023964. Regenerate with `python -m
# growth_engine.site.location --fetch`.
#
# origin_m is where the engine's entrance lands on the site. Not guessed
# -- `best_placement()` searched origin and rotation against the default
# program's footprint and this is the result: the whole building inside
# the 6m-inset boundary. Re-run it if the program changes shape enough to
# matter; `site_fit()` says whether it still holds.
#
# rotation_deg comes out 0, which is a real finding rather than a default
# left alone: Coffey Street bears 87 degrees and Deptford Church Street
# 176, so the site is within 4 degrees of cardinal and a building on the
# engine's own axes is already street-aligned.
DEPTFORD = SiteLocation(
    name="Deptford Church Street",
    address="Coffey St / Deptford Church St / Crossfield St, London SE8",
    lat=51.479058,
    lon=-0.023964,
    boundary_m=(
        (-47.9, 17.9),   # NW  Crossfield x Coffey
        (65.8, 23.9),    # NE  Coffey x Deptford Church
        (71.4, -56.5),   # S   Crossfield x Deptford Church
    ),
    origin_m=(26.0, 10.0),
    rotation_deg=0.0,
    source="OpenStreetMap street centrelines, fetched 2026-08-10",
    notes=(
        "Boundary is street CENTRELINES; use inset_m for the developable plot.",
        "Coffey St bears 87 deg, Deptford Church St 176 deg -- about 4 deg off cardinal.",
    ),
)

DEFAULT_SITE = DEPTFORD


def site_fit(site: SiteLocation, footprints, inset_m: float = 6.0) -> dict:
    """
    Does the generated building sit inside the site?

    `footprints` is one list of corner Points per placed element -- i.e.
    `[el.corners for el in plan.elements]`.

    It used to take the plan's bounding RECTANGLE, which was wrong the
    moment growth started respecting the boundary: this building is
    cross-shaped, so its bounding box has corners hanging over the site
    edge while every element inside it is comfortably on the plot. That
    reported 99.3% and `fits: False` for a plan that was, in fact,
    entirely on the site. Measuring the elements themselves is both the
    honest test and the one that agrees with the engine's own.
    """
    from ..geometry import Point, polygon_contains

    poly = [Point(x, y) for x, y in site.boundary_cm(inset_m)]
    inside = [polygon_contains(f, poly) for f in footprints]

    def _rect_area(f):
        xs = [p.x for p in f]
        ys = [p.y for p in f]
        return (max(xs) - min(xs)) * (max(ys) - min(ys)) / 10_000  # cm2 -> m2

    total = sum(_rect_area(f) for f in footprints)
    on = sum(_rect_area(f) for f, ok in zip(footprints, inside) if ok)
    return {
        "site": site.name,
        "site_area_m2": round(site.area_m2, 0),
        "developable_area_m2": round(_area(site.boundary(inset_m)), 0),
        "inset_m": inset_m,
        "elements": len(footprints),
        "elements_inside": sum(inside),
        "elements_outside": len(footprints) - sum(inside),
        "area_inside_pct": round(100 * on / total, 1) if total else 100.0,
        "fits": all(inside),
    }


def best_placement(site: SiteLocation, extent_cm, inset_m: float = 6.0,
                   rotations=range(0, 360, 5), step_m: int = 2) -> dict:
    """
    Where to stand the building so the most of it lands on the site.

    A brute-force sweep of origin offset and rotation, scoring the
    fraction of the footprint inside the inset boundary. Brute force is
    the right tool here: the search space is two metres and five degrees
    across a plot 140m wide, it runs in a couple of seconds, and the
    scoring function is a point-in-polygon test with no gradient to
    exploit.

    This is what produced DEPTFORD.origin_m. It is a placement aid, not a
    design: it knows nothing about which street the entrance should face.
    """
    from ..geometry import Point, point_in_polygon

    poly = [Point(x, y) for x, y in site.boundary(inset_m)]
    x0, y0, x1, y1 = (v / M_TO_CM for v in extent_cm)
    n = 20
    pts = [(x0 + (x1 - x0) * (i + 0.5) / n, y0 + (y1 - y0) * (j + 0.5) / n)
           for i in range(n) for j in range(n)]

    xs = [p[0] for p in site.boundary_m]
    ys = [p[1] for p in site.boundary_m]
    best = None
    for rot in rotations:
        th = math.radians(rot)
        c, s = math.cos(th), math.sin(th)
        rp = [(px * c - py * s, px * s + py * c) for px, py in pts]
        for ox in range(int(min(xs)), int(max(xs)), step_m):
            for oy in range(int(min(ys)), int(max(ys)), step_m):
                hits = sum(1 for px, py in rp
                           if point_in_polygon(Point(px + ox, py + oy), poly))
                if best is None or hits > best[0]:
                    best = (hits, rot, ox, oy)
    hits, rot, ox, oy = best
    return {
        "inside_pct": round(100 * hits / len(pts), 1),
        "rotation_deg": rot,
        "origin_m": (float(ox), float(oy)),
    }


def fetch_boundary(lat: float = DEPTFORD.lat, lon: float = DEPTFORD.lon,
                   streets: str = "Coffey|Crossfield|Deptford Church") -> list:
    """Re-derive the corners from OSM. Needs internet.

    Each corner is the point where two of the named streets share a node,
    so this returns exact intersections rather than a least-squares fit
    of two polylines.
    """
    import itertools
    import json
    import urllib.parse
    import urllib.request

    q = (f'[out:json][timeout:25];(way["highway"]["name"~"{streets}"]'
         f"({lat - 0.004},{lon - 0.003},{lat + 0.004},{lon + 0.003}););out geom;")
    req = urllib.request.Request(
        "https://overpass-api.de/api/interpreter",
        data=urllib.parse.urlencode({"data": q}).encode(),
        headers={"User-Agent": "growth-engine/0.1 (site lookup)"},
    )
    doc = json.loads(urllib.request.urlopen(req, timeout=60).read())

    m_lat = 111_320.0
    m_lon = 111_320.0 * math.cos(math.radians(lat))
    groups: dict[str, list] = {}
    for el in doc["elements"]:
        name = el.get("tags", {}).get("name", "")
        key = next((s for s in streets.split("|") if s in name), None)
        if key is None:
            continue
        groups.setdefault(key, []).extend(
            ((p["lon"] - lon) * m_lon, (p["lat"] - lat) * m_lat)
            for p in el.get("geometry", [])
        )

    corners = []
    for a, b in itertools.combinations(sorted(groups), 2):
        best = min(
            ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2, pa, pb)
            for pa in groups[a] for pb in groups[b]
        )
        d, pa, pb = best
        corners.append({
            "streets": (a, b),
            "gap_m": round(math.sqrt(d), 2),
            "point_m": (round((pa[0] + pb[0]) / 2, 1), round((pa[1] + pb[1]) / 2, 1)),
        })
    return corners


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Show or re-fetch the site boundary.")
    ap.add_argument("--fetch", action="store_true", help="re-derive corners from OSM")
    args = ap.parse_args(argv)

    s = DEFAULT_SITE
    print(f"{s.name} — {s.address}")
    print(f"  {s.lat}, {s.lon}   ({s.source})")
    print(f"  centreline area {s.area_m2:,.0f} m2   "
          f"at 6m inset {_area(s.boundary(6.0)):,.0f} m2")
    for i, (x, y) in enumerate(s.boundary_m):
        print(f"    corner {i}  ({x:7.1f}, {y:7.1f}) m")
    for n in s.notes:
        print(f"  note: {n}")

    if args.fetch:
        print("\n  re-fetching from OSM…")
        for c in fetch_boundary():
            print(f"    {c['streets'][0]:11s} x {c['streets'][1]:11s} "
                  f"gap {c['gap_m']:.2f} m  ->  {c['point_m']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
