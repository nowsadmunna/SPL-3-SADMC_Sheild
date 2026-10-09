"""
v3 raw collector: every 5 s, one row per service with the RAW values listed in feature_defs.RAW
(cumulative counters stay cumulative; features are derived later with feature_defs.derive_features).

All reads happen from inside the minikube node with ONE `docker exec` per cycle (cAdvisor + every app's /metrics +
the latency probe), plus one `kubectl get pods`. Nothing here changes the cluster.

Labels come from the injector through two shared dicts: state[service] -> int label, event_ids[service] -> str.
"""
import csv
import json
import logging
import os
import re
import subprocess
import threading
import time
from datetime import datetime, timezone

from feature_defs import LABEL_NAMES, RAW, RAW_COLUMNS, SERVICES, PROBE_TIMEOUT_MS

logger = logging.getLogger("collector_v3")

NAMESPACE = "sock-shop"
INTERVAL_S = 5
NODE = os.getenv("V3_NODE_CONTAINER", "minikube")
CADVISOR_URL = os.getenv("V3_CADVISOR_URL", "http://localhost:18080/metrics")
PROBE_PATHS = {"carts": "/health", "catalogue": "/health", "front-end": "/", "orders": "/", "payment": "/health",
               "shipping": "/health", "user": "/health"}
PROBES_PER_CYCLE = 3

CADVISOR_MAP = {
    "container_cpu_user_seconds_total": "cpu_user_s", "container_cpu_system_seconds_total": "cpu_system_s",
    "container_cpu_usage_seconds_total": "cpu_usage_s", "container_cpu_cfs_throttled_seconds_total": "cpu_throttled_s",
    "container_cpu_cfs_periods_total": "cpu_cfs_periods", "container_cpu_cfs_throttled_periods_total": "cpu_throttled_periods",
    "container_memory_rss": "mem_rss", "container_memory_cache": "mem_cache", "container_memory_usage_bytes": "mem_usage",
    "container_memory_working_set_bytes": "mem_working_set", "container_memory_swap": "mem_swap",
    "container_memory_failcnt": "mem_failcnt",
    "container_network_receive_bytes_total": "net_rx_bytes", "container_network_receive_packets_total": "net_rx_packets",
    "container_network_receive_errors_total": "net_rx_errors", "container_network_receive_packets_dropped_total": "net_rx_drop",
    "container_network_transmit_bytes_total": "net_tx_bytes", "container_network_transmit_packets_total": "net_tx_packets",
    "container_network_transmit_errors_total": "net_tx_errors", "container_network_transmit_packets_dropped_total": "net_tx_drop",
    "container_fs_reads_bytes_total": "fs_read_bytes", "container_fs_writes_bytes_total": "fs_write_bytes",
    "container_fs_reads_total": "fs_reads", "container_fs_writes_total": "fs_writes",
    "container_fs_io_time_seconds_total": "fs_io_time_s",
}
_CADVISOR_RE = re.compile(r"^(" + "|".join(CADVISOR_MAP) + r')\{(.*?)\}\s+(\S+)')
_LABEL_RE = re.compile(r'(\w+)="([^"]*)"')
_APP_REQ = re.compile(r'^request_duration_seconds_(count|sum)\{(.*?)\}\s+(\S+)')
_APP_GAUGES = (
    ("app_open_fds", re.compile(r"^process_open_fds\s+(\S+)")),
    ("app_cpu_s", re.compile(r"^process_cpu_seconds_total\s+(\S+)")),
    ("app_gc_s", re.compile(r"^go_gc_duration_seconds_sum\s+(\S+)")),
    ("app_threads", re.compile(r"^(?:jvm_threads_current|go_goroutines|nodejs_active_handles_total)\s+(\S+)")),
)
_NET_COUNTERS = {k for k, v in CADVISOR_MAP.items() if "network" in k}


