# SADMC Shield — SaaS Backend (Node.js)

Control-plane backend for SADMC Shield: tenant auth, API key management,
agent registration/metrics ingest/inference, remediation reporting,
dashboard REST API, and a real-time WebSocket event feed.

Built to be wire-compatible with the existing Python in-cluster agent at
`../Agent/` (do not need to change the agent) and to run the real trained
model at `../../SADMC-MT-FF-FL/saved_models/sadmc_global_model.pth` (not
the simplified sklearn model described in the design docs — see
`inference/export_to_onnx.py` for why/how).

## Stack

Express (plain JS, ESM) · PostgreSQL + TimescaleDB · Redis (cache + pub/sub)
· JWT + bcrypt · `onnxruntime-node` for model inference · `ws` for WebSocket.

## Setup

```bash
npm install
cp .env.example .env
docker compose up -d          # timescaledb (:5433) + redis (:6380)
npm run migrate               # applies db/schema.sql
npm start                     # listens on :8000 (INFERENCE_MODE=stub by default)
```

## Real model inference (ONNX)

The trained PyTorch model is exported once to ONNX so the backend's
runtime stays pure Node.js — no Python process required after export.

```bash
# one-time, using the existing torch venv:
SADMC-MT-FF-FL/sadmc-venv/bin/pip install onnx onnxruntime onnxscript
SADMC-MT-FF-FL/sadmc-venv/bin/python HelmAndSaas/Saas/inference/export_to_onnx.py

# mandatory parity gate before trusting the export:
SADMC-MT-FF-FL/sadmc-venv/bin/python HelmAndSaas/Saas/inference/verify_parity.py
npm run verify:parity

# then in .env:
INFERENCE_MODE=onnx
```

## Smoke test (no Kubernetes/Prometheus/Python needed)

`scripts/fake-agent.js` mirrors the real agent's request sequence
(register → ingest loop → remediation report) against this backend.
Auto-provisions a throwaway tenant + API key if `FAKE_AGENT_API_KEY` isn't set.

```bash
node scripts/fake-agent.js          # 5 quick cycles
node scripts/fake-agent.js --loop   # runs forever, ~15s interval like the real agent
```

## API surface

- `POST /auth/{register,login,refresh,logout}` — JWT access (15m) + opaque refresh token (7d)
- `GET/POST /api-keys`, `DELETE /api-keys/:id` — bcrypt-hashed, shown once
- `POST /v1/agent/{register,heartbeat}` — `X-API-Key` header
- `POST /v1/metrics/ingest` — `X-API-Key`; runs inference, persists anomalies, publishes to Redis
- `POST /v1/remediation/report` — `X-API-Key`; logs agent-executed remediation outcomes
- `GET /v1/clusters`, `/v1/clusters/:id/{services,anomalies,remediations,metrics}` — JWT
- `WS /ws/events` — JWT via `Sec-WebSocket-Protocol: Bearer,<token>` (or `?token=`)

## Notes

- The agent's own env vars (`SADMC_API_KEY`, `SAAS_ENDPOINT`, etc.) live in
  `../Helm/charts/sadmc-agent/values.yaml`, not in this backend's `.env`.
- Row-Level Security policies are defined in `db/schema.sql`, but this dev
  setup connects as the table owner (which bypasses RLS), so tenant
  isolation is additionally enforced by explicit `tenant_id` filters in
  `services/dashboardService.js`.
