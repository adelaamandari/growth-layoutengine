# LinX Growth Engine — Project Summary

Context for whoever (human or Claude) picks this up next. This covers everything
decided so far, so it doesn't need to be re-explained.

*Last revised 2026-07-31. Blockquoted notes mark where this document was
corrected or where a stated intention has since been implemented; the
surrounding text is the original.*

## Core geometric logic (the timber joinery system)

Rooms are not abstract graph nodes — a room is the physical space enclosed by
built wall/beam **components**, matching the mortise-tenon timber joinery in
Adela's renders.

- **Components**: N (node), SA, SB, SC (edges). A full span is a symmetric,
  mirrored sequence: **N + SA + SB + SC + SB + SA + N**, and a full span is
  **360cm**, one structural bay.

  > **Both numbers are surveyed, not chosen.** The Beam A assembly in
  > `components.glb` is 359.99 × 359.99, and one of its arms runs outward from
  > the node centre as SA (10–80), SB (60–140), SC (120–180) — each member
  > lapping the next by exactly 20cm, one member width, reaching 180cm. Mirror
  > that arm and you have the sequence above, node centre to node centre. The
  > nominal lengths agree exactly: **70 + 80 + 60 + 80 + 70 = 360**, so a bay
  > closes on real catalog parts with nothing left over.
  >
  > **Superseded 2026-08-05.** This previously read
  > `N + SA + SB + SB + SC + SB + SB + SA + N` — nine parts, doubled SBs —
  > with the sequence rescaled per wall to whatever length that wall happened
  > to be. That produced members no joinery shop could cut twice the same
  > (median 40cm off the nearest catalog length, only 17% within 5cm).
- **Circulation** has a fixed half-span of **170cm** (this is architect-set,
  independent of any catalog ratio, never derived).

  > **Corrected 2026-07-31.** This said 1700cm, and the code stored 1700 in
  > `CORRIDOR_WIDTH_CM` and `CORE_SIZE_CM` — a 17m-wide corridor and a
  > 17×17m core. The figures were transcribed off the drawings in
  > **millimetres** into fields named `_CM`. Everything sourced from Rhino
  > (unit footprints, the 300/600 storey heights) was always correct cm;
  > only the hand-typed constants were wrong, uniformly by 10×.

- **Room component sizes** are the catalog's own: **SA 70, SB 80, SC 60**, each
  20 wide × 10 thick, with a 60×60×10 connector plate at N. These are read
  straight out of `components.glb` and are no longer derived from a module or
  a ratio — the ratio question is answered by the bay closing exactly.

  > **The old derivation, kept for the record.** Sizes used to be scaled off a
  > 340cm module (2× circulation half-span) with ratios 50:80:100:80 and an
  > exact factor `k = 340/740 ≈ 0.4595`, landing at N≈23, SA≈37, SB≈46,
  > SC≈37cm. The note here used to say those were worth checking against the
  > joinery drawings, and that "if a component spans a whole structural bay
  > rather than a single member, the module is what needs revisiting". That
  > turned out to be exactly right: the bay is 360 and the members are the
  > surveyed lengths.
- **A wall run divides into whole 360cm bays, and only the LAST one adapts.**
  A wall is rarely a whole number of bays, so the run is split into the
  nearest whole number and the final bay takes up the difference — stretched
  or shortened. Every other bay is exactly 360 and its five members are
  exactly the catalog parts. **100% of primary grid beams and 47% of infill
  members now come out at exact catalog length**, against a median 40cm drift
  on every member before.
- **Rounding** still happens nowhere in the constants. There is still no
  `fabrication_length_cm()` anywhere in the codebase, so there is still no
  path from the engine to a real cut length — `export.py` writes metres at
  full float precision, which is not the same thing.