def sh(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout


def service_ips():
    out = {}
    for s in SERVICES:
        ip = sh(["kubectl", "get", "svc", "-n", NAMESPACE, s, "-o", "jsonpath={.spec.clusterIP}"], 20).strip()
        out[s] = ip
    return out


def node_script(ips):
    names = "|".join(CADVISOR_MAP)
    parts = [f"curl -s -m 8 {CADVISOR_URL} | grep -E '^({names})[{{]'", "echo '##END'"]
    for s in SERVICES:
        base = f"http://{ips[s]}:80"
        parts.append(f"echo '##APP {s}'")
        parts.append(f"curl -s -m 3 {base}/metrics | grep -E '^(request_duration_seconds_(count|sum)[{{]|process_open_fds |process_cpu_seconds_total |"
                     f"go_gc_duration_seconds_sum |jvm_threads_current |go_goroutines |nodejs_active_handles_total )'")
        parts.append(f"echo '##PROBE {s}'")
        parts.append(f"for i in $(seq {PROBES_PER_CYCLE}); do curl -s -o /dev/null -m 2 -w '%{{http_code}} %{{time_total}}\\n' "
                     f"{base}{PROBE_PATHS[s]}; done")
    return "; ".join(parts)


def parse_cadvisor(lines, uid_to_service, services=SERVICES):
    acc = {s: {} for s in services}
    for line in lines:
        m = _CADVISOR_RE.match(line)
        if not m:
            continue
        metric, labels, value = m.group(1), dict(_LABEL_RE.findall(m.group(2))), m.group(3)
        u = re.search(r"pod([0-9a-f_]{36})", labels.get("id", ""))
        if not u or u.group(1) not in uid_to_service:
            continue
        svc = uid_to_service[u.group(1)]
        if metric in _NET_COUNTERS:
            # the pod sandbox ("POD") owns the network namespace; count its eth0 only
            if labels.get("container_label_io_kubernetes_container_name") != "POD" or labels.get("interface") != "eth0":
                continue
        elif labels.get("id", "").endswith(".slice"):
            continue   # pod-level cgroup would double count its children (not exported with docker_only, kept as a guard)
        try:
            v = float(value)
        except ValueError:
            continue
        col = CADVISOR_MAP[metric]
        acc[svc][col] = acc[svc].get(col, 0.0) + v
    return acc


def parse_app(lines):
    r = {"http_n2xx": 0.0, "http_n4xx": 0.0, "http_n5xx": 0.0, "http_dur_sum_s": 0.0}
    seen = False
    for l in lines:
        m = _APP_REQ.match(l)
        if m:
            kind, lab, v = m.group(1), m.group(2), float(m.group(3))
            if 'route="metrics"' in lab:
                continue   # do not count our own scrape
            seen = True
            if kind == "sum":
                r["http_dur_sum_s"] += v
            else:
                c = re.search(r'status_code="(\d)', lab)
                if c and c.group(1) in "245":
                    r[f"http_n{c.group(1)}xx"] += v
            continue
        for col, pat in _APP_GAUGES:
            g = pat.match(l)
            if g:
                r[col] = float(g.group(1))
                seen = True
    return r if seen else {}


def parse_probe(lines):
    ms, ok = [], 0
    for l in lines:
        p = l.split()
        if len(p) != 2:
            continue
        code, t = p[0], float(p[1]) * 1000
        if code.startswith(("2", "3")):
            ms.append(t)
            ok += 1
        else:
            ms.append(PROBE_TIMEOUT_MS)
    ms += [PROBE_TIMEOUT_MS] * (PROBES_PER_CYCLE - len(ms))
    return {"probe_min_ms": min(ms), "probe_avg_ms": sum(ms) / len(ms), "probe_ok": ok / PROBES_PER_CYCLE}


def split_sections(text):
    sections, cur, key = {}, [], "cadvisor"
    for l in text.splitlines():
        if l.startswith("##END"):
            sections["cadvisor"] = cur; cur = []; key = None
        elif l.startswith("##APP ") or l.startswith("##PROBE "):
            if key:
                sections[key] = cur
            cur, key = [], l[2:].replace(" ", ":")
        else:
            cur.append(l)
    if key:
        sections[key] = cur
    return sections


def kube_state():
    data = json.loads(sh(["kubectl", "get", "pods", "-n", NAMESPACE, "-o", "json"], 30))
    uid_to_service, restarts, ready = {}, {s: 0 for s in SERVICES}, {s: 0 for s in SERVICES}
    for p in data["items"]:
        svc = re.sub(r"-[0-9a-f]{6,10}-[a-z0-9]{5}$", "", p["metadata"]["name"])
        if svc not in SERVICES:
            continue
        uid_to_service[p["metadata"]["uid"].replace("-", "_")] = svc
        st = p.get("status", {}).get("containerStatuses", [])
        restarts[svc] += sum(c.get("restartCount", 0) for c in st)
        if st and all(c.get("ready") for c in st):
            ready[svc] += 1
    return uid_to_service, restarts, ready


class CollectorV3:
    def __init__(self, raw_dir, state, event_ids, stop_event):
        self.state, self.event_ids, self.stop = state, event_ids, stop_event
        os.makedirs(raw_dir, exist_ok=True)
        self.ips = service_ips()
        self.header = ["t_unix", "t_iso"] + RAW_COLUMNS + ["label", "label_name", "event_id"]
        self.files, self.writers = {}, {}
        for s in SERVICES:
            path = os.path.join(raw_dir, f"{s}.csv")
            new = not os.path.exists(path) or os.path.getsize(path) == 0
            f = open(path, "a", newline="")
            w = csv.writer(f)
            if new:
                w.writerow(self.header)
            self.files[s], self.writers[s] = f, w
        self.failures = 0

    def once(self):
        t = time.time()
        iso = datetime.now(timezone.utc).isoformat()
        uid_to_service, restarts, ready = kube_state()
        out = sh(["docker", "exec", NODE, "sh", "-c", node_script(self.ips)], 40)
        sec = split_sections(out)
        cad = parse_cadvisor(sec.get("cadvisor", []), uid_to_service)
        for s in SERVICES:
            row = {}
            row.update(cad.get(s, {}))
            row.update(parse_app(sec.get(f"APP:{s}", [])))
            row.update(parse_probe(sec.get(f"PROBE:{s}", [])))
            row["restarts"], row["ready"] = restarts[s], ready[s]
            label = self.state.get(s, 0)
            self.writers[s].writerow([round(t, 3), iso] + [row.get(c, "") for c in RAW_COLUMNS]
                                     + [label, LABEL_NAMES[label], self.event_ids.get(s, "")])
            self.files[s].flush()

    def run(self):
        logger.info("collector v3 started (every %ss)", INTERVAL_S)
        while not self.stop.is_set():
            t0 = time.time()
            try:
                self.once()
            except Exception:
                self.failures += 1
                logger.exception("collection cycle failed (%d so far)", self.failures)
            self.stop.wait(max(0.0, INTERVAL_S - (time.time() - t0)))
        for f in self.files.values():
            f.close()
        logger.info("collector v3 stopped")


def start(raw_dir, state, event_ids, stop_event):
    c = CollectorV3(raw_dir, state, event_ids, stop_event)
    th = threading.Thread(target=c.run, daemon=True, name="collector_v3")
    th.start()
    return th
