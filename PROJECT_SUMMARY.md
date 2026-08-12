# LinX Growth Engine — Project Summary

Context for whoever (human or Claude) picks this up next. This covers everything
decided so far, so it doesn't need to be re-explained.

*Last revised 2026-08-11. Blockquoted notes mark where this document was
corrected or where a stated intention has since been implemented; the
surrounding text is the original.*

*Figures quoted here are from **seed 42** unless stated. Shared spaces draw
their size from a range, so an unseeded plan totals differently every run —
several numbers in this file were once quoted unseeded and could never be
reproduced. If a figure has no seed, treat it as indicative.*

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
  > On the default program — the 18-entry one in `app/schemas.py`, which is
  > what the API and the UI use — **at seed 42** this takes 945.7m of drawn
  > wall down to **752.2m across 147 walls, 44 of them shared — 2,256.7 m²**. A
  > consequence worth confirming against the drawings: cutting a corridor edge
  > where units meet it puts an **N node at each junction**, so a long corridor
  > wall is now several spans rather than one continuous mirrored sequence.
  >
  > The seed belongs in that figure. Shared spaces draw their size from a
  > range, so an unseeded plan totals differently every run — the numbers this
  > file used to quote (550.3 → 379.0 across 59 walls) came from one such run
  > and never reproduced. What holds on *any* run is `delta_m == 0.00`.
  >
  > **Updated 2026-08-11**: the resolved total is also genuinely higher than
  > those old figures, because walls now resolve per occupied storey — see
  > below.

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
- **Core**: **360 × 720 cm** — one bay of frontage on the corridor by two bays
  deep, 25.9m², holding a lift and a stair. Corridors run flush into its
  frontage.

  > **Resolved 2026-08-11**, and it had been open a while. This said 170×170
  > — 2.9m², the consistent ÷10 of the old value — with the note: *"too small
  > to hold a flight and landing. If the core really is vertical circulation,
  > it needs a real dimension (a single stair core wants roughly 250×500cm).
  > If it is a structural anchor only, 170 is fine. This is the one corrected
  > number that was not independently confirmed."*
  >
  > Adela settled it by pointing at the Core and Stairs components: the core
  > is a real room. There is no surveyed geometry for either in this repo, so
  > it is sized off the one dimension here that IS surveyed — the 360 bay.
  > 3.6 × 7.2m takes an 8-person accessible lift (about 2.2 × 2.4m
  > structural) and a switchback stair beside it (about 2.5 × 5.0m at a 3m
  > floor-to-floor), with the landing between. Real residential cores with one
  > lift and one stair run 20–25m², so this is right rather than generous.
  >
  > Whole bays for a second reason: a core on the grid CONTAINS grid nodes, so
  > it always carries its own columns. At 170 wide it fell between grid lines
  > and was the worst offender in the support report — a stair with an
  > unsupported floor.
  >
  > Two consequences, both measured. `CORE_MIN_SPACING_CM` (4 bays) stops two
  > stairs landing opposite each other across a corridor, which `core_pitch_cm`
  > could not because it counts per run and per side. And `core_pitch_cm` went
  > back to 800: at 1600 the new size gave 7.5 cores and a 43.4m worst walk,
  > against 12 cores and 19.7m at 800. That is not undoing the earlier halving
  > — 12 big cores is still half of the 25 small ones it replaced.
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
  - **Walls resolve per OCCUPIED storey.** A level-1 corridor stands directly
    above the level-0 one and `resolve_walls` works in plan, so resolving them
    together would merge two real walls into one and halve the take-off.

    > **Corrected 2026-08-11.** This used to group by the element's own
    > `el.level`, and `diagnostics.shared_boundaries` guarded with the matching
    > `e1.level == e2.level`. That looks like the same rule and is not: a
    > duplex is ONE element spanning levels 0–1, so it never met the ordinary
    > unit standing on level 1 beside it. They share a plan line and each built
    > its own copy — **177m of wall, built twice**, on the default plan.
    >
    > It verified clean because both modules made the same assumption.
    > `diagnostics` exists precisely to be able to disagree with `walls.py`,
    > and on this one thing it could not. An element now joins the group of
    > every storey it occupies, `Wall` carries its own `level`, and
    > `shared_boundaries` counts an overlap once per storey the pair *both*
    > occupy. `verify_walls` also reports `resolved_area_m2` — length alone
    > cannot tell a 300-tall wall from a 600-tall one of the same plan run,
    > which is why this hid for so long.
  - Pass a very large `max_branch_cm` for the old single-storey behaviour.
