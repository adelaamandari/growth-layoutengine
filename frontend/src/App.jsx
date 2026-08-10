import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import {
  download, getCatalog, getFacade, getFacadeCatalog, getFrame, getMassing, getPlan, getSite,
} from "./api";
import PlanView from "./components/PlanView";
import ProgramEditor from "./components/ProgramEditor";
import { MODES, useTheme } from "./useTheme";

// three.js is ~600kB and only the 3D tabs need it, so they load on
// first use rather than blocking the plan view.
const MassingView = lazy(() => import("./components/MassingView"));
const FrameView = lazy(() => import("./components/FrameView"));
const BuildView = lazy(() => import("./components/BuildView"));
const FacadeView = lazy(() => import("./components/FacadeView"));

// Course pitches offered on the Build tab. 300 is one course per
// storey -- the ceiling beam alone, i.e. the Frame tab's frame -- and
// anything finer fills the wall. All are whole divisions of a storey.
// 300 was described here but missing from the list -- it was tacked on
// after the loop as a bare "ceiling only" option, so the one pitch that
// matches the Frame tab sat last, out of numeric order and not looking
// like a pitch at all. It belongs in the list, at the top, and is the
// default.
const COURSE_OPTIONS = [300, 150, 100, 75, 60];

// A full mixed brief rather than housing alone: every unit type, the
// shared rooms that make it a building rather than a corridor of flats,
// and the open ground. Kept in step with DEFAULT_PROGRAM in
// backend/app/schemas.py, which is the API's default for a request that
// omits `program`.
const DEFAULT_PROGRAM = [
  "Lobby", "Studio_A", "Studio_B", "1Bed_A", "1Bed_B", "SK",
  "Workspace", "2Bed_A", "2Bed_B", "SL", "Gym", "3Bed_A",
  "3Bed_B", "Library", "4Bed_A", "4Bed_B", "Garden", "Playground",
];

const RATIOS = [50, 80, 100, 100, 80, 100, 100, 80, 50];
const NAMES = ["N", "SA", "SB", "SB", "SC", "SB", "SB", "SA", "N"];

