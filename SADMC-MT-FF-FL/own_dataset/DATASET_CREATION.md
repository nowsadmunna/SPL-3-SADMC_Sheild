# Creating a Custom Sock-Shop Anomaly Dataset

A step-by-step guide to generating the `own_dataset/` CSVs from a **live, running
Sock-Shop deployment** — a manual, reproducible alternative to the paper's
pre-packaged binary dataset. It mirrors the methodology in AD.pdf, Section 4.1
(Sock-Shop dataset collection), and every fix below is already implemented in the
scripts — follow this top to bottom on a fresh setup and it should just work.

## 1. Idea

The paper's Sock-Shop dataset was built by:
1. Running the real Sock-Shop microservices app under normal traffic.
2. Injecting 3 fault types (CPU Hog, Memory Leak, Network Latency) into each
   service, one at a time, for 1-5 minutes, repeated 5 times, with normal periods
   in between.
3. Scraping per-service metrics from Prometheus every 5 seconds throughout.
4. Labeling every collected row with whichever fault (if any) was active for that
   service at that timestamp.

This reproduces exactly that loop against a real Sock-Shop instance on **minikube**.

## 2. Prerequisites

| Component | Purpose | Check |
|---|---|---|
| `minikube` | Local Kubernetes cluster running Sock-Shop | `minikube status` |
| `kubectl` | Talk to the cluster | `kubectl get nodes` |
| Sock-Shop manifests | The app itself (Weaveworks demo) | cloned at `~/Desktop/microservices-demo` |
| `kube-prometheus-stack` (Helm) | Metrics source (cAdvisor/kubelet scraping) | `kubectl get pods -n monitoring` |
| `pumba` | Chaos-injection tool (CPU/mem/network faults) | `pumba --version` |
| Docker | Runtime backing minikube's node | `minikube docker-env` |
| Python 3 + `requests` | Runs the collector/injector scripts | `python -c "import requests"` |

If Sock-Shop isn't deployed yet:
```bash
minikube start
kubectl apply -f ~/Desktop/microservices-demo/deploy/kubernetes/complete-demo.yaml
kubectl get pods -n sock-shop     # wait until all pods are Running
```