- A **mirror pair** is the fundamental structural unit: a component and its
  mirror form a portal frame. `shared_walls` entries (e.g.
  `("Shower","Double_Room")`) mean two rooms share ONE physical built wall —
  built once, referenced by both, never duplicated.

  > **Implemented 2026-07-31** in `walls.py`. Previously every element walked
  > all four of its own edges, so a unit flush against a corridor built that
  > wall twice — and worse, the two copies didn't share breakpoints, because
  > each side rescaled the sequence to its own length. The members on the two
  > faces of one wall landed in different places.
  >
  > Deduplication is not "drop the second copy": a corridor edge can be 25m
  > long while a unit abuts only 10m of it, so they share a stretch OF a wall
  > rather than a whole wall. Edges are grouped by supporting line, projected
  > to 1D, and cut at every interval endpoint; each stretch becomes one `Wall`
  > owned by whichever elements cover it. `FloorPlan.walls` holds them,
  > `PlacedElement.wall_ids` references them.
  >
  > On the default program this took 550.3m of drawn wall down to **379.0m
  > across 59 walls, 28 of them shared**. A consequence worth confirming
  > against the drawings: cutting a corridor edge where units meet it puts an
  > **N node at each junction**, so a long corridor wall is now several spans
  > rather than one continuous mirrored sequence.

Draft reference file: `MANUAL - COMPONENT GEOMETRY RULESET.py` (delivered
earlier, has open questions worth resolving against her actual joinery
drawings — e.g. can SA mirror against SC, what's the real closure tolerance).
That file is *not* in this repo.

## Floor plan growth logic

**Entrance → Corridor → Core → Branching corridors → Rooms**

- **Entrance**: growth seed, a straight 2-bay (340cm) corridor run to the core.
- **Corridor**: fixed **170cm total width** throughout — built as a real
  enclosed strip with walls on both long edges (using the component sequence),
  not just a centerline. Rooms attach flush against the corridor's outer wall
  edge, never overlapping it, because their geometry starts exactly at that
  edge.
- **Core**: a defined **170×170cm** square, walled like a room, representing
  vertical circulation/structural anchor. Corridors run flush into its edges.

  > **Open question.** 170×170cm is 2.9m² — the consistent ÷10 of the old
  > value, but too small to hold a flight and landing. If the core really is
  > vertical circulation, it needs a real dimension (a single stair core wants
  > roughly 250×500cm). If it is a structural anchor only, 170 is fine. This
  > is the one corrected number that was *not* independently confirmed.
- **Branching**: strictly **orthogonal** (90° turns only — straight, left,
  right from the core). Diagonal branches were tried and rejected — they
  caused overlapping reserved zones near the core that made room placement
  fail more often, and aren't architecturally sound anyway (corridors turn at
  right angles).
- **The plan grows UP as well as out.** `max_branch_cm` (default **1200cm**)
  caps how far a branch may run from the core. Runs fill both sides of one
  branch before the next, so a corridor is double-loaded; when no run on the
  level can take the next unit inside the cap, growth starts the storey above
  instead of reaching further out. The default program went from a **60×35m**
  single-storey sprawl to **22×20m over 4 levels** — same floor area (787 →
  793m²), a third of the ground footprint (787 → 300m²).
  - Each level carries its own core and branch corridors, and its own
    occupancy. The core repeats on every storey the building passes through,
    because it is the stair.
  - A **duplex is 600cm and so reserves its footprint on TWO levels.** Its
    footprints can blanket the storey above, which is why a run steps past a
    blocked bay (`PROBE_STEP_CM`) and why growth tolerates a fully blocked
    storey (`MAX_EMPTY_LEVELS`) rather than giving up. Without either, a
    program of four duplexes placed four units and abandoned the other
    fourteen.
  - **Walls resolve per level.** A level-1 corridor stands directly above the
    level-0 one and `resolve_walls` works in plan, so resolving them together
    would merge two real walls into one and halve the take-off. Same reason
    `diagnostics.shared_boundaries` only compares elements on one level.
  - Pass a very large `max_branch_cm` for the old single-storey behaviour.
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

## Repo structure

The repo split into `backend/` + `frontend/` on 2026-07-31. The engine moved
to `backend/growth_engine/` (history preserved via `git mv`) and keeps its
no-dependencies rule — the API imports the engine, never the reverse.

```
backend/growth_engine/   the engine, pure stdlib
backend/app/             FastAPI adapter (main.py, schemas.py)
frontend/                React + Vite viewer
```

### `backend/growth_engine/`

