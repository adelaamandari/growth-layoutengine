# LinX Growth Engine — Project Summary

Context for whoever (human or Claude) picks this up next. This covers everything
decided so far, so it doesn't need to be re-explained.

## Core geometric logic (the timber joinery system)

Rooms are not abstract graph nodes — a room is the physical space enclosed by
built wall/beam **components**, matching the mortise-tenon timber joinery in
Adela's renders.

- **Components**: N (node/corner), SA, SB, SC (edges). A full span is a
  symmetric, mirrored sequence: **N + SA + SB + SB + SC + SB + SB + SA + N**
  (doubled SB flanking the centre SC — matches paired timber bracing members
  visible in her renders).
- **Circulation** has a fixed half-span of **1700cm** (this is architect-set,
  independent of any catalog ratio, never derived).
- **Room component sizes** (N/SA/SB/SC) scale proportionally off the same
  3400cm module (2× circulation half-span) using the original ratios
  50:80:100:80, via an exact scale factor `k`:
  - `k = 3400 / (2×50 + 2×80 + 4×100 + 80) = 3400/740 ≈ 4.595`
  - This is kept **unrounded** in formulas — rounding only happens at a
    separate `fabrication_length_cm()` step right before real-world export,
    never baked into the constants themselves. Baking rounding into constants
    lets closure error compound silently across every span in a building.
- Different rooms get different real sizes (not a uniform grid) by **locally
  rescaling the same component sequence per wall** to that wall's actual
  target length — same `k`-derivation, just computed per-wall instead of
  globally.
- A **mirror pair** is the fundamental structural unit: a component and its
  mirror form a portal frame. `shared_walls` entries (e.g.
  `("Shower","Double_Room")`) mean two rooms share ONE physical built wall —
  built once, referenced by both, never duplicated.

Draft reference file: `MANUAL - COMPONENT GEOMETRY RULESET.py` (delivered
earlier, has open questions worth resolving against her actual joinery
drawings — e.g. can SA mirror against SC, what's the real closure tolerance).

## Floor plan growth logic

**Entrance → Corridor → Core → Branching corridors → Rooms**

- **Entrance**: growth seed, a straight 2-bay (3400cm) corridor run to the core.
- **Corridor**: fixed **1700cm total width** throughout — built as a real
  enclosed strip with walls on both long edges (using the component sequence),
  not just a centerline. Rooms attach flush against the corridor's outer wall
  edge, never overlapping it, because their geometry starts exactly at that
  edge.
- **Core**: a defined **1700×1700cm** square, walled like a room, representing
  vertical circulation/structural anchor. Corridors run flush into its edges.
- **Branching**: strictly **orthogonal** (90° turns only — straight, left,
  right from the core). Diagonal branches were tried and rejected — they
  caused overlapping reserved zones near the core that made room placement
  fail more often, and aren't architecturally sound anyway (corridors turn at
  right angles).
- **Overlap checking**: proper polygon collision via **Separating Axis
  Theorem (SAT)**, tolerant of flush-touching edges within a small epsilon
  (1cm). This tolerance is critical — without it, any two components meant to
  share a wall (which is most of this system) register as a false-positive
  collision, since a shared boundary line has zero separation. This was a
  real bug hit and fixed during development (rooms silently failed to place
  for a while because of it).
- **No site boundary currently** — removed by request, growth is unconstrained
  in extent. Reintroducing one is a `point_in_polygon` check already present
  in `geometry.py` but not currently wired into `growth.py`.
- **Adjacency matrix**: only `SL-SK = 2.0` (SL preferentially follows an SK)
  is currently wired in as a real rule. The rest of `ADJACENCY_MATRIX.py`
  (GR/G avoiding residential, MH near entrance, ER-GA, etc.) is NOT yet
  implemented — this was a deliberate proof-of-concept scope cut, not an
  oversight.
- **Program is currently a fixed ordered list** (e.g.
  `["Studio_A","1Bed_B","SK","2Bed_A","SL","3Bed_A"]`), not randomly
  generated — guarantees exact counts rather than leaving it to chance.

## Real unit dimension catalog

Original approach used a uniform 3400×3400cm placeholder per unit — replaced
with **real bounding-box + per-room data exported from Rhino**.

**Export pipeline**: `export_unit_wall_infills.py` runs inside Rhino
(rhinoscriptsyntax), exports every named object's bounding box to JSON. Two
things matter for data quality:
1. Objects must be **named per room/component** in Rhino (Shower,
   Double_Room, Storage, etc.) — unnamed objects fall back to the layer name
   and can't be attributed to a specific room. Layers stay organized by unit
   TYPE (Studio_A, 1Bed_A, etc.) — do NOT subdivide layers further by room
   function, that doesn't scale. Naming is per-object, not per-layer.
2. Rhino 8 changed `rs.UnitScale()` to require a `Rhino.UnitSystem` enum
   instead of a string — the export script handles both old and new Rhino
   versions with a try/except fallback.

**Data status: all 10 unit types now have complete, real per-room geometry,
no known gaps.** Studio_A, Studio_B, 1Bed_A, 1Bed_B, 2Bed_A, 2Bed_B, 3Bed_A,
3Bed_B, 4Bed_A, 4Bed_B — every catalog entry loads real room boxes from
`growth_engine/unit_exports/`. All 10 place successfully together in a
single floor plan (verified).

