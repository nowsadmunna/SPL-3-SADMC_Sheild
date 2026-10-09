"""
Single source of truth for the v3 feature schema.

The v3 collector stores RAW values every 5 s (cumulative counters stay cumulative, gauges stay gauges).
Features are DERIVED from them by derive_features() below, with one fixed rate window. The SaaS agent must
build its features with the same definitions (same raw sources, same window, same units); keep this file the
only place where that is written down.

Why raw + derive instead of storing rates: the window length is a modelling choice (a 1-minute rate lags the
fault label by up to a minute), and storing raw counters lets us change it without collecting again.

Sources (all need no cooperation from the monitored app except the `app_*` / `http_*` group):
  cadvisor : standalone cAdvisor, series attributed to a service by POD UID in the cgroup path
             (the injected stress container carries no pod label, so label matching would miss it)
  app      : the application's own /metrics (request_duration_seconds, process_*, jvm_/go_/nodejs_ gauges)
  probe    : 3 HTTP GETs from inside the node to the service's ClusterIP (latency + success)
  kube     : pod status from the Kubernetes API
"""
import numpy as np

SERVICES = ["carts", "catalogue", "front-end", "orders", "payment", "shipping", "user"]
LABEL_NAMES = {0: "NORMAL", 1: "CPU_HOG", 2: "MEMORY_LEAK", 3: "NETWORK_LATENCY"}

# raw column -> (source, kind)   kind: counter = cumulative (rate is derived), gauge = instantaneous
RAW = {
    # cAdvisor, CPU
    "cpu_user_s": ("cadvisor", "counter"), "cpu_system_s": ("cadvisor", "counter"), "cpu_usage_s": ("cadvisor", "counter"),
    "cpu_throttled_s": ("cadvisor", "counter"), "cpu_cfs_periods": ("cadvisor", "counter"),
    "cpu_throttled_periods": ("cadvisor", "counter"),
    # cAdvisor, memory
    "mem_rss": ("cadvisor", "gauge"), "mem_cache": ("cadvisor", "gauge"), "mem_usage": ("cadvisor", "gauge"),
    "mem_working_set": ("cadvisor", "gauge"), "mem_swap": ("cadvisor", "gauge"), "mem_failcnt": ("cadvisor", "counter"),
    # cAdvisor, network (eth0 of the pod's sandbox)
    "net_rx_bytes": ("cadvisor", "counter"), "net_rx_packets": ("cadvisor", "counter"),
    "net_rx_errors": ("cadvisor", "counter"), "net_rx_drop": ("cadvisor", "counter"),
    "net_tx_bytes": ("cadvisor", "counter"), "net_tx_packets": ("cadvisor", "counter"),
    "net_tx_errors": ("cadvisor", "counter"), "net_tx_drop": ("cadvisor", "counter"),
    # cAdvisor, filesystem (fs_* is weak on this setup: device-level, see the pilot notes)
    "fs_read_bytes": ("cadvisor", "counter"), "fs_write_bytes": ("cadvisor", "counter"),
    "fs_reads": ("cadvisor", "counter"), "fs_writes": ("cadvisor", "counter"), "fs_io_time_s": ("cadvisor", "counter"),
    # app /metrics (cumulative request counters exclude the scrape of /metrics itself)
    "http_n2xx": ("app", "counter"), "http_n4xx": ("app", "counter"), "http_n5xx": ("app", "counter"),
    "http_dur_sum_s": ("app", "counter"), "app_cpu_s": ("app", "counter"), "app_gc_s": ("app", "counter"),
    "app_open_fds": ("app", "gauge"), "app_threads": ("app", "gauge"),
    # probe (per cycle, not cumulative)
    "probe_min_ms": ("probe", "gauge"), "probe_avg_ms": ("probe", "gauge"), "probe_ok": ("probe", "gauge"),
    # kube
    "restarts": ("kube", "gauge"), "ready": ("kube", "gauge"),
}
RAW_COLUMNS = list(RAW)

# A series that does not exist (no GC counter outside Go, no fs series for a container without a block device, ...)
# is reported as ABSENT by the source. For these columns absent means 0; anything else missing stays NaN.
ABSENT_MEANS_ZERO = {"fs_read_bytes", "fs_write_bytes", "fs_reads", "fs_writes", "fs_io_time_s", "app_gc_s",
                     "mem_swap", "mem_failcnt", "cpu_throttled_s", "cpu_throttled_periods"}