If the Prometheus stack isn't deployed yet:
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm install prometheus prometheus-community/kube-prometheus-stack -n monitoring --create-namespace
```

## 3. Required pre-flight fix: give Redis (`session-db`) a writable volume

**Do this before generating any load.** Sock-Shop's own upstream manifest
(`deploy/kubernetes/manifests/21-session-db-dep.yaml`) sets
`securityContext.readOnlyRootFilesystem: true` on the `session-db` (Redis)
container but never mounts a writable volume for `/data`, where Redis needs to
write its periodic snapshot. Under light manual browsing this rarely surfaces,
but under the sustained write load our load generator creates (Section 4), Redis's
background save fails on every attempt, its `stop-writes-on-bgsave-error` safety
setting kicks in, and it starts refusing all writes — which cascades into
`front-end` crash-looping (its session-manager calls to Redis start failing) and
compounds into a much noisier dataset. This is a genuine bug in the upstream repo,
not something introduced here, and simply redeploying the same manifest reproduces
it identically — it needs an actual patch:

```bash
kubectl patch deployment session-db -n sock-shop --type=json -p='[
  {"op":"add","path":"/spec/template/spec/volumes","value":[{"name":"redis-data","emptyDir":{}}]},
  {"op":"add","path":"/spec/template/spec/containers/0/volumeMounts","value":[{"name":"redis-data","mountPath":"/data"}]}
]'
kubectl rollout status deployment session-db -n sock-shop --timeout=60s
```

Verify it worked — force a save and confirm no "Read-only file system" error:
```bash
kubectl exec -n sock-shop deploy/session-db -- redis-cli BGSAVE
kubectl logs -n sock-shop -l name=session-db --tail=5
# expect: "BGSAVE done ... DB saved on disk ... Background saving terminated with success"
```

## 4. Generate a realistic "normal" baseline (load generator)

**This step matters and is easy to skip by mistake.** Without it, "normal" only
means *idle* (near-zero CPU/traffic), so the model never learns to tell legitimate
load apart from an actual anomaly. Deploy Sock-Shop's own Locust-based load
generator so normal-labeled data includes real, traffic-driven metric variation:

```bash
kubectl apply -f ~/Desktop/microservices-demo/deploy/kubernetes/manifests-loadtest/loadtest-dep.yaml
kubectl get pods -n loadtest    # wait until both replicas are Running
```

Verify it's actually generating load before moving on:
```bash
kubectl logs -n loadtest -l name=load-test --tail=15
```
You should see Locust request stats (GET /catalogue, /login, /basket.html, ...).

The default is 5 concurrent simulated users per replica (10 total). Adjust with:
```bash
kubectl patch deployment load-test -n loadtest --type='json' -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/args",
   "value":["-c","while true; do locust --host http://front-end.sock-shop.svc.cluster.local -f /config/locustfile.py --clients 5 --hatch-rate 5 --num-request 100 --no-web; done"]}
]'
```
Watch node memory headroom if you push this higher (`minikube ssh -- free -h`) —
this minikube node is genuinely resource-constrained (single node, shared with
Prometheus, the app, and every chaos-injection stress container), and heavier load
means more pod instability during the run (see Section 10).

## 5. Disable any auto-remediation agent

If you're also running the `sadmc-agent` (the live SaaS monitoring agent from
`HelmAndSaas/`), its auto-remediation rules (restart pod / throttle CPU / scale
replicas) will fire on the anomalies we're about to inject and corrupt the labels
(e.g. restarting the pod mid "Memory Leak" window). Scale it to 0 for the duration
of collection:

```bash
kubectl scale deployment sadmc-agent -n sadmc --replicas=0
```

`run_collection.py` does this automatically at startup and restores it to 1
replica in its `finally` block on exit (Section 7).

## 6. Point the chaos tool at the cluster

Minikube (with the `docker` driver) runs its own internal Docker daemon separate
from your host's. `pumba` needs to talk to *that* daemon to see the Sock-Shop
containers:

```bash
eval $(minikube docker-env)
```

Pre-pull the images `pumba` needs, so the first real injection doesn't stall on a
slow registry pull:
```bash
docker pull alexeiled/stress-ng
docker pull ghcr.io/alexei-led/pumba-alpine-nettools:latest
```

Sock-Shop container names inside minikube follow the pattern
`k8s_<container>_<pod>_sock-shop_<uid>_<attempt>`, so a container is targeted with
a regex like `re2:k8s_carts_.*_sock-shop_`.

## 7. The three anomaly types (manual pumba examples)

Useful to run by hand once, to see what each fault actually does before trusting
the automated scripts:

**CPU Hog** — pins one core to 100% load inside the target's cgroup:
```bash
pumba stress --duration 180s --stress-image alexeiled/stress-ng \
  --stressors "--cpu 1 --cpu-load 100" "re2:k8s_carts_.*_sock-shop_"
```

**Memory Leak** — continuously holds allocated memory:
```bash
pumba stress --duration 180s --stress-image alexeiled/stress-ng \
  --stressors "--vm 1 --vm-bytes 128M --vm-keep" "re2:k8s_carts_.*_sock-shop_"
```

**Network Latency** — delays egress packets via `tc netem`:
```bash
pumba netem --duration 180s --tc-image ghcr.io/alexei-led/pumba-alpine-nettools:latest \
  delay --time 500 "re2:k8s_carts_.*_sock-shop_"