const fmt = (v, d = 0) =>
  v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export default function App() {
  // `mode` is what the user picked (auto/light/dark); `theme` is what
  // that resolves to right now. The 3D views need the resolved one --
  // three.js has no cascade to inherit a scene colour from.
  const { mode, setMode, theme } = useTheme();
  const [catalog, setCatalog] = useState(null);
  // The nine panel types and their geometry. Static, so it is fetched
  // once beside the unit catalog rather than on every regenerate — it is
  // ~200KB and does not depend on the program.
  const [facadeCatalog, setFacadeCatalog] = useState(null);
  // The real plot the project sits on. Static, so fetched once.
  const [site, setSite] = useState(null);
  const [facade, setFacade] = useState(null);
  const [showMassing, setShowMassing] = useState(true);
  // The timber frame behind the panels. On by default: the panel module
  // (330) and the structural grid (360) are different, and seeing how a
  // panel meets a column is most of the point of this view.
  const [showFrameBehind, setShowFrameBehind] = useState(true);
  // Colour the panels by sun received instead of by type.
  const [heatmap, setHeatmap] = useState(false);
  // How the 330 cm panel module lands against the 360 cm structural bay.
  // They are incommensurable, so this is a choice, not a solve.
  const [align, setAlign] = useState("run");
  // Keep growth inside the real plot. On by default — the project has a
  // site, and a building that ignores it is a different drawing.
  const [constrainToSite, setConstrainToSite] = useState(true);
  // Isolate one panel type in the facade view, to read where it lands.
  const [onlyPanel, setOnlyPanel] = useState("");
  const [program, setProgram] = useState(DEFAULT_PROGRAM);
  const [seed, setSeed] = useState(42);
  const [plan, setPlan] = useState(null);
  const [massing, setMassing] = useState(null);
  const [frame, setFrame] = useState(null);
  // The Build tab's own frame: same plan, but with the walls filled at
  // a finer course pitch. Kept separate so the Frame tab keeps showing
  // the structural frame alone.
  const [buildFrame, setBuildFrame] = useState(null);
  // One course per storey by default, so Build opens on the same frame
  // the Frame tab draws. Drop to 100 to fill the walls with courses.
  const [courseCm, setCourseCm] = useState(300);
  const [perRoom, setPerRoom] = useState(true);
  const [animateGrowth, setAnimateGrowth] = useState(true);
  const [jointBlocks, setJointBlocks] = useState(false);
  // Ceilings read as the dominant surface from above, so they are worth
  // being able to drop. A view filter, not a rebuild -- the engine has
  // already sent them, and refetching to hide a member kind would throw
  // away the growth animation for nothing.
  const [showCeilings, setShowCeilings] = useState(true);
  // The dividers between the rooms inside a unit, as opposed to the
  // walls around it. Same filter mechanism as the ceilings.
  const [showPartitions, setShowPartitions] = useState(true);
  const [tab, setTab] = useState("plan");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [layers, setLayers] = useState({
    fills: true, rooms: true, walls: true, nodes: true, labels: true,
    shared: false, below: true, site: true,
  });
  // Which storey the plan draws. The plan stacks now, so drawing every
  // level at once would just overlay them.
  const [level, setLevel] = useState(0);

  useEffect(() => {
    getCatalog().then(setCatalog).catch((e) =>
      setError(`${e.message} — is the API running? Start it with: cd backend && uvicorn app.main:app --reload`)
    );
    // A missing facade catalog is not fatal: the other four views work
    // without it, and the Facade tab says what to run. So this failure
    // is kept out of the main error banner.
    getFacadeCatalog().then(setFacadeCatalog).catch((e) =>
      setFacadeCatalog({ error: e.message })
    );
    getSite().then(setSite).catch(() => setSite(null));
  }, []);

  const regenerate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const req = { program, seed, per_room: perRoom, constrain_to_site: constrainToSite };
      // The plan is deterministic in (program, seed), so asking the
      // frame endpoint twice returns two readings of the SAME building
      // -- the structural frame, and that frame with its walls filled.
      const [p, m, f, bf, fa] = await Promise.all([
        getPlan(req), getMassing(req), getFrame({ ...req, joint_blocks: jointBlocks }),
        getFrame({ ...req, joint_blocks: jointBlocks, course_cm: courseCm }),
        getFacade({ ...req, align }),
      ]);
      setPlan(p);
      setMassing(m);
      setFrame(f);
      setBuildFrame(bf);
      setFacade(fa);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [program, seed, perRoom, jointBlocks, courseCm, align, constrainToSite]);

  useEffect(() => { if (catalog) regenerate(); }, [catalog, regenerate]);

  // A shorter program can leave the selected level above the top of the
  // building, which would otherwise draw an empty plan with no clue why.
  useEffect(() => {
    if (plan && level > plan.level_count - 1) setLevel(0);
  }, [plan, level]);

  // Hiding a member kind drops it from what the views draw AND from the
  // counts the panel quotes, so the readout never claims members that
  // are not on screen. Identity is preserved when nothing is hidden, so
  // the views do not see a new object and rebuild for nothing.
  const hide = useMemo(() => {
    const s = new Set();
    if (!showCeilings) s.add("ceiling");
    if (!showPartitions) s.add("partition");
    return s;
  }, [showCeilings, showPartitions]);

  const visible = useCallback((f) => {
    if (!f || hide.size === 0) return f;
    const members = f.members.filter((m) => !hide.has(m.kind));
    return {
      ...f,
      members,
      summary: {
        ...f.summary,
        member_count: members.length,
        ceiling_count: hide.has("ceiling") ? 0 : f.summary.ceiling_count,
        partition_count: hide.has("partition") ? 0 : f.summary.partition_count,
      },
    };
  }, [hide]);

  const shownFrame = useMemo(() => visible(frame), [frame, visible]);
  const shownBuildFrame = useMemo(() => visible(buildFrame), [buildFrame, visible]);

  // Component census, walked client-side from the wall segments the API
  // already returns -- same 50:80:100:80 ratios as components.py.
  // Counted from plan.walls, so a shared wall contributes its components
  // once -- the census now matches what would actually be fabricated.
  const census = useMemo(() => {
    const c = { N: 0, SA: 0, SB: 0, SC: 0 };
    const len = { N: 0, SA: 0, SB: 0, SC: 0 };
    for (const w of plan?.walls ?? []) {
      for (const s of w.segments) {
        c[s.c] += 1;
        len[s.c] += Math.hypot(s.p[2] - s.p[0], s.p[3] - s.p[1]);
      }
    }
    return { c, len };
  }, [plan]);

  const s = plan?.stats;

  return (
    <div className="app">
      <header>
        <h1><b>LinX</b> Growth Engine</h1>
        <span className="sub">Floor plan &amp; massing</span>
        <div className="theme">
          <div className="seg" role="group" aria-label="Colour theme">
            {MODES.map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                aria-pressed={mode === m}
                title={m === "auto" ? `Follow the system — currently ${theme}` : `Always ${m}`}
              >
                {m}
              </button>
            ))}
          </div>
        </div>
      </header>

      <div className="layout">
        <div className="sidebar">
          <ProgramEditor
            program={program}
            setProgram={setProgram}
            catalog={catalog}
            suspect={plan?.suspect ?? []}
          />

          <div className="panel">
            <h2>Generate</h2>
            <label className="muted" style={{ display: "block", marginBottom: 8 }}>
              seed{" "}
              <input
                className="field num"
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                style={{ width: 76 }}
              />
            </label>
            <p className="note" style={{ marginBottom: 10, fontSize: 11 }}>
              The seed only varies where each flexible space lands inside its size
              range — every residential unit places deterministically. The program
              above is the real input.
            </p>
            <label className="muted" style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
              <input type="checkbox" checked={constrainToSite}
                     onChange={(e) => setConstrainToSite(e.target.checked)} />
              keep inside the site
            </label>
            <div className="btn-row">
              <button className="btn primary" onClick={regenerate} disabled={busy || !catalog}>
                {busy ? "Generating…" : "Regenerate"}
              </button>
              <button className="btn" onClick={() => setProgram(DEFAULT_PROGRAM)}>Reset</button>
            </div>
          </div>

          <div className="panel">
            <h2>Export</h2>
            <div className="btn-row">
              {["obj", "svg", "json"].map((k) => (
                <button key={k} className="btn" disabled={!plan}
                  onClick={() => download(k, { program, seed, per_room: perRoom }).catch((e) => setError(e.message))}>
                  .{k}
                </button>
              ))}
            </div>
            <p className="note" style={{ marginTop: 8, fontSize: 11 }}>
              OBJ is exported in metres, grouped per {perRoom ? "room" : "element"}.
            </p>
          </div>

          <div className="panel">
            <h2>Component census</h2>
            <table>
              <thead>
                <tr><th>Component</th><th className="n">Count</th><th className="n">Length</th></tr>
              </thead>
              <tbody>
                {["N", "SA", "SB", "SC"].map((k) => (
                  <tr key={k}>
                    <td>
                      {k === "N"
                        ? <span className="dot" />
                        : <span className="swatch" style={{ background: `var(--${k.toLowerCase()})` }} />}
                      {k}
                    </td>
                    <td className="n">{census.c[k]}</td>
                    <td className="n">{fmt(census.len[k] / 100)} m</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="main">
          {/* The error belongs to the main column, not the page: the
              sidebar is what you fix it with, so pushing that down was
              backwards. */}
          {error && <div className="banner">{error}</div>}

          <dl className="stats">
            <div className="stat"><dt>Units</dt><dd>{plan?.elements.filter((e) => e.kind === "unit").length ?? "—"}</dd></div>
            <div className="stat"><dt>Rooms</dt><dd>{plan?.elements.reduce((a, e) => a + e.rooms.length, 0) ?? "—"}</dd></div>
            <div className="stat">
              <dt>Extent</dt>
              <dd>{plan ? `${fmt((plan.extent_cm[2] - plan.extent_cm[0]) / 100)}×${fmt((plan.extent_cm[3] - plan.extent_cm[1]) / 100)}` : "—"}<span className="u">m</span></dd>
            </div>
            <div className="stat"><dt>Levels</dt><dd>{plan?.level_count ?? "—"}</dd></div>
            <div className="stat"><dt>Footprint</dt><dd>{s ? fmt(s.footprint_m2) : "—"}<span className="u">m² ground</span></dd></div>
            <div className="stat"><dt>Floor area</dt><dd>{s ? fmt(s.floor_area_m2 ?? 0) : "—"}<span className="u">m²</span></dd></div>
            {/* Only shown when there is open ground, so a purely
                residential program keeps the row it had. Deliberately
                separate from floor area — a garden is neither floor nor
                footprint, and adding it to either would read as density
                the scheme does not have. */}
            {s?.outdoor_area_m2 > 0 && (
              <div className="stat"><dt>Outdoor</dt><dd>{fmt(s.outdoor_area_m2)}<span className="u">m² open</span></dd></div>
            )}
            <div className="stat"><dt>Wall built</dt><dd>{s ? fmt(s.wall_length_m) : "—"}<span className="u">m</span></dd></div>
            <div className="stat"><dt>Shared</dt><dd>{s ? fmt(s.shared_wall_count) : "—"}<span className="u">of {s ? fmt(s.wall_count) : "—"}</span></dd></div>
          </dl>

          <div className="toolbar">
            <div className="seg" role="group" aria-label="View">
              <button onClick={() => setTab("plan")} aria-pressed={tab === "plan"}>Plan</button>
              <button onClick={() => setTab("massing")} aria-pressed={tab === "massing"}>3D massing</button>
              <button onClick={() => setTab("frame")} aria-pressed={tab === "frame"}>Frame</button>
              <button onClick={() => setTab("build")} aria-pressed={tab === "build"}>Build</button>
              <button onClick={() => setTab("facade")} aria-pressed={tab === "facade"}>Facade</button>
            </div>

            {tab === "plan" ? (
              <div className="toggles">
                {plan && plan.level_count > 1 && (
                  <span className="levels" role="group" aria-label="Level">
                    <button className="icon-btn" onClick={() => setLevel(Math.max(0, level - 1))}
                            disabled={level === 0} aria-label="Level down">−</button>
                    <span className="lv">L{level}</span>
                    <button className="icon-btn"
                            onClick={() => setLevel(Math.min(plan.level_count - 1, level + 1))}
                            disabled={level >= plan.level_count - 1} aria-label="Level up">+</button>
                  </span>
                )}
                {Object.keys(layers).map((k) => (
                  <label key={k}>
                    <input
                      type="checkbox"
                      checked={layers[k]}
                      onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })}
                    />
                    {k === "shared" ? "shared walls" : k === "below" ? "level below" : k}
                  </label>
                ))}
              </div>
            ) : tab === "facade" ? (
              <div className="toggles">
                <label>
                  <input type="checkbox" checked={heatmap}
                         onChange={(e) => setHeatmap(e.target.checked)} />
                  sun heatmap
                </label>
                <label>
                  <input type="checkbox" checked={showFrameBehind}
                         onChange={(e) => setShowFrameBehind(e.target.checked)} />
                  frame (ghosted)
                </label>
                <label>
                  <input type="checkbox" checked={showMassing}
                         onChange={(e) => setShowMassing(e.target.checked)} />
                  massing behind
                </label>
                <label>
                  module{" "}
                  <select className="field" value={align}
                          onChange={(e) => setAlign(e.target.value)}>
                    <option value="run">panels butt · 330</option>
                    <option value="grid">one per bay · 360</option>
                  </select>
                </label>
                <label>
                  only{" "}
                  <select className="field" value={onlyPanel}
                          onChange={(e) => setOnlyPanel(e.target.value)}>
                    <option value="">all panels</option>
                    {(facadeCatalog?.panels ?? []).map((p) => (
                      <option key={p.key} value={p.key}>{p.key} · {p.label}</option>
                    ))}
                  </select>
                </label>
              </div>
            ) : (
              <div className="toggles">
                {(tab === "massing" || tab === "build") && (
                  <label>
                    <input type="checkbox" checked={perRoom} onChange={(e) => setPerRoom(e.target.checked)} />
                    per-room massing
                  </label>
                )}
                <label>
                  <input type="checkbox" checked={animateGrowth} onChange={(e) => setAnimateGrowth(e.target.checked)} />
                  animate growth
                </label>
                {(tab === "frame" || tab === "build") && (
                  <label>
                    <input type="checkbox" checked={jointBlocks} onChange={(e) => setJointBlocks(e.target.checked)} />
                    full joint block
                  </label>
                )}
                {(tab === "frame" || tab === "build") && (
                  <label>
                    <input type="checkbox" checked={showCeilings} onChange={(e) => setShowCeilings(e.target.checked)} />
                    ceilings
                  </label>
                )}
                {(tab === "frame" || tab === "build") && (
                  <label>
                    <input type="checkbox" checked={showPartitions} onChange={(e) => setShowPartitions(e.target.checked)} />
                    room dividers
                  </label>
                )}
                {tab === "build" && (
                  <label>
                    course{" "}
                    <select
                      className="field"
                      value={courseCm}
                      onChange={(e) => setCourseCm(Number(e.target.value))}
                    >
                      {COURSE_OPTIONS.map((c) => (
                        <option key={c} value={c}>
                          {c} cm{c === 300 ? " · ceiling only" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
              </div>
            )}
          </div>

          {tab === "plan" && <PlanView plan={plan} layers={layers} level={level} site={site} />}
          {tab !== "plan" && (
            <Suspense fallback={<div className="viewport" style={{ padding: 20 }}><span className="muted">Loading 3D view…</span></div>}>
              {tab === "massing" && <MassingView massing={massing} animate={animateGrowth} theme={theme} />}
              {tab === "frame" && <FrameView frame={shownFrame} animate={animateGrowth} theme={theme} />}
              {tab === "build" && (
                <BuildView massing={massing} frame={shownBuildFrame} animate={animateGrowth} theme={theme} />
              )}
              {tab === "facade" && (
                facadeCatalog?.error ? (
                  <div className="viewport" style={{ padding: 20, display: "block" }}>
                    <p className="note warnbar">{facadeCatalog.error}</p>
                  </div>
                ) : (
                  <FacadeView
                    catalog={facadeCatalog} facade={facade} massing={massing}
                    frame={frame} theme={theme}
                    showMassing={showMassing} showFrame={showFrameBehind}
                    heat={heatmap} only={onlyPanel || null}
                  />
                )
              )}
            </Suspense>
          )}

          {tab === "build" && shownBuildFrame && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h2>Massing, then timber</h2>
              <p className="note">
                The volume rises first, in program order — entrance, corridor, core, branch
                corridors, then rooms. It fades to a ghost, and the surveyed components
                colonise it: <b>{shownBuildFrame.summary.member_count}</b> members filling the same
                walls the massing blocks stand on, at{" "}
                <b>{shownBuildFrame.summary.courses_per_storey}</b> course
                {shownBuildFrame.summary.courses_per_storey === 1 ? "" : "s"} to a storey
                ({courseCm} cm pitch).
              </p>
              <p className="note" style={{ marginTop: 8, fontSize: 11, color: "var(--ink-3)" }}>
                Growth is a three-dimensional front: it spreads out from the entrance across the
                node network <i>and</i> climbs, one ring per step, so a duplex fills from the
                ground up rather than arriving whole. Each storey stacks deck, volume, ceiling
                and beams — the pale soffit is the ceiling, the warmer plate below it the floor
                of the storey above.{" "}
                {shownBuildFrame.summary.courses_per_storey === 1
                  ? <>At one course to a storey the walls carry only that ceiling beam, which is
                      the frame the Frame tab draws. Drop the pitch to fill them with courses.</>
                  : <>The ceiling course of each storey stays on the wall centre line — it is the
                      structural beam — and the courses between it weave either side by half a
                      member, the way the surveyed capital's F1/F2 lacing layers do.</>}
              </p>
            </div>
          )}

          {tab === "facade" && facade?.summary && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h2>Cladding the envelope</h2>
              <p className="note">
                <b>{facade.summary.panel_count}</b> panels cover{" "}
                <b>{fmt(facade.summary.clad_length_m, 1)} m</b> of the{" "}
                <b>{fmt(facade.summary.exterior_length_m, 1)} m</b> exterior wall —{" "}
                <b>{fmt(facade.summary.clad_pct, 1)}%</b>. A panel is a fixed 330 cm
                component, so a run takes as many whole panels as fit and the rest is
                reported rather than stretched. Panels tile a RUN, not a wall: collinear
                exterior walls on one storey merge first, so a facade crossing from a
                unit into the lobby keeps its module and changes panel where the rooms
                change.
              </p>
              <p className="note" style={{ marginTop: 8, fontSize: 11, color: "var(--ink-3)" }}>
                The {fmt(facade.summary.unclad_length_m, 1)} m left over is two different
                problems. <b>{fmt(facade.summary.remainder_length_m, 1)} m</b> is remainder
                at the ends of runs that were clad — that wants a filler piece.{" "}
                <b>{fmt(facade.summary.too_short_length_m, 1)} m</b> is{" "}
                {facade.summary.too_short_count} runs narrower than any panel in the set,
                the widest {facade.summary.widest_too_short_cm} cm and nearly all of them
                corridor and core ends: no arrangement of these nine will ever cover
                those, they need a narrower type.
              </p>
              {facade.alignment && (
                <p className="note" style={{ marginTop: 10, fontSize: 11 }}>
                  <b>Against the columns.</b> The panel is a 330 cm module on a
                  50 cm post rhythm; the structural bay is a surveyed 360 cm.
                  360 is not a multiple of 50, so the two only realign every
                  39.6 m — there is no offset that fixes this, only a choice.{" "}
                  {facade.alignment.mode === "grid"
                    ? <><b>One panel per bay</b>: all{" "}
                        <b>{facade.alignment.panels}</b> panels are centred in a
                        structural bay, drift <b>0 cm</b>. Each column line keeps{" "}
                        <b>{facade.alignment.clear_to_column_cm} cm</b> clear either
                        side — but the column is 40 cm wide, so it laps{" "}
                        <b>{facade.alignment.column_lap_cm} cm</b> onto each
                        neighbouring panel. The panel is 10 cm too wide to sit
                        clear between columns; that lap is a fixing detail if it
                        was intended and a clash if it was not.</>
                    : <><b>Panels butt</b> at their own width and the run is
                        centred on the wall, so the facade is self-consistent and
                        drifts against the frame: only{" "}
                        <b>{facade.alignment.in_bay_pct}%</b> of panels land
                        centred in a bay, mean drift{" "}
                        <b>{facade.alignment.mean_offset_cm} cm</b>, worst{" "}
                        {facade.alignment.max_offset_cm} cm. Switch the{" "}
                        <b>module</b> control to one-per-bay to trade coverage for
                        alignment.</>}
                </p>
              )}

              {facade.connection_check && (
                <p className="note" style={{ marginTop: 10, fontSize: 11 }}>
                  {facade.connection_check.connected
                    ? <>verified · every panel column runs 0–{facade.connection_check.storey_cm} cm
                        on a {facade.connection_check.storey_cm} cm storey, so{" "}
                        <b>{facade.connection_check.stacked_pairs}</b> stacked pairs meet
                        column-on-column with no gap, and{" "}
                        <b>{facade.connection_check.adjacent_pairs}</b> neighbouring
                        pairs share an edge exactly. The module is anchored per
                        elevation, not per storey — that is what makes it stack.</>
                    : <><b>CHECK FAILED</b> · {facade.connection_check.vertical_gaps} vertical
                        and {facade.connection_check.horizontal_gaps} horizontal gaps
                        {facade.connection_check.misaligned_types.length > 0 &&
                          <>, panel types {facade.connection_check.misaligned_types.join(", ")} off
                            their storey datum</>}</>}
                </p>
              )}
              <p className="note" style={{ marginTop: 8, fontSize: 11, color: "var(--ink-3)" }}>
                Panel choice is a rule per row of the legend below: circulation takes{" "}
                <b>C</b>; a unit takes <b>B</b> at ground level, and higher up a{" "}
                <b>I</b> balcony on its principal elevation then <b>E</b>/<b>D</b> across
                it, with <b>D</b>/<b>A</b> on the flanks; a shared space takes{" "}
                <b>F</b>/<b>G</b>/<b>H</b> by how long the elevation is, so the most open
                panel lands on its best face. The panel module (330 cm) is deliberately
                not the structural bay (360 cm) — they are different systems.
              </p>
            </div>
          )}

          {tab === "frame" && shownFrame && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h2>Timber frame</h2>
              <p className="note">
                <b>{shownFrame.summary.member_count}</b> members — <b>{shownFrame.summary.post_count}</b> column
                parts standing at <b>{shownFrame.summary.node_count}</b> grid nodes,{" "}
                <b>{shownFrame.summary.beam_count}</b> primary beams over{" "}
                <b>{shownFrame.summary.span_count}</b> spans of the{" "}
                {(shownFrame.summary.grid_cm ?? 360) / 100} m grid,{" "}
                <b>{shownFrame.summary.infill_count}</b> infill members between the bays,{" "}
                {shownFrame.summary.partition_count > 0 && <>
                  <b>{shownFrame.summary.partition_count}</b> partition members dividing the
                  rooms inside the units,{" "}</>}
                <b>{shownFrame.summary.floor_count}</b> floor decks
                {shownFrame.summary.ceiling_count > 0
                  ? <> with <b>{shownFrame.summary.ceiling_count}</b> ceilings over them</>
                  : <> (ceilings hidden)</>}, and{" "}
                <b>{shownFrame.summary.plate_count}</b> connector plates.{" "}
                {shownFrame.summary.capital_count > 0
                  ? <>All <b>{shownFrame.summary.capital_count}</b> columns are topped with the woven
                      capital — <b>{shownFrame.summary.junction_count}</b> of them take three or more
                      beams, the rest fewer, but the head assembly is the same.</>
                  : <>Turn on <b>full joint block</b> to top every column with the woven
                      capital; <b>{shownFrame.summary.junction_count}</b> of the nodes take three or
                      more beams.</>}
              </p>
              <p className="note" style={{ marginTop: 8, fontSize: 11, color: "var(--ink-3)" }}>
                {shownFrame.summary.real_components
                  ? <>Sections are surveyed, read from <b>{shownFrame.summary.source}</b>: 10×10 posts on
                      30 cm centres, 20×10 beams, a 60×60 connector plate. The{" "}
                      {(shownFrame.summary.grid_cm ?? 360) / 100} m grid is surveyed too — the Beam A
                      assembly is 360×360 and its arm runs SA·SB·SC out to 180 cm, so one span is
                      N+SA+SB+SC+SB+SA+N and its five members are catalog parts with nothing left
                      over. Columns run unbroken from the ground, and growth spreads across{" "}
                      {shownFrame.summary.max_depth + 1} rings of grid <i>and</i> climbs.</>
                  : <>Drawing placeholder sections — run{" "}
                      <code>python -m growth_engine.glb_import components.glb</code> to load the
                      surveyed catalog.</>}
              </p>

              {shownFrame.summary.length_deviation?.sample > 0 && (
                <p className="note flagbar" style={{ marginTop: 12 }}>
                  <b>Primary beams are catalog parts; the infill is not all there yet.</b> Every
                  member on a grid span is exactly SA 70 / SB 80 / SC 60 cm. Wall infill divides
                  into 360 cm bays too, but a wall is rarely a whole number of them, so the last
                  bay of each run adapts — those members land a median{" "}
                  <b>{shownFrame.summary.length_deviation.median_cm} cm</b> from the nearest real
                  length, with <b>{shownFrame.summary.length_deviation.within_5cm_pct}%</b> within 5 cm
                  and a worst case of {shownFrame.summary.length_deviation.max_cm} cm.
                </p>
              )}

              {shownFrame.summary.joint_overlaps > 0 && (
                <p className="note warnbar" style={{ marginTop: 10 }}>
                  The full joint block is 240×240 cm, but{" "}
                  <b>{shownFrame.summary.joint_overlaps}</b> of {shownFrame.summary.node_count} columns
                  stand closer than that to a neighbour, so their capitals self-intersect. The
                  40×40 column and 60×60 plate fit at every node.
                </p>
              )}
            </div>
          )}

          {tab === "plan" && site && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h2>Site</h2>
              <p className="note">
                <b>{site.address}</b> — {site.lat.toFixed(6)}, {site.lon.toFixed(6)}.
                The triangle measures <b>{fmt(site.area_m2)} m²</b> to the street
                centrelines and <b>{fmt(site.developable_area_m2)} m²</b> after a{" "}
                {site.inset_m} m setback. A triangle loses area to a setback fast:
                all three edges come in at once and the corners are acute.
                {plan?.site_fit && (
                  <> <b>{plan.site_fit.elements_inside}</b> of{" "}
                    <b>{plan.site_fit.elements}</b> elements sit inside it —{" "}
                    <b>{fmt(plan.site_fit.area_inside_pct, 1)}%</b> of the built
                    footprint{plan.site_fit.fits ? ", so it fits" : ", so it overhangs"}.</>
                )}
              </p>
              {plan?.site_fit && (
                <p className="note" style={{ marginTop: 8, fontSize: 11 }}>
                  {plan.site_fit.constrained
                    ? <>Growth is <b>constrained to the plot</b>: nothing is placed
                        that does not lie wholly inside the boundary, at any level.
                        A run that cannot reach further stops, and the program goes
                        up a storey instead — the site is what makes it stack.</>
                    : <>Growth is <b>unconstrained</b> — the boundary is drawn but
                        not obeyed. Turn on <b>keep inside the site</b> in Generate
                        to enforce it.</>}
                  {plan.site_fit.off_site?.length > 0 && (
                    <> The entrance run and the core are laid down before any test
                      can run, and here{" "}
                      <b>{plan.site_fit.off_site.join(", ")}</b> ended up over the
                      line: the origin is too near an edge for this plot.</>
                  )}
                </p>
              )}
              <p className="note" style={{ marginTop: 8, fontSize: 11, color: "var(--ink-3)" }}>
                Corners are real OSM intersection nodes of Coffey St, Deptford
                Church St and Crossfield St — each pair of streets shares a node,
                so the corners are exact rather than two lines nearly meeting.
                Coffey St bears 87°, Deptford Church St 176°, so the plot is within
                4° of cardinal and the engine&rsquo;s own axes are already
                street-aligned (rotation {site.rotation_deg}°). The latitude now
                drives the facade sun study.
              </p>
            </div>
          )}

          {plan?.missing?.length > 0 && (
            <div className="banner" style={{ marginTop: 16 }}>
              Could not place: {plan.missing.join(", ")} — no free frontage was found on any branch.
            </div>
          )}

          {s && (
            <div className="panel sharedbar" style={{ marginTop: 16 }}>
              <h2>Shared walls</h2>
              <p className="note">
                The plan resolves to <b>{s.wall_count}</b> physical walls totalling{" "}
                <b>{fmt(s.wall_length_m, 1)} m</b>, of which <b>{s.shared_wall_count}</b> are
                shared between two elements — built once, referenced by both. Walking each
                element's own edges instead would have counted{" "}
                <b>{fmt(s.naive_length_m, 1)} m</b>, so deduplication removes{" "}
                <b>{fmt(s.saved_pct, 1)}%</b>. Turn on <b>shared</b> in the plan view to see them.
              </p>
              {plan?.wall_check && (
                <p className="note" style={{ marginTop: 8, fontSize: 11, color: "var(--ink-3)" }}>
                  {plan.wall_check.deduplicated
                    ? `verified · resolved ${fmt(plan.wall_check.resolved_length_m, 2)} m matches expected ${fmt(plan.wall_check.expected_length_m, 2)} m, no orphan walls`
                    : `CHECK FAILED · resolved ${fmt(plan.wall_check.resolved_length_m, 2)} m vs expected ${fmt(plan.wall_check.expected_length_m, 2)} m`}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