# Kept in the raw files, but NOT to be used as model input. The fault tool (Pumba) runs stress-ng / tc in an extra
# container inside the target's cgroup; its image reads, page cache and block I/O show up in these columns only while
# a fault is running (v3 pilot: payment fs_reads x28899, mem_cache 0 -> non-zero, only on the services that got a
# fault). A real incident has no such container, so a model would learn the tool, not the fault. fs_* is also
# device-level (nearly identical across services) and mostly empty.
ARTIFACT_SUSPECTS = {
    "mem_cache_mb": "page cache of the injected stress container",
    "fs_read_bytes_rate": "injected container's image reads / device-level", "fs_write_bytes_rate": "idem",
    "fs_reads_rate": "idem", "fs_writes_rate": "idem", "fs_io_time_rate": "idem",
}

RATE_WINDOW_S = 60          # same order as the 1 m window of the earlier datasets / of typical Prometheus rate()
PROBE_TIMEOUT_MS = 2000.0   # a failed probe counts as the timeout, as in the earlier datasets

# feature name -> (formula kind, raw column(s), scale)
#   rate   : counter delta over RATE_WINDOW_S per second, times scale   (negative deltas = counter reset -> 0)
#   gauge  : value times scale
#   ratio  : rate(num) / rate(den) times scale, 0 when den == 0
FEATURES = {
    "cpu_user_pct":           ("rate", "cpu_user_s", 100.0),
    "cpu_system_pct":         ("rate", "cpu_system_s", 100.0),
    "cpu_total_pct":          ("rate", "cpu_usage_s", 100.0),
    "cpu_throttled_rate":     ("rate", "cpu_throttled_s", 1.0),
    "cpu_cfs_periods_rate":   ("rate", "cpu_cfs_periods", 1.0),
    "cpu_throttled_periods_rate": ("rate", "cpu_throttled_periods", 1.0),
    "mem_rss_mb":             ("gauge", "mem_rss", 1 / 1048576),
    "mem_cache_mb":           ("gauge", "mem_cache", 1 / 1048576),
    "mem_usage_mb":           ("gauge", "mem_usage", 1 / 1048576),
    "mem_working_set_mb":     ("gauge", "mem_working_set", 1 / 1048576),
    "mem_swap_mb":            ("gauge", "mem_swap", 1 / 1048576),
    "mem_failcnt_rate":       ("rate", "mem_failcnt", 1.0),
    "net_rx_bytes_rate":      ("rate", "net_rx_bytes", 1.0),
    "net_rx_packets_rate":    ("rate", "net_rx_packets", 1.0),
    "net_rx_errors_rate":     ("rate", "net_rx_errors", 1.0),
    "net_rx_drop_rate":       ("rate", "net_rx_drop", 1.0),
    "net_tx_bytes_rate":      ("rate", "net_tx_bytes", 1.0),
    "net_tx_packets_rate":    ("rate", "net_tx_packets", 1.0),
    "net_tx_errors_rate":     ("rate", "net_tx_errors", 1.0),
    "net_tx_drop_rate":       ("rate", "net_tx_drop", 1.0),
    "fs_read_bytes_rate":     ("rate", "fs_read_bytes", 1.0),
    "fs_write_bytes_rate":    ("rate", "fs_write_bytes", 1.0),
    "fs_reads_rate":          ("rate", "fs_reads", 1.0),
    "fs_writes_rate":         ("rate", "fs_writes", 1.0),
    "fs_io_time_rate":        ("rate", "fs_io_time_s", 1.0),
    "http_req_rate":          ("rate", "http_n2xx", 1.0),          # replaced below: sum of the three classes
    "http_latency_ms":        ("ratio", ("http_dur_sum_s", "http_req_total"), 1000.0),
    "http_2xx_rate":          ("rate", "http_n2xx", 1.0),
    "http_4xx_rate":          ("rate", "http_n4xx", 1.0),
    "http_5xx_rate":          ("rate", "http_n5xx", 1.0),
    "app_cpu_pct":            ("rate", "app_cpu_s", 100.0),
    "app_gc_rate":            ("rate", "app_gc_s", 1.0),
    "app_open_fds":           ("gauge", "app_open_fds", 1.0),
    "app_threads":            ("gauge", "app_threads", 1.0),
    "probe_latency_min_ms":   ("gauge", "probe_min_ms", 1.0),
    "probe_latency_avg_ms":   ("gauge", "probe_avg_ms", 1.0),
    "probe_ok_ratio":         ("gauge", "probe_ok", 1.0),
    "restarts":               ("gauge", "restarts", 1.0),
    "ready":                  ("gauge", "ready", 1.0),
}
FEATURE_NAMES = list(FEATURES)


