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

- **Components**: N (node/corner), SA, SB, SC (edges). A full span is a
  symmetric, mirrored sequence: **N + SA + SB + SB + SC + SB + SB + SA + N**
  (doubled SB flanking the centre SC — matches paired timber bracing members
  visible in her renders).
- **Circulation** has a fixed half-span of **170cm** (this is architect-set,
  independent of any catalog ratio, never derived).

  > **Corrected 2026-07-31.** This said 1700cm, and the code stored 1700 in
  > `CORRIDOR_WIDTH_CM` and `CORE_SIZE_CM` — a 17m-wide corridor and a
  > 17×17m core. The figures were transcribed off the drawings in
  > **millimetres** into fields named `_CM`. Everything sourced from Rhino
  > (unit footprints, the 300/600 storey heights) was always correct cm;
  > only the hand-typed constants were wrong, uniformly by 10×.

- **Room component sizes** (N/SA/SB/SC) scale proportionally off the same
  340cm module (2× circulation half-span) using the original ratios
  50:80:100:80, via an exact scale factor `k`:
  - `k = 340 / (2×50 + 2×80 + 4×100 + 80) = 340/740 ≈ 0.4595`
  - At that scale the members land at N≈23cm, SA≈37cm, SB≈46cm, SC≈37cm.
    **Worth checking against the joinery drawings** — these are now
    member-scale, where the old 10× figures gave a 4.6m SB, which is
    room-scale. If the intended reading was that a component spans a whole
    structural bay rather than a single member, the module is what needs
    revisiting, not the ratios.
  - This is kept **unrounded** in formulas — rounding only happens at a
    separate `fabrication_length_cm()` step right before real-world export,
    never baked into the constants themselves. Baking rounding into constants
    lets closure error compound silently across every span in a building.

    > **Not yet built.** The unrounded discipline is correctly implemented —
    > `walk_wall()` derives `k` fresh from each wall's real length and nothing
    > is pre-rounded — but `fabrication_length_cm()` itself does not exist
    > anywhere in the codebase. There is currently no path from the engine to
    > a real-world cut length. `export.py` writes geometry in metres at full
    > float precision, which is *not* the same thing as a fabrication figure.
- Different rooms get different real sizes (not a uniform grid) by **locally
  rescaling the same component sequence per wall** to that wall's actual
  target length — same `k`-derivation, just computed per-wall instead of
  globally.
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
- **`components.py`** — the N-SA-SB-SB-SC-SB-SB-SA-N sequence, `walk_wall()`
  rescales it per-wall to any real length exactly.
- **`walls.py`** — **NEW.** `resolve_walls()` turns per-element edges into the
  set of physical walls, each built once, by collinear interval decomposition.
  Returns a `WallResolution` carrying the walls plus the length of any
  sub-5cm slivers it declined to build, so length accounting stays exact.
- **`catalog.py`** — `UnitType` and `RoomComponent` dataclasses,
  `load_unit_from_export()` parses Rhino JSON into real room geometry,
  `UNIT_CATALOG` auto-loads bundled exports from `unit_exports/` at import
  time. *Its module docstring still claims 3Bed/4Bed lack per-room exports —
  that is stale, all 10 types have real rooms.*
- **`growth.py`** — `generate_floorplan(program, seed)` runs the full
  entrance→corridor→core→branch→room growth, returns a `FloorPlan` with
  `elements` (corridor/core/unit/communal `PlacedElement`s) and `walls`.
- **`massing.py`** — `generate_massing()` extrudes each placed element into
  one box (coarse). `generate_room_massing()` extrudes real per-room
  geometry when available (uses `RoomComponent.z_min` for correct floor
  stacking), falls back to one box per unit otherwise.
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
