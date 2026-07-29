import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("SADMC_API_KEY", "")
    SAAS_ENDPOINT = os.getenv("SAAS_ENDPOINT", "https://api.sadmc.io")
    PROMETHEUS_MODE = os.getenv("PROMETHEUS_MODE", "existing")
    PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    
    # Discovery
    EXCLUDE_NAMESPACES = os.getenv("EXCLUDE_NAMESPACES", "kube-system,kube-public,sadmc").split(",")
    
    # Remediation
    REMEDIATION_ENABLED = os.getenv("REMEDIATION_ENABLED", "true").lower() == "true"
    CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
    
    # Monitoring Loop
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "15"))

config = Config()
