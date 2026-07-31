"""
site/osm_site_finder.py

Finds candidate infill sites -- gaps between existing building
footprints -- using real OpenStreetMap data via the Overpass API.

Requires network access (this needs `requests`; not runnable in a
sandboxed environment with a restricted domain allowlist -- run this
from Claude Code, a normal dev machine, or your backend server, all of
which have full internet access).

WHAT THIS DOES:
  1. Query Overpass for building footprints + street geometry in a
     bounding box.
  2. Look for gaps between adjacent buildings along the same street
     frontage -- these are infill-site candidates.
  3. For a chosen gap, extract: the boundary polygon, which edge faces
     the street (the frontage/access edge), and true north orientation
     (since OSM coordinates are real lat/lon, north is always "up" in
     the projected coordinate system used here -- no manual input
     needed).
  4. Convert everything from lat/lon into local planar coordinates in
     CENTIMETERS, matching growth_engine's Point/coordinate system, so
     the output plugs directly into the daylight/circulation analysis
     and growth engine without any further conversion.

WHAT THIS DOESN'T DO:
  - It does NOT give you the legal parcel boundary. OSM has building
    footprints and streets, not cadastral/land-registry plot lines.
    For a real infill site, you'd trace the actual buildable boundary
    yourself against the map (e.g. in QGIS or by hand), using this
    tool's gap-detection as a starting point, not a final answer.
  - Building height coverage (`building:levels`) is patchy. Don't
    assume every neighbor has it -- code that uses this for shadow
    casting needs to handle missing height data gracefully.
"""

from __future__ import annotations
from dataclasses import dataclass
import math

try:
    import requests
except ImportError:
    requests = None  # only needed when actually calling fetch_buildings()

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


@dataclass
class LatLon:
    lat: float
    lon: float


@dataclass
class Building:
    osm_id: int
    footprint: list[LatLon]
    levels: float | None  # None if OSM has no building:levels tag


@dataclass
class SiteCandidate:
    """A gap between two buildings, with everything needed to feed the
    daylight/circulation analysis and growth engine."""
    boundary_local_cm: list[tuple[float, float]]  # planar, meters->cm, origin at boundary centroid
    frontage_edge: tuple[tuple[float, float], tuple[float, float]]  # local cm coords of the street-facing edge
    neighbor_a_height_cm: float | None
    neighbor_b_height_cm: float | None
    origin_latlon: LatLon  # for converting back to real-world coordinates later


def _overpass_query(bbox: tuple[float, float, float, float]) -> str:
    """bbox = (south, west, north, east) in lat/lon degrees."""
    s, w, n, e = bbox
    return f"""
    [out:json][timeout:25];
    (
      way["building"]({s},{w},{n},{e});
      way["highway"]({s},{w},{n},{e});
    );
    out geom;
    """


def fetch_osm_data(bbox: tuple[float, float, float, float]) -> dict:
    """Raw Overpass query. Requires `requests` and live internet access."""
    if requests is None:
        raise RuntimeError("requests is not installed -- pip install requests")
    query = _overpass_query(bbox)
    response = requests.post(OVERPASS_URL, data={"data": query}, timeout=30)
    response.raise_for_status()
    return response.json()


def _local_projection(origin: LatLon):
    """
    Equirectangular approximation -- fine at building/street scale
    (errors are sub-centimeter over a few hundred meters), not meant
    for large-scale mapping.
    """
    lat0_rad = math.radians(origin.lat)
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(lat0_rad)

    def project(p: LatLon) -> tuple[float, float]:
        x_m = (p.lon - origin.lon) * m_per_deg_lon
        y_m = (p.lat - origin.lat) * m_per_deg_lat
        return (x_m * 100, y_m * 100)  # meters -> cm, matches growth_engine

    return project


def parse_buildings(osm_json: dict) -> list[Building]:
    buildings = []
    for el in osm_json.get("elements", []):
        if el.get("type") != "way" or "building" not in el.get("tags", {}):
            continue
        geometry = el.get("geometry", [])
        if not geometry:
            continue
        footprint = [LatLon(pt["lat"], pt["lon"]) for pt in geometry]
        levels_tag = el["tags"].get("building:levels")
        levels = float(levels_tag) if levels_tag else None
        buildings.append(Building(osm_id=el["id"], footprint=footprint, levels=levels))
    return buildings


