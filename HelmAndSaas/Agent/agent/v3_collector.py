"""
Agent-side collector: collect(services) returns, per service, the 33 model features of the v3 model, derived with the SAME definitions as the training data (feature_defs_v3 is a copy of
SADMC-MT-FF-FL/own_dataset/scripts/v3/feature_defs.py): raw counters are sampled each cycle, kept for a few minutes, and
rates are taken over RATE_WINDOW_S seconds. A service has no feature vector until a full window exists (warm-up ~75 s).

It works for any service the discovery returns (not only Sock-Shop). What it needs from the cluster: a cAdvisor endpoint
(V3_CADVISOR_SERVICE / V3_CADVISOR_URLS; the Helm chart deploys one) and the application's own /metrics with
`request_duration_seconds` and `process_*` (a service without them gets no v3 verdict, and the agent says so once).
"""
import asyncio
import logging
import time
from collections import deque

import numpy as np
from kubernetes import client

from .feature_defs_v3 import ARTIFACT_SUSPECTS, FEATURE_NAMES, RAW_COLUMNS, RATE_WINDOW_S, derive_features
from .v3_sources import key_of, sample_cluster, service_endpoints

logger = logging.getLogger(__name__)

# the model's input order: every derived feature except the injection artifacts (same filter as build_v3_dataset.py)
MODEL_FEATURES = [f for f in FEATURE_NAMES if f not in ARTIFACT_SUSPECTS]
HISTORY = 12          # samples kept per service (3 min at 15 s)


class V3Collector:
    def __init__(self):
        self.core_v1 = client.CoreV1Api()
        self.history = {}          # "<ns>/<name>" -> deque of (t, raw row)
        self._warned = set()

    def _sample(self, services):
        endpoints = service_endpoints(self.core_v1, services)
        missing = [s for s in services if key_of(*s) not in endpoints]
        for ns, name in missing:
            self._warn_once(f"nosvc:{ns}/{name}", f"v3: {ns}/{name} has no Service with a ClusterIP; it cannot be probed, skipped")
        t = time.time()
        for key, row in sample_cluster(self.core_v1, services, endpoints).items():
            self.history.setdefault(key, deque(maxlen=HISTORY)).append((t, row))

    def _warn_once(self, tag, msg):
        if tag not in self._warned:
            self._warned.add(tag)
            logger.warning(msg)

    def _features(self, key):
        h = self.history.get(key)
        if not h or len(h) < 2 or h[-1][0] - h[0][0] < RATE_WINDOW_S * 0.8 + 1:
            return None, "warming up"
        t = np.array([x[0] for x in h])
        raw = {c: np.array([x[1].get(c, np.nan) for x in h], dtype=float) for c in RAW_COLUMNS}
        feats = derive_features(t, raw)
        vec = [float(feats[f][-1]) for f in MODEL_FEATURES]
        bad = [f for f, v in zip(MODEL_FEATURES, vec) if np.isnan(v)]
        if bad:
            return None, f"no value for {bad[:4]}{'...' if len(bad) > 4 else ''} (does the app expose /metrics with request_duration_seconds and process_*?)"
        return (dict(zip(MODEL_FEATURES, vec)), vec), None

    async def collect(self, services):
        wanted = [(s["namespace"], s["name"]) for s in services]
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, self._sample, wanted)
        except Exception:
            logger.exception("v3 sampling failed")
            return []
        out = []
        for ns, name in wanted:
            res, why = self._features(key_of(ns, name))
            if res is None:
                if why == "warming up":
                    logger.info("v3: %s/%s warming up (%d samples)", ns, name, len(self.history.get(key_of(ns, name), [])))
                else:
                    self._warn_once(f"nofeat:{ns}/{name}", f"v3: {ns}/{name} skipped: {why}")
                continue
            named, vec = res
            metrics = dict(named)
            # the summary fields the backend/dashboard already store
            metrics.update({"cpu_usage_percent": named["cpu_total_pct"], "memory_usage_mb": named["mem_usage_mb"],
                            "network_latency_ms": named["probe_latency_avg_ms"], "request_rate": named["http_req_rate"],
                            "error_rate": named["http_5xx_rate"]})
            out.append({"service_name": name, "namespace": ns, "metrics": metrics, "feature_vector": vec})
        return out
