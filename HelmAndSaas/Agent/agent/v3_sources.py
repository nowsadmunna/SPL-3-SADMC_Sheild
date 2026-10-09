"""
v3 sources for the agent: reads cAdvisor, the apps' /metrics and the latency probe from INSIDE the node (one `docker exec` per
cycle) and the pod state from the Kubernetes API.

The constants and the parse_*/node_script/split_sections functions below are COPIED, not rewritten, from
SADMC-MT-FF-FL/own_dataset/scripts/v3/collector_v3.py (the collector that produced the training data). Regenerate with
Agent/tools/sync_v3_sources.py; tests/test_v3_sources_in_sync.py fails when they differ.

Dev/lab mode: the node is a docker container (minikube). An in-cluster deployment needs a different transport for the same
queries; the parsing and the feature definitions do not change.
"""
import json
import os
import re
import subprocess

from .feature_defs_v3 import PROBE_TIMEOUT_MS, RAW, RAW_COLUMNS, SERVICES

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


# ---------------------------------------------------------------------------------------------------------------------
# Agent-specific part (not copied): which services, and how the node-side script's output is obtained.
# A "service key" is "<namespace>/<name>"; everything copied above only sees these strings.
# ---------------------------------------------------------------------------------------------------------------------
import concurrent.futures
import time

import httpx

APP_LINE = re.compile(
    r"^(request_duration_seconds_(count|sum)[{]|process_open_fds |process_cpu_seconds_total |go_gc_duration_seconds_sum |"
    r"jvm_threads_current |go_goroutines |nodejs_active_handles_total )")
CADVISOR_LINE = re.compile(r"^(" + "|".join(CADVISOR_MAP) + r")[{]")


