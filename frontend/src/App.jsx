import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import { download, getCatalog, getMassing, getPlan } from "./api";
import PlanView from "./components/PlanView";
import ProgramEditor from "./components/ProgramEditor";

// three.js is ~600kB and only the massing tab needs it, so it loads on
// first use rather than blocking the plan view.
const MassingView = lazy(() => import("./components/MassingView"));

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
  const [perRoom, setPerRoom] = useState(true);
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
      const [p, m] = await Promise.all([getPlan(req), getMassing(req)]);
      setPlan(p);
      setMassing(m);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }, [program, seed, perRoom]);

  useEffect(() => { if (catalog) regenerate(); }, [catalog, regenerate]);

  // Component census, walked client-side from the wall segments the API
  // already returns -- same 50:80:100:80 ratios as components.py.
  const census = useMemo(() => {
    const c = { N: 0, SA: 0, SB: 0, SC: 0 };
    const len = { N: 0, SA: 0, SB: 0, SC: 0 };
    for (const el of plan?.elements ?? []) {
      for (const w of el.walls) {
        c[w.c] += 1;
        len[w.c] += Math.hypot(w.p[2] - w.p[0], w.p[3] - w.p[1]);
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
            <div className="stat"><dt>Wall drawn</dt><dd>{s ? fmt(s.wall_length_m) : "—"}<span className="u">m</span></dd></div>
            <div className="stat flag"><dt>Built twice</dt><dd>{s ? fmt(s.shared_length_m) : "—"}<span className="u">m</span></dd></div>
          </dl>

          <div className="toolbar">
            <div className="seg" role="group" aria-label="View">
              <button onClick={() => setTab("plan")} aria-pressed={tab === "plan"}>Plan</button>
              <button onClick={() => setTab("massing")} aria-pressed={tab === "massing"}>3D massing</button>
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
                <label>
                  <input type="checkbox" checked={perRoom} onChange={(e) => setPerRoom(e.target.checked)} />
                  per-room massing
                </label>
              </div>
            )}
          </div>

          {tab === "plan" ? (
            <PlanView plan={plan} layers={layers} />
          ) : (
            <Suspense fallback={<div className="viewport" style={{ padding: 20 }}><span className="muted">Loading 3D view…</span></div>}>
              <MassingView massing={massing} />
            </Suspense>
          )}

          {plan?.missing?.length > 0 && (
            <div className="banner" style={{ marginTop: 16 }}>
              Could not place: {plan.missing.join(", ")} — no free frontage was found on any branch.
            </div>
          )}

          {s && s.shared_length_m > 0 && (
            <div className="panel flagbar" style={{ marginTop: 16 }}>
              <h2>Shared boundaries</h2>
              <p className="note">
                <b>{fmt(s.shared_length_m, 1)} m</b> of the {fmt(s.wall_length_m, 1)} m drawn is
                boundary the engine builds <b>twice</b>, once from each side, across{" "}
                <b>{s.shared_count}</b> interfaces. A material take-off would over-count by{" "}
                <b>{fmt(s.shared_pct, 1)}%</b>. Turn on <b>shared walls</b> in the plan view to see where.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
