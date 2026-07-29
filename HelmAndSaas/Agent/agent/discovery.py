import logging
from kubernetes import client, config as k8s_config
from .config import config

logger = logging.getLogger(__name__)

class Discovery:
    def __init__(self):
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        self.apps_v1 = client.AppsV1Api()

    def discover_services(self):
        logger.debug("Running service discovery...")
        deployments = self.apps_v1.list_deployment_for_all_namespaces()
        
        services = []
        for dep in deployments.items:
            ns = dep.metadata.namespace
            if ns in config.EXCLUDE_NAMESPACES:
                continue
                
            services.append({
                "name": dep.metadata.name,
                "namespace": ns,
                "replicas": dep.spec.replicas,
                "labels": dep.metadata.labels
            })
            
        logger.info(f"Discovered {len(services)} services")
        return services