- **`geometry.py`** — `Point` class, vector math, SAT polygon overlap test
  (with the flush-touching epsilon fix), `point_in_polygon` (ready but
  unused since boundary was removed).
- **`components.py`** — the N-SA-SB-SC-SB-SA-N sequence and the 360cm bay it
  spans (`BAY_CM`, `BAY_LENGTHS`). `walk_wall()` divides a run into bays and
  only the last one adapts; `bay_lengths()` is that division on its own.
- **`walls.py`** — **NEW.** `resolve_walls()` turns per-element edges into the
  set of physical walls, each built once, by collinear interval decomposition.
  Returns a `WallResolution` carrying the walls plus the length of any
  sub-5cm slivers it declined to build, so length accounting stays exact.
- **`catalog.py`** — `UnitType` and `RoomComponent` dataclasses,
  `load_unit_from_export()` parses Rhino JSON into real room geometry,
  `UNIT_CATALOG` auto-loads bundled exports from `unit_exports/` at import
  time. All 10 types have real rooms. (Its module docstring used to deny
  this; corrected 2026-07-31, and it now says so explicitly.)
- **`growth.py`** — `generate_floorplan(program, seed, max_branch_cm,
  max_levels)` runs the full entrance→corridor→core→branch→room growth, level
  by level, and returns a `FloorPlan` with `elements`
  (corridor/core/unit/communal `PlacedElement`s), `walls` and `level_count`.
  Each element carries a `level`, a `z0` (its slab height) and `floors` (2 for
  a duplex). See the growth-logic section above for how the cap decides
  whether the plan spreads or stacks.
- **`massing.py`** — `generate_massing()` extrudes each placed element into
  one box (coarse). `generate_room_massing()` extrudes real per-room
  geometry when available, falls back to one box per unit otherwise. Two
  different vertical offsets both apply and are not the same thing:
  `RoomComponent.z_min` stacks a duplex's upper floor WITHIN the unit, while
  `PlacedElement.z0` lifts the whole unit onto its storey.
- **`glb_import.py`** — **was never documented here.** Reads Adela's
  `components.glb` into the component catalog with the standard library only:
  GLB is a JSON chunk plus a BIN chunk, and glTF *requires* every POSITION
  accessor to carry min/max, so per-part bounding boxes come out of the JSON
  without decoding a single vertex. Regenerate with
  `python -m growth_engine.glb_import path/to/components.glb`; the extracted
  `component_exports/components.json` is committed, the 13.5MB GLB is not.
  Surveyed result: 10×10 posts on 30cm centres in a 40×40 column bundle,
  20×10 beam sections (SA 70, SB 80, SC 60), a 60×60×10 connector plate, and
  a 240×240 woven capital of F1/F2 lacing and B2 verticals.
