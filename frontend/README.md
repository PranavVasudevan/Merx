# frontend

TypeScript quant terminal - dense, real-time, dark. Candles, treemaps, heatmaps, peer graphs, stress waterfalls. Phase 7.

**Requires signing in** (real OIDC via Keycloak — see `platform/auth/README.md`).
Local dev test users: `viewer1`/`viewer123` (read-only) or `analyst1`/`analyst123`
(can also run the Feature 16 stress simulator). Bring up
`docker compose -f ../platform/docker/docker-compose.dev.yml up -d keycloak opa`
before `npm run dev`.

