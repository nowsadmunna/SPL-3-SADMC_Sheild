import csv
import logging
import os
import threading
import time
from datetime import datetime, timezone

import requests

from metric_queries import FEATURE_NAMES, METRIC_QUERIES, LABEL_NAMES, SERVICES
from latency_prober import probe_latency

logger = logging.getLogger("collector")

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "raw")
NAMESPACE = "sock-shop"
SCRAPE_INTERVAL_SECONDS = 5
NET_LATENCY_MIN_IDX = FEATURE_NAMES.index("net_latency_min")
NET_LATENCY_AVG_IDX = FEATURE_NAMES.index("net_latency_avg")


class PrometheusClient:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session = requests.Session()

    def query_value(self, promql):
        try:
            resp = self.session.get(
                f"{self.base_url}/api/v1/query",
                params={"query": promql},
                timeout=8,
            )
            resp.raise_for_status()
            result = resp.json()["data"]["result"]
            if not result:
                return 0.0
            return float(result[0]["value"][1])
        except Exception as exc:
            logger.warning("query failed (%s): %s", promql[:60], exc)
            return 0.0


class Collector:
    """Polls Prometheus every SCRAPE_INTERVAL_SECONDS for all SERVICES and
    appends one labeled row per service to own_dataset/raw/<service>.csv.
    The label for each row is read from `shared_state[service]` at write time,
    so the injector can flip it live without any file-based IPC.
    """

    def __init__(self, prom_base_url, shared_state, stop_event, service_ports):
        self.prom = PrometheusClient(prom_base_url)
        self.shared_state = shared_state
        self.stop_event = stop_event
        self.service_ports = service_ports
        self._writers = {}
        self._files = {}
        os.makedirs(RAW_DIR, exist_ok=True)
        self._init_files()

    def _init_files(self):
        header = ["timestamp_unix", "timestamp_iso"] + FEATURE_NAMES + ["label", "label_name"]
        for svc in SERVICES:
            path = os.path.join(RAW_DIR, f"{svc}.csv")
            is_new = not os.path.exists(path) or os.path.getsize(path) == 0
            f = open(path, "a", newline="")
            writer = csv.writer(f)
            if is_new:
                writer.writerow(header)
                f.flush()
            self._files[svc] = f
            self._writers[svc] = writer

    def _collect_once(self):
        now = time.time()
        iso = datetime.now(timezone.utc).isoformat()
        for svc in SERVICES:
            row = [now, iso]
            for _, template in METRIC_QUERIES:
                q = template.format(name=svc, ns=NAMESPACE)
                row.append(self.prom.query_value(q))

            # net_latency_min/avg come from the PromQL istio_* queries above, which
            # are always 0 on this cluster (no service mesh installed). Overwrite
            # them with a real, actively-measured HTTP round-trip time instead, so
            # NETWORK_LATENCY anomalies are actually visible in the feature set.
            try:
                min_ms, avg_ms = probe_latency(self.service_ports[svc], svc)
                row[2 + NET_LATENCY_MIN_IDX] = min_ms
                row[2 + NET_LATENCY_AVG_IDX] = avg_ms
            except Exception:
                logger.exception("latency probe failed for %s", svc)

            label = self.shared_state.get(svc, 0)
            row.append(label)
            row.append(LABEL_NAMES[label])
            self._writers[svc].writerow(row)
            self._files[svc].flush()

    def run(self):
        logger.info("Collector started, scraping every %ss", SCRAPE_INTERVAL_SECONDS)
        while not self.stop_event.is_set():
            start = time.time()
            try:
                self._collect_once()
            except Exception:
                logger.exception("collection cycle failed")
            elapsed = time.time() - start
            self.stop_event.wait(max(0.0, SCRAPE_INTERVAL_SECONDS - elapsed))
        for f in self._files.values():
            f.close()
        logger.info("Collector stopped")


def start_collector_thread(prom_base_url, shared_state, stop_event, service_ports):
    collector = Collector(prom_base_url, shared_state, stop_event, service_ports)
    thread = threading.Thread(target=collector.run, daemon=True, name="collector")
    thread.start()
    return thread
