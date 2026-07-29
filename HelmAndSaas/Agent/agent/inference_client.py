import httpx
import logging
import uuid
from .config import config

logger = logging.getLogger(__name__)

class InferenceClient:
    def __init__(self):
        self.cluster_uuid = str(uuid.uuid4()) # Initialized at startup, register will override
        self.headers = {"X-API-Key": config.API_KEY}

    async def register(self):
        url = f"{config.SAAS_ENDPOINT}/v1/agent/register"
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, headers=self.headers, json={"cluster_id": self.cluster_uuid})
                if resp.status_code == 200:
                    data = resp.json()
                    self.cluster_uuid = data.get("cluster_uuid", self.cluster_uuid)
                    logger.info(f"Registered agent with cluster_uuid: {self.cluster_uuid}")
                    return True
                else:
                    logger.error(f"Registration failed: {resp.status_code} {resp.text}")
                    return False
        except Exception as e:
            logger.error(f"Error during registration: {e}")
            return False

    async def ingest_metrics(self, payload):
        url = f"{config.SAAS_ENDPOINT}/v1/metrics/ingest"
        payload["cluster_uuid"] = self.cluster_uuid
        
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
