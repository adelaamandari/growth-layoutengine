"""
frame.py
The timber FRAME: the real surveyed components, placed on a plan and
ordered by parasitic growth outward from the entrance.

WHY THIS IS NOT THE MASSING VIEW
massing.py answers "what volume does this building occupy". This module
answers "what gets built" -- columns standing at the structural nodes,
beams spanning between them. Every node is an N from walls.py and every
beam runs along an SA/SB/SC member from the same component walk, so N
being where members meet is why N is where a column goes.

THE GEOMETRY IS SURVEYED, NOT INVENTED
Sections, the column, and the connector all come from Adela's
components.glb via glb_import.py -- 10x10 posts on 30cm centres in a
40x40 bundle, 20x10 beam sections, a 60x60x10 connector plate. An
earlier version of this file guessed those numbers and got the post
section, the beam section and the bundle spacing all wrong. If the
extracted catalog is missing, _FALLBACK below keeps the view working,
but it is a placeholder and says so.

PARASITIC GROWTH ORDER
The massing view grows in PROGRAM order -- whichever unit was placed
first. This module grows TOPOLOGICALLY: breadth-first across the node
network from the entrance, so the frame colonises itself along real
structural adjacency. Posts and beams alternate:

    step 2d      columns rise at every node at BFS depth d, capped by
                 their connector plate
    step 2d + 1  beams reach out along the walls leaving those nodes

TWO PLACES THE SOURCE AND THE ENGINE DISAGREE
Both are reported rather than papered over, because they are the
evidence for whether the engine's own constants need revisiting.

1. MEMBER LENGTH. The catalog is FIXED: SA=70, SB=80, SC=60 on a 100mm
   grid. components.py instead derives k per wall so the sequence
   stretches to fit any length, which produces members no joinery shop
   could cut twice the same. `length_deviation` in the summary measures
   how far the drawn members land from the nearest catalog length.
2. BAY SIZE. The joint assembly is 240x240, but 24 of the plan's 43
   nodes sit closer than 240cm to a neighbour, so the full woven block
   cannot be placed everywhere without intersecting itself. It is
   therefore off by default and its overlap is counted. The 40x40
   column and 60x60 plate fit at every node with room to spare.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import atan2, hypot

from .glb_import import load_catalog
from .growth import FloorPlan

# Two N nodes within this distance are the same physical node. Wall ends
# meeting at a junction are computed from different elements, so they
# land a hair apart.
NODE_CLUSTER_CM = 25.0

STOREY_CM = 300.0

# Used only if component_exports/components.json is absent. Regenerate
# it with `python -m growth_engine.glb_import <file>.glb`.
_FALLBACK = {
    "catalog": {
        "N": {"length_cm": 60.0, "width_cm": 60.0, "thickness_cm": 10.0},
        "SA": {"length_cm": 70.0, "width_cm": 20.0, "thickness_cm": 10.0},
        "SB": {"length_cm": 80.0, "width_cm": 20.0, "thickness_cm": 10.0},
        "SC": {"length_cm": 60.0, "width_cm": 20.0, "thickness_cm": 10.0},
    },
    "assemblies": {},
}

_DATA = load_catalog() or _FALLBACK
CATALOG: dict[str, dict] = _DATA.get("catalog") or _FALLBACK["catalog"]
ASSEMBLIES: dict[str, dict] = _DATA.get("assemblies") or {}
HAS_REAL_COMPONENTS = bool(ASSEMBLIES)


@dataclass(frozen=True)
class FrameMember:
    """One drawn timber member: an axis-aligned box rotated about the
    vertical axis by `angle`. Centre and size are both in cm."""
    kind: str            # "post" | "beam" | "plate" | "lacing"
    component: str       # catalog name, or the assembly part it came from
    cx: float
    cy: float
    cz: float
    sx: float
    sy: float
    sz: float
    angle: float
    growth_step: int
    node_id: int         # -1 for beams
    # Which end of a beam stays put while it extends: -1 anchors the
    # start end, +1 the far end. Set so a beam grows OUT of the column
    # nearer the seed. Unused for members that rise vertically.
    grow_sign: int = -1


@dataclass(frozen=True)
class FrameNode:
    id: int
    x: float
    y: float
    height_cm: float
    wall_count: int
    axis_count: int
    depth: int

    @property
    def is_junction(self) -> bool:
        """A capital: a T or a cross. Two walls is just an L, the corner
        of one room, not the splayed node in the reference render."""
        return self.wall_count >= 3


@dataclass
class Frame:
    members: list[FrameMember]
    nodes: list[FrameNode]
    growth_steps: int
    step_labels: list[str] = field(default_factory=list)
    length_deviation: dict = field(default_factory=dict)
    joint_overlaps: int = 0


def _key(x: float, y: float) -> tuple[int, int]:
    return (round(x / NODE_CLUSTER_CM), round(y / NODE_CLUSTER_CM))


def _storeys(height_cm: float) -> int:
    return max(1, int(round(height_cm / STOREY_CM)))


def build_frame(plan: FloorPlan, joint_blocks: bool = False) -> Frame:
    """
    Resolve a plan into real components, ordered by parasitic growth.

    Reads only plan.walls -- already deduplicated, so every member here
    is built exactly once -- and plan.elements for heights.

    joint_blocks places the full 240x240 woven capital at every junction.
    Off by default: it is wider than the spacing of most of the plan's
    nodes, so it self-intersects. See the module docstring.
    """
    buckets: dict[tuple[int, int], dict] = {}

    def _touch(x, y, wall_id, height, axis):
        k = _key(x, y)
        b = buckets.setdefault(
            k, {"xs": [], "ys": [], "walls": set(), "axes": set(), "h": 0.0})
        b["xs"].append(x)
        b["ys"].append(y)
        b["walls"].add(wall_id)
        b["axes"].add(axis)
        b["h"] = max(b["h"], height)
        return k

    def _axis_of(wall) -> int:
        """Direction folded to a half-turn in 15-degree buckets, so a
        wall and its reverse are the same axis."""
        ang = atan2(wall.end.y - wall.start.y, wall.end.x - wall.start.x)
        return round((ang % 3.141592653589793) / 0.2617993877991494) % 12

    def _wall_height(wall) -> float:
        hs = [plan.elements[i].height_cm for i in wall.owners]
        return max(hs) if hs else STOREY_CM

    wall_ends = []
    for wall in plan.walls:
        h = _wall_height(wall)
        ax = _axis_of(wall)
        ka = _touch(wall.start.x, wall.start.y, wall.id, h, ax)
        kb = _touch(wall.end.x, wall.end.y, wall.id, h, ax)
        wall_ends.append((wall, ka, kb, h))

    keys = sorted(buckets)
    index = {k: i for i, k in enumerate(keys)}

    # --- parasitic spread: BFS from the node nearest the entrance ----
    adj: dict[int, set[int]] = {i: set() for i in range(len(keys))}
    for _wall, ka, kb, _h in wall_ends:
        a, b = index[ka], index[kb]
        if a != b:
            adj[a].add(b)
            adj[b].add(a)

    centres = [
        (sum(buckets[k]["xs"]) / len(buckets[k]["xs"]),
         sum(buckets[k]["ys"]) / len(buckets[k]["ys"]))
        for k in keys
    ]
    seed = min(range(len(keys)),
               key=lambda i: hypot(centres[i][0] - plan.entrance.x,
                                   centres[i][1] - plan.entrance.y)) if keys else 0

    depth = {seed: 0} if keys else {}
    queue = deque([seed] if keys else [])
    while queue:
        cur = queue.popleft()
        for nxt in sorted(adj[cur]):
            if nxt not in depth:
                depth[nxt] = depth[cur] + 1
                queue.append(nxt)
    if depth:
        tail = max(depth.values()) + 1
        for i in range(len(keys)):
            depth.setdefault(i, tail)

    nodes = [
        FrameNode(id=i, x=centres[i][0], y=centres[i][1],
                  height_cm=buckets[keys[i]]["h"] or STOREY_CM,
                  wall_count=len(buckets[keys[i]]["walls"]),
                  axis_count=len(buckets[keys[i]]["axes"]),
                  depth=depth.get(i, 0))
        for i in range(len(keys))
    ]

    members: list[FrameMember] = []
    column = ASSEMBLIES.get("column")
    joint = ASSEMBLIES.get("joint")
    # The connector plate caps each column. In the source it sits at
    # z 290..300, i.e. the top 10cm of a storey, so it is rebased here
    # against the storey line rather than trusting an absolute z.
    plate = None
    if joint:
        plate = next((m for m in joint["members"] if m["name"] == "N"), None)
    lacing = [m for m in (joint["members"] if joint else []) if m["name"] != "N"]

    # --- columns + connector: step 2d --------------------------------
    for node in nodes:
        step = node.depth * 2
        for s in range(_storeys(node.height_cm)):
            base = s * STOREY_CM
            if column:
                for m in column["members"]:
                    members.append(FrameMember(
                        kind="post", component="Column",
                        cx=node.x + m["c"][0], cy=node.y + m["c"][1],
                        cz=base + m["c"][2],
                        sx=m["s"][0], sy=m["s"][1], sz=m["s"][2],
                        angle=0.0, growth_step=step, node_id=node.id,
                    ))
            else:
                sec = CATALOG["N"]["thickness_cm"]
                members.append(FrameMember(
                    kind="post", component="Column",
                    cx=node.x, cy=node.y, cz=base + STOREY_CM / 2,
                    sx=sec * 4, sy=sec * 4, sz=STOREY_CM,
                    angle=0.0, growth_step=step, node_id=node.id,
                ))
            if plate:
                members.append(FrameMember(
                    kind="plate", component="N",
                    cx=node.x + plate["c"][0], cy=node.y + plate["c"][1],
                    # Source z is absolute against a 300 storey (the
                    # plate spans 290..300), so the storey base is all
                    # that needs adding.
                    cz=base + plate["c"][2],
                    sx=plate["s"][0], sy=plate["s"][1], sz=plate["s"][2],
                    angle=0.0, growth_step=step, node_id=node.id,
                ))

    # --- the woven capital, only where asked for ---------------------
    joint_overlaps = 0
    if joint:
        span = max(joint["footprint_cm"])
        for node in nodes:
            if not node.is_junction:
                continue
            near = min((hypot(node.x - o.x, node.y - o.y)
                        for o in nodes if o.id != node.id), default=1e9)
            if near < span:
                joint_overlaps += 1
            if not joint_blocks:
                continue
            step = node.depth * 2
            for s in range(_storeys(node.height_cm)):
                base = s * STOREY_CM
                for m in lacing:
                    members.append(FrameMember(
                        kind="lacing", component=m["name"],
                        cx=node.x + m["c"][0], cy=node.y + m["c"][1],
                        cz=base + m["c"][2],
                        sx=m["s"][0], sy=m["s"][1], sz=m["s"][2],
                        angle=0.0, growth_step=step, node_id=node.id,
                    ))

    # --- beams: step 2d + 1 ------------------------------------------
    # All four Beam A arms sit coplanar at z 290..300 in the source --
    # they interlock by halving, not by vertical offset. An earlier
    # version of this file staggered them, which was invented.
    deviations: list[float] = []
    for wall, ka, kb, h in wall_ends:
        a, b = index[ka], index[kb]
        da, db = depth.get(a, 0), depth.get(b, 0)
        step = min(da, db) * 2 + 1
        grow_sign = -1 if da <= db else 1
        levels = [(s + 1) * STOREY_CM for s in range(_storeys(h))]
        for seg in wall.segments:
            if seg.component == "N":
                continue  # N is the connector plate, drawn with the column
            dx = seg.end.x - seg.start.x
            dy = seg.end.y - seg.start.y
            length = hypot(dx, dy)
            if length < 1:
                continue
            spec = CATALOG.get(seg.component, CATALOG["SB"])
            deviations.append(abs(length - spec["length_cm"]))
            ang = atan2(dy, dx)
            for lv in levels:
                members.append(FrameMember(
                    kind="beam", component=seg.component,
                    cx=(seg.start.x + seg.end.x) / 2,
                    cy=(seg.start.y + seg.end.y) / 2,
                    cz=lv - spec["thickness_cm"] / 2,
                    sx=length, sy=spec["width_cm"], sz=spec["thickness_cm"],
                    angle=ang, growth_step=step, node_id=-1,
                    grow_sign=grow_sign,
                ))

    steps = (max((m.growth_step for m in members), default=-1) + 1)

    labels: list[str] = []
    for s in range(steps):
        at = [m for m in members if m.growth_step == s]
        posts = sum(1 for m in at if m.kind != "beam")
        beams = sum(1 for m in at if m.kind == "beam")
        if posts and not beams:
            n = len({m.node_id for m in at})
            caps = sum(1 for nd in nodes if nd.depth * 2 == s and nd.is_junction)
            labels.append(f"columns · {n} node{'s' if n != 1 else ''}"
                          + (f", {caps} capital" if caps else ""))
        elif beams and not posts:
            labels.append(f"beams · {beams} member{'s' if beams != 1 else ''}")
        elif at:
            labels.append(f"columns + beams · {len(at)} members")
        else:
            labels.append("—")

    dev = {}
    if deviations:
        ordered = sorted(deviations)
        dev = {
            "mean_cm": round(sum(deviations) / len(deviations), 1),
            "median_cm": round(ordered[len(ordered) // 2], 1),
            "max_cm": round(ordered[-1], 1),
            "within_5cm_pct": round(100 * sum(1 for d in deviations if d <= 5) / len(deviations), 1),
            "sample": len(deviations),
        }

    return Frame(members=members, nodes=nodes, growth_steps=steps,
                 step_labels=labels, length_deviation=dev,
                 joint_overlaps=joint_overlaps)


def frame_summary(frame: Frame) -> dict:
    """Counts for a sanity check and for the UI census."""
    by_component: dict[str, int] = {}
    for m in frame.members:
        by_component[m.component] = by_component.get(m.component, 0) + 1
    return {
        "member_count": len(frame.members),
        "post_count": sum(1 for m in frame.members if m.kind == "post"),
        "beam_count": sum(1 for m in frame.members if m.kind == "beam"),
        "plate_count": sum(1 for m in frame.members if m.kind == "plate"),
        "lacing_count": sum(1 for m in frame.members if m.kind == "lacing"),
        "node_count": len(frame.nodes),
        "junction_count": sum(1 for n in frame.nodes if n.is_junction),
        "max_depth": max((n.depth for n in frame.nodes), default=0),
        "by_component": by_component,
        # Provenance, so the UI can say whether it is drawing surveyed
        # geometry or the placeholder.
        "real_components": HAS_REAL_COMPONENTS,
        "source": _DATA.get("source", "fallback"),
        "catalog": CATALOG,
        # How far the drawn members land from the nearest catalog length,
        # i.e. the cost of components.py rescaling instead of using fixed
        # members. See the module docstring.
        "length_deviation": frame.length_deviation,
        "joint_overlaps": frame.joint_overlaps,
    }