- **Overlap checking**: proper polygon collision via **Separating Axis
  Theorem (SAT)**, tolerant of flush-touching edges within a small epsilon
  (1cm). This tolerance is critical — without it, any two components meant to
  share a wall (which is most of this system) register as a false-positive
  collision, since a shared boundary line has zero separation. This was a
  real bug hit and fixed during development (rooms silently failed to place
  for a while because of it).
- ~~**No site boundary currently**~~ — **superseded.** Growth is constrained to
  a real plot (Deptford Church St, SE8) via `site/location.py`; `generate_
  floorplan(..., boundary=…)` rejects any placement `polygon_contains` fails,
  and `plan.off_site` audits the result. On by default through `/api/plan`'s
  `constrain_to_site`. The site outline draws in all four 3D views.
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
- **`facade.py` / `facade_import.py`** — **NEW.** The envelope. `facade_import`
  reads the nine panel GLBs (A–I) into `facade_exports/facades.json` the same
  library-free way `glb_import` reads the components; `facade.py` picks a panel
  for every exterior bay and places it. Three things worth knowing:
  - **Exterior means one owner.** `walls.resolve_walls` already computes this —
    a wall with two owners is internal — so there is no separate envelope model.
  - **Panels tile a RUN, not a wall.** Collinear exterior walls on one storey
    merge first, because a facade is continuous across the building. Tiling each
    resolved wall alone clad 65% of the envelope; merging takes it to 73%.
  - **330 ≠ 360, and it cannot be made to.** Measured: the panel's own posts are
    on a **50 cm** rhythm (7 pairs, 300 cm end post to end post) inside a 330 cm
    overall; the structural bay is a surveyed **360 cm**. 360 is not a multiple of
    50, so no offset lands the panel posts on the column grid — 330 and 360
    realign only every LCM 3960 cm (12 panels to 11 bays, 39.6 m). There is no
    arrangement to search for. `build_facade(align=…)` therefore offers the two
    honest readings of `330 + 30 = 360`, and `column_alignment()` measures the
    result rather than asserting it:
    | | panels | clad | centred in a bay | mean drift |
    |---|---|---|---|---|
    | `"run"` (default) | 78 | 65.3% | 2.6% | 85 cm |
    | `"grid"` | 56 | 46.9% | **100%** | **0 cm** |
    Grid mode costs 18 points of coverage, because a whole 330 panel must fit
    inside a 360 bay that is wholly on wall. It also leaves 15 cm clear at each
    column line, into which a 40 cm column laps **5 cm onto each neighbouring
    panel** — the panel is 10 cm too wide to sit clear between columns. That lap
    is reported, not swallowed: it is a fixing detail if intended and a clash if
    not, and the engine cannot tell which. **The real fix is a 320 cm panel (or a
    360 cm one), which is a question for Adela, not for this code.**
  - The panel module is not the structural bay, deliberately.
    Panels are fixed components, so a run takes whole panels and the remainder is
    reported (`unclad_cm`, split into `too_short_cm` and `remainder_cm`) rather
    than stretched. Nearly all of `too_short_cm` is 170cm corridor ends, which
    want a narrower panel type that does not exist yet.

    > **Updated 2026-08-12.** There is a fourth figure, `open_cm`, and it is
    > deliberately NOT part of `unclad_cm`: the deck-access corridors take no
    > cladding at all, because an outdoor walkway wrapped in solid panels stops
    > being a walkway. Billing that to the shortfall would file a design
    > decision under "needs a narrower panel", which is the one line in this
    > report anyone acts on. On the Deptford spine at seed 42: clad 637m, open
    > 195m, remainder 228m, too short 37m.
    >
    > `too_short_cm` also fell sharply — the bay datum below is shared by every
    > storey on a line, and a storey covering only part of that line could
    > contain no whole bay at those positions, so walls twice a panel wide came
    > out bare and were reported as too short. Two fallbacks now re-anchor on
    > the span, and then on the wall, when that happens. Walls at least one
    > panel wide with no panel: 0.
  - **The module is anchored per ELEVATION, not per storey.** One datum per plan
    line, shared by every level on it, so panels can only land at
    `base + k*pitch` and a panel on level 2 sits exactly above the one on level 1.
    Tiling each storey independently is the obvious way to write it and it never
    stacks — nothing errors, the panels just come out offset a metre or two per
    floor. `verify_facade` catches exactly that (it reported 0 stacked pairs), and
    `/api/facade` returns it as `connection_check` on every response.
  - **The vertical datum is the column, not the bounding box.** Eight panels model
    their column at z 0..300 and let the shading fins overhang to 310. Panel D
    does not — its whole panel sits 10cm low. `facade_import` therefore takes the
    datum from the column zone, which fixes D at the source; rebasing on the
    bounding box preserved the error and hung every D below its slab.
