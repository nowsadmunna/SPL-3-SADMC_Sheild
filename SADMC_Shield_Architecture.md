# SADMC SHIELD

**Anomaly Detection & Auto-Remediation SaaS for Microservices Architecture**

*SADMC Shield — Technical Architecture*

| | |
| --- | --- |
| **Student** | Md. Nowsad Hossen Munna |
| **Roll No.** | 1407 |
| **Supervisor** | Dr. Naushin Nower |
| **Institute** | Institute of Information Technology (IIT) |
| **University** | University of Dhaka |
| **Document Type** | Technical Architecture Specification |
| **Version** | 2.0 — Final |

---

## Table of Contents

1. System Overview
2. End-to-End System Flow
3. SaaS Backend — Control Plane
4. Helm Chart & In-Cluster Agent
5. Database Schema
6. API Specification
7. React Dashboard
8. Security Architecture
9. Technology Stack
10. Implementation Roadmap
11. Quick Start — Demo Setup
12. Glossary

---

## 1. System Overview

SADMC Shield is a cloud-native SaaS platform that provides real-time anomaly detection and automated remediation for microservices running on Kubernetes. The system is built on a two-plane architecture — a central SaaS Control Plane hosted by the developer, and a lightweight Data Plane Agent that runs inside each user's Kubernetes cluster via a Helm Chart.

### 1.1 Design Philosophy

The architecture follows three core principles:

- **Separation of concerns:** The model inference is performed centrally in the SaaS backend. The in-cluster agent remains lightweight, only collecting metrics and executing Kubernetes actions — it contains no ML model.
- **Privacy-preserving:** Raw metrics leave the cluster only as numerical time-series vectors. No source code, secrets, or business logic is ever transmitted.
- **Zero-trust security:** Every agent authenticates via a per-tenant API Key. All communication is TLS-encrypted. The agent runs under a least-privilege Kubernetes ServiceAccount.

### 1.2 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    USER'S KUBERNETES CLUSTER                        │
│                                                                       │
│  ┌──────────────────┐    ┌───────────────────┐    ┌──────────────┐ │
│  │   Prometheus     │───▶│   SADMC Agent     │───▶│ Kubernetes   │ │
│  │  (existing OR    │    │   (Helm Chart)    │    │    API       │ │
│  │  auto-installed) │    │                   │    │ (remediation)│ │
│  └──────────────────┘    └────────┬──────────┘    └──────────────┘ │
│                                   │  HTTPS + X-API-Key              │
└───────────────────────────────────┼─────────────────────────────────┘
                                    │
                    ┌───────────────▼──────────────────────────────┐
                    │          SADMC SHIELD SAAS PLATFORM           │
                    │                                               │
                    │  ┌─────────┐ ┌──────────┐ ┌──────────────┐  │
                    │  │  Auth & │ │  Model   │ │  PostgreSQL  │  │
                    │  │ API Key │ │Inference │ │ + TimescaleDB│  │
                    │  │ Service │ │ (FastAPI)│ │              │  │
                    │  └─────────┘ └──────────┘ └──────────────┘  │
                    │  ┌──────────────────────┐ ┌──────────────┐  │
                    │  │    Redis (cache +     │ │   React      │  │
                    │  │    pub/sub)           │ │  Dashboard   │  │
                    │  └──────────────────────┘ └──────────────┘  │
                    └───────────────────────────────────────────────┘
```

### 1.3 Component Roles at a Glance

| Component | Runs On | Responsibility |
| --- | --- | --- |
| SaaS Backend (FastAPI) | Developer's server (AWS/GCP/etc.) | Auth, inference, event storage, API gateway |
| Model Inference Engine | Inside SaaS backend | Runs the trained SADMC model, returns anomaly class + confidence |
| PostgreSQL + TimescaleDB | Inside SaaS backend | Stores tenants, clusters, anomaly events, metrics time-series |
| Redis | Inside SaaS backend | API Key cache, WebSocket pub/sub broker |
| React Dashboard | Browser (served by SaaS) | Real-time anomaly feed, charts, remediation history |
| SADMC Agent (Helm Chart) | User's Kubernetes cluster | Service discovery, metrics collection, remediation execution |
| Prometheus | User's cluster (existing or auto) | Metrics scraping from all pods |

---

## 2. End-to-End System Flow

The following describes the complete lifecycle from a new user signing up to automated remediation executing inside their cluster.

### 2.1 Phase 1 — User Onboarding

- **Registration:** User visits the SADMC Shield dashboard, enters email, password, and organisation name. A Tenant record is created in the database with a unique tenant_id.
- **API Key Generation:** After logging in, the user navigates to Settings → API Keys and generates a new key. The system creates a cryptographically random 32-byte token, hashes it with bcrypt, and stores only the hash. The plaintext key is shown once and must be copied immediately.
- **Helm Installation:** The dashboard shows the user a ready-to-copy helm install command with their API Key pre-filled.

```bash
helm repo add sadmc https://charts.sadmc.io
helm repo update

helm install sadmc-agent sadmc/sadmc-agent \
  --namespace sadmc \
  --create-namespace \
  --set sadmc.apiKey="sadmc_sk_live_t1407_xxxxxxxxxxxxxxxx" \
  --set sadmc.saasEndpoint="https://api.sadmc.io"

