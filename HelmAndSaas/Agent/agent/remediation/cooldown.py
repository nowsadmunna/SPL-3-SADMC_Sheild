import time
import logging

logger = logging.getLogger(__name__)

class CooldownTracker:
    def __init__(self):
        # Key: (service_name, namespace, action) -> timestamp of last execution
        self._last_executed = {}

    def is_on_cooldown(self, service_name, namespace, action, cooldown_seconds):
        key = (service_name, namespace, action)
        if key not in self._last_executed:
            return False
        
        elapsed = time.time() - self._last_executed[key]
        return elapsed < cooldown_seconds

    def record_execution(self, service_name, namespace, action):
        key = (service_name, namespace, action)
        self._last_executed[key] = time.time()
        logger.debug(f"Recorded execution for {key}")

cooldown_tracker = CooldownTracker()