- **`site/location.py`** — **NEW.** The project has a real site: the triangle at
  Coffey St / Deptford Church St / Crossfield St, London SE8 (51.479058,
  −0.023964). Corners are the real OSM intersection **nodes** — each pair of
  streets shares one, so they come back with a 0.00 m gap rather than as two
  polylines nearly meeting. 4,588 m² to centrelines, 2,797 m² at a 6 m setback.
  Three things to know:
  - `boundary(inset_m)` is a **true edge offset**, each edge pushed along its own
    inward normal. Not a scale about the centroid, which is the tempting
    one-liner and over-shrinks this scalene triangle by ~400 m². Verified against
    the closed form `A·((r−d)/r)²` at every inset, exact to <0.5 m².
  - The degeneracy guard is a **half-plane test, not a winding test**: offsetting
    a triangle past its inradius is a negative homothety about the incentre,
    which preserves winding, so a sign check hands back a plausible-looking
    inverted triangle.
  - `best_placement()` searched origin and rotation and returned **rotation 0** —
    a real finding, not a default left alone. Coffey St bears 87° and Deptford
    Church St 176°, so the plot is within 4° of cardinal and the engine's axes
    are already street-aligned.
  **Growth is now constrained to it** — the long-standing open item is closed.
  `generate_floorplan(..., boundary=…)` places nothing that is not wholly inside
  the polygon, at any level, and `/api/plan` does it by default. Four notes:
  - **Both tests are needed.** `geometry.polygon_contains` checks every corner
    inside AND no edge properly crossing. Corners alone pass a rectangle
    bridging a concave notch; edge-crossing alone passes a footprint entirely
    outside. Together they are exact for any simple polygon, which matters
    because a boundary need not be a triangle.
  - **The corridor is tested, not just the room.** A unit can sit legitimately
    inside the boundary while the only corridor reaching it crosses out, so each
    bay's corridor strip is tested alongside the footprint, and branch corridors
    are trimmed back to what fits rather than assumed.
  - **The armature is audited, not trusted.** The entry run and the core are
    placed before any test can run — they are what everything else is placed
    against. `plan.off_site` lists what the constraint could not stop; on this
    site at a 6 m setback it is empty, and at a 12 m setback it correctly
    reports `Corridor (L0)`, meaning the origin is too near an edge.
  - **It makes the building stack**, which is the point: 6 levels unconstrained
    → 5 constrained on the default program, and a 30-unit program that will not
    fit goes to the 12-level cap and reports 6 unplaced rather than sprawling.
  Still not modelled: `max_branch_cm` and the boundary both stay on and do
  different jobs (compactness vs possibility), and growth does not try to
  *choose* placements that fit better — it just refuses the ones that do not.
