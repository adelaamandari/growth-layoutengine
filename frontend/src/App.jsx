import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { download, getCatalog, getFrame, getMassing, getPlan } from "./api";
import PlanView from "./components/PlanView";
import ProgramEditor from "./components/ProgramEditor";

// three.js is ~600kB and only the 3D tabs need it, so both load on
// first use rather than blocking the plan view.
const MassingView = lazy(() => import("./components/MassingView"));
const FrameView = lazy(() => import("./components/FrameView"));

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
  const [perRoom, setPerRoom] = useState(true);
  const [animateGrowth, setAnimateGrowth] = useState(true);
  const [jointBlocks, setJointBlocks] = useState(false);
  const [tab, setTab] = useState("plan");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [layers, setLayers] = useState({
    fills: true, rooms: true, walls: true, nodes: true, labels: true, shared: false,
  });

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
      const [p, m, f] = await Promise.all([
        getPlan(req), getMassing(req), getFrame({ ...req, joint_blocks: jointBlocks }),
      ]);
      setPlan(p);
      setMassing(m);
      setFrame(f);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [program, seed, perRoom, jointBlocks]);

  useEffect(() => { if (catalog) regenerate(); }, [catalog, regenerate]);

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
            <div className="stat"><dt>Footprint</dt><dd>{s ? fmt(s.footprint_m2) : "—"}<span className="u">m²</span></dd></div>
            <div className="stat"><dt>Wall built</dt><dd>{s ? fmt(s.wall_length_m) : "—"}<span className="u">m</span></dd></div>
            <div className="stat"><dt>Shared</dt><dd>{s ? fmt(s.shared_wall_count) : "—"}<span className="u">of {s ? fmt(s.wall_count) : "—"}</span></dd></div>
          </dl>

          <div className="toolbar">
            <div className="seg" role="group" aria-label="View">
              <button onClick={() => setTab("plan")} aria-pressed={tab === "plan"}>Plan</button>
              <button onClick={() => setTab("massing")} aria-pressed={tab === "massing"}>3D massing</button>
              <button onClick={() => setTab("frame")} aria-pressed={tab === "frame"}>Frame</button>
            </div>

            {tab === "plan" ? (
              <div className="toggles">
                {Object.keys(layers).map((k) => (
                  <label key={k}>
                    <input
                      type="checkbox"
                      checked={layers[k]}
                      onChange={(e) => setLayers({ ...layers, [k]: e.target.checked })}
                    />
                    {k === "shared" ? "shared walls" : k}
                  </label>
                ))}
              </div>
            ) : (
              <div className="toggles">
                {tab === "massing" && (
                  <label>
                    <input type="checkbox" checked={perRoom} onChange={(e) => setPerRoom(e.target.checked)} />
                    per-room massing
                  </label>
                )}
                <label>
                  <input type="checkbox" checked={animateGrowth} onChange={(e) => setAnimateGrowth(e.target.checked)} />
                  animate growth
                </label>
                {tab === "frame" && (
                  <label>
                    <input type="checkbox" checked={jointBlocks} onChange={(e) => setJointBlocks(e.target.checked)} />
                    full joint block
                  </label>
                )}
              </div>
            )}
          </div>

          {tab === "plan" && <PlanView plan={plan} layers={layers} />}
          {tab !== "plan" && (
            <Suspense fallback={<div className="viewport" style={{ padding: 20 }}><span className="muted">Loading 3D view…</span></div>}>
              {tab === "massing"
                ? <MassingView massing={massing} animate={animateGrowth} />
                : <FrameView frame={frame} animate={animateGrowth} />}
            </Suspense>
          )}

          {tab === "frame" && frame && (
            <div className="panel" style={{ marginTop: 16 }}>
              <h2>Timber frame</h2>
              <p className="note">
                <b>{frame.summary.member_count}</b> members — <b>{frame.summary.post_count}</b> column
                parts standing at <b>{frame.summary.node_count}</b> structural nodes,{" "}
                <b>{frame.summary.beam_count}</b> beams spanning between them, and{" "}
                <b>{frame.summary.plate_count}</b> connector plates.{" "}
                <b>{frame.summary.junction_count}</b> of those nodes are capitals, where three or
                more walls arrive.
              </p>
              <p className="note" style={{ marginTop: 8, fontSize: 11.5, color: "var(--ink-3)" }}>
                {frame.summary.real_components
                  ? <>Sections are surveyed, read from <b>{frame.summary.source}</b>: 10×10 posts on
                      30 cm centres, 20×10 beams, a 60×60 connector plate. Growth is topological,
                      not program order — it spreads breadth-first from the entrance across{" "}
                      {frame.summary.max_depth + 1} rings of nodes.</>
                  : <>Drawing placeholder sections — run{" "}
                      <code>python -m growth_engine.glb_import components.glb</code> to load the
                      surveyed catalog.</>}
              </p>

              {frame.summary.length_deviation?.sample > 0 && (
                <p className="note flagbar" style={{ marginTop: 12 }}>
                  <b>Members do not match the catalog.</b> The surveyed parts are fixed lengths
                  (SA 70, SB 80, SC 60 cm) but <code>components.py</code> rescales the sequence to
                  each wall, so drawn members land a median{" "}
                  <b>{frame.summary.length_deviation.median_cm} cm</b> from the nearest real
                  length — only <b>{frame.summary.length_deviation.within_5cm_pct}%</b> are within
                  5 cm, worst case {frame.summary.length_deviation.max_cm} cm. Fixing that means
                  changing how walls resolve, not just how they draw.
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
