import logging
import time

import requests

logger = logging.getLogger("latency_prober")

# Per-service lightweight path that returns quickly when the service is healthy.
# Falls back to "/" for services whose /health endpoint isn't reliable/fast.
PROBE_PATHS = {
    "carts": "/health",
    "catalogue": "/health",
    "front-end": "/",
    "orders": "/",
    "payment": "/health",
    "shipping": "/health",
    "user": "/health",
}

PROBE_TIMEOUT_SECONDS = 2.0
PROBES_PER_CYCLE = 3
# Recorded when a probe times out or the connection is refused/reset - i.e. the
# service was not able to answer within budget. Keeps a real anomaly (or a
# crash-looping pod) visible as "very high latency" instead of a missing value.
TIMEOUT_SENTINEL_MS = PROBE_TIMEOUT_SECONDS * 1000


def probe_latency(local_port, service):
    """Runs PROBES_PER_CYCLE quick HTTP GETs against the service's port-forwarded
    local port and returns (min_ms, avg_ms) measured round-trip time."""
    path = PROBE_PATHS.get(service, "/")
    url = f"http://localhost:{local_port}{path}"
    samples = []
    for _ in range(PROBES_PER_CYCLE):
        start = time.perf_counter()
        try:
            requests.get(url, timeout=PROBE_TIMEOUT_SECONDS)
        except requests.RequestException:
            samples.append(TIMEOUT_SENTINEL_MS)
            continue
        samples.append((time.perf_counter() - start) * 1000)
    return min(samples), sum(samples) / len(samples)
