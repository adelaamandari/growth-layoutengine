"""
growth_engine
Pure Python generative layout engine: entrance -> corridor -> core ->
branching corridors -> real-dimension residential units + flexible
shared spaces (lobby, gym, library, workspace, shared kitchen/living)
and outdoor ground (garden, playground), with a massing (3D extrusion)
step on top.

No Rhino/Grasshopper dependency. Intended usage from Claude Code:

    from growth_engine import generate_floorplan, generate_massing

    plan = generate_floorplan(
        program=["Studio_A", "1Bed_B", "SK", "2Bed_A", "SL", "3Bed_A"],
        seed=42,
    )
    blocks = generate_massing(plan)

Geometry export exists: plan_to_obj/save_obj (OBJ, metres) in export.py,
and render_svg/save_svg plus plan_to_dict in preview.py. What is still
missing is a fabrication-length step -- OBJ writes full-precision floats,
which is not the same thing as a real-world cut length.
"""

from .geometry import Point, polygons_overlap, point_in_polygon
from .catalog import UNIT_CATALOG, UnitType, RoomComponent, get_unit, load_catalog_from_dir, load_unit_from_export
from .shared_spaces import SHARED_CATALOG, SharedSpace, INDOOR_KEYS, OUTDOOR_KEYS, get_shared, is_outdoor
from .growth import generate_floorplan, FloorPlan, PlacedElement, builds_walls, CORRIDOR_WIDTH_CM, CORE_SIZE_CM
from .walls import Wall, resolve_walls, wall_summary
from .massing import generate_massing, generate_room_massing, massing_summary, MassingBlock
from .frame import build_frame, frame_summary, Frame, FrameMember, FrameNode
from .export import plan_to_obj, blocks_to_obj, save_obj

__all__ = [
    "build_frame", "frame_summary", "Frame", "FrameMember", "FrameNode",
    "plan_to_obj", "blocks_to_obj", "save_obj",
    "Point", "polygons_overlap", "point_in_polygon",
    "UNIT_CATALOG", "UnitType", "RoomComponent", "get_unit", "load_catalog_from_dir", "load_unit_from_export",
    "SHARED_CATALOG", "SharedSpace", "INDOOR_KEYS", "OUTDOOR_KEYS", "get_shared", "is_outdoor",
    "generate_floorplan", "FloorPlan", "PlacedElement", "builds_walls",
    "Wall", "resolve_walls", "wall_summary",
    "CORRIDOR_WIDTH_CM", "CORE_SIZE_CM",
    "generate_massing", "generate_room_massing", "massing_summary", "MassingBlock",
]
