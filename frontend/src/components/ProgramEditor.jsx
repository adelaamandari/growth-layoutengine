import { useState } from "react";

// The program list is the engine's only real design input: the seed
// only varies communal room widths, every residential unit lands
// deterministically. So this editor is the actual control surface.
export default function ProgramEditor({ program, setProgram, catalog, suspect }) {
  const [pick, setPick] = useState("");

  const residential = catalog?.residential_keys ?? [];
  const communal = catalog?.communal_keys ?? [];
  const byName = Object.fromEntries((catalog?.units ?? []).map((u) => [u.name, u]));

  const move = (i, delta) => {
    const j = i + delta;
    if (j < 0 || j >= program.length) return;
    const next = [...program];
    [next[i], next[j]] = [next[j], next[i]];
    setProgram(next);
  };
  const remove = (i) => setProgram(program.filter((_, k) => k !== i));
  const add = () => {
    if (!pick) return;
    setProgram([...program, pick]);
  };

  return (
    <div className="panel">
      <h2>Program · {program.length} entries</h2>

      <ul className="prog-list">
        {program.map((key, i) => {
          const u = byName[key];
          const isCommunal = !u;
          const isSuspect = suspect.includes(key);
          return (
            <li
              key={`${key}-${i}`}
              className={`prog-item${isCommunal ? " is-communal" : ""}${isSuspect ? " is-suspect" : ""}`}
            >
              <span className="idx">{String(i + 1).padStart(2, "0")}</span>
              <span className="nm" title={isSuspect ? "Not a catalog unit — built as a communal room" : key}>
                {key}
                <br />
                <span className="meta">
                  {u ? `${(u.width_cm / 100).toFixed(1)}×${(u.depth_cm / 100).toFixed(1)} m` : "flexible"}
                </span>
              </span>
              <span style={{ display: "flex", gap: 1 }}>
                <button className="icon-btn" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${key} up`}>↑</button>
                <button className="icon-btn" onClick={() => move(i, 1)} disabled={i === program.length - 1} aria-label={`Move ${key} down`}>↓</button>
                <button className="icon-btn" onClick={() => remove(i)} aria-label={`Remove ${key}`}>×</button>
              </span>
            </li>
          );
        })}
      </ul>

      <div className="add-row">
        <select value={pick} onChange={(e) => setPick(e.target.value)} aria-label="Type to add">
          <option value="">Add…</option>
          <optgroup label="Residential">
            {residential.map((k) => <option key={k} value={k}>{k}</option>)}
          </optgroup>
          <optgroup label="Communal">
            {communal.map((k) => <option key={k} value={k}>{k}</option>)}
          </optgroup>
        </select>
        <button className="btn" onClick={add} disabled={!pick}>Add</button>
      </div>

      {suspect.length > 0 && (
        <p className="note warnbar" style={{ marginTop: 10 }}>
          <b>{suspect.join(", ")}</b> {suspect.length === 1 ? "is" : "are"} not in the catalog,
          so the engine built {suspect.length === 1 ? "it" : "them"} as {suspect.length === 1 ? "a" : ""} blank
          communal {suspect.length === 1 ? "room" : "rooms"}. Check for a typo.
        </p>
      )}
    </div>
  );
}
