import logging
from kubernetes import client, config as k8s_config

logger = logging.getLogger(__name__)

class RemediationExecutor:
    def __init__(self):
        try:
            k8s_config.load_incluster_config()
        except Exception:
            k8s_config.load_kube_config()
        
        self.apps_v1 = client.AppsV1Api()
        self.core_v1 = client.CoreV1Api()

    async def execute(self, action, params, service_name, namespace):
        logger.info(f"Executing {action} on {namespace}/{service_name}")
        
        try:
            if action == "THROTTLE_CPU":
                patch = {"spec": {"template": {"spec": {"containers": [{
                    "name": service_name,
                    "resources": {"limits": {"cpu": params["cpu_limit"]}}
                }]}}}}
                self.apps_v1.patch_namespaced_deployment(service_name, namespace, patch)

            elif action == "RESTART_POD":
                pods = self.core_v1.list_namespaced_pod(
                    namespace, label_selector=f"app={service_name}")
                for pod in pods.items:
                    self.core_v1.delete_namespaced_pod(pod.metadata.name, namespace)
                # Kubernetes Deployment controller recreates pods automatically

            elif action == "SCALE_UP":
                dep = self.apps_v1.read_namespaced_deployment(service_name, namespace)
                current = dep.spec.replicas or 1
                new = min(current + params["replica_increase"], params["max_replicas"])
                self.apps_v1.patch_namespaced_deployment(
                    service_name, namespace, {"spec": {"replicas": new}})
            
            elif action == "NO_ACTION":
                pass
            
            return True
        except Exception as e:
            logger.error(f"Failed to execute {action} on {service_name}: {e}")
            return False

remediation_executor = RemediationExecutor()
