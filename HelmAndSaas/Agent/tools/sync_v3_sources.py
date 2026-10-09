"""
Regenerates agent/v3_sources.py and agent/feature_defs_v3.py from the training-side originals
(SADMC-MT-FF-FL/own_dataset/scripts/v3/{collector_v3,feature_defs}.py), so the agent computes features exactly as the
dataset was built.   python tools/sync_v3_sources.py [--check]   (--check exits 1 if the generated files differ)
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))   # repo root (SPL-3)
V3 = os.path.join(ROOT, "SADMC-MT-FF-FL", "own_dataset", "scripts", "v3")
AGENT = os.path.join(ROOT, "HelmAndSaas", "Agent", "agent")

HEADER = '''"""
v3 sources for the agent: reads cAdvisor, the apps' /metrics and the latency probe from INSIDE the node (one `docker exec` per
cycle) and the pod state from the Kubernetes API.

The constants and the parse_*/node_script/split_sections functions below are COPIED, not rewritten, from
SADMC-MT-FF-FL/own_dataset/scripts/v3/collector_v3.py (the collector that produced the training data). Regenerate with
Agent/tools/sync_v3_sources.py; tests/test_v3_sources_in_sync.py fails when they differ.

Dev/lab mode: the node is a docker container (minikube). An in-cluster deployment needs a different transport for the same
queries; the parsing and the feature definitions do not change.
"""
import json
import os
import re
import subprocess

from .feature_defs_v3 import PROBE_TIMEOUT_MS, RAW, RAW_COLUMNS, SERVICES

'''
TAIL = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "v3_sources_tail.py.txt")).read()


def generate():
    src = open(os.path.join(V3, "collector_v3.py")).read()
    consts = src[src.index("NAMESPACE = "):src.index("def sh(")]
    funcs = src[src.index("def node_script"):src.index("def kube_state")]
    return {"v3_sources.py": HEADER + consts.rstrip() + "\n\n\n" + funcs.rstrip() + "\n" + TAIL,
            "feature_defs_v3.py": open(os.path.join(V3, "feature_defs.py")).read()}


if __name__ == "__main__":
    bad = 0
    for name, text in generate().items():
        path = os.path.join(AGENT, name)
        if "--check" in sys.argv:
            if not os.path.exists(path) or open(path).read() != text:
                print(f"OUT OF SYNC: {path}")
                bad += 1
        else:
            open(path, "w").write(text)
            print("wrote", path)
    sys.exit(1 if bad else 0)