- **`frame.py`** — `build_frame(plan)` resolves a plan into the real
  components. There are five kinds of member and they are not the same thing:
  `post` and `plate` (the column bundle and its connector), `beam` (a primary
  member on a grid line), `infill` (a wall member between the bays), and
  `floor` (a storey deck).
  - **The grid is independent of the rooms, and no column stands outside the
    volume.** A column stands at every intersection of the 360cm grid that
    falls inside the massing — so some land inside rooms, and walls become
    infill between the bays. The grid is anchored at the entrance, the growth
    seed.
  - **Where the massing runs past the last column, the frame reaches the
    building line with a HALF SPAN and stops** (`STUB_CM`, half a bay,
    clipped to the face). This replaces snapping columns to the nearest
    gridline, which planted **1,792 post members up to 195cm out in open
    air** with a full bay run out to each. A stub is the bay sequence
    truncated — half a span comes out as SA + SB + half an SC, which is the
    arm of the surveyed assembly. Stubs close exactly on the face: measured
    max overhang 0cm.
  - **A beam is only built where the bay it spans is in the building.** Both
    ends being inside is not enough — two arms of a cross-shaped plan can face
    each other across a notch, and the span between them is open air.
  - **A column stops where it stops holding floor.** Where the building is
    full height so is the column, but where an upper storey sets back, its
    columns end with it instead of carrying on up holding nothing.
    `FrameNode.levels` is the storeys at which any of the four bays meeting at
    the node has floor in them, and the top of the highest one is where the
    column ends — verified as 0 columns topping out above their own floor,
    over 60 random programs, 59 of which come out with stepped column
    heights.
  - **A column runs unbroken from the ground** to the top of the highest level
    above it, passing through any storey the plan does not occupy there. A
    column with a gap in it is not a column.
  - **A primary span is exactly one bay**, so its five members are catalog
    parts with no scaling at all.
  - **Every column is tied to every grid neighbour at every storey both
    reach** — not only where the plan occupies both ends. A column rising with
    nothing spanning to its neighbour is not braced, and the rooms happening
    to stop short of that bay does not change the structure's problem. Tying
    only the occupied bays left 6 of 41 adjacent pairs with a storey of
    unconnected column on the default program. Measured over 100 random
    programs after the fix: **0 isolated columns and 0 untied column-storeys
    out of 10,306**.
  - `course_cm` divides each storey into that many horizontal courses and
    repeats the whole component walk at each one, filling the wall instead of
    outlining it. Storeys divide a whole number of times, so the ceiling
    course always lands on the storey line — that beam is structural and does
    not move. The default (one course per storey) is the ceiling beam alone.
    Intermediate courses weave ±half a member either side of the wall centre
    line, which is what the surveyed capital's F1/F2 layers do.
  - Growth is TOPOLOGICAL and three-dimensional, not program order. A *ring*
    is BFS depth across the GRID from the entrance node, plus storeys climbed
    — out and up in the same currency, so the front is a diagonal shell rather
    than a plan that fills before it rises. Each ring builds in the order the
    thing is assembled:

        step 4r + 0   columns rise through this storey
        step 4r + 1   primary beams span the grid lines between them
        step 4r + 2   the floor deck lands on those beams
        step 4r + 3   the walls infill between the bays
  - `frame_summary()` reports provenance (surveyed vs. placeholder catalog),
    the course pitch, and two places the source and the engine disagree:
    `length_deviation` (the catalog is fixed-length, `components.py` rescales)
    and `joint_overlaps` (on the default program, 15 of 28 capitals sit closer
    to a neighbour than the 240cm joint is wide, so the full joint block
    self-intersects there and is off by default).
- **`preview.py`** — **NEW.** `render_svg()` / `save_svg()` draw a plan to a
  plain SVG, no matplotlib. Also `plan_to_dict()` for a web viewer. Runs as
  `python -m growth_engine.preview --seed 42 --out plan.svg`.
- **`export.py`** — **NEW.** `plan_to_obj()` / `save_obj()`, cm → metres, one
  OBJ group per block.
- **`diagnostics.py`** — **NEW.** Measurements *about* a plan.
  `shared_boundaries()` finds coincident element edges independently of
  `walls.py`; `verify_walls()` checks the deduplication invariant and is
  returned on every `/api/plan` response.
- **`site/`** — **was never documented here.** `osm_site_finder.py` finds
  candidate infill sites from OpenStreetMap via Overpass (needs `requests`,
  the only non-stdlib import anywhere, and it is guarded). `analysis.py`
  scores a grid over a site boundary for daylight (VSC-style obstruction
  angle off known neighbour heights) and circulation (distance decay from
  the frontage edge). Neither is wired into `growth.py` yet.
- **`unit_exports/`** — bundled real JSON exports, auto-loaded by
  `catalog.py`. Drop new exports here.
- **`__init__.py`** — exposes everything needed:
  `generate_floorplan`, `generate_massing`, `generate_room_massing`,
  `plan_to_obj`, `Wall`, `resolve_walls`, `get_unit`, `UNIT_CATALOG`,
  `Point`, `polygons_overlap`, etc.

### `frontend/src/components/` — the four views

All four read the same plan; they differ in what they choose to draw.

- **Plan** — SVG, the component walk in 2D, with layer toggles. Draws ONE
  storey at a time (the stepper appears once a plan stacks), with the level
  below dashed underneath and the upper half of any duplex hatched.
- **3D massing** — one box per element (or per room), rising in PROGRAM order:
  entrance → corridor → core → branch corridors → rooms.
