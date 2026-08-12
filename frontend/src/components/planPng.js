/**
 * planPng.js
 * Rasterise the plan SVG to a high-resolution PNG, in the browser.
 *
 * Client-side on purpose. The other three exports go through the API
 * because the engine owns the geometry, but the plan is already drawn
 * here as an SVG, and rasterising it in the browser is the only way to
 * get exactly what is on screen -- same layers, same level, same zoom,
 * same theme. Asking the server for a PNG would mean a second renderer
 * that could disagree with this one, which is the class of bug this
 * project keeps finding.
 *
 * Two things have to be carried into the standalone image by hand,
 * because an SVG rasterised through an <img> is isolated from the page:
 *
 *   CUSTOM PROPERTIES  Every fill in PlanView is a var(--fill-unit) and
 *                      the like, resolved off :root. Inside the image
 *                      there is no :root to resolve against, so they are
 *                      copied in as a <style> on the svg itself.
 *   THE FONT           An <img> load fetches no external resources, so
 *                      the webfont is not there and labels fall back.
 *                      The face is inlined as base64 when it can be
 *                      fetched; see embedFont, which fails soft.
 */

const XMLNS = "http://www.w3.org/2000/svg";

/** Every --custom-property in force, as a CSS declaration block. */
function rootVariables() {
  const cs = getComputedStyle(document.documentElement);
  const out = [];
  for (let i = 0; i < cs.length; i += 1) {
    const name = cs[i];
    if (name.startsWith("--")) out.push(`${name}:${cs.getPropertyValue(name).trim()};`);
  }
  return out.join("");
}

/**
 * The page's own webfont, as an @font-face with the file inlined.
 *
 * Returns "" on any failure -- offline, CORS, a face that is not woff2.
 * A plan whose labels fell back to Century Gothic is worth having; an
 * export button that throws because the network was down is not.
 */
async function embedFont() {
  try {
    const link = [...document.querySelectorAll('link[rel="stylesheet"]')]
      .map((l) => l.href)
      .find((h) => h.includes("fonts.googleapis.com"));
    if (!link) return "";
    const css = await fetch(link).then((r) => r.text());
    // The first woff2 in the sheet is the latin face at the first weight,
    // which is what the labels are set in.
    const url = css.match(/url\((https:[^)]+\.woff2)\)/)?.[1];
    if (!url) return "";
    const buf = await fetch(url).then((r) => r.arrayBuffer());
    let bin = "";
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i += 1) bin += String.fromCharCode(bytes[i]);
    const b64 = btoa(bin);
    const family = (css.match(/font-family:\s*'([^']+)'/) || [])[1] || "Jost";
    return `@font-face{font-family:'${family}';src:url(data:font/woff2;base64,${b64}) format('woff2');font-weight:100 900;font-display:block;}`;
  } catch {
    return "";
  }
}

/**
 * Draw `svg` to a PNG and hand it to the browser as a download.
 *
 * `scale` multiplies the on-screen pixel size. 3 puts a 1200px-wide
 * viewport at 3600px, which prints legibly at A3 -- the point of the
 * feature is a drawing you can put in a document, not a screenshot.
 */
export async function exportPlanPng(svg, { scale = 3, filename = "plan.png" } = {}) {
  if (!svg) throw new Error("The plan view is not open — switch to the Plan tab first.");

  const rect = svg.getBoundingClientRect();
  const w = Math.max(1, Math.round(rect.width));
  const h = Math.max(1, Math.round(rect.height));

  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", XMLNS);
  clone.setAttribute("width", String(w));
  clone.setAttribute("height", String(h));

  const face = await embedFont();
  const style = document.createElementNS(XMLNS, "style");
  style.textContent = `${face} svg{${rootVariables()}}`;
  clone.insertBefore(style, clone.firstChild);

  const xml = new XMLSerializer().serializeToString(clone);
  const src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(xml)}`;

  const img = new Image();
  await new Promise((resolve, reject) => {
    img.onload = resolve;
    img.onerror = () => reject(new Error("The plan could not be rasterised."));
    img.src = src;
  });

  const canvas = document.createElement("canvas");
  canvas.width = w * scale;
  canvas.height = h * scale;
  const ctx = canvas.getContext("2d");
  // Painted, not left transparent: the plan is drawn FOR its background
  // -- the paper colour is what the wall strokes and labels are legible
  // against, and a transparent PNG dropped on a dark slide loses them.
  ctx.fillStyle = getComputedStyle(document.documentElement)
    .getPropertyValue("--paper").trim() || "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

  const blob = await new Promise((res) => canvas.toBlob(res, "image/png"));
  if (!blob) throw new Error("The PNG could not be encoded.");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return { width: canvas.width, height: canvas.height };
}
