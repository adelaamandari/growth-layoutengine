import { useState } from "react";

// The program list is the engine's only real design input: the seed
// only varies the size a flexible space picks inside its range, every
// residential unit lands deterministically. So this editor is the actual
// control surface.
export default function ProgramEditor({ program, setProgram, catalog, suspect }) {
  const [pick, setPick] = useState("");

  const residential = catalog?.residential_keys ?? [];
  const communal = catalog?.communal_keys ?? [];
  const outdoor = catalog?.outdoor_keys ?? [];
  const byName = Object.fromEntries((catalog?.units ?? []).map((u) => [u.name, u]));
  const sharedByName = Object.fromEntries(
    (catalog?.shared_spaces ?? []).map((s) => [s.name, s])
  );

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

  // A unit quotes its surveyed footprint; a shared space quotes the
  // RANGE it will pick inside, because that is the only honest thing to
  // show before the plan is generated. An unrecognised key has neither.
  const meta = (key) => {
    const u = byName[key];
    if (u) return `${(u.width_cm / 100).toFixed(1)}×${(u.depth_cm / 100).toFixed(1)} m`;
    const s = sharedByName[key];
    if (!s) return "flexible";
    const rng = (a, b) => `${(a / 100).toFixed(0)}–${(b / 100).toFixed(0)}`;
    return `${rng(...s.frontage_cm)} × ${rng(...s.depth_cm)} m`;
  };

  return (
    <div className="panel">
      <h2>Program · {program.length} entries</h2>

      <ul className="prog-list">
        {program.map((key, i) => {
          const u = byName[key];
          const s = sharedByName[key];
          const isCommunal = !u;
          const isOutdoor = s?.kind === "outdoor";
          const isSuspect = suspect.includes(key);
          return (
            <li
              key={`${key}-${i}`}
              className={`prog-item${isCommunal ? " is-communal" : ""}${isOutdoor ? " is-outdoor" : ""}${isSuspect ? " is-suspect" : ""}`}
            >
              <span className="idx">{String(i + 1).padStart(2, "0")}</span>
              <span
                className="nm"
                title={
                  isSuspect
                    ? "Not a catalog unit — built as a blank flexible room"
                    : s
                      ? `${s.description} ${s.min_area_m2}–${s.max_area_m2} m²`
                      : key
                }
              >
                {key}
                <br />
                <span className="meta">{meta(key)}</span>
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
          <optgroup label="Shared rooms">
            {communal.map((k) => <option key={k} value={k}>{k}</option>)}
          </optgroup>
          <optgroup label="Outdoor">
            {outdoor.map((k) => <option key={k} value={k}>{k}</option>)}
          </optgroup>
        </select>
        <button className="btn" onClick={add} disabled={!pick}>Add</button>
      </div>

      {outdoor.some((k) => program.includes(k)) && (
        <p className="note" style={{ marginTop: 10, fontSize: 11, color: "var(--ink-3)" }}>
          Outdoor areas are laid on the ground after the building has stacked, so
          they land on level 0 wherever they sit in this order. They build no
          walls and are not floor area.
        </p>
      )}

      {suspect.length > 0 && (
        <p className="note warnbar" style={{ marginTop: 10 }}>
          <b>{suspect.join(", ")}</b> {suspect.length === 1 ? "is" : "are"} in neither
          catalog, so the engine built {suspect.length === 1 ? "it" : "them"} as{" "}
          {suspect.length === 1 ? "a" : ""} blank flexible{" "}
          {suspect.length === 1 ? "room" : "rooms"}. Check for a typo.
        </p>
      )}
    </div>
  );
}