- **`solar.py`** — **NEW.** Clear-sky irradiation per facade panel: real sun
  geometry (declination, hour angle, altitude, azimuth) over 132 above-horizon
  positions in the year, direct beam by incidence angle plus isotropic diffuse
  through a 0.5 sky view factor, and a ray-AABB shadow test against the
  building's own massing. ~160ms on the default program, so `/api/facade` always
  runs it and the heatmap is a display toggle rather than a refetch. Sanity: at
  52°N a south elevation comes out ~1200 kWh/m²·yr, east and west ~720 and
  near-equal (as they must be), north ~200 — non-zero because of the diffuse
  term, which is right; a north window is dimmer, not dark.
- **`shared_spaces.py`** — **NEW.** The flexible half of the program:
  `SharedSpace` carries a frontage RANGE and a depth RANGE rather than a
  measurement, because a shared space has a brief and not a survey. Holds the
  indoor rooms (Lobby, Gym, Library, Workspace, SK, SL) and the outdoor
  ground (Garden, Playground); `kind` is the `PlacedElement` kind each
  produces, which is what makes an outdoor area walls-free everywhere
  downstream. An unrecognised key falls back to a blank flexible room.
- **`growth.py`** — `generate_floorplan(program, seed, max_branch_cm,
  max_levels)` runs the full entrance→corridor→core→branch→room growth, level
  by level, and returns a `FloorPlan` with `elements`
  (corridor/core/unit/communal/outdoor `PlacedElement`s), `walls` and
  `level_count`.
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
  `partition` (a divider between the rooms *inside* a unit, as against the
  envelope around it), `floor` (a storey deck — one per element **per storey
  it spans**, since a duplex is one element two storeys tall and needs a floor
  at its mid-storey line as well as at its base) and `ceiling` (the soffit
  capping that same storey).
  - **Room partitions come from the surveyed rooms, not from a tiling.** The
    rooms do *not* tile their unit: Studio_A's five rooms sum to 45.2m² inside
    a 42.2m² footprint, and its Entrance sits bodily *inside* the LDK
    rectangle. So there are no "shared edges" to read partitions off. What
    works is handing every room rectangle to `walls.resolve_walls` — the same
    machinery the envelope uses — which groups edges by supporting line, cuts
    at every interval endpoint and emits each stretch once. Two rooms either
    side of a divider produce it once; the Entrance nook's overlap resolves
    into stretches rather than doubled members. Partitions are then coursed by
    the same `_emit_wall` as the envelope, so the two cannot drift into
    drawing a wall two different ways.
  - Three things that each cost a real bug on the way in, all guarded now:
    rooms are grouped **by storey** (per-unit grouping missed partitions two
    neighbours put on the same line — 5 members built twice); each wall takes
    the z-span of **the rooms that own it**, from `resolve_walls`' owner
    indices (taking the storey's own min/max let one tall room stretch every
    wall on that floor, 440 phantom members); and a member-level guard catches
    the last case storey grouping cannot see, where a double-height room
    reaches into the storey above and meets an ordinary room's divider there.
  - A course may not sit above the wall it belongs to. `_levels` rounds a
    part-storey up to a whole one, which is right for the envelope — every
    element wall is a whole storey — but rooms are not, and a 150cm balcony
    parapet was getting its course 145cm above the room, floating in open air.
  - **A storey stacks floor / volume / ceiling / beams / next floor**, with
    nothing coplanar. The deck sits on the slab line (0–10), the ceiling hangs
    at 280–290, and the primary beams keep the top 10cm (290–300) they have in
    the source assembly. The ceiling is deliberately *under* the beams rather
    than level with them — coplanar faces z-fight, and the beams are structure
    while the ceiling is not. It is drawn in a cool pale grey against the
    deck's warm grey (`Ceiling` vs `Deck` in `frameInstances.js`) so a storey
    reads floor-below / ceiling-above at a glance. Floor and ceiling of a
    storey arrive in the same growth step, which is why the ring is taken from
    the storey datum and not the soffit height — the latter rounds up into the
    storey above.
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
  - The woven capital tops **every** column, not only the nodes where three or
    more beams arrive. A corner column heads into its capital the same way a
    cross does; the arms with no beam to meet simply stop. Restricting it to
    junctions left the perimeter columns capped with a bare plate while the
    interior ones were woven, which read as two different buildings.
    `capital_count` in the summary is how many columns actually carry one — all
    of them when `joint_blocks` is on, none when it is off, which is what the
    growth-step labels now count too.
  - `frame_summary()` reports provenance (surveyed vs. placeholder catalog),
    the course pitch, and `length_deviation` — the one place the source and
    the engine still disagree, since the catalog is fixed-length and
    `components.py` rescales. `joint_overlaps` measures capital clearance and
    is **0** on the 360 grid: the joint is 240 wide, so it fits at every node
    with 120 to spare. It is kept because an irregular grid would report it.
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
- ~~**No site boundary**~~ — **solved.** Growth is constrained to the Deptford
  plot and audited by `plan.off_site`; see the correction above. What remains
  open is weaker and worth stating separately: the engine *respects* the
  boundary but does not *seek* placements that use the plot well, and
  `site/analysis.py`'s daylight/circulation bias field is still not wired into
  where things go.
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
  to **80cm outside the volume** — 348 lacing members on the default program,
  now that every column carries a capital rather than only the junctions. It
  is the same category of problem the columns and beams have been fixed for,
  but clipping it would mean drawing a partial capital, which is a decision
  about the assembly rather than about where it goes. This is the joint
  block's remaining open question; whether it belongs on every column is not,
  it does.