# If user already has Prometheus:
# --set prometheus.mode="existing" \
# --set prometheus.existingUrl="http://prometheus-server.monitoring:9090"
```

### 2.2 Phase 2 — Agent Bootstrap (inside the cluster)

When `helm install` runs, Kubernetes creates the following resources from the Helm templates:

- **Secret** — stores the API Key (base64-encoded at rest)
- **ConfigMap** — all non-secret configuration (SaaS endpoint, Prometheus mode, remediation rules)
- **ServiceAccount + ClusterRole + ClusterRoleBinding** — RBAC permissions for the agent pod
- **Deployment** — pulls the Docker image and starts the agent pod. The pod reads config from the Secret and ConfigMap as environment variables
- **Conditional Prometheus** — if `prometheus.mode` is `install` or auto-detect finds none, a Prometheus Deployment and Service are also created

On startup, the agent pod executes the following initialisation sequence:

1. Loads Kubernetes in-cluster config (uses the mounted ServiceAccount token automatically).
2. Reads all config from environment variables injected by the Helm ConfigMap and Secret.
3. Runs Prometheus auto-detection (if `mode=auto`) — checks common service names across namespaces.
4. Calls `POST /v1/agent/register` on the SaaS API with its API Key. The SaaS validates the key, looks up the tenant, and returns a `cluster_uuid` that the agent caches for all future calls.
5. Enters the continuous monitoring loop.

### 2.3 Phase 3 — Continuous Monitoring Loop (every 15 seconds)

```
EVERY 15 SECONDS:

  Step 1 — Service Discovery
    kubernetes_client.list_deployment_for_all_namespaces()
    → returns all Deployments except excluded namespaces
    → builds list: [{name, namespace, replicas, labels}, ...]

  Step 2 — Metrics Collection (parallel async)
    for each service:
      prometheus_client.query(PromQL for cpu, memory, latency, req_rate, error_rate)
    → returns: [{service_name, namespace, metrics: {cpu, mem, lat, ...}}, ...]

  Step 3 — Send to SaaS
    POST /v1/metrics/ingest
    Header: X-API-Key: sadmc_sk_live_xxxx
    Body: { cluster_uuid, timestamp, services: [...] }

  Step 4 — Receive Inference Results
    Response: {
      results: [
        { service_name: "payment", anomaly_type: "CPU_HOG",
          confidence: 0.94, is_anomaly: true },
        { service_name: "orders",  anomaly_type: "NORMAL",
          confidence: 0.97, is_anomaly: false },
      ]
    }

  Step 5 — Remediation Decision (AGENT decides, not SaaS)
    for each result where is_anomaly=true AND confidence >= 0.85:
      rule = REMEDIATION_RULES[anomaly_type]
      if cooldown not active for this service+action:
        execute kubernetes action
        report action to SaaS (for dashboard logging)
```

### 2.4 Phase 4 — Remediation Execution

The agent applies rule-based remediation. The model only classifies the anomaly type — the agent independently decides what action to take based on a static rule table configured via the Helm values.

| Anomaly Type | Action | Kubernetes Operation | Default Cooldown |
| --- | --- | --- | --- |
| CPU_HOG | THROTTLE_CPU | PATCH Deployment → resources.limits.cpu = 200m | 300 seconds |
| MEMORY_LEAK | RESTART_POD | DELETE all pods matching the deployment (Deployment auto-recreates) | 180 seconds |
| NETWORK_DELAY | SCALE_UP | PATCH Deployment → spec.replicas += 1 (max 10) | 600 seconds |
| NORMAL | NO_ACTION | Nothing executed | — |

> **Cooldown Mechanism:** Each service+action pair is tracked in memory. If a remediation was executed within the cooldown window, subsequent detections for the same pair are skipped. This prevents remediation loops and gives the system time to stabilise before re-evaluating.

---

## 3. SaaS Backend — Control Plane

The SaaS backend is a Python FastAPI application. It handles tenant authentication, receives metrics from agents, runs the trained SADMC model, persists all events, and serves the React dashboard via WebSocket for real-time updates.

### 3.1 Internal Service Architecture

```
sadmc-saas/
├── main.py                   ← FastAPI app entry point
├── routers/
│   ├── auth.py               ← /auth/register, /auth/login, /auth/refresh
│   ├── api_keys.py           ← /api-keys CRUD
│   ├── agent.py              ← /v1/agent/register, /v1/agent/heartbeat
│   ├── metrics.py            ← /v1/metrics/ingest  (core pipeline)
│   ├── remediation.py        ← /v1/remediation/report
│   └── dashboard.py          ← /v1/clusters, /v1/anomalies, /v1/metrics
├── services/
│   ├── auth_service.py       ← JWT creation, bcrypt verification
│   ├── api_key_service.py    ← key generation, hash storage, validation
│   ├── inference_service.py  ← model loading, feature extraction, predict
│   └── event_service.py      ← anomaly event persistence
├── models/
│   ├── sadmc_model_v1.pkl    ← trained SADMC model
│   └── minmax_scaler.pkl     ← fitted MinMax scaler from training
├── db/
│   ├── connection.py         ← PostgreSQL + TimescaleDB async connection
│   └── schema.sql            ← full DDL
├── websocket/
│   └── manager.py            ← WebSocket connection pool, Redis pub/sub
└── middleware/
    ├── api_key_auth.py       ← validates X-API-Key for agent routes
    └── jwt_auth.py           ← validates Bearer token for dashboard routes
```

### 3.2 Authentication & API Key Design

#### 3.2.1 JWT-based User Authentication

Dashboard users authenticate with email and password. On successful login, the SaaS issues two tokens:

- **Access Token** — short-lived (15 minutes), signed JWT containing `tenant_id` and `user_id`. Sent in `Authorization: Bearer` header.
- **Refresh Token** — long-lived (7 days), opaque random token stored in the database. Used to issue new access tokens without re-login.

#### 3.2.2 API Key Structure

```
Format:       sadmc_sk_live_[tenant_prefix]_[32 random hex chars]
Example:      sadmc_sk_live_t1407_a3f8b2c1d9e4f705a6b7c8d9e0f1a2b3

