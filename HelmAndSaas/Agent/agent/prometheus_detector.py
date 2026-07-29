import os
import httpx
import logging
from kubernetes import client, config as k8s_config

logger = logging.getLogger(__name__)

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

    # In-cluster installed Prometheus might have a predictable name via Helm
    installed_url = os.getenv("INSTALLED_PROMETHEUS_URL", "http://sadmc-agent-prometheus.sadmc.svc.cluster.local:9090")

    if mode == "install":
        return installed_url

    # mode == "auto"
    try:
        k8s_config.load_incluster_config()
    except Exception:
        k8s_config.load_kube_config()

    k8s = client.CoreV1Api()
    for namespace, svc_name in KNOWN_LOCATIONS:
        try:
            k8s.read_namespaced_service(svc_name, namespace)
            url = f"http://{svc_name}.{namespace}.svc.cluster.local:9090"
            resp = httpx.get(f"{url}/-/healthy", timeout=3)
            if resp.status_code == 200:
                logger.info(f"Detected existing Prometheus at {url}")
                return url
        except Exception:
            continue

    logger.warning("Could not auto-detect Prometheus, falling back to installed default")
    return installed_url