- **A large program's frame gets heavy.** The frame is one
  `InstancedMesh`, so it is still a single draw call, but `applyMembers()`
  rewrites every instance matrix each tick while the growth animation runs.
  The default program is ~7.6k members at 100cm courses, **17.5k** with the
  joint block on — the capital is now 9,888 of them, up from ~6.6k when only
  junctions got one. A 24-entry program reached **19,599** without it. If that
  stutters, the fix is to stop rewriting members that have finished growing,
  not to thin the frame.
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
- **The seed barely does anything.** `random` is called only to pick a
  flexible space's size inside its range. Every residential unit places
  deterministically, so two seeds on the same program differ only in the size
  of the shared rooms and outdoor areas. The program list is the real design
  input.
- **An unknown program key silently becomes a blank flexible room.** That is
  the fallback `SK`/`SL` relied on before `shared_spaces.py` existed, so it
  can't be rejected — but it means `Studio_C` builds a blank box rather than
  failing. The API reports `communal` and `suspect` keys so the UI can warn
  (a key that IS in the shared catalog is never suspect); the engine itself
  still accepts anything.
- **The entrance is now recessed.** With circulation at true scale, units on
  the east–west branches (4–8m deep) project past the 3.4m entry run, so the
  entrance sits in a notch rather than at the building edge. Not a bug — it
  follows from the spec's own numbers — but it only became visible once the
  10× error was fixed.
- **Shared-space sizes are a brief, not Adela's numbers.** `shared_spaces.py`
  gives each of Lobby, Gym, Library, Workspace, SK, SL, Garden and Playground
  its own frontage and depth RANGE, scaled against the real unit catalog
  (roughly 20–110 m² indoors, 42–192 m² outdoors). That is a step up from the
  single 600 × 400–700 cm placeholder every communal room used to share, but
  it is still a brief. Replace when the shared catalog is fixed.
- **Shared room interiors** (SK, SL, Lobby, Gym, …) are single flexible
  boxes, not subdivided — correct, since nothing defines sub-spaces for them,
  just noting it's asymmetric with residential treatment.
- **The facade covers 65% of the envelope, and that is the honest number.** The
  panel set is nine fixed 330cm components; a run takes whole panels and the rest
  is reported. Of the 137m left on the default program, 106m is remainder at the
  ends of clad runs (wants a filler piece) and 31m is runs narrower than any
  panel — almost entirely the 170cm corridor and core ends, which no arrangement
  of these nine will ever cover. **A narrow panel type is the missing piece.**
  Coverage was 73% before the module was anchored per elevation; alignment costs
  8 points and is worth it, because the 73% version did not stack. A building
  whose storeys all use the same unit type (so the elevations coincide) clads to
  79% with 56 stacked pairs — the loss is the plan stepping, not the rule.
