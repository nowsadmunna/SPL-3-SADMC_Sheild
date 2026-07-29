# SADMC Shield — API & Data Flow Reference

This document describes the SaaS backend (`HelmAndSaas/Saas/`) built for SADMC Shield: every
HTTP/WebSocket endpoint it exposes, how a request flows through the system end-to-end, and
why each piece of infrastructure (PostgreSQL/TimescaleDB, Redis, ONNX Runtime) is used the
way it is. It documents the *real, running* implementation — where that diverges from the
original design docs (`SADMC_Shield_Architecture.md`, `SADMC_Shield_Midterm_Report.docx`),
this file reflects what's actually built.

## 1. System at a glance

```
┌──────────────────────────┐        ┌───────────────────────────────────────────┐        ┌─────────────────┐
│   In-Cluster Agent        │        │            SaaS Backend (Node.js)          │        │  Angular         │
│  (HelmAndSaas/Agent)      │        │            HelmAndSaas/Saas/               │        │  Dashboard        │
│                           │  HTTPS │  Express routes ─▶ services ─▶ ONNX model  │  WSS   │                  │
│  discovers services       │───────▶│  auth · api-keys · agent · metrics ·       │◀──────▶│  login/register  │
│  queries Prometheus       │ X-API- │  remediation · dashboard · /ws/events      │  JWT   │  cluster health  │
│  runs remediation actions │  Key   │                                             │        │  live feed, etc. │
└──────────────────────────┘        └──────────┬───────────────────┬─────────────┘        └─────────────────┘
                                                │                   │
                                     PostgreSQL │                   │ Redis
                                     +TimescaleDB│                  │ (cache + pub/sub)
                                                ▼                   ▼
                                     tenants, api_keys,       api-key lookup cache,
                                     clusters, services,      events:{tenant_id}
                                     anomaly_events,          pub/sub channel
                                     remediation_actions,
                                     metrics (hypertable)
```

Two authentication schemes are used, matching who's calling:

- **`X-API-Key` header** — the in-cluster Agent authenticates every request with the API key
  generated for its tenant. Used by all `/v1/agent/*`, `/v1/metrics/*`, `/v1/remediation/*` routes.
- **`Authorization: Bearer <JWT>`** — the human tenant, via the dashboard, authenticates with a
  short-lived (15 min) access token. Used by `/api-keys/*`, all `/v1/clusters*` routes, and the
  `/ws/events` WebSocket.

## 2. End-to-end data flow

This is the actual lifecycle, phase by phase, with the endpoints and infrastructure touched
at each step.

### Phase 1 — Tenant onboarding
1. `POST /auth/register` creates a `tenants` row (bcrypt-hashed password).
2. `POST /auth/login` returns a 15-minute JWT **access token** and a 7-day opaque **refresh
   token** (the refresh token's bcrypt hash is stored in `refresh_tokens`; the plaintext token
   itself encodes `tenant_id` so a refresh/logout call can find its own candidate rows without
   a lookup column that would defeat the point of hashing it).
3. `POST /api-keys` generates a per-cluster credential (`sadmc_sk_live_...`), returns the
   **plaintext key exactly once**; only its bcrypt hash and a display prefix are stored.

### Phase 2 — Agent bootstrap (inside the tenant's cluster)
4. The agent calls `POST /v1/agent/register` with its self-generated `cluster_id` and the
   `X-API-Key` header. The backend resolves the key → tenant (via `apiKeyService.resolveApiKey`,
   Redis-cached), upserts a `clusters` row, and returns the `cluster_uuid` the agent will use
   for every subsequent call.

### Phase 3 — Continuous monitoring loop (every ~15s, driven by the agent)
5. The agent posts a batch to `POST /v1/metrics/ingest`: one entry per discovered service, each
   with a human-readable `metrics` object *and* a fixed-order 35-float `feature_vector`.
6. For each service, the backend:
   - upserts a `services` row and inserts one row into the `metrics` **TimescaleDB hypertable**;
   - pads the feature vector to 36 values and runs it through the exported **ONNX model**
     (`inference/onnxModel.js`) — softmax → predicted class + confidence;
   - if anomalous, inserts an `anomaly_events` row and **publishes** a JSON frame to the Redis
     channel `events:{tenant_id}`;
   - returns `{service_name, anomaly_type, confidence, is_anomaly, event_id}` per service —
     `event_id` is the new `anomaly_events.id`, which the agent will echo back in Phase 4.