```

## 8. The scripts, and the fixes already built into them

Everything above is automated by five scripts in `own_dataset/scripts/`. You don't
need to re-derive any of the fixes below — they're already implemented — but
understanding *why* they exist matters for interpreting the data.

| File | Role |
|---|---|
| `metric_queries.py` | The 35 PromQL feature queries (same schema as `HelmAndSaas/Agent/agent/metrics_collector.py`), the 7 service names, and the label map (`NORMAL=0, CPU_HOG=1, MEMORY_LEAK=2, NETWORK_LATENCY=3`). |
| `latency_prober.py` | Fires 3 quick HTTP GETs per service per cycle at its port-forwarded endpoint and returns (min, avg) round-trip ms. |
| `collector.py` | Runs in a background thread. Every 5s, queries all 35 metrics for all 7 services from Prometheus, overwrites the `net_latency_min`/`net_latency_avg` slots with the real probe result, and appends one row per service to `raw/<service>.csv`, tagged with whatever label is currently active for that service. |
| `injector.py` | Loops over all (service × anomaly type) combinations, 5 repeats each, interleaved so partial runs still cover every class. For each event: flips that service's label, runs the matching `pumba` command for a random 60-300s (1-5 min, matching the paper), then flips the label back to `NORMAL` and logs the event to `logs/injection_log.csv`. |
| `run_collection.py` | Entry point. Starts a `kubectl port-forward` to Prometheus plus one per service for the latency prober (8 total, each with a watchdog that restarts it if it drops), scales `sadmc-agent` to 0, starts the collector thread, then runs the injector loop. Restores `sadmc-agent` to 1 replica in its `finally` block on exit. |

**Fix 1 — pod-name regex contamination.** `pod=~"{name}-.*"` also matches a
service's own `-db` sibling (e.g. `carts-.*` matches both `carts-f4f6c98b9-cqfpz`
*and* `carts-db-594b68dc85-gx76m`), silently summing an unrelated database pod's
metrics into `carts`/`catalogue`/`orders`/`user`'s numbers and diluting every
anomaly signal for those 4 services. Fixed by anchoring the regex to the exact
two-segment Deployment pod-name pattern: `pod=~"{name}-[^-]+-[^-]+"` — a `-db`
pod's 3-segment suffix can't match this.

**Fix 2 — Network Latency had no real feature signal.** The original
`net_latency_min`/`net_latency_avg` columns queried Istio metrics, which are
always 0 here (no service mesh installed), and cAdvisor doesn't expose per-pod
network stats on this runtime either (Section 11). That left `NETWORK_LATENCY`
rows correctly labeled but with zero informative features. `latency_prober.py`
now measures real HTTP round-trip time and writes it into those same column
slots — verified to jump from ~50-90ms baseline to ~500-560ms during an actual
500ms-delay injection.

**Fix 3 — `pumba netem`'s helper image entrypoint bug.** The tc-image
(`ghcr.io/alexei-led/pumba-alpine-nettools`) has `ENTRYPOINT ["tail", "-f",
"/dev/null"]` (a keep-alive shim), not a shell — running a `tc` command against
it without overriding the entrypoint gets silently appended as arguments to
`tail` and hangs forever instead of executing. Separately, when a target
container crash-restarts mid-injection (common under sustained load — see
Section 10), `pumba`'s own cleanup can be interrupted, leaving a stale `tc` qdisc
that makes the *next* injection attempt fail with `tc ... failed with exit code
2` ("file exists"). Together these caused `NETWORK_LATENCY` injections to fail
outright for some services (`catalogue` failed all 5/5 attempts in the first full
run). Fixed in `injector.py`: before every `NETWORK_LATENCY` attempt, a
`clear_stale_qdisc()` helper joins the target's network namespace via a
throwaway container (`docker run --rm --cap-add NET_ADMIN --net
container:<target> --entrypoint tc <tc-image> qdisc del dev eth0 root`) to
guarantee a clean slate; if the real attempt still fails with that specific
error, it clears again and retries once.

## 9. Run the collector + injector

Run it (foreground, for a quick test):
```bash
cd own_dataset/scripts
python run_collection.py
```

Run it as a long-lived background job (the full sweep takes ~8.5 hours: 7
services × 3 anomaly types × 5 repeats, ~1-5 min anomaly + 2 min recovery gap per
event — shortened from the paper's 10-30 min gap purely to keep a full sweep
tractable):
```bash
cd own_dataset/scripts
nohup python run_collection.py > /dev/null 2>&1 &
disown
```

Stop it early any time with `kill <pid>` — it shuts down gracefully and restores
`sadmc-agent`. Rows already written to the CSVs are never lost (every write is
flushed to disk immediately), so a partial run is still usable.

## 10. What's normal to see during a long run (don't panic)

Over several hours of continuous load + repeated stress injections, this
single-node minikube setup accumulates real resource pressure — none of the
following indicates the pipeline is broken:

- **`front-end`/`catalogue`/`payment`/`user` cycling between `Running` and
  `CrashLoopBackOff`, restart counts climbing into the dozens or higher.** These
  services have tight readiness/liveness probe timeouts (as low as 1s). As node
  memory fills up (swap can go fully exhausted over a multi-hour run) and CPU gets
  contended by concurrent Locust traffic and stress containers, ordinarily-instant
  health checks occasionally take just over that timeout, and kubelet restarts
  the container. This is *not* correlated with a service's own targeted
  injection windows — it's general node pressure, and it gets worse the longer
  the run goes and the higher the load-test client count is set.
- **`net_latency_min/avg` reading exactly `2000` (the probe timeout ceiling) for
  a service during a restart cycle.** This is the latency prober correctly
  reporting "this pod was unreachable," not a broken measurement.
- **A single injection event's logged start-to-end span being much longer than
  its `duration_s`** (e.g. a 249s event spanning 1.5 real hours). This means the
  laptop was suspended (lid closed) partway through. Suspend freezes every
  process — the script, `pumba`, the target container — exactly where they were;
  everything resumes correctly on wake with no data loss, just a time gap in the
  timestamps. Keep the laptop plugged in during a long run so the battery
  doesn't die mid-suspend, which *would* actually kill the run.
- **A handful of `NETWORK_LATENCY` events still failing here and there** even
  with Fix 3 applied (Section 8) — a container can still crash at the exact
  instant of injection. If one *specific* service ends up with persistently poor
  `NETWORK_LATENCY` coverage after a full sweep, see Section 12 for a targeted
  top-up rather than rerunning everything.

## 11. Output

```
own_dataset/
├── raw/
│   ├── carts.csv
│   ├── catalogue.csv
│   ├── front-end.csv
│   ├── orders.csv
│   ├── payment.csv
│   ├── shipping.csv
│   └── user.csv
└── logs/
    ├── run.log                       # full run log
    ├── port-forward-prometheus.log   # Prometheus tunnel output
    ├── port-forward-<service>.log    # one per service, for the latency prober
    └── injection_log.csv             # ground-truth: which service/fault/window, per event