def find_gap_candidates(buildings: list[Building], min_gap_m: float = 4.0,
                         max_gap_m: float = 25.0) -> list[SiteCandidate]:
    """
    Naive adjacency check: for every pair of buildings, find their
    closest edge-to-edge distance. If it falls in [min_gap_m, max_gap_m]
    -- wide enough to build on, narrow enough to still read as "between
    two buildings" rather than an open field -- treat it as a candidate.

    This is a starting point, not a rigorous solver: it doesn't check
    that the gap is actually accessible from a street, doesn't verify
    ownership/parcel boundaries, and picks the frontage edge heuristically
    (the shared edge closest to any 'highway' geometry, if provided).
    Review candidates visually before treating one as a real site.
    """
    candidates = []
    for i, a in enumerate(buildings):
        for b in buildings[i + 1:]:
            dist_m, edge_a, edge_b = _closest_approach(a.footprint, b.footprint)
            if min_gap_m <= dist_m <= max_gap_m:
                origin = LatLon(
                    (edge_a.lat + edge_b.lat) / 2,
                    (edge_a.lon + edge_b.lon) / 2,
                )
                project = _local_projection(origin)
                gap_poly = _gap_rectangle(edge_a, edge_b, a, b, project)
                candidates.append(SiteCandidate(
                    boundary_local_cm=gap_poly,
                    frontage_edge=(gap_poly[0], gap_poly[1]),  # heuristic: first edge
                    neighbor_a_height_cm=(a.levels * 300) if a.levels else None,
                    neighbor_b_height_cm=(b.levels * 300) if b.levels else None,
                    origin_latlon=origin,
                ))
    return candidates


def _closest_approach(poly_a: list[LatLon], poly_b: list[LatLon]):
    """Closest pair of points between two footprints, in meters (haversine-ish flat approx)."""
    best = (float("inf"), None, None)
    for pa in poly_a:
        for pb in poly_b:
            d = _haversine_m(pa, pb)
            if d < best[0]:
                best = (d, pa, pb)
    return best


def _haversine_m(a: LatLon, b: LatLon) -> float:
    r = 6_371_000
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dphi = math.radians(b.lat - a.lat)
    dlambda = math.radians(b.lon - a.lon)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _gap_rectangle(edge_a: LatLon, edge_b: LatLon, building_a: Building,
                    building_b: Building, project) -> list[tuple[float, float]]:
    """
    Rough rectangular gap boundary between the two closest points.
    Placeholder geometry -- good enough to test the pipeline end to
    end, not a substitute for tracing the real plot boundary by hand.
    """
    ax, ay = project(edge_a)
    bx, by = project(edge_b)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy)
    if length == 0:
        return []
    nx, ny = -dy / length, dx / length  # perpendicular, depth direction
    depth_cm = 1000  # 10m placeholder depth into the site
    return [
        (ax, ay), (bx, by),
        (bx + nx * depth_cm, by + ny * depth_cm),
        (ax + nx * depth_cm, ay + ny * depth_cm),
    ]


if __name__ == "__main__":
    # Example: Evelyn Street / Deptford, matching Adela's established
    # site interest. Small bounding box -- adjust as needed.
    DEPTFORD_BBOX = (51.4855, -0.0380, 51.4895, -0.0320)  # south, west, north, east

    print("Fetching OSM data for Evelyn Street, Deptford...")
    data = fetch_osm_data(DEPTFORD_BBOX)
    buildings = parse_buildings(data)
    print(f"Found {len(buildings)} building footprints.")

    candidates = find_gap_candidates(buildings)
    print(f"Found {len(candidates)} gap candidates between {4}-{25}m wide.")
    for i, c in enumerate(candidates[:5]):
        print(f"  candidate {i}: origin {c.origin_latlon}, "
              f"neighbor heights: {c.neighbor_a_height_cm}cm / {c.neighbor_b_height_cm}cm")
