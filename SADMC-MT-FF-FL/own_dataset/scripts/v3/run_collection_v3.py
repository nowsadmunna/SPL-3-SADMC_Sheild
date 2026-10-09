"""
Runs the v3 collection: raw collector + diversified injector, writing to
  $V3_OUT/raw/<service>.csv   $V3_OUT/logs/injection_log.csv   $V3_OUT/meta.json   $V3_OUT/DONE

    V3_OUT=~/sadmc/own_dataset/v3/<run> python run_collection_v3.py            # full run (about 15 h)
    V3_OUT=~/sadmc/own_dataset/v3/pilot V3_PILOT=1 V3_WARMUP=120 V3_GAP_MIN=60 V3_GAP_MAX=60 python run_collection_v3.py
"""
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))   # v2 injector helpers

import collector_v3
import injector_v3
from feature_defs import ARTIFACT_SUSPECTS, FEATURE_NAMES, RATE_WINDOW_S, RAW_COLUMNS, SERVICES

OUT = os.path.expanduser(os.getenv("V3_OUT", "~/sadmc/own_dataset/v3/run"))
os.makedirs(f"{OUT}/logs", exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
                    handlers=[logging.FileHandler(f"{OUT}/logs/run.log"), logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("run_v3")

stop = threading.Event()
signal.signal(signal.SIGINT, lambda *a: stop.set())
signal.signal(signal.SIGTERM, lambda *a: stop.set())


def version(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip().splitlines()[0][:120]
    except Exception:
        return "?"


def main():
    state = {s: 0 for s in SERVICES}
    event_ids = {s: "" for s in SERVICES}
    plan = injector_v3.pilot_plan() if os.getenv("V3_PILOT") == "1" else injector_v3.make_plan()
    meta = {"started": datetime.now(timezone.utc).isoformat(), "pilot": os.getenv("V3_PILOT") == "1",
            "events_planned": len(plan), "repeats": injector_v3.REPEATS, "duration_range_s": injector_v3.DURATION_RANGE,
            "gap_range_s": injector_v3.GAP_RANGE, "warmup_s": injector_v3.WARMUP_S, "rate_window_s": RATE_WINDOW_S,
            "levels": {"cpu": injector_v3.CPU_LEVELS, "mem": injector_v3.MEM_LEVELS, "net_ms": injector_v3.NET_LEVELS},
            "raw_columns": RAW_COLUMNS, "features": FEATURE_NAMES, "artifact_suspects": ARTIFACT_SUSPECTS,
            "versions": {"minikube": version(["minikube", "version"]), "kubectl": version(["kubectl", "version", "--client"]),
                         "pumba": version(["pumba", "--version"]), "docker": version(["docker", "--version"])}}
    json.dump(meta, open(f"{OUT}/meta.json", "w"), indent=2, default=str)
    th = collector_v3.start(f"{OUT}/raw", state, event_ids, stop)
    inj = injector_v3.InjectorV3(state, event_ids, stop, f"{OUT}/logs/injection_log.csv")
    try:
        inj.run(plan)
        if not stop.is_set():
            logger.info("cool-down 120 s of NORMAL rows")
            stop.wait(120)
    finally:
        stop.set()
        th.join(timeout=15)
        open(f"{OUT}/DONE", "w").write("done\n")
        logger.info("collection finished")


if __name__ == "__main__":
    main()