- **Frame** — the structural frame alone: a column at every node, one beam
  course at each storey ceiling. This is what gets built, not what it occupies.
- **Build** — **NEW.** Both at once, on one clock. The massing rises, fades to
  a ghost at 12% opacity (depth-write off, so the timber reads through it),
  and then the components colonise it ring by ring until the walls are filled
  with courses. The course pitch is selectable; 300cm falls back to the
  ceiling beam alone, i.e. the Frame view's frame with the volume behind it.
  It asks `/api/frame` a second time with `course_cm` — same seed, same plan,
  so the two frames are two readings of one building.

`frameInstances.js` holds what the Frame and Build views share: the whole
frame is one `InstancedMesh` (a few thousand members would otherwise be a few
thousand draw calls), and one `applyMembers()` writes every instance matrix
per tick. Posts rise from their underside; beams *extend* along their own axis
away from the column already standing, which is what makes the spread read as
reaching outward rather than as members switching on.

## Usage

```python
from growth_engine import generate_floorplan, generate_room_massing, plan_to_obj

plan = generate_floorplan(
    program=["Studio_A", "1Bed_B", "SK", "2Bed_A", "SL", "3Bed_A"],
    seed=42,
)
blocks = generate_room_massing(plan)  # real rooms where available, else 1 box/unit
open("massing.obj", "w").write(plan_to_obj(plan))   # metres

plan.walls          # the physical walls, each built once
plan.elements[0].wall_ids   # which of them this element sits on
```

Run the web app with `uvicorn app.main:app --reload` from `backend/` and
`npm run dev` from `frontend/`. See README.md.

No Rhino/Grasshopper dependency — pure Python, standard library only
(`dataclasses`, `json`, `pathlib`, `random`, `math`). Deliberately kept this
way so it's testable in Claude Code without Rhino running; a GHPython adapter
layer to feed this into Grasshopper is a planned separate step. FastAPI and
React live strictly outside the engine, for the same reason.

**Everything internal is centimetres.** OBJ export is the one place that
converts (to metres), because that is what Blender and Rhino expect.

## Known gaps / honest limitations (not yet solved)

- **Adjacency matrix** is barely wired in (one rule: `SL-SK=2.0`). The rest
  of `ADJACENCY_MATRIX.py` needs real implementation, not just a proof of
  concept. (`ADJACENCY_MATRIX.py` is not in this repo either.)
- **No site boundary** — growth is currently unconstrained. `point_in_polygon`
  exists in `geometry.py` but isn't called from `growth.py`. Note that
  `site/analysis.py` already produces the daylight/circulation bias field
  this would need; only the wiring is missing.
- **Overlap resolution is blunt**: when a communal room doesn't fit, it
  shrinks proportionally (×0.68 per retry, up to 7 attempts) rather than
  trying alternate positions first. Works, but not elegant. *Correction to
  the original note: this applies only to communal rooms. `_try_add_unit`
  has no retry at all — a residential unit either fits or is skipped, which
  is arguably right, since squashing a surveyed unit out of proportion would
  be worse.*
- **Branch count is hardcoded to 3** (straight/left/right) — a real system
  might vary branch count based on program size or site geometry.
- **The woven joint capital still projects past the massing.** With
  `joint_blocks` on, the 240×240 assembly at an edge node throws its arms up
  to **75cm outside the volume** — the same category of problem the columns
  and beams have now been fixed for, but clipping it would mean drawing a
  partial capital, which is a decision about the assembly rather than about
  where it goes. Left alone because the joint block is still an open question.
- **A large program's frame gets heavy.** The frame is one
  `InstancedMesh`, so it is still a single draw call, but `applyMembers()`
  rewrites every instance matrix each tick while the growth animation runs.
  The default program is ~7.6k members; a 24-entry program reached **19,599**.
  If that stutters, the fix is to stop rewriting members that have finished
  growing, not to thin the frame.
- **The branch cap is one number for the whole building.** `max_branch_cm`
  applies to every run on every level, so the plan compacts uniformly rather
  than, say, keeping a longer ground floor under a smaller upper one. A
  setback or a per-level cap would be a real design move; this is not one yet.