Generation:   secrets.token_hex(32)  (Python standard library)
Storage:      bcrypt hash of the full key — plaintext NEVER stored
Validation:   incoming key → bcrypt.checkpw(key, stored_hash) → tenant lookup
Caching:      Redis caches tenant_id → hash for 5 minutes to reduce DB load
Transmission: HTTPS only, header: X-API-Key
```

### 3.3 Model Inference Pipeline

The inference service loads the trained SADMC model at startup and keeps it in memory as a singleton. Each ingest request triggers a batch inference across all reported services.

```python
# services/inference_service.py

import pickle, numpy as np
from pathlib import Path

ANOMALY_CLASSES = {0: "NORMAL", 1: "CPU_HOG", 2: "MEMORY_LEAK", 3: "NETWORK_DELAY"}

class InferenceService:
    _instance = None

    @classmethod
    def get(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self.model  = pickle.load(open("models/sadmc_model_v1.pkl",  "rb"))
        self.scaler = pickle.load(open("models/minmax_scaler.pkl",   "rb"))

    def predict_batch(self, services: list) -> list:
        results = []
        for svc in services:
            m = svc["metrics"]
            feature_vector = [
                m.get("cpu_usage_percent",  0.0),
                m.get("memory_usage_mb",    0.0),
                m.get("network_latency_ms", 0.0),
                m.get("request_rate",        0.0),
                m.get("error_rate",           0.0),
                m.get("cpu_trend",            0.0),   # delta over window
                m.get("memory_trend",         0.0),   # delta over window
            ]
            norm = self.scaler.transform([feature_vector])
            pred  = int(self.model.predict(norm)[0])
            proba = self.model.predict_proba(norm)[0]

            results.append({
                "service_name": svc["service_name"],
                "namespace":     svc["namespace"],
                "anomaly_type":  ANOMALY_CLASSES[pred],
                "confidence":    float(proba.max()),
                "is_anomaly":    pred != 0,
            })
        return results
```

> **Feature Engineering Note:** The agent maintains a rolling window (last 10 readings) per service in memory. Before sending metrics to the SaaS, it appends two derived features: **cpu_trend** (cpu[now] − cpu[10 readings ago]) and **memory_trend** (memory[now] − memory[10 readings ago]). These capture increasing resource exhaustion patterns that a single-point reading cannot.

### 3.4 Event Persistence & WebSocket Broadcasting

After inference, every anomaly event (and every NORMAL result where anomaly_type changes from a previous anomaly) is written to the `anomaly_events` table. The event is also published to a Redis channel keyed by `tenant_id`.

```python
# Publish to Redis after DB insert
await redis.publish(
    channel=f"events:{tenant_id}",
    message=json.dumps({
        "service_name": result["service_name"],
        "anomaly_type":  result["anomaly_type"],
        "confidence":    result["confidence"],
        "timestamp":     datetime.utcnow().isoformat(),
    })
)

# WebSocket manager subscribes to Redis and fans out to connected browsers
# websocket/manager.py
async def broadcast_loop(tenant_id: str):
    async with redis.subscribe(f"events:{tenant_id}") as channel:
        async for message in channel.iter():
            for ws in connected_clients[tenant_id]:
                await ws.send_text(message)
```

---

## 4. Helm Chart & In-Cluster Agent

The Helm Chart is the delivery vehicle for the in-cluster SADMC Agent. It packages all Kubernetes manifests (RBAC, Deployment, Secret, ConfigMap, optional Prometheus) and exposes configuration via `values.yaml`. The agent itself is a Python application packaged as a Docker image published to Docker Hub.

### 4.1 Repository Structure

The project spans three separate Git repositories:

```
github.com/user/sadmc-agent/          ← Python source + Dockerfile
│
├── agent/
│   ├── __main__.py                   ← entry point: python -m agent
│   ├── config.py                     ← reads all env vars
│   ├── main.py                       ← SADMCAgent class + monitoring loop
│   ├── discovery.py                  ← k8s Deployment lister
│   ├── prometheus_detector.py        ← auto-detect existing Prometheus
│   ├── metrics_collector.py          ← PromQL queries (async)
│   ├── inference_client.py           ← HTTP client for SaaS /v1/metrics/ingest
│   └── remediation/
│       ├── rules.py                  ← static rule table
│       ├── cooldown.py               ← cooldown tracker
│       └── executor.py               ← k8s API calls
├── requirements.txt
└── Dockerfile

github.com/user/sadmc-helm-charts/    ← Helm Chart repo
│
├── charts/
│   └── sadmc-agent/
│       ├── Chart.yaml
│       ├── values.yaml
│       └── templates/
│           ├── _helpers.tpl
│           ├── secret.yaml
│           ├── configmap.yaml
│           ├── serviceaccount.yaml
│           ├── clusterrole.yaml
│           ├── clusterrolebinding.yaml
│           ├── deployment.yaml
│           └── prometheus/
│               ├── deployment.yaml   ← conditional on prometheus.mode
│               ├── service.yaml
│               └── configmap.yaml
└── index.yaml                        ← auto-generated, served via GitHub Pages

github.com/user/sadmc-saas/           ← SaaS backend + dashboard
```

### 4.2 Docker Image Build & Publish

The agent Docker image is built from the `sadmc-agent` repository and published to Docker Hub. This image is what Kubernetes actually runs — the Helm Chart simply references it.

```dockerfile
# Dockerfile  (sadmc-agent/Dockerfile)
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY agent/ ./agent/

# Non-root user (security best practice)
RUN useradd -m -u 1000 sadmc
USER sadmc

# Start the agent
CMD ["python", "-m", "agent"]
```

```bash
# Build and push commands (run from sadmc-agent/ directory)

docker build -t sadmc-agent:1.0.0 .

docker tag sadmc-agent:1.0.0 yourusername/sadmc-agent:1.0.0
docker tag sadmc-agent:1.0.0 yourusername/sadmc-agent:latest

docker login
docker push yourusername/sadmc-agent:1.0.0
docker push yourusername/sadmc-agent:latest

# Image is now publicly available at:
# docker.io/yourusername/sadmc-agent:1.0.0
```

### 4.3 Helm Chart — values.yaml

This is the primary configuration interface for users. Most users only need to set `sadmc.apiKey`; everything else has sensible defaults.

```yaml
# values.yaml — annotated

# ─── REQUIRED ───────────────────────────────────────────────────
sadmc:
  apiKey: ""                          # Paste your API Key from the dashboard
  saasEndpoint: "https://api.sadmc.io"

# ─── AGENT DOCKER IMAGE ─────────────────────────────────────────
agent:
  image:
    repository: "yourusername/sadmc-agent"
    tag: "1.0.0"
    pullPolicy: IfNotPresent
  resources:
    requests: { cpu: "100m", memory: "128Mi" }
    limits:   { cpu: "500m", memory: "512Mi" }

# ─── PROMETHEUS ─────────────────────────────────────────────────
prometheus:
  # auto    = agent detects if Prometheus already exists
  # existing = point to user's existing Prometheus
  # install  = always install a fresh Prometheus
  mode: "auto"
  existingUrl: ""    # e.g. http://prometheus-server.monitoring:9090
  install:
    storageSize: "10Gi"
    retention: "15d"

# ─── SERVICE DISCOVERY ──────────────────────────────────────────
discovery:
  excludeNamespaces:
    - "kube-system"
    - "kube-public"
    - "sadmc"

# ─── REMEDIATION ─────────────────────────────────────────────────
remediation:
  enabled: true
  confidenceThreshold: 0.85
  rules:
    cpuHog:
      cpuLimitMillicores: 200
      cooldownSeconds: 300
    memoryLeak:
      cooldownSeconds: 180
    networkDelay:
      replicaIncrease: 1
      maxReplicas: 10
      cooldownSeconds: 600
```

### 4.4 Helm Chart — Key Templates

#### 4.4.1 secret.yaml — API Key Storage

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ include "sadmc-agent.fullname" . }}-secret
  namespace: {{ .Release.Namespace }}
type: Opaque
data:
  api-key: {{ .Values.sadmc.apiKey | b64enc | quote }}
  # Kubernetes Secret stores base64-encoded value.
  # The pod reads it as plaintext via env var; only sent to SaaS over HTTPS.
```

#### 4.4.2 clusterrole.yaml — Least-Privilege RBAC

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: {{ include "sadmc-agent.fullname" . }}
rules:
  # Service Discovery — READ ONLY
  - apiGroups: [""]
    resources: ["pods", "services", "namespaces", "nodes", "endpoints"]
    verbs: ["get", "list", "watch"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets", "statefulsets"]
    verbs: ["get", "list", "watch"]

  # Remediation — WRITE (minimal surface)
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["delete"]                   # RESTART_POD
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["patch", "update"]          # THROTTLE_CPU + SCALE_UP

  # NOT granted: secrets, configmaps-write, nodes-write, cluster-admin
```

#### 4.4.3 deployment.yaml — Where Docker Image Connects

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "sadmc-agent.fullname" . }}
  namespace: {{ .Release.Namespace }}
spec:
  replicas: 1
  selector:
    matchLabels:
      {{- include "sadmc-agent.selectorLabels" . | nindent 6 }}
  template:
    spec:
      serviceAccountName: {{ include "sadmc-agent.fullname" . }}
      containers:
        - name: sadmc-agent
          # ↓ This line pulls the Docker image you pushed to Docker Hub ↓
          image: "{{ .Values.agent.image.repository }}:{{ .Values.agent.image.tag }}"
          imagePullPolicy: {{ .Values.agent.image.pullPolicy }}

          env:
            - name: SADMC_API_KEY
              valueFrom:
                secretKeyRef:
                  name: {{ include "sadmc-agent.fullname" . }}-secret
                  key: api-key

            - name: SAAS_ENDPOINT
              valueFrom:
                configMapKeyRef:
                  name: {{ include "sadmc-agent.fullname" . }}-config
                  key: SAAS_ENDPOINT

            - name: PROMETHEUS_MODE
              valueFrom:
                configMapKeyRef:
                  name: {{ include "sadmc-agent.fullname" . }}-config
                  key: PROMETHEUS_MODE
            # ... all other env vars from ConfigMap ...

          resources:
            requests:
              cpu: {{ .Values.agent.resources.requests.cpu }}
              memory: {{ .Values.agent.resources.requests.memory }}
            limits:
              cpu: {{ .Values.agent.resources.limits.cpu }}
              memory: {{ .Values.agent.resources.limits.memory }}
```

### 4.5 Prometheus Auto-Detection Logic

When `prometheus.mode` is set to `auto`, the agent systematically probes well-known Prometheus service locations before falling back to installing a new instance.

```python
# agent/prometheus_detector.py

KNOWN_LOCATIONS = [
    ("monitoring",          "prometheus-server"),
    ("monitoring",          "prometheus-operated"),
    ("prometheus",          "prometheus-server"),
    ("default",             "prometheus"),
    ("kube-system",         "prometheus"),
    ("observability",       "prometheus-server"),
]

def detect(mode, existing_url) -> str:
    if mode == "existing":
        return existing_url

    if mode == "install":
        return INSTALLED_PROMETHEUS_URL  # set by Helm conditional template

    # mode == "auto"
    k8s = client.CoreV1Api()
    for namespace, svc_name in KNOWN_LOCATIONS:
        try:
            k8s.read_namespaced_service(svc_name, namespace)
            url = f"http://{svc_name}.{namespace}.svc.cluster.local:9090"
            resp = httpx.get(f"{url}/-/healthy", timeout=3)
            if resp.status_code == 200:
                return url
        except Exception:
            continue

    # Not found — use the Prometheus the Helm Chart installed
    return "http://sadmc-agent-prometheus.sadmc.svc.cluster.local:9090"
```

### 4.6 Agent Remediation Engine

```python
# agent/remediation/rules.py
# Static rule table — loaded from Helm ConfigMap at startup

REMEDIATION_RULES = {
    "CPU_HOG": {
        "action":           "THROTTLE_CPU",
        "cpu_limit":        "200m",
        "cooldown_seconds": 300,
    },
    "MEMORY_LEAK": {
        "action":           "RESTART_POD",
        "cooldown_seconds": 180,
    },
    "NETWORK_DELAY": {
        "action":           "SCALE_UP",
        "replica_increase": 1,
        "max_replicas":     10,
        "cooldown_seconds": 600,
    },
    "NORMAL": {
        "action": "NO_ACTION",
    },
}
```

```python
# agent/remediation/executor.py

async def execute(action, params, service_name, namespace):

    if action == "THROTTLE_CPU":
        patch = {"spec": {"template": {"spec": {"containers": [{
            "name": service_name,
            "resources": {"limits": {"cpu": params["cpu_limit"]}}
        }]}}}}
        apps_v1.patch_namespaced_deployment(service_name, namespace, patch)

    elif action == "RESTART_POD":
        pods = core_v1.list_namespaced_pod(
            namespace, label_selector=f"app={service_name}")
        for pod in pods.items:
            core_v1.delete_namespaced_pod(pod.metadata.name, namespace)
        # Kubernetes Deployment controller recreates pods automatically

    elif action == "SCALE_UP":
        dep = apps_v1.read_namespaced_deployment(service_name, namespace)
        current = dep.spec.replicas or 1
        new = min(current + params["replica_increase"], params["max_replicas"])
        apps_v1.patch_namespaced_deployment(
            service_name, namespace, {"spec": {"replicas": new}})
```

---

## 5. Database Schema

The SaaS uses PostgreSQL with the TimescaleDB extension. TimescaleDB converts the metrics table into a hypertable, enabling efficient time-range queries and automatic data retention policies.

### 5.1 Entity Relationship Summary

```
tenants ──< api_keys
        ──< clusters ──< services
                       ──< anomaly_events ──< remediation_actions
                       ──< metrics  (TimescaleDB hypertable)
```

### 5.2 Full DDL

```sql
-- ── TENANTS ──────────────────────────────────────────────────
CREATE TABLE tenants (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_name VARCHAR(255) NOT NULL,
    email             VARCHAR(255) UNIQUE NOT NULL,
    password_hash     VARCHAR(255) NOT NULL,
    subscription_plan VARCHAR(50)  DEFAULT 'free',
    created_at        TIMESTAMPTZ  DEFAULT NOW()
);

-- ── API KEYS (plaintext never stored) ─────────────────────────
CREATE TABLE api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id    UUID REFERENCES tenants(id) ON DELETE CASCADE,
    key_hash     VARCHAR(255) UNIQUE NOT NULL,  -- bcrypt hash
    key_prefix   VARCHAR(40)  NOT NULL,          -- for display (first 20 chars)
    name         VARCHAR(100),                   -- user-defined label
    is_active    BOOLEAN      DEFAULT TRUE,
    created_at   TIMESTAMPTZ  DEFAULT NOW(),
    last_used_at TIMESTAMPTZ
);

-- ── CLUSTERS ───────────────────────────────────────────────────
CREATE TABLE clusters (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID REFERENCES tenants(id) ON DELETE CASCADE,
    cluster_uuid    VARCHAR(100) UNIQUE NOT NULL,
    k8s_version     VARCHAR(20),
    node_count      INTEGER,
    agent_version   VARCHAR(20),
    status          VARCHAR(20)  DEFAULT 'active',
    last_heartbeat  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ  DEFAULT NOW()
);

-- ── SERVICES (dynamically updated each discovery cycle) ────────
CREATE TABLE services (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id   UUID REFERENCES clusters(id) ON DELETE CASCADE,
    service_name VARCHAR(255) NOT NULL,
    namespace    VARCHAR(255) NOT NULL,
    last_seen    TIMESTAMPTZ  DEFAULT NOW(),
    UNIQUE(cluster_id, service_name, namespace)
);

-- ── ANOMALY EVENTS ───────────────────────────────────────────────
CREATE TABLE anomaly_events (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cluster_id       UUID REFERENCES clusters(id) ON DELETE CASCADE,
    service_id       UUID REFERENCES services(id),
    service_name     VARCHAR(255) NOT NULL,
    namespace        VARCHAR(255) NOT NULL,
    anomaly_type     VARCHAR(50)  NOT NULL,  -- NORMAL│CPU_HOG│MEMORY_LEAK│NETWORK_DELAY
    confidence       FLOAT        NOT NULL,
    metrics_snapshot JSONB,                  -- raw metric values at detection time
    timestamp        TIMESTAMPTZ  DEFAULT NOW()
);
CREATE INDEX idx_anomaly_cluster ON anomaly_events(cluster_id, timestamp DESC);
CREATE INDEX idx_anomaly_service ON anomaly_events(service_name, timestamp DESC);

-- ── REMEDIATION ACTIONS ──────────────────────────────────────────
CREATE TABLE remediation_actions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    anomaly_event_id UUID REFERENCES anomaly_events(id),
    cluster_id       UUID REFERENCES clusters(id),
    service_name     VARCHAR(255) NOT NULL,
    namespace        VARCHAR(255) NOT NULL,
    action_type      VARCHAR(50)  NOT NULL,  -- THROTTLE_CPU│RESTART_POD│SCALE_UP
    action_params    JSONB,
    status           VARCHAR(20)  DEFAULT 'pending',  -- pending│success│failed│skipped
    executed_at      TIMESTAMPTZ,
    duration_ms      INTEGER,
    error_message    TEXT
);

-- ── METRICS TIME-SERIES (TimescaleDB hypertable) ─────────────────
CREATE TABLE metrics (
    time                  TIMESTAMPTZ NOT NULL,
    cluster_id            UUID        NOT NULL,
    service_name          VARCHAR(255) NOT NULL,
    namespace             VARCHAR(255) NOT NULL,
    cpu_usage_percent     FLOAT,
    memory_usage_mb       FLOAT,
    network_latency_ms    FLOAT,
    request_rate          FLOAT,
    error_rate            FLOAT
);
SELECT create_hypertable('metrics', 'time');
-- Auto-drop data older than 90 days:
SELECT add_retention_policy('metrics', INTERVAL '90 days');

-- ── ROW-LEVEL SECURITY (multi-tenant isolation) ───────────────────
ALTER TABLE anomaly_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON anomaly_events
  USING (cluster_id IN (
    SELECT id FROM clusters WHERE tenant_id = current_setting('app.tenant_id')::UUID
  ));
```

---

## 6. API Specification

The SaaS exposes three groups of endpoints. Auth routes and Dashboard routes use JWT Bearer tokens. Agent routes use X-API-Key headers.

### 6.1 Authentication Routes

| Method | Endpoint | Auth | Description |
| --- | --- | --- | --- |
| POST | /auth/register | None | Create tenant account |
| POST | /auth/login | None | Returns access_token + refresh_token |
| POST | /auth/refresh | Refresh Token | Issues new access token |
| POST | /auth/logout | Bearer JWT | Invalidates refresh token |

### 6.2 API Key Management Routes

| Method | Endpoint | Auth | Description |
| --- | --- | --- | --- |
| GET | /api-keys | Bearer JWT | List all API Keys for tenant (hashed, prefix shown) |
| POST | /api-keys | Bearer JWT | Generate new API Key — plaintext shown once |
| DELETE | /api-keys/{key_id} | Bearer JWT | Revoke and delete an API Key |

### 6.3 Agent Routes (X-API-Key)

| Method | Endpoint | Description |
| --- | --- | --- |
| POST | /v1/agent/register | Agent startup registration. Returns cluster_uuid. |
| POST | /v1/agent/heartbeat | Periodic alive ping. Updates last_heartbeat in DB. |
| POST | /v1/metrics/ingest | Core endpoint: receives metrics batch, runs inference, returns anomaly results. |
| POST | /v1/remediation/report | Agent reports the outcome of a remediation action (for dashboard logging). |

#### 6.3.1 /v1/metrics/ingest — Request & Response

```
POST /v1/metrics/ingest
Header: X-API-Key: sadmc_sk_live_t1407_xxxx
Content-Type: application/json

Request body:
{
  "cluster_uuid": "clust_abc123",
  "timestamp": "2025-06-01T12:00:00Z",
  "services": [
    {
      "service_name": "payment",
      "namespace":    "default",
      "metrics": {
        "cpu_usage_percent":  87.5,
        "memory_usage_mb":   512.0,
        "network_latency_ms": 45.0,
        "request_rate":       120.0,
        "error_rate":           0.02,
        "cpu_trend":           14.3,   # derived by agent
        "memory_trend":         2.1    # derived by agent
      }
    }
  ]
}

Response 200:
{
  "results": [
    {
      "service_name": "payment",
      "namespace":    "default",
      "anomaly_type": "CPU_HOG",
      "confidence":    0.94,
      "is_anomaly":    true
    }
  ]
}

# The SaaS does NOT include remediation instructions.
# The agent reads anomaly_type and applies its own rule table.
```

### 6.4 Dashboard REST Routes

| Method | Endpoint | Description |
| --- | --- | --- |
| GET | /v1/clusters | List all clusters for authenticated tenant |
| GET | /v1/clusters/{id}/services | List discovered services for a cluster |
| GET | /v1/clusters/{id}/anomalies | Paginated anomaly event history |
| GET | /v1/clusters/{id}/remediations | Paginated remediation action history |
| GET | /v1/clusters/{id}/metrics | Time-series metrics query (start, end, service_name) |

### 6.5 WebSocket

```
WS wss://api.sadmc.io/ws/events
Header: Authorization: Bearer <access_token>

Server pushes JSON frames whenever a new anomaly event is stored:

{
  "type":         "ANOMALY_DETECTED",
  "service_name": "payment",
  "namespace":    "default",
  "anomaly_type": "CPU_HOG",
  "confidence":    0.94,
  "timestamp":    "2025-06-01T12:00:00Z"
}

{
  "type":         "REMEDIATION_EXECUTED",
  "service_name": "payment",
  "action":       "THROTTLE_CPU",
  "status":       "success",
  "duration_ms":   2340
}
```

---

## 7. React Dashboard

### 7.1 Page Structure

```
sadmc-saas/dashboard/src/
├── pages/
│   ├── LoginPage.tsx
│   ├── RegisterPage.tsx
│   ├── DashboardPage.tsx         ← cluster health overview
│   ├── ServicesPage.tsx          ← per-service status list
│   ├── AnomalyFeedPage.tsx       ← real-time event feed (WebSocket)
│   ├── RemediationLogPage.tsx    ← history table with status
│   ├── MetricsPage.tsx           ← time-series charts
│   └── SettingsPage.tsx          ← API Key management
├── components/
│   ├── AnomalyBadge.tsx          ← colour-coded badge per type
│   ├── ServiceHealthCard.tsx
│   ├── MetricsChart.tsx          ← Recharts LineChart
│   └── RemediationTimeline.tsx
├── hooks/
│   ├── useWebSocket.ts           ← connects to /ws/events
│   └── useAnomalyFeed.ts
└── store/
    └── useAppStore.ts            ← Zustand global state
```

### 7.2 Real-time Anomaly Feed

```typescript
// hooks/useWebSocket.ts

export function useWebSocket() {
  const { addEvent } = useAppStore();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    const ws = new WebSocket(
      `wss://api.sadmc.io/ws/events`,
      ["Bearer", token]
    );

    ws.onmessage = (e) => {
      const event = JSON.parse(e.data);
      if (event.type === "ANOMALY_DETECTED") {
        addEvent(event);
        // Show toast notification for high-confidence anomalies
        if (event.confidence > 0.9) toast.error(`${event.service_name}: ${event.anomaly_type}`);
      }
    };

    return () => ws.close();
  }, []);
}
```

### 7.3 Dashboard Layout Wireframe

```
┌────────────────────────────────────────────────────────────────────┐
│  SADMC Shield   [Cluster: prod-cluster-1 ▾]         [Settings]    │
├─────────────────────────┬──────────────────────────────────────────┤
│  Service Health         │  Real-time Anomaly Feed          [Live]  │
│                         │                                          │
│  ● payment   ⚠ CPU_HOG │  12:34:05  payment → CPU_HOG (94%)       │
│  ● orders    ✓ NORMAL  │             └─ THROTTLE_CPU → SUCCESS ✓  │
│  ● frontend  ✓ NORMAL  │  12:31:22  orders  → NORMAL               │
│  ● catalogue ✓ NORMAL  │  12:28:10  frontend→ MEMORY_LEAK (89%)    │
│  ● cart      ✓ NORMAL  │             └─ RESTART_POD → SUCCESS ✓   │
│  ● shipping  ✓ NORMAL  │                                          │
├─────────────────────────┴──────────────────────────────────────────┤
│  CPU Usage — payment (last 1h)    │  Memory Usage — all (last 1h) │
│  [Line Chart: shows CPU spike     │  [Line Chart: memory trends]  │
│   and throttle recovery]          │                               │
├───────────────────────────────────┴───────────────────────────────┤
│  Remediation Log                                                   │
│  TIME       SERVICE    ANOMALY       ACTION         STATUS  DURN  │
│  12:34:05   payment    CPU_HOG       THROTTLE_CPU   ✓       2.3s  │
│  12:28:10   frontend   MEMORY_LEAK   RESTART_POD    ✓       8.1s  │
│  11:52:44   orders     NETWORK_DELAY SCALE_UP       ✓       1.1s  │
└────────────────────────────────────────────────────────────────────┘
```

---

## 8. Security Architecture

### 8.1 Threat Model Summary

| Threat | Mitigation |
| --- | --- |
| API Key leakage | Hashed with bcrypt (cost=12). Plaintext never stored. Shown once on generation. |
| Inter-tenant data access | PostgreSQL Row-Level Security enforces tenant_id isolation on all tables. |
| Man-in-the-middle | All agent-to-SaaS communication over TLS 1.3. HTTPS enforced by load balancer. |
| Overprivileged agent | ClusterRole grants only delete on pods and patch on deployments. No secrets access. |
| Malicious metrics payload | All incoming metrics validated via Pydantic schema before model inference. |
| JWT token theft | 15-minute expiry. Refresh tokens stored hashed; invalidated on logout. |
| Cluster enumeration by SaaS | SaaS never initiates connections to user clusters. Agent is the only initiator. |

### 8.2 Network Security

```
Agent  ──HTTPS──▶  SaaS API         (agent initiates, SaaS never calls into cluster)
Browser──HTTPS──▶  SaaS Dashboard   (JWT in Authorization header)
Browser──WSS───▶  SaaS WebSocket   (JWT in sub-protocol header)

