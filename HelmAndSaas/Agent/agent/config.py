import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("SADMC_API_KEY", "")
    # Human-readable name shown in the dashboard instead of the id. Empty = the SaaS uses the API key's name.
    CLUSTER_NAME = os.getenv("SADMC_CLUSTER_NAME", "")
    SAAS_ENDPOINT = os.getenv("SAAS_ENDPOINT", "https://api.sadmc.io")

    # The feature vector this agent sends (33 features: cAdvisor + the apps' /metrics + a probe). The backend uses it to pick
    # the matching model and scaler.
    FEATURE_SET = "v3"

    # Discovery
    EXCLUDE_NAMESPACES = os.getenv("EXCLUDE_NAMESPACES", "kube-system,kube-public,sadmc").split(",")
    
    # Optional allow-list of service names (comma-separated); empty = every deployment outside EXCLUDE_NAMESPACES.
    # The model is trained on the application tier only, so databases/queues can be left out.
    INCLUDE_SERVICES = [x for x in os.getenv("INCLUDE_SERVICES", "").split(",") if x]
    # Optional allow-list of namespaces; empty = every namespace not in EXCLUDE_NAMESPACES. EXCLUDE_NAMESPACES always wins.
    INCLUDE_NAMESPACES = [x.strip() for x in os.getenv("INCLUDE_NAMESPACES", "").split(",") if x.strip()]
    # Deployment names to leave out (inside the selected namespaces), e.g. a database next to the application.
    EXCLUDE_SERVICES = [x.strip() for x in os.getenv("EXCLUDE_SERVICES", "").split(",") if x.strip()]

    # Remediation
    REMEDIATION_ENABLED = os.getenv("REMEDIATION_ENABLED", "true").lower() == "true"
    CONFIDENCE_THRESHOLD = float(os.getenv("CONFIDENCE_THRESHOLD", "0.85"))
    # Act only after the same verdict repeated this many cycles in a row for a service: one noisy
    # sample (JVM warm-up, a load spike) must not restart or throttle a healthy workload.
    REMEDIATION_CONSECUTIVE = int(os.getenv("REMEDIATION_CONSECUTIVE", "3"))
    # Optional allow-list for staged roll-outs (comma-separated service names); empty = all services.
    REMEDIATION_SERVICES = [x for x in os.getenv("REMEDIATION_SERVICES", "").split(",") if x]
    
    # Monitoring Loop
    CHECK_INTERVAL_SECONDS = int(os.getenv("CHECK_INTERVAL_SECONDS", "15"))

config = Config()
