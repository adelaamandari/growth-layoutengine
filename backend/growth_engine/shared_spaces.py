"""
shared_spaces.py
The flexible half of the program: shared INDOOR rooms (lobby, gym,
library, workspace, shared kitchen, shared living) and OUTDOOR ground
areas (garden, playground).

WHY THESE ARE NOT UnitTypes
A residential unit is a surveyed object. catalog.py reads its real
footprint and its real rooms straight out of a Rhino export, and
growth.py places that footprint unchanged -- the engine is not allowed
an opinion about how big a 2Bed_A is. A shared space has no survey: its
size is a brief, not a measurement. So each one is defined here as a
RANGE the generator picks inside. That is precisely what "flexible"
means in this engine, and it is the only thing the seed varies.

INDOOR vs OUTDOOR
`kind` is the PlacedElement kind these produce, and the difference is
structural rather than cosmetic:

    communal   a room. Enclosed by built walls, a storey tall, framed in
               timber, counts toward floor area.
    outdoor    a piece of ground. No walls, no ceiling, no frame, no
               floor area -- walls.py, frame.py and the area stats all
               skip it, via growth.builds_walls.

An outdoor area is still placed by the same growth logic as everything
else, flush against a corridor edge, because it has to be reachable
from the building. It simply does not enclose anything, so nothing is
built on its boundary.

The ranges below are a BRIEF, not survey data -- the same status the old
COMMUNAL_WIDTH_RANGE had, and they are sized against the real unit
catalog for the same reason: a 6m-frontage unit next to a 1.7m corridor
sets the scale everything else has to sit next to. Replace them with
Adela's numbers when the shared-space brief is fixed.

Naming: `frontage_cm` runs ALONG the corridor, `depth_cm` runs away from
it. The old constants called these the other way round, which is why
COMMUNAL_DEPTH_CM was the frontage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SharedSpace:
    """One flexible program entry: a size range, not a size."""
    name: str
    kind: str                          # "communal" | "outdoor"
    frontage_cm: tuple[float, float]   # along the corridor
    depth_cm: tuple[float, float]      # away from the corridor
    description: str

    @property
    def is_outdoor(self) -> bool:
        return self.kind == "outdoor"

    @property
    def min_area_m2(self) -> float:
        return (self.frontage_cm[0] / 100) * (self.depth_cm[0] / 100)

    @property
    def max_area_m2(self) -> float:
        return (self.frontage_cm[1] / 100) * (self.depth_cm[1] / 100)


_SPACES = (
    # --- shared indoor rooms ----------------------------------------
    SharedSpace(
        "Lobby", "communal", (600.0, 1000.0), (500.0, 800.0),
        "Entrance hall off the arrival corridor — the shared front door.",
    ),
    SharedSpace(
        "Gym", "communal", (800.0, 1200.0), (600.0, 900.0),
        "Exercise room. The largest of the shared rooms, and the one "
        "least willing to be squeezed.",
    ),
    SharedSpace(
        "Library", "communal", (600.0, 1000.0), (500.0, 800.0),
        "Quiet room — reading and study, away from the circulation.",
    ),
    SharedSpace(
        "Workspace", "communal", (600.0, 1100.0), (450.0, 750.0),
        "Shared desks and meeting space for working from home.",
    ),
    SharedSpace(
        "SK", "communal", (500.0, 700.0), (400.0, 700.0),
        "Shared kitchen. Keeps the size the old flexible communal room "
        "had, so existing programs generate as before.",
    ),
    SharedSpace(
        "SL", "communal", (500.0, 800.0), (450.0, 700.0),
        "Shared living room — the informal counterpart to the workspace.",
    ),

    # --- outdoor ground areas ---------------------------------------
    SharedSpace(
        "Garden", "outdoor", (800.0, 1600.0), (600.0, 1200.0),
        "Planted open ground. Reached off the corridor, unroofed, and "
        "not counted as floor area.",
    ),
    SharedSpace(
        "Playground", "outdoor", (700.0, 1200.0), (600.0, 1000.0),
        "Open play area. Same status as the garden — ground, not floor.",
    ),
)

SHARED_CATALOG: dict[str, SharedSpace] = {s.name: s for s in _SPACES}

INDOOR_KEYS: tuple[str, ...] = tuple(s.name for s in _SPACES if not s.is_outdoor)
OUTDOOR_KEYS: tuple[str, ...] = tuple(s.name for s in _SPACES if s.is_outdoor)

# An unrecognised program key still becomes a flexible communal room
# rather than an error -- that behaviour predates this module and is
# deliberate (it is what made SK/SL work before there was a catalog for
# them). The API reports such keys as `suspect` so a typo is visible
# instead of silently building a blank box. Sized as the old
# COMMUNAL_WIDTH_RANGE / COMMUNAL_DEPTH_CM pair, so nothing that relied
# on the fallback changes shape.
FALLBACK_SHARED = SharedSpace(
    "", "communal", (600.0, 600.0), (400.0, 700.0),
    "Unrecognised program key, built as a blank flexible room.",
)


def get_shared(name: str) -> SharedSpace:
    """The spec for a program key, or the blank-room fallback. Never
    raises: growth.py relies on any non-residential key being placeable."""
    spec = SHARED_CATALOG.get(name)
    return spec if spec is not None else FALLBACK_SHARED


def is_outdoor(name: str) -> bool:
    return name in SHARED_CATALOG and SHARED_CATALOG[name].is_outdoor