SaaS Internal:
  FastAPI ──▶ PostgreSQL  (private VPC, no public exposure)
  FastAPI ──▶ Redis       (private VPC, no public exposure)
```

---

## 9. Technology Stack

### 9.1 SaaS Backend

| Layer | Technology | Version | Rationale |
| --- | --- | --- | --- |
| API Framework | FastAPI (Python) | 0.111+ | Async-native, OpenAPI auto-generation, Pydantic validation |
| Database | PostgreSQL | 16 | ACID compliance, JSONB, Row-Level Security |
| Time-series ext. | TimescaleDB | 2.x | Efficient time-range queries on metrics table |
| Cache / Pub-Sub | Redis | 7.x | API Key cache (5-min TTL), WebSocket fan-out |
| Auth | python-jose + bcrypt | — | JWT signing, password hashing |
| Containerisation | Docker + Compose | — | Local dev and prod deployment |

### 9.2 In-Cluster Agent

| Layer | Technology | Version | Rationale |
| --- | --- | --- | --- |
| Language | Python | 3.11 | Official kubernetes-client is Python-first |
| K8s Client | kubernetes (official) | 28.x | Service discovery, RBAC-controlled API calls |
| HTTP Client | httpx | 0.27 | Async HTTP for parallel Prometheus queries |
| Config | pydantic-settings | 2.x | Type-safe env var parsing |
| Base Image | python:3.11-slim | — | Minimal attack surface (~130 MB) |
| Distribution | Docker Hub + Helm + GitHub Pages | — | Zero-infra chart hosting |

### 9.3 Dashboard

| Layer | Technology | Rationale |
| --- | --- | --- |
| Framework | React 18 + TypeScript | Type safety, component reuse |
| Charts | Recharts | Composable, SVG-based, works well with time-series |
| Real-time | Native WebSocket | No extra library needed; built into browsers |
| Styling | TailwindCSS | Utility-first, no runtime cost |
| State | Zustand | Lightweight; no boilerplate vs Redux |
| HTTP Client | Axios | Interceptors for JWT refresh |

---

## 10. Implementation Roadmap

| Phase | Weeks | Deliverables | Acceptance Criteria |
| --- | --- | --- | --- |
| Phase 1 — Core SaaS | 1–2 | User registration & login; JWT auth + refresh; API Key generation (bcrypt); PostgreSQL schema deployed; Model loaded as FastAPI endpoint; /v1/metrics/ingest working | Postman: POST /v1/metrics/ingest returns correct anomaly_type for known input vectors |
| Phase 2 — Helm Agent (basic) | 3–4 | Python agent reads env vars; Kubernetes service discovery; Prometheus metrics collection; Sends to SaaS, receives results; Docker image on Docker Hub; Helm Chart installs on minikube | kubectl logs shows discovery + inference cycle every 15s on minikube with Sock-Shop |
| Phase 3 — Prometheus Conditional | 5 | Auto-detection across namespaces; Conditional Prometheus install (Helm); ServiceMonitor for pod scraping; mode=existing tested with live URL | Helm install works on cluster with no Prometheus (auto-installs) AND on cluster with existing Prometheus (skips install) |
| Phase 4 — Remediation Engine | 6 | Rule table from ConfigMap; Cooldown tracker in memory; THROTTLE_CPU, RESTART_POD, SCALE_UP via k8s API; Report back to SaaS after action | Inject CPU stress → CPU_HOG detected → CPU throttled within 60s → Dashboard shows THROTTLE_CPU: success |
| Phase 5 — Dashboard | 7–8 | React app with auth pages; Service health overview; WebSocket anomaly feed; Recharts time-series graphs; Remediation history table; API Key management UI | Browser shows anomaly event within 5s of agent reporting it; remediation log updates automatically |
| Phase 6 — Demo & Polish | 9 | Helm repo on GitHub Pages; README with helm install steps; Demo: Sock-Shop + anomaly injection; Supervisor presentation slides | Full demo: fresh cluster → helm install → anomaly inject → dashboard shows detection + auto-remediation |

---

## 11. Quick Start — Demo Setup

The following steps reproduce a complete end-to-end demo on a local minikube cluster using the Sock-Shop microservices benchmark.

### Step 1 — Start minikube

```bash
minikube start --cpus=4 --memory=8192 --driver=docker
```

### Step 2 — Deploy Sock-Shop

```bash
kubectl create namespace sock-shop
kubectl apply -f \
  https://raw.githubusercontent.com/microservices-demo/microservices-demo/master/deploy/kubernetes/complete-demo.yaml

