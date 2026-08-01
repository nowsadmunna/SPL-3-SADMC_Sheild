import logging
import os
import signal
import subprocess
import sys
import threading
import time

from metric_queries import SERVICES
from collector import start_collector_thread
from injector import Injector

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "run.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("run_collection")

PROM_LOCAL_PORT = 9090
PROM_BASE_URL = f"http://localhost:{PROM_LOCAL_PORT}"

SERVICE_BASE_PORT = 18000
SERVICE_PORTS = {svc: SERVICE_BASE_PORT + i for i, svc in enumerate(SERVICES)}

stop_event = threading.Event()
shared_state = {svc: 0 for svc in SERVICES}

# name -> (popen_args, log_filename)
PORT_FORWARD_SPECS = {
    "prometheus": (
        ["kubectl", "port-forward", "-n", "monitoring",
         "svc/prometheus-kube-prometheus-prometheus", f"{PROM_LOCAL_PORT}:9090"],
        "port-forward-prometheus.log",
    ),
}
for svc, port in SERVICE_PORTS.items():
    PORT_FORWARD_SPECS[f"svc-{svc}"] = (
        ["kubectl", "port-forward", "-n", "sock-shop", f"svc/{svc}", f"{port}:80"],
        f"port-forward-{svc}.log",
    )


def start_port_forward(name):
    args, log_name = PORT_FORWARD_SPECS[name]
    return subprocess.Popen(
        args,
        stdout=open(os.path.join(LOG_DIR, log_name), "a"),
        stderr=subprocess.STDOUT,
    )


def port_forward_watchdog(procs):
    while not stop_event.is_set():
        for name in PORT_FORWARD_SPECS:
            if procs[name].poll() is not None:
                logger.warning("port-forward '%s' died, restarting", name)
                procs[name] = start_port_forward(name)
        stop_event.wait(15)


def handle_signal(signum, frame):
    logger.info("received signal %s, shutting down gracefully", signum)
    stop_event.set()


def main():
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    procs = {name: start_port_forward(name) for name in PORT_FORWARD_SPECS}
    time.sleep(5)  # let all tunnels come up

    watchdog_thread = threading.Thread(
        target=port_forward_watchdog, args=(procs,), daemon=True, name="pf-watchdog"
    )
    watchdog_thread.start()

    collector_thread = start_collector_thread(
        PROM_BASE_URL, shared_state, stop_event, SERVICE_PORTS
    )

    injector = Injector(shared_state, stop_event)
    try:
        injector.run()
    finally:
        stop_event.set()
        collector_thread.join(timeout=10)
        for proc in procs.values():
            proc.terminate()
        try:
            subprocess.run(
                ["kubectl", "scale", "deployment", "sadmc-agent", "-n", "sadmc", "--replicas=1"],
                check=True, capture_output=True, text=True,
            )
            logger.info("restored sadmc-agent to 1 replica")
        except Exception:
            logger.exception("failed to restore sadmc-agent replica count - restore manually")
        logger.info("run_collection finished / stopped")


if __name__ == "__main__":
    main()
