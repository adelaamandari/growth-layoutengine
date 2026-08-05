"""
schemas.py
Request/response models for the growth engine API.

All geometry crosses the wire in CENTIMETRES, matching the engine's
internal units. The frontend converts for display; nothing converts on
the way out, so there is exactly one place a unit error can be
introduced (and see growth.py for what happened last time there were
two).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# Keys the engine treats as real residential units; anything else in a
# program is built as a flexible communal room.
RESIDENTIAL = (
    "Studio_A", "Studio_B", "1Bed_A", "1Bed_B", "2Bed_A",
    "2Bed_B", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
)

DEFAULT_PROGRAM = [
    "Studio_A", "Studio_B", "1Bed_A", "1Bed_B", "SK", "2Bed_A",
    "2Bed_B", "SL", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
]


class PlanRequest(BaseModel):
    program: list[str] = Field(default_factory=lambda: list(DEFAULT_PROGRAM))
    seed: int | None = 42
    per_room: bool = True
    # /api/frame only: place the full 240x240 woven capital at every
    # junction. Off by default because it is wider than the spacing of
    # most nodes -- see growth_engine.frame.
    joint_blocks: bool = False
    # /api/frame only: vertical pitch of the beam courses filling each
    # wall. None means one course per storey, i.e. the ceiling beam
    # alone -- the frame as the Frame view has always drawn it. The
    # Build view asks for a finer pitch to fill the massing envelope.
    course_cm: float | None = None


class RoomOut(BaseModel):
    name: str
    poly: list[list[float]]
    z_min: float
    height_cm: float


class SegmentOut(BaseModel):
    c: str                # "N" | "SA" | "SB" | "SC"
    p: list[float]        # [x1, y1, x2, y2]


class WallOut(BaseModel):
    """One PHYSICAL wall, built once. A wall on the boundary between two
    elements is referenced by both but appears here a single time."""
    id: int
    owners: list[int]              # indices into `elements`
    owner_labels: list[str]
    shared: bool
    length_cm: float
    # Which storey it stands on. Walls resolve per level, so a wall
    # above another is a different wall, not the same one seen twice.
    level: int
    segments: list[SegmentOut]


class ElementOut(BaseModel):
    kind: str             # "corridor" | "core" | "unit" | "communal"
    label: str
    height_cm: float
    corners: list[list[float]]
    wall_ids: list[int]   # into PlanResponse.walls
    rooms: list[RoomOut]
    # Storey index, 0 = ground, and the height of its floor slab. A
    # duplex is listed once, at its lower level, and is 600cm tall.
    level: int = 0
    z0: float = 0.0


class SharedSegment(BaseModel):
    """One stretch of wall that two elements both build. See
    growth_engine.diagnostics for why this is worth reporting."""
    a: str
    b: str
    length_cm: float
    p: list[float]        # [x1, y1, x2, y2]


class PlanResponse(BaseModel):
    elements: list[ElementOut]
    walls: list[WallOut]
    shared_segments: list[SharedSegment]
    # Report from diagnostics.verify_walls -- proves the wall set really
    # is deduplicated rather than asking the client to trust it.
    wall_check: dict
    entrance: list[float]
    core_position: list[float]
    unit_counts: dict[str, int]
    missing: list[str]
    # Keys the engine built as flexible communal rooms because it did not
    # recognise them. `suspect` is the subset that looks like a misspelt
    # unit type -- see _classify_program in main.py.
    communal: list[str]
    suspect: list[str]
    extent_cm: list[float]
    # How many storeys the program needed. The plan view filters on it.
    level_count: int = 1
    stats: dict[str, float]


class BlockOut(BaseModel):
    kind: str
    label: str
    base_corners: list[list[float]]
    z0: float
    z1: float
    element_index: int
    # Where this block's element sits in the growth sequence -- entrance
    # -> corridor -> core -> branch corridors -> rooms. Blocks sharing a
    # step grow together, so a unit's rooms rise as one unit. See
    # growth._assign_growth_steps for why this is not element_index.
    growth_step: int


class MassingResponse(BaseModel):
    blocks: list[BlockOut]
    summary: dict[str, dict]
    # Number of distinct growth steps, so a client can size a timeline
    # without scanning every block.
    growth_steps: int


class FrameMemberOut(BaseModel):
    """One timber member. Centre `c` and size `s` are packed as arrays
    rather than named fields because a frame runs to a few thousand
    members and the field names would dominate the payload."""
    kind: str             # "post" | "beam"
    component: str        # "N" | "SA" | "SB" | "SC"
    c: list[float]        # centre [x, y, z], cm
    s: list[float]        # size [length, width, depth], cm
    angle: float          # radians about the vertical axis
    growth_step: int
    grow_sign: int


class FrameNodeOut(BaseModel):
    id: int
    x: float
    y: float
    height_cm: float
    wall_count: int
    # True where 3+ walls meet -- a T or a cross, the splayed capital.
    is_junction: bool
    depth: int            # BFS distance from the entrance node


class FrameResponse(BaseModel):
    members: list[FrameMemberOut]
    nodes: list[FrameNodeOut]
    # Growth here is TOPOLOGICAL, not program order: posts rise at BFS
    # depth d on step 2d, beams reach out from them on step 2d+1.
    growth_steps: int
    step_labels: list[str]
    summary: dict


class RoomInfo(BaseModel):
    name: str
    width_cm: float
    depth_cm: float
    height_cm: float
    z_min: float
    area_m2: float


class UnitInfo(BaseModel):
    name: str
    width_cm: float
    depth_cm: float
    height_cm: float
    floors: int
    object_count: int
    has_real_rooms: bool
    footprint_area_m2: float
    rooms: list[RoomInfo]


class CatalogResponse(BaseModel):
    units: list[UnitInfo]
    communal_keys: list[str]
    residential_keys: list[str]
    corridor_width_cm: float
    core_size_cm: float
