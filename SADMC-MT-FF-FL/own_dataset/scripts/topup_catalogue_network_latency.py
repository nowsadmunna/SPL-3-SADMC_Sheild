import logging
import os
import signal
import subprocess
import sys
import threading
import time

import collector
import injector

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "topup_catalogue.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("topup")

# Restrict both modules to just the one service/class we're topping up.
TARGET_SERVICE = "catalogue"
collector.SERVICES = [TARGET_SERVICE]
injector.SERVICES = [TARGET_SERVICE]
injector.ANOMALY_TYPES = ["NETWORK_LATENCY"]
injector.REPEATS = 5

PROM_LOCAL_PORT = 9090
CATALOGUE_LOCAL_PORT = 18001

stop_event = threading.Event()
shared_state = {TARGET_SERVICE: 0}

PORT_FORWARD_SPECS = {
    "prometheus": (
        ["kubectl", "port-forward", "-n", "monitoring",
         "svc/prometheus-kube-prometheus-prometheus", f"{PROM_LOCAL_PORT}:9090"],
        "topup-pf-prometheus.log",
    ),
    "svc-catalogue": (
        ["kubectl", "port-forward", "-n", "sock-shop", "svc/catalogue",
         f"{CATALOGUE_LOCAL_PORT}:80"],
        "topup-pf-catalogue.log",
    ),
}


def start_port_forward(name):
    args, log_name = PORT_FORWARD_SPECS[name]
    return subprocess.Popen(
        args, stdout=open(os.path.join(LOG_DIR, log_name), "a"), stderr=subprocess.STDOUT,
    )


def watchdog(procs):
    while not stop_event.is_set():
        for name in PORT_FORWARD_SPECS:
            if procs[name].poll() is not None:
                logger.warning("port-forward '%s' died, restarting", name)
                procs[name] = start_port_forward(name)
        stop_event.wait(15)


def handle_signal(signum, frame):
    logger.info("received signal %s, shutting down", signum)
    stop_event.set()


def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    logger.info("Scaling down sadmc-agent for the duration of the top-up")
    subprocess.run(
        ["kubectl", "scale", "deployment", "sadmc-agent", "-n", "sadmc", "--replicas=0"],
        check=True, capture_output=True, text=True,
    )

    procs = {name: start_port_forward(name) for name in PORT_FORWARD_SPECS}
    time.sleep(5)

    wd = threading.Thread(target=watchdog, args=(procs,), daemon=True)
    wd.start()

    collector_thread = collector.start_collector_thread(
        f"http://localhost:{PROM_LOCAL_PORT}", shared_state, stop_event,
        {TARGET_SERVICE: CATALOGUE_LOCAL_PORT},
    )

    inj = injector.Injector(shared_state, stop_event)
    try:
        inj.run()
    finally:
        stop_event.set()
        collector_thread.join(timeout=10)
        for p in procs.values():
            p.terminate()
        subprocess.run(
            ["kubectl", "scale", "deployment", "sadmc-agent", "-n", "sadmc", "--replicas=1"],
            check=True, capture_output=True, text=True,
        )
        logger.info("Top-up finished, sadmc-agent restored to 1 replica")


if __name__ == "__main__":
    main()
