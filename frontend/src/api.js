// All geometry crosses the wire in CENTIMETRES, matching the engine.
// Convert for display only, never on the way in.

async function post(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* non-JSON error body; keep the status text */
    }
    throw new Error(detail);
  }
  return res;
}

export async function getCatalog() {
  const res = await fetch("/api/catalog");
  if (!res.ok) throw new Error("Could not load the unit catalog.");
  return res.json();
}

export async function getPlan(req) {
  return (await post("/api/plan", req)).json();
}

export async function getMassing(req) {
  return (await post("/api/massing", req)).json();
}

export async function getFrame(req) {
  return (await post("/api/frame", req)).json();
}

// Streams the file straight to the browser's downloader.
export async function download(kind, req) {
  const res = await post(`/api/export/${kind}`, req);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = { obj: "growth_engine.obj", svg: "plan.svg", json: "plan.json" }[kind];
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