- **Nothing checks that an upper-level unit has anything under it.** Occupancy
  is per level and a run steps past blocked bays, so a unit can land over the
  gap where the storey below stops. Measured over 120 random programs, **24 of
  1024 above-ground units (2.3%)** have no element directly beneath them. The
  massing and frame both draw them happily. Rare, but real: it wants either a
  support rule at placement or a deliberate decision that the timber frame
  cantilevers there.
- **Only one program list per run** — no automatic program generation from
  a target unit mix or area budget; you hand it an explicit ordered list.
- **The seed barely does anything.** `random` is called in exactly one place,
  for communal room width. Every residential unit places deterministically,
  so two seeds on the same program differ only in how wide SK and SL are.
  The program list is the real design input.
- **An unknown program key silently becomes a communal room.** That is how
  `SK`/`SL` work, so it can't be rejected — but it means `Studio_C` builds a
  blank box rather than failing. The API reports `communal` and `suspect`
  keys so the UI can warn; the engine itself still accepts anything.
- **The entrance is now recessed.** With circulation at true scale, units on
  the east–west branches (4–8m deep) project past the 3.4m entry run, so the
  entrance sits in a notch rather than at the building edge. Not a bug — it
  follows from the spec's own numbers — but it only became visible once the
  10× error was fixed.
- **Communal room sizes are placeholders and not Adela's numbers.** Set to
  600cm frontage × 400–700cm deep, scaled against the real unit catalog.
  Replace when the communal catalog defines them.
- **Communal room interiors** (SK, SL) are single flexible boxes, not
  subdivided — correct, since the communal catalog doesn't define
  sub-spaces for them, just noting it's asymmetric with residential
  treatment.
- **Infill members in a run's last bay are still bespoke.** Primary grid beams
  are all catalog parts, but a wall run rarely divides into whole bays, so its
  final bay stretches or shortens — 47% of infill members come out at exact
  catalog length and the rest land a median 10cm off (worst case 77cm).
  `frame_summary()["length_deviation"]` measures only the infill now, because
  averaging in the exact spans would dilute the one number that matters.
  Closing the remainder properly means either a real closer part or snapping
  wall lengths to the grid, which would move the surveyed unit footprints.
- **The 240×240 joint block does not fit its own plan.** On the default
  program, 15 of 28 capitals sit closer to a neighbour than the woven capital
  is wide, so it self-intersects there. Off by default, counted, and
  toggleable — but whether the answer is a smaller capital, wider bays, or
  clipping the assembly per node is unresolved.

## Solved since the original summary

- ~~**Shared walls were built twice.**~~ Resolved 2026-07-31 in `walls.py`;
  see the mirror-pair section above. Guarded by `diagnostics.verify_walls()`,
  checked over 400 random programs with zero invariant failures.
- ~~**No file export.**~~ OBJ, SVG and JSON export all exist now
  (`export.py`, `preview.py`, and `/api/export/*`). Note this landed *before*
  the growth logic was fully settled, contrary to the original sequencing —
  it was requested explicitly.
- ~~**Uniform placeholder unit sizes.**~~ All 10 types carry real per-room
  geometry, as the original summary already recorded.
- ~~**Columns stood wherever a wall happened to end.**~~ Resolved 2026-08-05.
  They now stand on an independent 360cm grid and run unbroken from the
  ground, so the structure is a vertical system rather than a per-storey
  accident. The sequence changed with it, from nine rescaled parts to seven
  fixed ones spanning one bay. Checked over 120 random programs: **100% of
  primary beam members come out at exact catalog length**, every column starts
  at ground level, nothing is drawn below it, and `verify_walls` still holds
  at delta 0.00m.
- ~~**There was no floor.**~~ A deck is drawn per element at its own storey
  datum, growing in its own phase after the beams it lands on.
- ~~**The plan only ever grew outward.**~~ Every unit ran onto the three
  ground-floor branches, so the composition sprawled and the core served one
  storey. `max_branch_cm` now stacks it. Checked over 200 random programs
  (3–24 entries): all place fully, no same-level overlaps, `verify_walls`
  delta 0.00m throughout, and the extent stays inside ~26×22m however long the
  program gets — the building grows up instead.