Larger units (3Bed, 4Bed) introduced a new room type not seen in the smaller
units: **Balcony** — no special handling needed, it's just another named
`RoomComponent`, works generically like any other room.

`load_unit_from_export()` filters out any room group with near-zero height
(<1cm) rather than emitting a degenerate massing box — this caught a real
data issue in an earlier `4Bed_B` export (its `Entrance` was a single flat/
zero-height object, likely a stray marker, not real geometry). That's since
been fixed at the source with a proper re-export; `4Bed_B` now has a normal
full-height `Entrance` room like every other unit. The filter itself stays
in the code as a safety net for any future exports with the same issue.

**Duplex units** (3Bed/4Bed, height_z=6m = 2 floors): confirmed via reference
render to be **single-entry maisonettes with a private internal stair**, not
double-loaded corridor access on both floors. This means:
- Footprint attachment to the corridor is IDENTICAL to single-floor units —
  no special-case logic needed in `growth.py`.
- Each room's real `z_min` (floor level within the unit) is tracked in
  `RoomComponent`, so ground-floor rooms start at z=0 and upper-floor rooms
  automatically stack at z≈300cm when real data exists, rather than
  collapsing to ground level.
- 3Bed_A's real export confirmed this: `Stairs` component is a real
  4.24m×1.02m run from z=0.27 to z=4.46m; `Foyer` is a full-height (0-6m)
  double-height entry hall enclosing the stair; `Void` is a separate
  double-height opening over the living room upper level; `LDK` correctly
  dropped from a wrongly-inflated 4.46m to a real 3.2m once Stairs objects
  were properly separated out and named.

## Module structure (`growth_engine/`)

- **`geometry.py`** — `Point` class, vector math, SAT polygon overlap test
  (with the flush-touching epsilon fix), `point_in_polygon` (ready but
  unused since boundary was removed).
- **`components.py`** — the N-SA-SB-SB-SC-SB-SB-SA-N sequence, `walk_wall()`
  rescales it per-wall to any real length exactly.
- **`catalog.py`** — `UnitType` and `RoomComponent` dataclasses,
  `load_unit_from_export()` parses Rhino JSON into real room geometry,
  `UNIT_CATALOG` auto-loads bundled exports from `unit_exports/` at import
  time, falls back to placeholder bounding-box data for unit types without
  real exports yet.
- **`growth.py`** — `generate_floorplan(program, seed)` runs the full
  entrance→corridor→core→branch→room growth, returns a `FloorPlan` with
  `elements` (corridor/core/unit/communal `PlacedElement`s).
- **`massing.py`** — `generate_massing()` extrudes each placed element into
  one box (coarse). `generate_room_massing()` extrudes real per-room
  geometry when available (uses `RoomComponent.z_min` for correct floor
  stacking), falls back to one box per unit otherwise.
- **`unit_exports/`** — bundled real JSON exports, auto-loaded by
  `catalog.py`. Drop new exports here.
- **`__init__.py`** — exposes everything needed:
  `generate_floorplan`, `generate_massing`, `generate_room_massing`,
  `get_unit`, `UNIT_CATALOG`, `Point`, `polygons_overlap`, etc.

## Usage

```python
from growth_engine import generate_floorplan, generate_room_massing

plan = generate_floorplan(
    program=["Studio_A", "1Bed_B", "SK", "2Bed_A", "SL", "3Bed_A"],
    seed=42,
)
blocks = generate_room_massing(plan)  # real rooms where available, else 1 box/unit
```

No Rhino/Grasshopper dependency — pure Python, standard library only
(`dataclasses`, `json`, `pathlib`, `random`, `math`). Deliberately kept this
way so it's testable in Claude Code without Rhino running; a GHPython adapter
layer to feed this into Grasshopper is a planned separate step.

## Known gaps / honest limitations (not yet solved)

- **Adjacency matrix** is barely wired in (one rule: `SL-SK=2.0`). The rest
  of `ADJACENCY_MATRIX.py` needs real implementation, not just a proof of
  concept.
- **No site boundary** — growth is currently unconstrained. `point_in_polygon`
  exists in `geometry.py` but isn't called from `growth.py`.
- **Overlap resolution is blunt**: when a room doesn't fit, it shrinks
  proportionally (×0.68 per retry, up to 7 attempts) rather than trying
  alternate positions first. Works, but not elegant — a real solver might
  reposition before resorting to shrinking a room out of proportion.
- **Branch count is hardcoded to 3** (straight/left/right) — a real system
  might vary branch count based on program size or site geometry.
- **Only one program list per run** — no automatic program generation from
  a target unit mix or area budget; you hand it an explicit ordered list.
- **No file export yet** (OBJ, Rhino geometry, etc.) — deliberately deferred
  until the growth logic itself is settled, per explicit request.
- **Communal room interiors** (SK, SL) are single flexible boxes, not
  subdivided — correct, since the communal catalog doesn't define
  sub-spaces for them, just noting it's asymmetric with residential
  treatment.