7. Any browser connected to `/ws/events` for that tenant receives the `ANOMALY_DETECTED` frame
   immediately, via the WebSocket server's Redis subscriber.

### Phase 4 — Remediation (decided and executed entirely by the agent)
8. The agent's own rule table decides the action (`THROTTLE_CPU` / `RESTART_POD` / `SCALE_UP`)
   and executes it directly against the Kubernetes API — the backend has no say in this.
9. The agent reports the outcome via `POST /v1/remediation/report` with the `event_id` from
   step 6. The backend inserts a `remediation_actions` row (looking up a display `action_type`
   from a local mirror of the agent's rule table, keyed by the parent anomaly's type) and
   publishes a `REMEDIATION_EXECUTED` frame to the same Redis channel.

### Phase 5 — Dashboard (human tenant, browser)
10. The Angular app calls `GET /v1/clusters`, then the cluster-scoped `GET /v1/clusters/:id/*`
    routes to render service health, anomaly history, remediation history, and metrics charts.
11. It also opens `WS /ws/events` (JWT via the `Sec-WebSocket-Protocol` header) to receive live
    `ANOMALY_DETECTED` / `REMEDIATION_EXECUTED` frames without polling, filtering them client-side
    by `cluster_uuid` so a tenant with multiple clusters only sees the selected one's events.

## 3. Full API reference

All request/response bodies below are JSON. UUIDs and keys shown are illustrative.

### 3.1 Auth — `/auth/*` (no auth required)

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register` | Create a tenant account |
| POST | `/auth/login` | Exchange credentials for tokens |
| POST | `/auth/refresh` | Exchange a refresh token for a new access token |
| POST | `/auth/logout` | Revoke a refresh token |

**`POST /auth/register`**
```json
// Request
{ "organization_name": "Acme Corp", "email": "acme@example.com", "password": "hunter2pass" }

// Response 201
{ "tenant": {
    "id": "b7e1a2c4-1111-4a2b-9c3d-000000000001",
    "organization_name": "Acme Corp",
    "email": "acme@example.com",
    "subscription_plan": "free",
    "created_at": "2026-07-29T13:52:53.672Z"
} }
```

**`POST /auth/login`**
```json
// Request
{ "email": "acme@example.com", "password": "hunter2pass" }

