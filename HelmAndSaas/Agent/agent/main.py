import asyncio
import logging
import time
from datetime import datetime
from collections import deque

from .config import config
from .discovery import Discovery
from .prometheus_detector import detect
from .metrics_collector import MetricsCollector
from .inference_client import InferenceClient
from .remediation.rules import REMEDIATION_RULES
from .remediation.cooldown import cooldown_tracker
from .remediation.executor import remediation_executor

logger = logging.getLogger(__name__)

class SADMCAgent:
    def __init__(self):
        self.discovery = Discovery()
        self.inference_client = InferenceClient()
        
        # History for trend calculation: {service_key -> deque of (cpu, mem)}
        self._history = {}
        self.max_history = 10

    async def run(self):
        # 1. Prometheus Detection
        prom_url = detect(config.PROMETHEUS_MODE, config.PROMETHEUS_URL)
        self.metrics_collector = MetricsCollector(prom_url)

        # 2. SaaS Registration
        registered = await self.inference_client.register()
        if not registered:
            logger.warning("Agent registration failed, will retry in metrics loop")

        # 3. Monitoring Loop
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

        logger.info(f"Discovered services list: {[f'{s['namespace']}/{s['name']}' for s in services]}")

        # Step 2: Metrics Collection
        collected = await self.metrics_collector.collect(services)
        logger.info(f"Successfully collected metrics for {len(collected)} services")
        for svc in collected:
            logger.info(f"Metrics for {svc['namespace']}/{svc['service_name']}: {svc['metrics']}")
        
        # Enrich with trends
        for svc in collected:
            self._enrich_trends(svc)

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

    def _enrich_trends(self, svc):
        name = svc["service_name"]
        ns = svc["namespace"]
        key = f"{ns}/{name}"
        
        metrics = svc["metrics"]
        current_cpu = metrics["cpu_usage_percent"]
        current_mem = metrics["memory_usage_mb"]
        
        if key not in self._history:
            self._history[key] = deque(maxlen=self.max_history)
        
        history = self._history[key]
        
        if len(history) == self.max_history:
            prev_cpu, prev_mem = history[0]
            metrics["cpu_trend"] = current_cpu - prev_cpu
            metrics["memory_trend"] = current_mem - prev_mem
        
        history.append((current_cpu, current_mem))

    async def _process_anomalies(self, results):
        for result in results:
            if result.get("is_anomaly") and result.get("confidence", 0) >= config.CONFIDENCE_THRESHOLD:
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
