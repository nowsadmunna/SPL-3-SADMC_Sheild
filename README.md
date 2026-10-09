# SADMC Shield

Anomaly detection and auto-remediation for microservices on Kubernetes, offered as a multi-tenant SaaS.

A small agent runs inside the tenant's cluster, measures every service every 15 seconds and sends **33 numbers per service** to the SaaS. A neural network (EA-MRS, after Hao et al., 2024) classifies each sample as `NORMAL`, `CPU_HOG`, `MEMORY_LEAK` or `NETWORK_DELAY`. Detections appear on a live dashboard and, if the tenant allows it, the agent repairs the problem in the cluster (cap the CPU limit, restart the pod, add a replica).

Only numerical features leave the cluster; the agent is the only component that can change it.

**Contents:** [How it works](#how-it-works) · [Repository layout](#repository-layout) · [Requirements](#requirements) · [Quick start](#quick-start) · [Monitor a real cluster](#monitor-a-real-cluster) · [Model](#model) · [Create a dataset and train a model](#create-a-dataset-and-train-a-model) · [Tests](#tests) · [Limitations](#limitations) · [Reference](#reference)

## How it works

```
 Kubernetes cluster                         SaaS (Node.js)                          Browser
 ------------------                         ---------------                         -------
 cAdvisor, app /metrics,   every 15 s       scale + ONNX model                      Angular dashboard
 probe, Kubernetes API  -> agent  -------->  -> PostgreSQL/TimescaleDB  -- REST -->  Overview, Incidents,
                              ^             -> Redis -> WebSocket  ---------------->  Metrics, Remediation Log
                              |  (if enabled)
                              +-- patch CPU limit / delete pod / add replica
```

## Repository layout

| Path | Contents |
|---|---|
| `HelmAndSaas/Saas/` | Backend: REST API, WebSocket, ONNX inference, database schema |
| `HelmAndSaas/Agent/` | In-cluster agent (Python) and its Dockerfile |
| `HelmAndSaas/Helm/charts/sadmc-agent/` | Helm chart: agent, cAdvisor, RBAC, configuration |
| `HelmAndSaas/Dashboard/` | Angular web dashboard |
| `SADMC-MT-FF-FL/code/` | The EA-MRS network (`network_fed.py`) and the training script (`train_pooled_own.py`) |
| `SADMC-MT-FF-FL/own_dataset/scripts/` | Data collection, fault injection and dataset building |

The served model is in `HelmAndSaas/Saas/inference/model/v3/`. The datasets and training checkpoints are large and are not part of the repository.

## Requirements

- **Backend and dashboard:** Node.js (tested with 24) and Docker with the Compose plugin.
- **A real cluster (optional, see [Monitor a real cluster](#monitor-a-real-cluster)):** `kubectl`, Helm 3 and a Kubernetes cluster whose nodes run the **Docker container runtime with the `systemd` cgroup driver** (cgroup v2 in our tests). The agent identifies a pod by the pod UID inside cAdvisor's cgroup path (underscore form, as the `systemd` driver writes it) and reads network counters of the pod's `POD` container, and the chart's cAdvisor is started with `--docker_only=true`. On other setups the agent receives no data: containerd-based clusters (kind, k3s, most managed clusters) and Docker with the `cgroupfs` driver are not supported and were not tested. Tested with minikube 1.39 (Docker driver, Docker runtime) and Sock-Shop.
- **Monitored applications:** a Prometheus-format `/metrics` page with `request_duration_seconds` (with a `status_code` label) and `process_*` metrics. A service without it is skipped, with one warning in the agent log.
- **Creating a dataset and training a model (optional):** Python 3.12, see the section below.

## Quick start

### 1. Start the backend

```bash
cd HelmAndSaas/Saas
cp .env.example .env              # change the secrets
docker compose up -d              # TimescaleDB (port 5433) and Redis (port 6380); wait until both are healthy
npm install
npm run migrate                   # applies db/schema.sql
INFERENCE_MODE=onnx npm start     # http://localhost:8000
```

### 2. Start the dashboard

```bash
cd HelmAndSaas/Dashboard
npm install
npm start                         # http://localhost:4200
```

Open http://localhost:4200 and register an organization on the sign-in page. The backend address is set in `src/app/core/api-config.ts`.

### 3. Try it without a cluster

In the dashboard open *Settings*, generate an API key, then send synthetic samples (a problem appears every third cycle):

```bash
cd HelmAndSaas/Saas
FAKE_AGENT_API_KEY=<key> node scripts/fake-agent.js --loop
```

## Monitor a real cluster

### Deploy a demo application

Start a cluster with the Docker runtime (for example minikube) and deploy the Sock-Shop demo application with its load generator:

```bash
kubectl create -f https://raw.githubusercontent.com/microservices-demo/microservices-demo/master/deploy/kubernetes/complete-demo.yaml
kubectl create -f https://raw.githubusercontent.com/microservices-demo/microservices-demo/master/deploy/kubernetes/manifests-loadtest/loadtest-dep.yaml
kubectl get pods -n sock-shop      # wait until every pod is Running; the Java services need a few minutes
```

### Build the agent image

Build the agent image so that the cluster can pull it (for minikube, run `eval $(minikube docker-env)` first; for another cluster push it to a registry and add `--set agent.image.repository=<registry>/sadmc-agent`):

```bash
docker build -t sadmc-agent:1.1.5 HelmAndSaas/Agent
```

### Install the agent

The dashboard's *Connect a Cluster* page generates the install command with a new API key. Run it from the repository root. It looks like this:

```bash
helm install sadmc-agent ./HelmAndSaas/Helm/charts/sadmc-agent \
  --namespace sadmc --create-namespace \
  --set sadmc.apiKey="<API_KEY>" \
  --set sadmc.saasEndpoint="http://<backend-address>:8000" \
  --set sadmc.clusterName="my-cluster" \
  --set 'discovery.namespaces={sock-shop}'
```

The backend address must be reachable from the cluster's pods (use the LAN address of the machine that runs the backend, not `localhost`). The first verdicts appear after about 75 seconds, when the agent has a full minute of readings. Remediation is off by default; enable it with `--set remediation.enabled=true --set 'remediation.services={a,b}'`.

### See a detection

To see a detection, inject a fault with [Pumba](https://github.com/alexei-led/pumba) (with minikube, run `eval $(minikube docker-env)` in that terminal first). The dashboard shows *CPU overload* on `payment` within about a minute:

```bash
pumba stress --duration 120s --stress-image alexeiled/stress-ng --stressors "--cpu 1 --cpu-load 100" 're2:k8s_payment_.*_sock-shop_'
```

## Model

| Measure | Value |
|---|---|
| Input | 33 features per service and 15-second sample (cAdvisor, application `/metrics`, probe, pod state) |
| Training data | Sock-Shop on minikube: 105 injected faults at five intensities, 10 load spikes |
| Macro-F1 on held-out events | 0.948 (39 of 42 fault events named, no false alarm on held-out normal periods) |
| Macro-F1 on a service never seen in training | 0.659 |

The faults are synthetic (Pumba with stress-ng and netem), and all results come from one application on one cluster.

## Create a dataset and train a model

The served model was trained on data collected from Sock-Shop; the same scripts create a dataset from your own cluster and train a model from it. Python 3.12.

```bash
pip install -r SADMC-MT-FF-FL/requirements.txt
cd SADMC-MT-FF-FL/own_dataset/scripts/v3

# 1. Collect: raw counters plus fault injections (about 15 hours; see the prerequisites below)
V3_OUT=~/runs/run1 python run_collection_v3.py

# 2. Raw run -> training files: 60 s rates, labels from the injection log, split by fault event
python build_v3_dataset.py ~/runs/run1 ~/runs/built --model-features-only

# 3. Training files -> arrays and one fixed global scaler (fitted on the training rows only)
python export_mul_class_v3.py ~/runs/built ../../datasets/my_dataset global

# 4. Train the model (prints the macro F1 on the held-out events after every epoch)
cd ../../../code
SADMC_DATASET=my_dataset POOLED_SAVE=last python -u train_pooled_own.py

# 5. Convert to ONNX
MODEL_PTH=../saved_models/my_dataset/pooled/sadmc_global_model_own.pth python ../../HelmAndSaas/Saas/inference/export_to_onnx.py
```

Step 5 overwrites the model that the backend serves (`HelmAndSaas/Saas/inference/model/v3/sadmc_model.onnx`); copy `own_dataset/datasets/my_dataset/scalers/_global.json` to `HelmAndSaas/Saas/inference/model/v3/global_scaler.json` as well, so that the scaler matches the model.

Prerequisites of step 1: minikube with the Docker runtime and Sock-Shop running under a constant load generator, a standalone cAdvisor reachable from the node (`V3_CADVISOR_URL`, default `http://localhost:18080/metrics`), and `kubectl`, `docker` and [Pumba](https://github.com/alexei-led/pumba) on the path. Steps 2 to 5 need only the files from step 1.

## Tests

```bash
cd HelmAndSaas/Saas && npm run verify:parity               # served ONNX model equals the trained model
python3 HelmAndSaas/Agent/tools/sync_v3_sources.py --check # agent feature code equals the training definitions
helm lint HelmAndSaas/Helm/charts/sadmc-agent --set sadmc.apiKey=x
```

## Limitations

- **Supported clusters:** Docker container runtime with the `systemd` cgroup driver, tested with minikube only (see [Requirements](#requirements)). Containerd-based clusters and Docker with the `cgroupfs` driver give the agent no data.
- **Evidence:** all results come from one application (Sock-Shop) on one cluster, with synthetic faults. On a service the model has not seen in training the macro-F1 is 0.659.
- **Applications:** a service without a suitable `/metrics` page is skipped.
- **Remediation:** a fixed rule table (cap the CPU limit, restart the pod, add a replica) with a cooldown per action; it is not learned. It is off by default.
- **Agent image:** built locally; push it to a registry to use it on other clusters.
- **Training data:** the datasets are not in the repository; creating one takes about 15 hours on a minikube cluster.

## Reference

J. Hao, P. Chen, J. Chen and X. Li, "Multi-task federated learning-based system anomaly detection and multi-classification for microservices architecture," *Future Generation Computer Systems*, vol. 159, pp. 77-90, 2024.