def _rate(t, x, window=RATE_WINDOW_S):
    """Per-second increase of a cumulative counter over the last `window` seconds (NaN until a full window exists).
    A negative delta means the counter was reset by a pod restart: reported as 0."""
    out = np.full(len(x), np.nan)
    j = 0
    for i in range(len(x)):
        while j < i and t[j + 1] <= t[i] - window:
            j += 1
        if t[i] - t[j] >= window * 0.8 and not (np.isnan(x[i]) or np.isnan(x[j])):
            d = x[i] - x[j]
            out[i] = max(d, 0.0) / (t[i] - t[j])
    return out


def derive_features(t, raw):
    """t: seconds (ascending), raw: dict raw_column -> np.ndarray (same length). Returns dict feature -> np.ndarray."""
    t = np.asarray(t, dtype=float)
    raw = {k: np.asarray(v, dtype=float) for k, v in raw.items()}
    for k in ABSENT_MEANS_ZERO & set(raw):
        raw[k] = np.nan_to_num(raw[k], nan=0.0)
    raw["http_req_total"] = raw["http_n2xx"] + raw["http_n4xx"] + raw["http_n5xx"]
    feats = {}
    for name, (kind, col, scale) in FEATURES.items():
        if name == "http_req_rate":
            feats[name] = _rate(t, raw["http_req_total"]) * scale
        elif kind == "rate":
            feats[name] = _rate(t, raw[col]) * scale
        elif kind == "gauge":
            feats[name] = raw[col] * scale
        elif kind == "ratio":
            num, den = _rate(t, raw[col[0]]), _rate(t, raw[col[1]])
            with np.errstate(divide="ignore", invalid="ignore"):
                feats[name] = np.where(den > 1e-12, num / den, 0.0) * scale
    return feats


# Limit-relative view: CPU and memory features divided by the service's own limit (cpu limit in cores, memory limit in MB,
# both read from the workload's resources.limits). A 5 % rise of a 200 MB Go service and of a 500 MB Java service become
# comparable, which is what lets one model serve services it never saw. Feature name gets the suffix `_rel`.
#   cpu_*_pct are percent of ONE core -> pct / 100 / cpu_limit_cores     mem_*_mb -> mb / mem_limit_mb
LIMIT_RELATIVE = {
    "cpu_user_pct": "cpu", "cpu_system_pct": "cpu", "cpu_total_pct": "cpu", "app_cpu_pct": "cpu",
    "mem_rss_mb": "mem", "mem_usage_mb": "mem", "mem_working_set_mb": "mem", "mem_swap_mb": "mem",
}


def to_limit_relative(feats, cpu_limit_cores, mem_limit_mb):
    """feats: dict feature -> array. Returns a new dict where the features in LIMIT_RELATIVE are replaced by `<name>_rel`."""
    out = {}
    for name, x in feats.items():
        kind = LIMIT_RELATIVE.get(name)
        if kind == "cpu":
            out[name.replace("_pct", "") + "_rel"] = x / 100.0 / cpu_limit_cores
        elif kind == "mem":
            out[name.replace("_mb", "") + "_rel"] = x / mem_limit_mb
        else:
            out[name] = x
    return out


# Load-normalised features: how much CPU / network a request costs. A rise in CPU that comes WITH a rise in request rate
# (healthy, busy) leaves these flat; a CPU hog raises CPU while the request rate stays put, so cost per request jumps.
# Computed from the derived features before the limit-relative conversion (needs cpu_total_pct).
RATIO_FEATURES = ["cpu_ms_per_req", "net_tx_bytes_per_req"]


def add_ratio_features(feats):
    rate = feats["http_req_rate"]
    out = dict(feats)
    out["cpu_ms_per_req"] = (feats["cpu_total_pct"] / 100.0 * 1000.0) / (rate + 1.0)
    out["net_tx_bytes_per_req"] = feats["net_tx_bytes_rate"] / (rate + 1.0)
    return out