```

Each `raw/<service>.csv` row:
```
timestamp_unix, timestamp_iso, <35 feature columns>, label, label_name
```

| label | label_name | meaning |
|---|---|---|
| 0 | NORMAL | no fault active (includes load-generator traffic) |
| 1 | CPU_HOG | CPU stress active on this service |
| 2 | MEMORY_LEAK | memory stress active on this service |
| 3 | NETWORK_LATENCY | network delay active on this service |

Every service is scraped every 5s **regardless of which service is currently
being attacked** — so while `carts` is under CPU_HOG, the other 6 services keep
collecting clean `NORMAL` rows in parallel. That's what makes each per-service
CSV end up with a realistic mix of all 4 classes once the full sweep finishes.

Checking progress while it runs:
```bash
tail -f own_dataset/logs/run.log                 # live log
cat own_dataset/logs/injection_log.csv           # completed events so far (note: use csv.reader,
                                                  # not wc -l - failed-event error text can contain
                                                  # embedded newlines and will overcount plain line counts)

python3 -c "
import csv, collections, glob
for path in sorted(glob.glob('own_dataset/raw/*.csv')):
    with open(path) as f:
        r = csv.reader(f); header = next(r)
        idx = header.index('label_name')
        print(path, dict(collections.Counter(row[idx] for row in r)))
