"""
solar.py
How much sun each facade panel actually receives.

This is a real calculation, not a gradient painted on by orientation. For
each panel it walks a year of sun positions, and for each one that is
above the horizon and in front of the panel it adds the beam that gets
through -- after testing whether the building itself is in the way.

WHAT IS MODELLED

  sun position   standard solar geometry from latitude, day of year and
                 solar hour: declination, hour angle, altitude, azimuth.
  direct beam    clear-sky DNI by the usual atmospheric attenuation,
                 1367 * 0.7 ^ (AM ^ 0.678), with air mass AM = 1/sin(alt).
                 Projected onto the panel by the cosine of the incidence
                 angle, and dropped entirely when the sun is behind it.
  diffuse        isotropic sky, seen by a vertical surface through a view
                 factor of 0.5. Small, but it is what keeps a north
                 elevation from reading as a flat zero, which would be
                 wrong -- a north window is dimmer, not dark.
  self-shading   a ray from the panel to the sun, tested against the
                 building's own massing boxes. This is the part that makes
                 the map worth looking at: it is why a low panel in the
                 crook of two wings reads cold while the one above it,
                 same orientation, reads warm.

WHAT IS NOT MODELLED, AND SHOULD BE SAID PLAINLY

  - No neighbouring buildings or terrain. site/analysis.py knows about
    flanking neighbours; that is not wired in here yet.
  - No panel-on-panel shading. A balcony shades the window beneath it and
    this does not see that, because the panels are rotated boxes and the
    shading test works on axis-aligned ones. It means balconied
    elevations read slightly warm.
  - No weather. This is clear-sky irradiation, so it is an upper bound
    and a comparison between panels, not a prediction of yield.
  - No reflection off the ground or off neighbouring surfaces.

So the number is comparable panel-to-panel, which is what a heatmap is
for. It is not a certified daylight study, and the same caveat that
site/analysis.py carries applies here.

ORIENTATION CONVENTION
Engine +y is NORTH and engine +x is EAST, matching site/osm_site_finder,
which builds its local frame from lat/lon that way. Azimuth is measured
from north, clockwise, so due south is 180 degrees.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .massing import generate_massing

SOLAR_CONSTANT = 1367.0        # W/m2 at the top of the atmosphere

# One sample per month at midday-ish resolution. 12 months x hourly is
# 204 samples, of which roughly half are above the horizon -- enough to
# separate east from west (a single equinox day cannot) without making
# the endpoint slow. Samples are equally weighted, so each stands for
# 365/12 days of one hour.
SAMPLE_DAYS = tuple(15 + 30 * m for m in range(12))
SAMPLE_HOURS = tuple(range(4, 21))
_HOURS_PER_SAMPLE = 365.0 / len(SAMPLE_DAYS)

# Vertical surface, so it sees half the sky dome.
_SKY_VIEW_VERTICAL = 0.5
# Fraction of the extraterrestrial beam that arrives as diffuse on the
# horizontal under a clear sky. A blunt constant, deliberately: anything
# more elaborate would imply a weather model this does not have.
_DIFFUSE_FRACTION = 0.12

# Start the shadow ray this far out from the wall so it does not
# immediately hit the element the panel is cladding.
_RAY_OFFSET_CM = 60.0

# The real site's latitude, not a placeholder. Deptford Church Street,
# London SE8 -- see site/location.py. Imported lazily-ish at module level
# because solar has no other reason to know about the site, and a project
# that moves site should only have to change it in one place.
from .site.location import DEFAULT_SITE

DEFAULT_LATITUDE = DEFAULT_SITE.lat


@dataclass(frozen=True)
class SunSample:
    altitude: float   # radians above the horizon
    azimuth: float    # radians from north, clockwise
    dni: float        # direct normal irradiance, W/m2
    dhi: float        # diffuse horizontal irradiance, W/m2


def sun_samples(latitude_deg: float) -> list[SunSample]:
    """Every above-horizon sun position in the sampling year."""
    lat = math.radians(latitude_deg)
    out: list[SunSample] = []
    for day in SAMPLE_DAYS:
        decl = math.radians(23.45) * math.sin(math.radians(360 * (284 + day) / 365))
        for hour in SAMPLE_HOURS:
            ha = math.radians(15.0 * (hour - 12))
            sin_alt = (math.sin(lat) * math.sin(decl)
                       + math.cos(lat) * math.cos(decl) * math.cos(ha))
            sin_alt = max(-1.0, min(1.0, sin_alt))
            alt = math.asin(sin_alt)
            if alt <= math.radians(3.0):
                # Below (or barely above) the horizon: the air-mass model
                # blows up here and the energy is negligible anyway.
                continue

            cos_alt = math.cos(alt)
            cos_az = ((math.sin(decl) * math.cos(lat)
                       - math.cos(decl) * math.sin(lat) * math.cos(ha))
                      / cos_alt) if cos_alt > 1e-9 else 1.0
            cos_az = max(-1.0, min(1.0, cos_az))
            az = math.acos(cos_az)
            if ha > 0:      # afternoon -- sun is west of south
                az = 2 * math.pi - az

            air_mass = 1.0 / sin_alt
            dni = SOLAR_CONSTANT * (0.7 ** (air_mass ** 0.678))
            dhi = SOLAR_CONSTANT * _DIFFUSE_FRACTION * sin_alt
            out.append(SunSample(alt, az, dni, dhi))
    return out


def _sun_vector(s: SunSample) -> tuple[float, float, float]:
    """Unit vector toward the sun in engine axes: +x east, +y north, +z up."""
    ca = math.cos(s.altitude)
    return (ca * math.sin(s.azimuth), ca * math.cos(s.azimuth), math.sin(s.altitude))


def _boxes(plan) -> list[tuple[float, float, float, float, float, float]]:
    """The building as axis-aligned boxes, for the shadow test.

    Element-level massing, not per-room: a room box is inside its unit
    and cannot shade anything the unit does not already shade, so the
    finer set is four times the ray tests for the same answer.
    """
    out = []
    for b in generate_massing(plan):
        xs = [c.x for c in b.base_corners]
        ys = [c.y for c in b.base_corners]
        out.append((min(xs), min(ys), b.z0, max(xs), max(ys), b.z1))
    return out


def _blocked(ox: float, oy: float, oz: float,
             dx: float, dy: float, dz: float, boxes) -> bool:
    """Does anything stand between this point and the sun?

    Slab method, with the ray treated as a half-line: only hits in FRONT
    of the panel count, or the building behind it would shade it from a
    sun it can see perfectly well.
    """
    for x0, y0, z0, x1, y1, z1 in boxes:
        tmin, tmax = 0.0, float("inf")
        for o, d, lo, hi in ((ox, dx, x0, x1), (oy, dy, y0, y1), (oz, dz, z0, z1)):
            if abs(d) < 1e-9:
                if o < lo or o > hi:
                    tmin = float("inf")
                    break
            else:
                inv = 1.0 / d
                t1, t2 = (lo - o) * inv, (hi - o) * inv
                if t1 > t2:
                    t1, t2 = t2, t1
                tmin = max(tmin, t1)
                tmax = min(tmax, t2)
                if tmin > tmax:
                    tmin = float("inf")
                    break
        if tmin != float("inf") and tmin <= tmax:
            return True
    return False


def apply_solar(facade, plan, latitude_deg: float = DEFAULT_LATITUDE) -> dict:
    """
    Fill in `sun_kwh` and `sun_norm` on every panel, and return a summary.

    kWh/m2/yr of clear-sky irradiation on the panel's plane, and that
    value rescaled 0..1 across this building so the heatmap uses its full
    range rather than a slice of an absolute scale.
    """
    if not facade.panels:
        return {"latitude": latitude_deg, "samples": 0, "panels": 0}

    samples = sun_samples(latitude_deg)
    boxes = _boxes(plan)
    vectors = [(_sun_vector(s), s) for s in samples]

    shaded_total = 0
    lit_total = 0

    for p in facade.panels:
        # Measured at mid-storey on the panel's own face, stood off the
        # wall so the ray does not start inside the element behind it.
        ox = p.cx + p.nx * _RAY_OFFSET_CM
        oy = p.cy + p.ny * _RAY_OFFSET_CM
        oz = p.z0 + 150.0

        beam = 0.0
        diffuse = 0.0
        for (dx, dy, dz), s in vectors:
            # Diffuse arrives whatever the sun is doing.
            diffuse += s.dhi * _SKY_VIEW_VERTICAL * _HOURS_PER_SAMPLE

            cos_inc = dx * p.nx + dy * p.ny   # panel is vertical, so no dz term
            if cos_inc <= 0:
                continue                       # sun is behind the panel
            if _blocked(ox, oy, oz, dx, dy, dz, boxes):
                shaded_total += 1
                continue
            lit_total += 1
            beam += s.dni * cos_inc * _HOURS_PER_SAMPLE

        p.sun_kwh = round((beam + diffuse) / 1000.0, 1)

    values = [p.sun_kwh for p in facade.panels]
    lo, hi = min(values), max(values)
    span = hi - lo
    for p in facade.panels:
        p.sun_norm = round((p.sun_kwh - lo) / span, 4) if span > 1e-9 else 0.5

    return {
        "latitude": latitude_deg,
        "samples": len(samples),
        "panels": len(facade.panels),
        "min_kwh": round(lo, 1),
        "max_kwh": round(hi, 1),
        "mean_kwh": round(sum(values) / len(values), 1),
        # How often the building shaded itself, over every panel-sun pair
        # where the sun was in front of the panel at all.
        "self_shaded_pct": (round(100 * shaded_total / (shaded_total + lit_total), 1)
                            if (shaded_total + lit_total) else 0.0),
    }