- **The solar map is comparable, not predictive.** Clear-sky, so it is an upper
  bound; no neighbours, no weather, no ground reflection, and no panel-on-panel
  shading, which means balconied elevations read slightly warm since a balcony
  does not shade the window under it. Latitude now comes from the real site
  (51.479°N). The neighbouring buildings still do not join the shadow test —
  `site/analysis.py` already knows how to find them, so that is the next honest
  improvement.
- **The site is obeyed, but not designed to.** Growth refuses placements outside
  the boundary; it does not *seek* placements that use the plot well. A triangle
  has two acute corners this engine will never fill, because it only ever builds
  axis-aligned rectangles off three orthogonal branches. Rotating the armature
  to the hypotenuse, or letting a run follow a diagonal edge, is the next real
  move — and it is a growth-logic change, not a boundary one.
- **`site_fit` used to measure the bounding box.** That was defensible while
  nothing was constrained and wrong the moment something was: this building is
  cross-shaped, so its bounding rectangle hangs over the site edge while every
  element inside it is comfortably on the plot. It reported 99.3% and
  `fits: False` for a plan that was entirely on the site. It measures the
  elements now, and agrees with the engine's own test.
- **Panel choice is a rule table, not a survey.** Adela gave the nine panels'
  *purposes*; which bay gets which is `facade._choose`, and it leans on the one
  ordering available without a site: a run's rank by length among its element's
  exterior walls, i.e. the longest exterior face is the principal elevation. Once
  `site/analysis.py` is wired in, orientation and daylight are the better input
  and this rule should be replaced rather than extended.
- **Outdoor areas are ground, not rooms.** Garden and Playground are placed by
  the same growth logic, flush against a corridor edge so they stay reachable,
  but they build no walls, carry no frame, take no ceiling, and are reported
  as `outdoor_area_m2` rather than floor area. `growth.builds_walls` is the
  single predicate; `walls.py`, `frame.py` and `diagnostics.py` all filter on
  it, and they have to agree or `verify_walls` fails against its own plan.
  They are also placed in a ground-floor pass AFTER the building has stacked
  and are exempt from `max_branch_cm` — that cap decides how compact the
  *building* is, and open ground has no upper storey to be pushed into. The
  consequence to know about: an outdoor entry's position in the program order
  is not honoured, only its order relative to other outdoor entries.
- **Infill members in a run's last bay are still bespoke.** Primary grid beams
  are all catalog parts, but a wall run rarely divides into whole bays, so its
  final bay stretches or shortens — 47% of infill members come out at exact
  catalog length and the rest land a median 10cm off (worst case 77cm).
  `frame_summary()["length_deviation"]` measures only the infill now, because
  averaging in the exact spans would dilute the one number that matters.
  Closing the remainder properly means either a real closer part or snapping
  wall lengths to the grid, which would move the surveyed unit footprints.

## Solved since the original summary

- ~~**The 240×240 joint block does not fit its own plan.**~~ Resolved
  2026-08-06 — by the structural grid rather than by anything done to the
  joint. When nodes came from wall ends they landed wherever a wall happened
  to stop, and 15 of 28 capitals sat closer to a neighbour than the 240cm
  assembly is wide. On the 360 grid the closest two nodes can be is 360, so
  the capital clears with 120 to spare and `joint_overlaps` is **0**. The
  capital now goes on every column. **`joint_blocks` defaults ON since
  2026-08-11** — `joint_overlaps` is 0 on the default plan, so there is
  nothing to hide behind the simpler view; it costs 17,700 → 43,428 members
  to draw.

- ~~**Shared walls were built twice.**~~ Resolved 2026-07-31 in `walls.py`;
  see the mirror-pair section above. Guarded by `diagnostics.verify_walls()`,
  checked over 400 random programs with zero invariant failures.

- ~~**Shared walls were built twice — again, one storey up.**~~ Resolved
  2026-08-11. The 2026-07-31 fix held in plan but not in section: walls were
  grouped by `el.level`, so a duplex spanning levels 0–1 never met the unit
  standing on level 1 beside it, and each built its own copy of the line they
  share. **177m, built twice.** `verify_walls` called it clean because
  `shared_boundaries` skipped the same pairs by the same test — two modules
  that are supposed to be independent, sharing the one assumption that was
  wrong. Now resolved per *occupied* storey on both sides, `Wall` carries its
  own `level`, and the report adds `resolved_area_m2`. Verified delta 0.000
  and zero doubly-built wall across 5 program shapes × 3 seeds and 6 site
  seeds. Deptford spine seed 42: 1,212 → **1,434m / 4,302 m²**.

