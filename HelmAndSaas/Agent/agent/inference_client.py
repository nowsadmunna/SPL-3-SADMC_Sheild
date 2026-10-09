import httpx
import logging
import os
import uuid
from .config import config

logger = logging.getLogger(__name__)

def _stable_cluster_id():
    """Same id on every start of the same agent, so a restart does not create a new cluster in the dashboard.
    SADMC_CLUSTER_ID wins; otherwise the id is kept in SADMC_CLUSTER_ID_FILE (default ~/.sadmc_cluster_id)."""
    cid = os.getenv("SADMC_CLUSTER_ID")
    if cid:
        return cid
    path = os.path.expanduser(os.getenv("SADMC_CLUSTER_ID_FILE", "~/.sadmc_cluster_id"))
    try:
        with open(path) as f:
            cid = f.read().strip()
        if cid:
            return cid
    except OSError:
        pass
    cid = str(uuid.uuid4())
    try:
        with open(path, "w") as f:
            f.write(cid)
    except OSError:
        logger.warning("could not persist the cluster id to %s; a restart will register a new cluster", path)
    return cid


class InferenceClient:
    def __init__(self):
        self.cluster_uuid = _stable_cluster_id()   # register() confirms (or replaces) it
        self.headers = {"X-API-Key": config.API_KEY}
        self.registered = False

    async def register(self):
        url = f"{config.SAAS_ENDPOINT}/v1/agent/register"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=self.headers, json={"cluster_id": self.cluster_uuid, "cluster_name": config.CLUSTER_NAME})
                if resp.status_code == 200:
                    data = resp.json()
                    self.cluster_uuid = data.get("cluster_uuid", self.cluster_uuid)
                    logger.info(f"Registered agent with cluster_uuid: {self.cluster_uuid}")
                    self.registered = True
                    return True
                elif resp.status_code == 409:
                    # the cluster name is already used by another cluster of this account: only the user can fix it
                    logger.error(f"Registration refused: {resp.json().get('error', resp.text)} "
                                 f"(set a different sadmc.clusterName / SADMC_CLUSTER_NAME; retrying every cycle)")
                    return False
                else:
                    logger.error(f"Registration failed: {resp.status_code} {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Error during registration: {e}")
            return False

    async def ingest_metrics(self, payload):
        if not self.registered and not await self.register():
            return None            # not registered yet (name refused, SaaS unreachable): try again next cycle
        url = f"{config.SAAS_ENDPOINT}/v1/metrics/ingest"
        payload["cluster_uuid"] = self.cluster_uuid
        payload["feature_set"] = config.FEATURE_SET     # which model and scaler the backend applies to this vector
        
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=self.headers, json=payload, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                else:
                    logger.error(f"Metric ingestion failed: {resp.status_code}")
                    return None
        except Exception as e:
            logger.error(f"Error during metric ingestion: {e}")
            return None

    async def report_remediation(self, event_id, status, error=None):
        url = f"{config.SAAS_ENDPOINT}/v1/remediation/report"
        payload = {
            "cluster_uuid": self.cluster_uuid,
            "event_id": event_id,
            "status": status,
            "error_message": error
        }
        try:
            async with httpx.AsyncClient() as client:
                await client.post(url, headers=self.headers, json=payload)
        except Exception as e:
            logger.error(f"Error reporting remediation: {e}")
