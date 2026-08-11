// prism.js
// Turn a footprint's REAL corners into a solid, instead of extruding its
// bounding box.
//
// WHY THIS EXISTS
// Every element used to be an axis-aligned rectangle, so `BoxGeometry`
// built from min/max of the corners was not an approximation -- the box
// WAS the shape. The site strategy broke that: it lays each frontage
// band on the grid of the street it fronts, so elements now sit at 4 and
// 58 degrees off cardinal.
//
// A 10 x 4 m unit rotated 58 degrees has a bounding box about three times
// its area. Drawn that way the building reads as a pile of overlapping
// blocks -- on one test plan, 20 pairs of bounding boxes intersected
// while ZERO pairs of real footprints did. The plan was correct and the
// picture was not, which is the worst way round for a drawing tool.
//
// So: build a Shape from the actual corners and extrude it.

import * as THREE from "three";

// The engine works in centimetres; three.js is happier around unit
// scale. Same constant as frameInstances, kept here so this module can
// be used without pulling in the frame machinery.
export const CM_TO_M = 0.01;

/**
 * A vertical prism over `corners` (engine cm, any number of points, any
 * rotation), `heightCm` tall.
 *
 * Its BASE sits at local y = 0, so the caller positions it by setting
 * mesh.position.y to the slab height. That is deliberate and it is what
 * makes the growth animation work: scaling y then grows the block upward
 * from its own slab, with no position correction. The old BoxGeometry
 * was centred on its own middle, so it had to be re-positioned every
 * frame as it scaled or it sank into the ground.
 */
export function prismGeometry(corners, heightCm) {
  const shape = new THREE.Shape();
  corners.forEach(([x, y], i) => {
    const sx = x * CM_TO_M;
    const sy = y * CM_TO_M;
    if (i === 0) shape.moveTo(sx, sy);
    else shape.lineTo(sx, sy);
  });
  shape.closePath();

  const geo = new THREE.ExtrudeGeometry(shape, {
    depth: Math.max(heightCm, 0.1) * CM_TO_M,
    bevelEnabled: false,
  });

  // ExtrudeGeometry builds in XY and extrudes along +Z. The engine is
  // Z-up with plan in XY; three.js is Y-up with plan in XZ. Rotating -90
  // about X sends shape-y to world -z and the extrusion to world +y, so
  // engine (x, y) lands at world (x, ·, -y) -- the same mapping every
  // other view uses -- and the prism grows upward.
  geo.rotateX(-Math.PI / 2);
  return geo;
}

/** Edge lines for the same prism, so it reads as a drawn solid. */
export function prismEdges(geo, color, opacity = 0.35) {
  return new THREE.LineSegments(
    new THREE.EdgesGeometry(geo),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity })
  );
}

/**
 * True plan area of a footprint, in m2, by the shoelace formula.
 *
 * Bounding-box area is what the summaries used to quote and it is wrong
 * by the same factor the geometry was: it over-reports a rotated
 * footprint, so a building that turns to follow a street appears to gain
 * floor area by turning.
 */
export function polygonAreaM2(corners) {
  let s = 0;
  for (let i = 0; i < corners.length; i += 1) {
    const [x0, y0] = corners[i];
    const [x1, y1] = corners[(i + 1) % corners.length];
    s += x0 * y1 - x1 * y0;
  }
  return Math.abs(s) / 2 / 10_000;
}

/**
 * The site boundary as a closed loop lying on the ground plane.
 *
 * Drawn at a hair above zero rather than exactly at it: the ground grid
 * sits at y=0 too, and two coplanar surfaces z-fight into a flickering
 * dashed mess as the camera moves.
 */
export function siteOutline(THREE, boundaryCm, color, opacity = 1) {
  const pts = boundaryCm.map(
    ([x, y]) => new THREE.Vector3(x * CM_TO_M, 0.02, -y * CM_TO_M)
  );
  pts.push(pts[0].clone());
  return new THREE.Line(
    new THREE.BufferGeometry().setFromPoints(pts),
    new THREE.LineBasicMaterial({ color, transparent: true, opacity })
  );
}

/**
 * Add the plot to a scene group: the developable boundary solid, the
 * street centrelines faint behind it. Every 3D view draws it the same
 * way, from one place, so they cannot drift apart.
 *
 * `box`, if given, is expanded to include the site so the camera frames
 * the plot rather than only the building standing on it.
 */
export function addSiteOutline(THREE, group, site, box) {
  if (!site) return;
  const green = 0x7d8a6a;
  const outer = siteOutline(THREE, site.centreline_cm, green, 0.35);
  const inner = siteOutline(THREE, site.boundary_cm, green, 0.9);
  group.add(outer);
  group.add(inner);
  if (box) box.expandByObject(outer);
}
