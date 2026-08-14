// us-atlas ships pre-built TopoJSON as plain .json files (ISC-licensed, bundled at
// build time — no runtime network fetch, no API key; see BranchMapCanvas.tsx). These
// ambient declarations pin the two files this app imports to topojson-specification's
// `Topology` type instead of letting `resolveJsonModule` infer a giant structural
// literal type from an ~800KB JSON file (slow to check, and not useful — we only ever
// consume these through topojson-client's `feature`/`mesh`, which take `Topology`).
declare module 'us-atlas/states-albers-10m.json' {
  import type { Objects, Topology } from 'topojson-specification';
  // Properties = {} (not the default GeoJsonProperties, which allows `null`) so
  // `.objects.X` lines up with topojson-client's feature()/mesh() signatures,
  // which default their own GeometryObject params to Properties = {}.
  const topology: Topology<Objects<{}>>;
  export default topology;
}

declare module 'us-atlas/counties-albers-10m.json' {
  import type { Objects, Topology } from 'topojson-specification';
  const topology: Topology<Objects<{}>>;
  export default topology;
}
