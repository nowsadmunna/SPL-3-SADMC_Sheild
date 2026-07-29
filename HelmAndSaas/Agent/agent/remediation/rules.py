import os
import json
import logging

logger = logging.getLogger(__name__)

DEFAULT_RULES = {
    "CPU_HOG": {
        "action":           "THROTTLE_CPU",
        "cpu_limit":        "200m",
        "cooldown_seconds": 300,
    },
    "MEMORY_LEAK": {
        "action":           "RESTART_POD",
        "cooldown_seconds": 180,
    },
    "NETWORK_DELAY": {
        "action":           "SCALE_UP",
        "replica_increase": 1,
        "max_replicas":     10,
        "cooldown_seconds": 600,
    },
    "NORMAL": {
        "action": "NO_ACTION",
    },
}

REMEDIATION_RULES = DEFAULT_RULES

env_rules = os.getenv("REMEDIATION_RULES")
if env_rules:
    try:
        REMEDIATION_RULES = json.loads(env_rules)
        logger.info("Loaded custom remediation rules from REMEDIATION_RULES env var.")
    except Exception as e:
        logger.error(f"Failed to parse REMEDIATION_RULES env var: {e}. Falling back to default rules.")

