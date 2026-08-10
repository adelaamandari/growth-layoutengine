// Scene colours for the three three.js views, in one place so they
// cannot drift apart. The light set is the LinX Massing Engine palette
// from phase2/UI-STYLE-SPEC.md; hex numbers because that is what
// three.js takes, and the same values are CSS custom properties in
// styles.css.
//
// The spec defines no dark palette, so the dark set comes from the
// supplied reference (the Polyblock hero): true black, achromatic, high
// contrast. These match the dark tokens in styles.css.

const SCENES = {
  light: {
    background: 0xf1f3f5,  // --bg-dark
    gridMajor: 0xb9bfc5,   // --border-dark
    gridMinor: 0xd3d8dd,   // --border-medium
    edge: 0x969da4,        // --text-tertiary
    lightScale: 1,
  },
  dark: {
    // The reference's own black, so the canvas and the page around it
    // are the same ground and the viewport border is the only seam.
    background: 0x000000,
    gridMajor: 0x2e2e2e,
    gridMinor: 0x171717,
    // Mesh colours do NOT invert (see KIND_COLOR), so a pale box needs a
    // DARKER edge to read against itself, not a lighter one. Inverting
    // this with the background is the obvious move and the wrong one.
    edge: 0x000000,
    // A lit model on black takes less light than one on a white page, or
    // the pale volumes blow out. Not lower than this, though: the
    // reference's whole character is bright forms against real black,
    // and dimming the model to match the room throws that away.
    lightScale: 0.8,
  },
};

export const sceneTheme = (theme) => SCENES[theme] ?? SCENES.light;

// Massing volumes stay in the palette's neutral greys rather than taking
// the spec's saturated zone fills (residential #6e2424 and friends).
// Two reasons, both about what these views are for: the Build view exists
// to read the timber growing INSIDE a ghosted envelope, and a dark
// maroon shell muddies the wood it is meant to reveal; and per-room
// massing subdivides a unit, so the unit's own hue would be carrying no
// information anyway.
//
// These do not change with the theme either. The building is a lit
// object; the theme changes the room it stands in, not the model. Making
// the volumes dark in dark mode would leave nothing to light.
//
// Outdoor is the exception to the neutrals and takes the spec's green
// (#7d8a6a) at full strength, because there the colour IS the
// information: that pad is ground, not a storey.
export const KIND_COLOR = {
  corridor: 0xcfccc6,   // spec: corridor
  core: 0x9a9690,       // spec: core / lobby
  unit: 0xeaedf0,       // --border-light
  communal: 0xd3d8dd,   // --border-medium
  room: 0xe4e7ea,       // --bg-medium
  outdoor: 0x7d8a6a,    // spec: green / garden / playground
};

export const KIND_FALLBACK = 0xbdbab5;  // spec: default / fallback

// Repaint an existing scene for a theme change.
//
// Deliberately NOT a teardown: rebuilding the renderer would drop the
// camera wherever the user had orbited it and restart the growth
// animation from zero, which is a lot to pay for a change of colour.
//
// `state` is the views' stateRef object; it must carry `scene`, may
// carry a `grid` to replace, and may carry `lights` as
// [{ light, base }] where `base` is the intensity at lightScale 1.
export function applySceneTheme(THREE, state, theme) {
  const t = sceneTheme(theme);
  state.scene.background = new THREE.Color(t.background);

  // GridHelper bakes its two colours into vertex colours at
  // construction, so there is nothing to reassign -- it gets rebuilt.
  // One small mesh, and only on a theme change.
  if (state.grid) {
    state.scene.remove(state.grid);
    state.grid.geometry.dispose();
    state.grid.material.dispose();
  }
  state.grid = new THREE.GridHelper(200, 40, t.gridMajor, t.gridMinor);
  state.scene.add(state.grid);

  for (const l of state.lights ?? []) l.light.intensity = l.base * t.lightScale;

  // Block outlines are the one mesh colour that DOES follow the theme --
  // a pale volume needs a dark edge on a dark ground and a mid-grey one
  // on a white page. Recoloured in place: they are built inside the
  // geometry effect, and adding `theme` to that effect's deps instead
  // would rebuild every mesh and restart the growth animation, which is
  // a lot of motion to spend on an outline.
  state.group?.traverse((o) => {
    if (o.isLineSegments && o.material?.color) o.material.color.setHex(t.edge);
  });

  return t;
}