// Response 200
{
  "access_token": "eyJhbGciOi...",   // JWT, 15 min expiry, {tenant_id}
  "refresh_token": "OTNiNjZk...",     // opaque, 7 day expiry
  "tenant": { "id": "b7e1...", "organization_name": "Acme Corp", "email": "acme@example.com" }
}
```

**`POST /auth/refresh`**
```json
// Request
{ "refresh_token": "OTNiNjZk..." }
// Response 200
{ "access_token": "eyJhbGciOi..." }   // new 15-minute token
```

**`POST /auth/logout`**
```json
// Request
{ "refresh_token": "OTNiNjZk..." }
// Response 204 (no body) — the refresh token is marked revoked
```

### 3.2 API Keys — `/api-keys/*` (`Authorization: Bearer <access_token>`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/api-keys` | List this tenant's keys (metadata only) |
| POST | `/api-keys` | Generate a new key (plaintext shown once) |
| DELETE | `/api-keys/:id` | Revoke a key |

**`POST /api-keys`**
```json
// Request
{ "name": "prod-cluster" }

// Response 201 — the ONLY time the plaintext key is ever returned
{
  "id": "d4a5b6c7-2222-4a2b-9c3d-000000000002",
  "key_prefix": "sadmc-sk-live-EXAMPLE",
  "name": "prod-cluster",
  "is_active": true,
  "created_at": "2026-07-29T13:53:08.712Z",
  "api_key": "<REDACTED — 64 hex chars, shown once at creation, never logged or stored in plaintext>"
}
```

**`GET /api-keys`**
```json
// Response 200 — plaintext/hash never included
{ "api_keys": [
  { "id": "d4a5b6c7-...", "key_prefix": "sadmc-sk-live-EXAMPLE", "name": "prod-cluster",
    "is_active": true, "created_at": "2026-07-29T13:53:08.712Z", "last_used_at": "2026-07-29T14:16:45.759Z" }
] }
```

**`DELETE /api-keys/:id`** → `204`. The key's `is_active` flips to `false`; it stops
authenticating within `API_KEY_CACHE_TTL_SECONDS` (default 300s) even if it was cached.

### 3.3 Agent — `/v1/agent/*` (`X-API-Key: <api_key>`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/v1/agent/register` | First contact — resolve/mint a `cluster_uuid` |
| POST | `/v1/agent/heartbeat` | Explicit liveness ping (ingest also refreshes this) |

**`POST /v1/agent/register`**
```json
// Request
{ "cluster_id": "5f240edf-3012-4945-93a3-951536ce6c43" }   // agent-generated uuid4
// Response 200
{ "cluster_uuid": "5f240edf-3012-4945-93a3-951536ce6c43" } // normally echoed back verbatim
```

**`POST /v1/agent/heartbeat`**
```json
// Request
{ "cluster_uuid": "5f240edf-3012-4945-93a3-951536ce6c43" }
// Response 200
{ "status": "ok" }
```

### 3.4 Metrics ingest — `/v1/metrics/ingest` (`X-API-Key`) — the core pipeline

```json
// Request
{
  "timestamp": "2026-07-29T14:16:45.700Z",
  "cluster_uuid": "5f240edf-3012-4945-93a3-951536ce6c43",
  "services": [
    {
      "service_name": "payment",
      "namespace": "sock-shop",
      "metrics": {
        "cpu_user": 12.1, "cpu_system": 4.3, "cpu_total": 16.4, "cpu_throttled": 0, "cpu_cfs_periods": 0,
        "mem_rss": 210.5, "mem_cache": 40.1, "mem_swap": 0, "mem_failcnt": 0, "mem_usage": 256.0,
        "...": "…30 more raw Prometheus-derived fields (see METRIC_QUERIES in the Agent)",
        "cpu_usage_percent": 16.4, "memory_usage_mb": 256.0, "network_latency_ms": 10.0,
        "request_rate": 5.0, "error_rate": 0.0, "cpu_trend": 1.2, "memory_trend": -3.4
      },
      "feature_vector": [12.1, 4.3, 16.4, 0, 0, 210.5, 40.1, "...35 floats total, fixed order"]
    }
  ]
}

// Response 200
{ "results": [
  {
    "service_name": "payment",
    "namespace": "sock-shop",
    "anomaly_type": "CPU_HOG",           // NORMAL | CPU_HOG | MEMORY_LEAK | NETWORK_DELAY
    "confidence": 0.94,
    "is_anomaly": true,
    "event_id": "e3a1c2b4-3333-4a2b-9c3d-000000000003"   // null when anomaly_type is NORMAL
  }
] }
```

What happens per service on the backend, in order: upsert `services` → insert one `metrics`
hypertable row (5 typed columns + a `raw_metrics` JSONB blob with everything) → run ONNX
inference → if anomalous, insert `anomaly_events` and publish to Redis. An unknown
`cluster_uuid` returns `{"results": []}` (HTTP 200) rather than an error, so a stale agent
doesn't crash-loop.

### 3.5 Remediation report — `/v1/remediation/report` (`X-API-Key`)

```json
// Request
{
  "cluster_uuid": "5f240edf-3012-4945-93a3-951536ce6c43",
  "event_id": "e3a1c2b4-3333-4a2b-9c3d-000000000003",
  "status": "success",              // success | failed
  "error_message": null
}
// Response 204 (no body)
```

The backend never decides *what* remediation to run — the agent already executed it. This
call only persists the outcome (`remediation_actions` row, `action_type` looked up for display
from the parent anomaly's type) and publishes `REMEDIATION_EXECUTED` to Redis.

### 3.6 Dashboard — `/v1/clusters*` (`Authorization: Bearer <access_token>`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/clusters` | List the tenant's clusters |
| GET | `/v1/clusters/:id/services` | Discovered services for a cluster |
| GET | `/v1/clusters/:id/anomalies?limit=&offset=` | Anomaly history, newest first |
| GET | `/v1/clusters/:id/remediations?limit=&offset=` | Remediation history, newest first |
| GET | `/v1/clusters/:id/metrics?start=&end=&service_name=` | Time-series metrics for charts |

```json
// GET /v1/clusters → 200
{ "clusters": [
  { "id": "a1b2c3d4-...", "cluster_uuid": "5f240edf-...", "k8s_version": null,
    "node_count": null, "agent_version": null, "status": "active",
    "last_heartbeat": "2026-07-29T14:16:45.759Z", "created_at": "2026-07-29T13:56:09.314Z" }
] }

// GET /v1/clusters/:id/anomalies → 200
{ "anomalies": [
  { "id": "e3a1c2b4-...", "service_name": "payment", "namespace": "sock-shop",
    "anomaly_type": "CPU_HOG", "confidence": 0.94, "timestamp": "2026-07-29T14:16:45.789Z" }
] }
```

Every `:id` route first checks the cluster belongs to the calling tenant (`404` otherwise) —
this application-level check is the real enforcement of multi-tenant isolation in this dev
setup (see §4.1 on why Row-Level Security alone isn't sufficient here).

### 3.7 Live events — `WS /ws/events`

Connect with the JWT access token as a WebSocket sub-protocol:
```js
new WebSocket("ws://localhost:8000/ws/events", ["Bearer", accessToken]);
```
(`?token=<jwt>` query param also accepted.) The server verifies the JWT on the upgrade
request, resolves `tenant_id`, and adds the socket to a per-tenant fan-out set. Frames:

```json
{ "type": "ANOMALY_DETECTED", "cluster_uuid": "5f240edf-...", "service_name": "payment",
  "namespace": "sock-shop", "anomaly_type": "CPU_HOG", "confidence": 0.94,
  "timestamp": "2026-07-29T14:16:45.789Z" }

{ "type": "REMEDIATION_EXECUTED", "cluster_uuid": "5f240edf-...", "service_name": "payment",
  "namespace": "sock-shop", "action": "THROTTLE_CPU", "status": "success",
  "timestamp": "2026-07-29T14:16:45.807Z" }
```

Every connected browser for a tenant receives every frame for that tenant (across all its
clusters) — `cluster_uuid` is included so the frontend can filter to whichever cluster is
currently selected.

## 4. Infrastructure — what's used, why, and how

### 4.1 PostgreSQL + TimescaleDB

**What it is**: PostgreSQL is the relational store for everything that isn't a raw metric
reading — tenants, API keys, clusters, services, anomaly events, remediation actions.
**TimescaleDB** is a PostgreSQL extension (`CREATE EXTENSION timescaledb;`) that turns one
specific table into a *hypertable* — transparently partitioned by time under the hood, while
still queried with ordinary SQL.

**Why it's used here**: the `metrics` table receives one row per service per ~15-second
ingest cycle, indefinitely, across every tenant's every cluster. That's a classic time-series
write/query pattern (append-mostly, always filtered/ordered by time) that a plain PostgreSQL
table handles fine at small scale but degrades on as data grows — indexes and vacuum both
get more expensive on one ever-growing table. TimescaleDB's hypertable auto-partitions by
time so recent-data queries (which is what every dashboard chart needs — "last hour for this
service") stay fast, and `add_retention_policy('metrics', INTERVAL '90 days')` (see
`db/schema.sql`) makes dropping old data a built-in background job instead of a manual
`DELETE` that would otherwise have to scan the whole table.

**Concretely in this project**:
- `db/schema.sql` defines the hypertable and retention policy.
- `services/metricsService.js` inserts one row per service per ingest call — 5 typed columns
  (`cpu_usage_percent`, `memory_usage_mb`, `network_latency_ms`, `request_rate`, `error_rate`)
  for fast chart queries, plus a `raw_metrics` JSONB column with the full ~42-field payload
  and feature vector (kept for future model retraining/debugging, not used by any current query).
- `services/dashboardService.js`'s `queryMetrics` is the only reader — a time-range +
  service-name filtered `SELECT`, which is exactly the query shape TimescaleDB optimizes for.
- Every other table (`tenants`, `api_keys`, `clusters`, `services`, `anomaly_events`,
  `remediation_actions`, `refresh_tokens`) is ordinary PostgreSQL — they're low-volume,
  relational, and gain nothing from hypertable partitioning.

### 4.2 Redis

Redis is used for two unrelated jobs in this project — worth calling out separately, since
they're accessed via two separate connections (`redis/client.js` exports `redis` and
`redisSub`; `ioredis` requires a dedicated connection once you call `.subscribe`/`.psubscribe`
on it, so one connection can't serve both roles).

**Role 1 — API key validation cache** (`services/apiKeyService.js`). API keys are stored as
bcrypt hashes (correctly — never plaintext), but bcrypt is *deliberately* slow (that's what
makes it resistant to brute-forcing), and the agent authenticates with `X-API-Key` on every
single ingest call, every ~15 seconds, forever. Running a bcrypt compare against every active
key on every request would mean paying that cost constantly for no security benefit (the key
isn't changing between requests). So on first successful validation, `resolveApiKey` caches
`sha256(raw_key) → {tenant_id, api_key_id}` in Redis with a 5-minute TTL
(`API_KEY_CACHE_TTL_SECONDS`); subsequent requests in that window hit Redis (fast) instead of
re-running bcrypt. A revoked key can stay valid for up to that TTL — a documented,
deliberate trade-off (matches the original architecture doc's own caching design).

**Role 2 — pub/sub fan-out for the live dashboard feed** (`services/eventService.js` +
`ws/wsServer.js`). When an anomaly is detected or a remediation is reported, the backend
needs to notify *every currently-connected browser tab* for that tenant, immediately, without
polling. Redis pub/sub is a natural fit: `eventService.js` does
`redis.publish('events:{tenant_id}', JSON.stringify(frame))` on every anomaly/remediation;
`ws/wsServer.js` maintains one long-lived `redisSub.psubscribe('events:*')` subscription and
fans each message out to the in-memory set of WebSocket connections for that tenant. This
also happens to decouple "what detects an anomaly" from "what pushes it to a browser" — if
the backend were ever scaled to multiple processes, every process's WebSocket server would
independently receive every publish and only forward it to *its own* connected sockets,
without needing any cross-process coordination beyond the shared Redis instance.

**Why Redis specifically, not just in-memory state**: both roles are ephemeral (a stale
cache entry or a missed pub/sub message during a restart is a minor, self-healing
inconvenience — not persisted data). An external Redis process — rather than an in-process
`Map` — is what makes the pub/sub fan-out work at all beyond a single process, and is also
just simpler to reason about than adding a home-grown TTL-cache module for the API-key case.

### 4.3 ONNX Runtime (`onnxruntime-node`)

**What it is**: a runtime that executes a neural network exported to the ONNX (Open Neural
Network Exchange) format, in pure JavaScript/Node — no Python process involved.

**Why it's used here**: the real trained anomaly classifier
(`SADMC-MT-FF-FL/saved_models/sadmc_global_model.pth`) is a custom PyTorch model (a 1D-CNN +
External Attention hybrid, `MLSTM` in `SADMC-MT-FF-FL/code/network_fed.py`) — not the simple
scikit-learn model the original design docs describe. PyTorch itself only runs in Python.
Since the backend is explicitly a Node.js service, the model was exported **once, offline**
(`HelmAndSaas/Saas/inference/export_to_onnx.py`, run with the Python venv that already had
torch installed) to a `.onnx` file, and the Node backend loads and runs *that* via
`onnxruntime-node` at request time — Python is a one-time build step, never a runtime
dependency. Numeric parity between the original PyTorch model and the exported ONNX version
was verified against 19 fixture vectors (`inference/verify_parity.{py,js}`) before this was
trusted in the ingest path — every fixture matched within `1e-4`.

**Concretely**: `inference/onnxModel.js` loads `inference/model/sadmc_model.onnx` once at
process startup (a singleton `InferenceSession`), and `predict(featureVector)` pads the
35-value input to 36, replaces `NaN`/`Infinity` with 0, runs the session, applies softmax,
and returns `{anomaly_type, confidence, is_anomaly}`. `services/inferenceService.js` sits in
front of it with an `INFERENCE_MODE=stub|onnx` switch — `stub` always returns `NORMAL`,
which is what let the rest of the ingest pipeline (persistence, Redis publish, response
shape) get built and tested before the real model was wired in.

## 5. Tech stack summary

| Concern | Technology | Why |
|---|---|---|
| API framework | Express (Node.js, ESM) | Matches the explicit "Node.js backend" requirement; simple, well-understood routing/middleware model |
| Relational data | PostgreSQL 16 | Tenants, API keys, clusters, events, remediation — all relational, low volume |
| Time-series data | TimescaleDB (Postgres extension) | Auto-partitioning + retention policy for the ever-growing `metrics` table (§4.1) |
| Cache + pub/sub | Redis (`ioredis`) | API-key validation cache (avoid bcrypt on every request) and cross-connection event fan-out (§4.2) |
| Auth | `jsonwebtoken` + `bcrypt` | Short-lived JWT access tokens, bcrypt-hashed passwords/API keys/refresh tokens |
| ML inference | `onnxruntime-node` | Runs the real trained PyTorch model, exported once to ONNX, with a pure-Node runtime (§4.3) |
| Real-time transport | `ws` (WebSocket) | Native browser WebSocket API support, no extra client library needed |
| Frontend | Angular 20 + Tailwind CSS v4 | Explicit requirement; standalone components + signals, no state-management library needed at this scope |
| Charts | Chart.js + ng2-charts | Small-multiple line charts per metric (never dual-axis — see the dataviz method used for the Metrics page) |







Why Redis pub/sub sits between the detector and the WebSocket
Your instinct is right that a WebSocket, once open, absolutely can push to the browser directly — that part's not in question. The question is: how does the code that just found an anomaly get the message to the right socket object sitting in memory?

In your current setup — one Node process — you're correct that it's technically overkill: eventService.js could reach into wsServer.js's in-memory Map<tenant_id, Set<ws>> directly and call .send(). No Redis required for that.

The reason it's built with Redis pub/sub anyway is what happens the moment you're not running just one process — which is the normal case for any real SaaS backend (multiple replicas behind a load balancer, or several Kubernetes pods):

The scenario that breaks without it:

The agent's POST /v1/metrics/ingest request gets routed by the load balancer to Instance A.
The tenant's browser opened its WebSocket a few minutes earlier, and got routed to Instance B.
Instance A detects the anomaly. It has no way to reach into Instance B's memory — they're separate processes, possibly separate machines. Instance A doesn't even know Instance B exists, let alone that it's the one holding this tenant's socket.
What Redis pub/sub does: it's a shared message bus every instance can talk to. Instance A doesn't try to find "the right instance" — it just publishes to a channel (events:{tenant_id}), like posting to a shared bulletin board. Every instance (A, B, C…) is independently subscribed. Whichever one actually holds that tenant's live socket (Instance B) receives the message and relays it to its own local connections. Instance A never needs to know or care where the browser is connected.

Analogy: the anomaly detector is a reporter who doesn't personally deliver newspapers door-to-door. They broadcast over the radio (Redis). Every local radio station (server instance) that's tuned in hears it and relays it to whoever's listening in their area. The reporter never needs a list of listeners' addresses.

Why it's worth having even today, with one process:

Separation of concerns — eventService.js just states a fact ("this happened, for tenant X") without knowing anything about WebSocket connection management; wsServer.js just relays whatever arrives without knowing anything about why it happened. Each piece stays simple and testable on its own.
Free scaling later — if this ever runs as multiple replicas, zero code changes are needed anywhere. Without Redis, you'd have to retrofit exactly this kind of cross-instance messaging under time pressure later.
Honest tradeoff: Redis pub/sub is fire-and-forget — if nobody's subscribed at the exact instant of publish, that message is gone (no replay). That's fine here because it's just the live-update convenience layer; the anomaly itself is already safely committed to anomaly_events in Postgres regardless of whether any browser happened to be connected at that moment.