"
```

## 12. Topping up a sparse service/anomaly-type combination

If, after a full sweep, one (service, anomaly type) pair ended up with too few
rows (a run of consecutive failures, or the service happened to be unstable
every time that combination came up), don't rerun the whole 105-event sweep —
top up just that one gap. `own_dataset/scripts/topup_catalogue_network_latency.py`
is a template for this: it monkeypatches `collector.SERVICES` /
`injector.SERVICES` down to a single service and `injector.ANOMALY_TYPES` down to
a single fault type, reuses the same collector/injector/port-forward machinery,
and appends directly to the existing `raw/<service>.csv` and
`logs/injection_log.csv` — no data is overwritten. To reuse it for a different
gap, copy the file and change `TARGET_SERVICE`, the anomaly type list, and the
local port number to match the service you need.

## 13. Known limitations (for the write-up)

- **Feature set**: the 35 columns match the paper's feature dimension for
  comparability. `net_latency_min`/`net_latency_avg` are real, actively-measured
  values (Section 8, Fix 2) — the strongest signal for the `NETWORK_LATENCY`
  class. CPU usage/throttling, memory RSS/cache/usage, and disk read/write also
  carry real signal. The remaining columns (container network *byte counters*,
  Istio request count/2xx/4xx/5xx, Go-runtime goroutines/GC) are still
  structurally zero: raw cAdvisor output on this node only reports network byte
  counters at the root cgroup level (never attributed to a specific pod — a
  runtime/CRI limitation, not a Prometheus config issue), and no Istio service
  mesh is installed. Sock-Shop's own services *do* expose rich native metrics on
  their own `/metrics` endpoints (JVM heap for `carts`/`orders`/`shipping`, Go
  runtime stats for `catalogue`/`payment`/`user`) — but nothing currently
  scrapes them (no ServiceMonitor/PodMonitor targets the `sock-shop` namespace).
  That's a separate, addable enhancement, not attempted here since it mainly
  helps CPU_HOG/MEMORY_LEAK detection, which cAdvisor already covers well,
  rather than the network case.
- **Timing**: anomaly duration (1-5 min) matches the paper; the recovery gap
  between repeats was shortened to 2 minutes (from the paper's 10-30 min) purely
  to keep a full sweep to ~8.5 hours instead of ~24.
- **`front-end`'s dataset specifically may include some real cascading-failure
  noise**: it's the only service that synchronously calls several others
  (`carts`, `catalogue`, `orders`, `user`); if one of those crashes or slows down
  under its own injected fault, `front-end` can show secondary distress (crashes,
  latency spikes) while still correctly labeled `NORMAL` (since *it* wasn't the
  injection target). This mirrors the real "anomaly propagation" problem the
  paper itself describes as a core microservices challenge, but it does mean
  `front-end`'s `NORMAL` class isn't perfectly clean. `logs/injection_log.csv`
  has exact timestamps for every other service's injection windows, so this is
  cleanable at preprocessing time (drop or relabel `front-end` rows whose
  timestamp falls inside another service's active injection window) rather than
  something to fix at collection time.
- **Old Sock-Shop images**: this Weaveworks demo is several years old.
  `front-end` in particular runs Node.js v4.8.0 (2016-era) and doesn't handle
  unexpected/malformed responses from a degraded dependency gracefully — an
  unhandled `JSON.parse` exception on an empty response is enough to crash the
  whole process (this is the mechanism behind the cascading-failure note above).
  This is a pre-existing app defect in the upstream demo, not something to patch.

## 14. Final dataset achieved (one completed run, for reference)

A full 105-event sweep plus one small top-up (Section 12, to fix `catalogue`'s
`NETWORK_LATENCY` class, which failed all 5 attempts in the main sweep due to
Fix 3's underlying bug not yet being applied at the time) produced:

| Service | rows | NORMAL | CPU_HOG | MEMORY_LEAK | NETWORK_LATENCY |
|---|---|---|---|---|---|
| carts | 5,567 | 5,082 | 143 | 179 | 163 |
| catalogue | 5,850 | 5,305 | 186 | 194 | 165 |
| front-end | 5,567 | 5,339 | 112 | 61 | 55 |
| orders | 5,567 | 4,972 | 200 | 202 | 193 |
| payment | 5,567 | 5,089 | 193 | 225 | 60 |
| shipping | 5,567 | 5,094 | 131 | 200 | 142 |
| user | 5,567 | 5,150 | 192 | 185 | 40 |
| **Total** | **39,252** | **36,031** | **1,157** | **1,246** | **818** |

15/105 events (14%, all `NETWORK_LATENCY`) failed in the main sweep before Fix 3
was applied — this is the expected failure rate to compare against if you rerun
the sweep with the fix already in place from the start; it should be far lower.

## 15. Optional next step: matching the training pipeline's format

The existing federated-learning code (`code/sadmc-mt-ff-fl.py`) expects
`Mul_Class_Data/<service>.csv_{Xtrain,Ytrain,Xtest,Ytest}.npy` (MinMax-normalized,
one-hot labels — see `code/dataprocessing.py` for the original conversion logic).
Converting `own_dataset/raw/*.csv` into that format (drop timestamps, MinMax
scale, train/test split, one-hot encode) is a separate, later step once enough
data has been collected.
