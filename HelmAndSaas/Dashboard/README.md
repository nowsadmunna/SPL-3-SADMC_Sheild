# SADMC Shield — Dashboard (Angular + Tailwind)

Tenant-facing SPA for SADMC Shield: auth, API key management, cluster/service
health, live anomaly feed, remediation log, and per-service metrics charts.
Talks to the Node.js backend at `../Saas/`.

## Stack

Angular 20 (standalone components, signals) · Tailwind CSS v4 · chart.js +
ng2-charts · native WebSocket for the live event feed.

## Setup

```bash
npm install
ng serve   # http://localhost:4200
```

The backend must be running at `http://localhost:8000` (see `../Saas/README.md`).
API base URL / WebSocket URL are set in `src/app/core/api-config.ts`.

## Structure

- `core/` — `auth.service` (JWT + refresh, signals), `auth.interceptor` (attaches
  Bearer token, silent-refreshes once on 401), `auth.guard`, `cluster.service`
  (clusters/services/anomalies/remediations/metrics REST calls + the selected-cluster
  signal), `events.service` (WebSocket client, auto-reconnect), `api-key.service`.
- `layout/shell/` — topbar (org name, cluster selector, logout) + side nav.
- `pages/` — `login`, `register`, `dashboard-overview` (service health cards),
  `anomaly-feed` (live), `remediation-log` (live), `metrics` (chart.js small
  multiples — one chart per metric, since different-scale metrics never share
  an axis), `settings` (API key generate/list/revoke).
- `shared/anomaly-badge/` — color-coded pill by anomaly type.

## Notes

- WebSocket auth uses `new WebSocket(url, ["Bearer", accessToken])` (the
  `Sec-WebSocket-Protocol` header), matching `../Saas/ws/wsServer.js`.
- Live event frames carry `cluster_uuid`; the Anomaly Feed / Remediation Log
  pages filter incoming frames against the currently selected cluster so
  events from a tenant's other clusters don't leak into the wrong view.
- Verified end-to-end with Playwright against a running backend + `fake-agent.js`,
  including a live (no-refresh) WebSocket update test.
