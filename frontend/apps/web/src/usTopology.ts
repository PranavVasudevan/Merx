// State/county boundaries for BranchMapCanvas, from us-atlas's pre-built Census
// TopoJSON — bundled at install time (npm install us-atlas topojson-client d3-geo),
// zero runtime network calls, ISC/public-domain licensed. No map-tile provider, no
// API key: same offline posture the hand-rolled projection this replaced (formerly
// albers.ts, removed as part of E7 — see docs/audit/04-remediation-prompts.md) had,
// just with real boundary data and AK/HI insets this time.
//
// `states-albers-10m.json` / `counties-albers-10m.json` are PRE-PROJECTED with
// Alaska and Hawaii already repositioned as insets, using d3-geo's geoAlbersUsa()
// with its default scale (1070) and translate ([480, 250]) — that's the exact
// convention these files were built with, so geometries and freshly-projected
// branch points share one coordinate space with no extra fitting math needed. See
// https://github.com/topojson/us-atlas.
import { geoAlbersUsa, geoPath } from 'd3-geo';
import { feature, mesh } from 'topojson-client';
import type { Feature, MultiPolygon, Polygon } from 'geojson';
import statesTopology from 'us-atlas/states-albers-10m.json';
import countiesTopology from 'us-atlas/counties-albers-10m.json';

/** A single county polygon carrying its FIPS `id` — see `countyFeatures` below. */
export type CountyFeature = Feature<Polygon | MultiPolygon, { name?: string }> & { id: string };

/** Projects (lon, lat) into the same coordinate space the bundled topology is pre-projected in. */
export const usAlbersProjection = geoAlbersUsa();

/** Nation outline — a single (multi)polygon, cheap to fill+stroke every frame. */
export const nationFeature = feature(statesTopology, statesTopology.objects.nation);

/** Interior state borders only (shared edges deduped) — cheap, always drawn. */
export const stateMesh = mesh(statesTopology, statesTopology.objects.states, (a, b) => a !== b);

/** Interior county borders — 3,142 counties' worth of paths; only draw past a zoom threshold. */
export const countyMesh = mesh(countiesTopology, countiesTopology.objects.counties, (a, b) => a !== b);

/** [[minX, minY], [maxX, maxY]] of the nation outline, in projected units — used to fit the map to the canvas. */
export const nationBounds = geoPath().bounds(nationFeature);

/**
 * Every individual county polygon (not just the deduped interior mesh above), each
 * carrying `id` = the 5-digit zero-padded Census FIPS state+county code — verified
 * directly against the bundled us-atlas JSON (e.g. "04015" for Mohave County, AZ),
 * the exact format `banklens_transforms.footprint.county_key()` produces server-side
 * for `get_county_concentration`'s `fips` field, so features join to API rows by a
 * plain string match with no reformatting. Used by CountyChoropleth (MarketSharePage)
 * to fill/outline individual counties rather than just stroke shared borders.
 */
export const countyFeatures = (
  feature(countiesTopology, countiesTopology.objects.counties) as unknown as {
    features: CountyFeature[];
  }
).features;
