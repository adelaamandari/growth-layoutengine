import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { download, getCatalog, getFrame, getMassing, getPlan } from "./api";
import PlanView from "./components/PlanView";
import ProgramEditor from "./components/ProgramEditor";

// three.js is ~600kB and only the 3D tabs need it, so they load on
// first use rather than blocking the plan view.
const MassingView = lazy(() => import("./components/MassingView"));
const FrameView = lazy(() => import("./components/FrameView"));
const BuildView = lazy(() => import("./components/BuildView"));

// Course pitches offered on the Build tab. 300 is one course per
// storey -- the ceiling beam alone, i.e. the Frame tab's frame -- and
// anything finer fills the wall. All are whole divisions of a storey.
const COURSE_OPTIONS = [150, 100, 75, 60];

const DEFAULT_PROGRAM = [
  "Studio_A", "Studio_B", "1Bed_A", "1Bed_B", "SK", "2Bed_A",
  "2Bed_B", "SL", "3Bed_A", "3Bed_B", "4Bed_A", "4Bed_B",
];

const RATIOS = [50, 80, 100, 100, 80, 100, 100, 80, 50];
const NAMES = ["N", "SA", "SB", "SB", "SC", "SB", "SB", "SA", "N"];

const fmt = (v, d = 0) =>
  v.toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });

export default function App() {
  const [catalog, setCatalog] = useState(null);
  const [program, setProgram] = useState(DEFAULT_PROGRAM);
  const [seed, setSeed] = useState(42);
  const [plan, setPlan] = useState(null);
  const [massing, setMassing] = useState(null);
  const [frame, setFrame] = useState(null);
  // The Build tab's own frame: same plan, but with the walls filled at
  // a finer course pitch. Kept separate so the Frame tab keeps showing
  // the structural frame alone.
  const [buildFrame, setBuildFrame] = useState(null);
  const [courseCm, setCourseCm] = useState(100);
  const [perRoom, setPerRoom] = useState(true);
  const [animateGrowth, setAnimateGrowth] = useState(true);
  const [jointBlocks, setJointBlocks] = useState(false);
  const [tab, setTab] = useState("plan");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [layers, setLayers] = useState({
    fills: true, rooms: true, walls: true, nodes: true, labels: true,
    shared: false, below: true,
  });
  // Which storey the plan draws. The plan stacks now, so drawing every
  // level at once would just overlay them.
  const [level, setLevel] = useState(0);

  useEffect(() => {
    getCatalog().then(setCatalog).catch((e) =>
      setError(`${e.message} — is the API running? Start it with: cd backend && uvicorn app.main:app --reload`)
    );
  }, []);

  const regenerate = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      const req = { program, seed, per_room: perRoom };
      // The plan is deterministic in (program, seed), so asking the
      // frame endpoint twice returns two readings of the SAME building
      // -- the structural frame, and that frame with its walls filled.
      const [p, m, f, bf] = await Promise.all([
        getPlan(req), getMassing(req), getFrame({ ...req, joint_blocks: jointBlocks }),
        getFrame({ ...req, joint_blocks: jointBlocks, course_cm: courseCm }),
      ]);
      setPlan(p);
      setMassing(m);
      setFrame(f);
      setBuildFrame(bf);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [program, seed, perRoom, jointBlocks, courseCm]);

  useEffect(() => { if (catalog) regenerate(); }, [catalog, regenerate]);

  // A shorter program can leave the selected level above the top of the
  // building, which would otherwise draw an empty plan with no clue why.
  useEffect(() => {
    if (plan && level > plan.level_count - 1) setLevel(0);
  }, [plan, level]);

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
        <p className="eyebrow">LinX Growth Engine</p>
        <h1>Floor plan &amp; massing</h1>
      </header>

      {error && <div className="banner">{error}</div>}

      <div className="layout">
        <div>
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
                type="number"
                value={seed}
                onChange={(e) => setSeed(Number(e.target.value))}
                style={{ width: 76, fontFamily: "var(--mono)", padding: "3px 5px",
                         background: "var(--paper)", color: "var(--ink)", border: "1px solid var(--rule)" }}
              />
            </label>
            <p className="note" style={{ marginBottom: 10, fontSize: 11.5 }}>
              The seed only varies communal room widths — every residential unit
              places deterministically. The program above is the real input.
            </p>
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
            <p className="note" style={{ marginTop: 8, fontSize: 11.5 }}>
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

        <div>
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
            <div className="stat"><dt>Wall built</dt><dd>{s ? fmt(s.wall_length_m) : "—"}<span className="u">m</span></dd></div>
            <div className="stat"><dt>Shared</dt><dd>{s ? fmt(s.shared_wall_count) : "—"}<span className="u">of {s ? fmt(s.wall_count) : "—"}</span></dd></div>
          </dl>

          <div className="toolbar">
            <div className="seg" role="group" aria-label="View">
              <button onClick={() => setTab("plan")} aria-pressed={tab === "plan"}>Plan</button>
              <button onClick={() => setTab("massing")} aria-pressed={tab === "massing"}>3D massing</button>
              <button onClick={() => setTab("frame")} aria-pressed={tab === "frame"}>Frame</button>
              <button onClick={() => setTab("build")} aria-pressed={tab === "build"}>Build</button>
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
                {tab === "build" && (
                  <label>
                    course{" "}
                    <select
                      value={courseCm}
                      onChange={(e) => setCourseCm(Number(e.target.value))}
                      style={{ fontFamily: "var(--mono)", fontSize: 11.5, padding: "2px 4px",
                               background: "var(--paper)", color: "var(--ink)", border: "1px solid var(--rule)" }}
                    >
                      {COURSE_OPTIONS.map((c) => (
                        <option key={c} value={c}>{c} cm</option>
                      ))}
                      <option value={300}>ceiling only</option>
                    </select>
                  </label>
                )}
              </div>
            )}
          </div>

          {tab === "plan" && <PlanView plan={plan} layers={layers} level={level} />}
          {tab !== "plan" && (
            <Suspense fallback={<div className="viewport" style={{ padding: 20 }}><span className="muted">Loading 3D view…</span></div>}>
              {tab === "massing" && <MassingView massing={massing} animate={animateGrowth} />}
              {tab === "frame" && <FrameView frame={frame} animate={animateGrowth} />}
              {tab === "build" && (
                <BuildView massing={massing} frame={buildFrame} animate={animateGrowth} />
              )}
            </Suspense>
          )}

          {tab === "build" && buildFrame && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h2>Massing, then timber</h2>
              <p className="note">
                The volume rises first, in program order — entrance, corridor, core, branch
                corridors, then rooms. It fades to a ghost, and the surveyed components
                colonise it: <b>{buildFrame.summary.member_count}</b> members filling the same
                walls the massing blocks stand on, at{" "}
                <b>{buildFrame.summary.courses_per_storey}</b> course
                {buildFrame.summary.courses_per_storey === 1 ? "" : "s"} to a storey
                ({courseCm} cm pitch).
              </p>
              <p className="note" style={{ marginTop: 8, fontSize: 11.5, color: "var(--ink-3)" }}>
                Growth is a three-dimensional front: it spreads out from the entrance across the
                node network <i>and</i> climbs, one ring per step, so a duplex fills from the
                ground up rather than arriving whole. The ceiling course of each storey stays on
                the wall centre line — it is the structural beam — and the courses between it
                weave either side by half a member, the way the surveyed capital's F1/F2 lacing
                layers do.
              </p>
            </div>
          )}

          {tab === "frame" && frame && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h2>Timber frame</h2>
              <p className="note">
                <b>{frame.summary.member_count}</b> members — <b>{frame.summary.post_count}</b> column
                parts standing at <b>{frame.summary.node_count}</b> grid nodes,{" "}
                <b>{frame.summary.beam_count}</b> primary beams over{" "}
                <b>{frame.summary.span_count}</b> spans of the{" "}
                {(frame.summary.grid_cm ?? 360) / 100} m grid,{" "}
                <b>{frame.summary.infill_count}</b> infill members between the bays,{" "}
                <b>{frame.summary.floor_count}</b> floor decks and{" "}
                <b>{frame.summary.plate_count}</b> connector plates.{" "}
                <b>{frame.summary.junction_count}</b> of the nodes are capitals, where three or
                more beams arrive.
              </p>
              <p className="note" style={{ marginTop: 8, fontSize: 11.5, color: "var(--ink-3)" }}>
                {frame.summary.real_components
                  ? <>Sections are surveyed, read from <b>{frame.summary.source}</b>: 10×10 posts on
                      30 cm centres, 20×10 beams, a 60×60 connector plate. The{" "}
                      {(frame.summary.grid_cm ?? 360) / 100} m grid is surveyed too — the Beam A
                      assembly is 360×360 and its arm runs SA·SB·SC out to 180 cm, so one span is
                      N+SA+SB+SC+SB+SA+N and its five members are catalog parts with nothing left
                      over. Columns run unbroken from the ground, and growth spreads across{" "}
                      {frame.summary.max_depth + 1} rings of grid <i>and</i> climbs.</>
                  : <>Drawing placeholder sections — run{" "}
                      <code>python -m growth_engine.glb_import components.glb</code> to load the
                      surveyed catalog.</>}
              </p>

              {frame.summary.length_deviation?.sample > 0 && (
                <p className="note flagbar" style={{ marginTop: 12 }}>
                  <b>Primary beams are catalog parts; the infill is not all there yet.</b> Every
                  member on a grid span is exactly SA 70 / SB 80 / SC 60 cm. Wall infill divides
                  into 360 cm bays too, but a wall is rarely a whole number of them, so the last
                  bay of each run adapts — those members land a median{" "}
                  <b>{frame.summary.length_deviation.median_cm} cm</b> from the nearest real
                  length, with <b>{frame.summary.length_deviation.within_5cm_pct}%</b> within 5 cm
                  and a worst case of {frame.summary.length_deviation.max_cm} cm.
                </p>
              )}

              {frame.summary.joint_overlaps > 0 && (
                <p className="note warnbar" style={{ marginTop: 10 }}>
                  The full joint block is 240×240 cm, but{" "}
                  <b>{frame.summary.joint_overlaps}</b> of {frame.summary.junction_count} capitals
                  sit closer than that to a neighbour, so it self-intersects there. The 40×40 column
                  and 60×60 plate fit at every node. Turn on <b>full joint block</b> to see it anyway.
                </p>
              )}
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
                <p className="note" style={{ marginTop: 8, fontSize: 11.5, color: "var(--ink-3)" }}>
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