- ~~**The facade stopped two storeys below the highest room.**~~ Resolved
  2026-08-11, and it was the same bug seen from the other end: the facade is
  built from the wall set, and duplex upper storeys had no walls to clad. Seed
  42 went from 90/66/7 panels on levels 0–2 to **88/75/25/6 on levels 0–3**
  against a highest room on level 3.

- ~~**33m of corridor before the building started.**~~ Resolved 2026-08-11.
  The spine strategy set `entry_run_cm = length * 0.3` — a third of the
  109.8m spine edge — and nothing ever hung off it, because the three arms
  start at the core. It could not simply be deleted: the arms leave along −v,
  −u and +u with none pointing back at the street, so the core's position *is*
  the building's street edge, and a two-bay run crowded the plan onto one end
  of the plot (ground 1107 → 831 m², green 81%). Swept and set to **16m**:
  more building and a shorter worst walk to a stair than the value it
  replaced, for half the corridor.

- ~~**The green target was reported, not met.**~~ `generate_spine_floorplan`
  now closes a loop on it — grow, measure, steer `courtyard_ratio`, keep the
  best of 4. When the reserve hits its floor and green is still over, the miss
  is structural (ground the building never reached, not courtyard), so it
  perturbs the *layout* seed deterministically instead of pulling a spent
  lever. In the 30–40% band on 6 of 10 seeds, from 1 of 6.
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
- ~~**There was no floor.**~~ A deck is drawn per element per storey the
  element spans, growing in its own phase after the beams it lands on, with a
  ceiling soffit capping the same storey.
- ~~**One course per storey was hidden on the Build tab.**~~ Resolved
  2026-08-06. `COURSE_OPTIONS` in `App.jsx` was `[150, 100, 75, 60]` and 300 —
  the pitch that draws the frame the Frame tab draws — was tacked on after the
  loop as a bare `ceiling only` option. It was reachable, but it sat last, out
  of numeric order, and did not read as a pitch, so Build always opened with
  its walls filled with courses and looked crowded next to Frame. 300 is now
  first in the list, labelled `300 cm · ceiling only`, and is the default.
  Drop the pitch to fill the walls again.
- ~~**A four-storey building drew three floors.**~~ Resolved 2026-08-06. The
  deck loop emitted one plate per element at its base `z0`, but an element is
  not one storey tall — the plan places **duplexes**, 600cm units spanning two
  storeys (see the growth-logic section). Three of them top out at 1200, so
  the building is four storeys, but slabs only ever landed at 0/300/600 and
  the mid-storey line of each duplex had no floor. `_spanned_storeys()` now
  returns every slab line an element crosses, and both the deck loop and the
  node-height calculation read it, so a column and the floors it carries
  cannot disagree about which storeys an element occupies. Decks on the
  default program: 24 → 28, at 0/300/600/**900**.
  - The half-storey threshold in `MIN_STOREY_OCCUPANCY_CM` is the reason this
    is not just `z1 // STOREY_CM`. Surveyed unit heights overshoot the nominal
    300 storey by a few cm — one unit in the default program is **307.5** —
    and 7.5cm of survey drift is not another floor. A real duplex clears the
    line by a full 300, so half a storey separates them cleanly. Feeding the
    same rule into the node heights also dropped 4 stub beams that were being
    drawn at a storey the plan does not occupy, which is what
    `FrameNode.levels` always said should happen.
- ~~**The plan only ever grew outward.**~~ Every unit ran onto the three
  ground-floor branches, so the composition sprawled and the core served one
  storey. `max_branch_cm` now stacks it. Checked over 200 random programs
  (3–24 entries): all place fully, no same-level overlaps, `verify_walls`
  delta 0.00m throughout, and the extent stays inside ~26×22m however long the
  program gets — the building grows up instead.
