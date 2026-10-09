import asyncio
import logging
import time
from datetime import datetime

from .config import config
from .discovery import Discovery
from .v3_collector import V3Collector
from .inference_client import InferenceClient
from .remediation.rules import REMEDIATION_RULES
from .remediation.cooldown import cooldown_tracker
from .remediation.executor import remediation_executor

logger = logging.getLogger(__name__)

class SADMCAgent:
    def __init__(self):
        self.discovery = Discovery()
        self.inference_client = InferenceClient()

        # service_key -> (last anomaly_type, consecutive count) for the remediation guard
        self._streak = {}

    async def run(self):
        # 1. Collector: 33 features per service from cAdvisor, the apps' /metrics, a probe and the Kubernetes API
        self.metrics_collector = V3Collector()
        logger.info("collecting 33 features per service from cAdvisor, app /metrics and a probe")

        # 2. SaaS registration
        registered = await self.inference_client.register()
        if not registered:
            logger.warning("Agent registration failed, will retry in metrics loop")

        # 3. Monitoring loop
        while True:
            try:
                start_time = time.time()
                await self._step()
                elapsed = time.time() - start_time
                wait = max(0, config.CHECK_INTERVAL_SECONDS - elapsed)
                await asyncio.sleep(wait)
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
                await asyncio.sleep(10)

    async def _step(self):
        # Step 1: Discovery
        services = self.discovery.discover_services()
        if not services:
            logger.info("No services discovered.")
            return

        service_labels = [f"{s['namespace']}/{s['name']}" for s in services]
        logger.info(f"Discovered services list: {service_labels}")

        # Step 2: Metrics Collection
        collected = await self.metrics_collector.collect(services)
        logger.info(f"Successfully collected metrics for {len(collected)} services")
        for svc in collected:
            logger.info(f"Metrics for {svc['namespace']}/{svc['service_name']}: {svc['metrics']}")
        
        # Step 3: Send to SaaS for Inference
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "services": collected
        }
        inference_resp = await self.inference_client.ingest_metrics(payload)
        
        if not inference_resp:
            logger.error("Inference request failed")
            return

        # Step 4: Remediation
        if config.REMEDIATION_ENABLED:
            await self._process_anomalies(inference_resp.get("results", []))

    def _confirmed(self, result):
        """True once the same confident verdict has been seen REMEDIATION_CONSECUTIVE cycles in a row."""
        key = f"{result['namespace']}/{result['service_name']}"
        confident = result.get("is_anomaly") and result.get("confidence", 0) >= config.CONFIDENCE_THRESHOLD
        last_type, count = self._streak.get(key, (None, 0))
        if not confident:
            self._streak[key] = (None, 0)
            return False
        count = count + 1 if last_type == result["anomaly_type"] else 1
        self._streak[key] = (result["anomaly_type"], count)
        return count >= config.REMEDIATION_CONSECUTIVE

    async def _process_anomalies(self, results):
        for result in results:
            confirmed = self._confirmed(result)
            if confirmed and (not config.REMEDIATION_SERVICES or result["service_name"] in config.REMEDIATION_SERVICES):
                anomaly_type = result["anomaly_type"]
                service_name = result["service_name"]
                namespace = result["namespace"]
                
                rule = REMEDIATION_RULES.get(anomaly_type)
                if not rule or rule["action"] == "NO_ACTION":
                    continue
                
                action = rule["action"]
                cooldown = rule.get("cooldown_seconds", 300)
                
                if cooldown_tracker.is_on_cooldown(service_name, namespace, action, cooldown):
                    logger.info(f"Skipping remediation for {service_name} (on cooldown)")
                    continue
                
                # Execute remediation
                success = await remediation_executor.execute(action, rule, service_name, namespace)
                
                if success:
                    cooldown_tracker.record_execution(service_name, namespace, action)
                    await self.inference_client.report_remediation(
                        result.get("event_id"), "success"
                    )
                else:
                    await self.inference_client.report_remediation(
                        result.get("event_id"), "failed", "Execution error"
                    )