# Wait until all pods are Running
kubectl get pods -n sock-shop -w
```

### Step 3 — Install SADMC Shield Agent

```bash
helm repo add sadmc https://yourusername.github.io/sadmc-helm-charts
helm repo update

helm install sadmc-agent sadmc/sadmc-agent \
  --namespace sadmc \
  --create-namespace \
  --set sadmc.apiKey="sadmc_sk_live_YOUR_KEY" \
  --set sadmc.saasEndpoint="https://api.sadmc.io"

# Watch agent startup
kubectl logs -n sadmc -l app=sadmc-agent -f
```

### Step 4 — Inject an Anomaly

```bash
# Inject CPU Hog into the payment service
kubectl exec -it -n sock-shop deployment/payment \
  -- sh -c "apt-get install -y stress && stress --cpu 4 --timeout 120s"

# Within 15-30 seconds the agent will report CPU_HOG.
# The agent will then THROTTLE_CPU on the payment deployment.
# Dashboard will show the event and remediation status.
```

### Step 5 — Observe in Dashboard

- Dashboard → Anomaly Feed: shows CPU_HOG on payment with confidence ≥ 0.85.
- Dashboard → Remediation Log: shows THROTTLE_CPU → success within ~5 seconds of detection.
- Dashboard → Metrics → payment: CPU chart shows spike followed by reduction after throttle.

---

## 12. Glossary

| Term | Definition |
| --- | --- |
| SaaS (Control Plane) | The centrally hosted SADMC Shield backend. Handles auth, inference, storage, and dashboard. |
| Data Plane Agent | The lightweight Python process running inside the user's Kubernetes cluster via Helm Chart. |
| Helm Chart | A package of Kubernetes YAML templates with a values.yaml interface. Equivalent to an installer for Kubernetes. |
| Tenant | A registered user organisation. All clusters, API Keys, and events belong to exactly one tenant. |
| API Key | A long-lived credential issued to a tenant for agent authentication. Stored hashed; never logged in plaintext. |
| cluster_uuid | A server-assigned stable identifier for a registered cluster. Generated on first agent registration. |
| Inference | The act of passing collected metrics through the trained SADMC model to obtain an anomaly classification. |
| PromQL | Prometheus Query Language. Used by the agent to fetch CPU, memory, and latency metrics from Prometheus. |
| THROTTLE_CPU | Remediation action that patches a Deployment to add or reduce a CPU resource limit. |
| RESTART_POD | Remediation action that deletes all pods of a Deployment. The Deployment controller recreates them. |
| SCALE_UP | Remediation action that increases the replica count of a Deployment by a configurable amount. |
| Cooldown | A per-service-per-action timer that prevents repeated remediation before the system can stabilise. |
| TimescaleDB | PostgreSQL extension that adds time-series optimisations (automatic partitioning, retention policies). |
| Row-Level Security | PostgreSQL feature that filters rows based on a session-level setting, enforcing multi-tenant data isolation. |

---

*IIT, University of Dhaka — Confidential Project Document*