def sh(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout


def key_of(namespace, name):
    return f"{namespace}/{name}"


def service_endpoints(core_v1, services):
    """services: [(namespace, name)] -> {key: {"ip", "port"}} from the Service objects (first port)."""
    out = {}
    wanted = set(services)
    for s in core_v1.list_service_for_all_namespaces().items:
        k = (s.metadata.namespace, s.metadata.name)
        if k in wanted and s.spec.cluster_ip and s.spec.ports:
            out[key_of(*k)] = {"ip": s.spec.cluster_ip, "port": s.spec.ports[0].port}
    return out


def pod_state(core_v1, services):
    """-> (uid_to_key, restarts, ready) for the pods behind `services` ([(namespace, name)])."""
    wanted = set(services)
    uid_to_key, restarts, ready = {}, {}, {}
    for p in core_v1.list_pod_for_all_namespaces().items:
        name = re.sub(r"-[0-9a-f]{6,10}-[a-z0-9]{5}$", "", p.metadata.name)
        if (p.metadata.namespace, name) not in wanted:
            continue
        k = key_of(p.metadata.namespace, name)
        uid_to_key[p.metadata.uid.replace("-", "_")] = k
        st = p.status.container_statuses or []
        restarts[k] = restarts.get(k, 0) + sum(c.restart_count for c in st)
        ready[k] = ready.get(k, 0) + (1 if st and all(c.ready for c in st) else 0)
    return uid_to_key, restarts, ready


def transport_mode():
    """"incluster" when running as a pod (cAdvisor, the apps and the probe are read over the pod network),
    "node-exec" in the lab (one `docker exec` into the minikube node). V3_TRANSPORT forces one."""
    forced = os.getenv("V3_TRANSPORT")
    if forced:
        return forced
    return "incluster" if os.getenv("KUBERNETES_SERVICE_HOST") else "node-exec"


def cadvisor_urls(core_v1):
    """V3_CADVISOR_URLS (comma separated) or the endpoints of the Service named in V3_CADVISOR_SERVICE ("<ns>/<name>")."""
    explicit = os.getenv("V3_CADVISOR_URLS")
    if explicit:
        return [u.strip() for u in explicit.split(",") if u.strip()]
    ref = os.getenv("V3_CADVISOR_SERVICE")
    if not ref:
        return []
    ns, name = ref.split("/")
    ep = core_v1.read_namespaced_endpoints(name, ns)
    port = int(os.getenv("V3_CADVISOR_PORT", "8080"))
    return [f"http://{a.ip}:{port}/metrics" for sub in (ep.subsets or []) for a in (sub.addresses or [])]


def _fetch_service(client, key, ep):
    base = f"http://{ep['ip']}:{ep['port']}"
    app_lines = []
    try:
        r = client.get(f"{base}/metrics", timeout=3)
        app_lines = [l for l in r.text.splitlines() if APP_LINE.match(l)]
    except httpx.HTTPError:
        pass
    path = PROBE_PATHS.get(key.split("/", 1)[1], "/")
    probes = []
    for _ in range(PROBES_PER_CYCLE):
        t0 = time.perf_counter()
        try:
            r = client.get(f"{base}{path}", timeout=2)
            probes.append(f"{r.status_code} {time.perf_counter() - t0:.6f}")
        except httpx.HTTPError:
            probes.append("000 2.000000")
    return key, app_lines, probes


def incluster_sections(core_v1, endpoints):
    sections = {"cadvisor": []}
    with httpx.Client() as client:
        for url in cadvisor_urls(core_v1):
            try:
                sections["cadvisor"] += [l for l in client.get(url, timeout=8).text.splitlines() if CADVISOR_LINE.match(l)]
            except httpx.HTTPError:
                pass
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            for key, app_lines, probes in pool.map(lambda kv: _fetch_service(client, *kv), endpoints.items()):
                sections[f"APP:{key}"] = app_lines
                sections[f"PROBE:{key}"] = probes
    return sections


def node_script_for(ips):
    """node_script() loops over the fixed SERVICES list; this builds the same script for any name -> ip map (lab transport)."""
    names = "|".join(CADVISOR_MAP)
    parts = [f"curl -s -m 8 {CADVISOR_URL} | grep -E '^({names})[{{]'", "echo '##END'"]
    for s, ip in ips.items():
        base = f"http://{ip}:80"
        parts.append(f"echo '##APP {s}'")
        parts.append(f"curl -s -m 3 {base}/metrics | grep -E '^(request_duration_seconds_(count|sum)[{{]|process_open_fds |process_cpu_seconds_total |"
                     f"go_gc_duration_seconds_sum |jvm_threads_current |go_goroutines |nodejs_active_handles_total )'")
        parts.append(f"echo '##PROBE {s}'")
        parts.append(f"for i in $(seq {PROBES_PER_CYCLE}); do curl -s -o /dev/null -m 2 -w '%{{http_code}} %{{time_total}}\\n' "
                     f"{base}{PROBE_PATHS.get(s, '/')}; done")
    return "; ".join(parts)


def node_exec_sections(endpoints):
    """Lab transport: the same reads as incluster_sections, done inside the minikube node by one `docker exec`.
    The script addresses services by bare name, so this mode supports services of one namespace at a time per name."""
    by_name = {k.split("/", 1)[1]: k for k in endpoints}
    ips = {name: endpoints[k]["ip"] for name, k in by_name.items()}
    sec = split_sections(sh(["docker", "exec", NODE, "sh", "-c", node_script_for(ips)], 40))
    sections = {"cadvisor": sec.get("cadvisor", [])}
    for name, k in by_name.items():
        sections[f"APP:{k}"] = sec.get(f"APP:{name}", [])
        sections[f"PROBE:{k}"] = sec.get(f"PROBE:{name}", [])
    return sections


def sample_cluster(core_v1, services, endpoints):
    """One raw sample per service key: {key: {raw_column: value}}.  services: [(namespace, name)]."""
    uid_to_key, restarts, ready = pod_state(core_v1, services)
    keys = list(endpoints)
    sections = incluster_sections(core_v1, endpoints) if transport_mode() == "incluster" else node_exec_sections(endpoints)
    cad = parse_cadvisor(sections.get("cadvisor", []), uid_to_key, keys)
    rows = {}
    for k in keys:
        row = {}
        row.update(cad.get(k, {}))
        row.update(parse_app(sections.get(f"APP:{k}", [])))
        row.update(parse_probe(sections.get(f"PROBE:{k}", [])))
        row["restarts"], row["ready"] = restarts.get(k, 0), ready.get(k, 0)
        rows[k] = row
    return rows
