import csv
import logging
import os
import random
import re
import subprocess
from datetime import datetime, timezone

from metric_queries import LABELS, SERVICES

logger = logging.getLogger("injector")

LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
INJECTION_LOG_PATH = os.path.join(LOG_DIR, "injection_log.csv")

ANOMALY_TYPES = ["CPU_HOG", "MEMORY_LEAK", "NETWORK_LATENCY"]
REPEATS = 5
ANOMALY_DURATION_RANGE = (60, 300)   # seconds, matches paper's 1-5 min
NORMAL_GAP_SECONDS = 120             # shortened from paper's 10-30min so a full sweep is tractable
TC_IMAGE = "ghcr.io/alexei-led/pumba-alpine-nettools:latest"


def get_minikube_docker_env():
    out = subprocess.check_output(["minikube", "docker-env", "--shell", "bash"], text=True)
    env = dict(os.environ)
    for match in re.finditer(r'export (\w+)="([^"]*)"', out):
        env[match.group(1)] = match.group(2)
    return env


def target_regex(service):
    return f"re2:k8s_{service}_.*_sock-shop_"


def find_container_name(env, service):
    """Resolves the live docker container name for a service, so we can clear
    any stale qdisc left over from a previous netem attempt that got cut short
    by the container crash-restarting mid-injection (common on this cluster -
    see DATASET_CREATION.md Section 7.3)."""
    try:
        out = subprocess.check_output(
            ["docker", "ps", "--format", "{{.Names}}"], env=env, text=True,
        )
    except subprocess.CalledProcessError:
        return None
    prefix = f"k8s_{service}_"
    for name in out.splitlines():
        if name.startswith(prefix):
            return name
    return None


def clear_stale_qdisc(env, service):
    """Best-effort cleanup: remove any leftover root qdisc on the target
    container's eth0 before attempting a fresh netem injection. The target
    container itself has no `tc` binary (minimal app image), so - same as
    pumba does internally - we join its network namespace from a throwaway
    container built from the tc-image instead. The image's default
    ENTRYPOINT is `tail -f /dev/null` (a keep-alive shim, not a shell), so
    it must be overridden with --entrypoint or the command silently gets
    appended as arguments to `tail` and hangs forever - discovered the hard
    way (see DATASET_CREATION.md Section 7.3). "Cannot delete qdisc with
    handle of zero" (nothing to delete) is the expected/harmless outcome
    when there's no stale qdisc, so failures here are ignored either way."""
    container = find_container_name(env, service)
    if not container:
        return
    subprocess.run(
        ["docker", "run", "--rm", "--cap-add", "NET_ADMIN",
         "--net", f"container:{container}", "--entrypoint", "tc", TC_IMAGE,
         "qdisc", "del", "dev", "eth0", "root"],
        env=env, capture_output=True, text=True, timeout=15,
    )


def build_command(anomaly_type, service, duration):
    target = target_regex(service)
    if anomaly_type == "CPU_HOG":
        return [
            "pumba", "stress", "--duration", f"{duration}s",
            "--stress-image", "alexeiled/stress-ng",
            "--stressors", "--cpu 1 --cpu-load 100",
            target,
        ]
    if anomaly_type == "MEMORY_LEAK":
        return [
            "pumba", "stress", "--duration", f"{duration}s",
            "--stress-image", "alexeiled/stress-ng",
            "--stressors", "--vm 1 --vm-bytes 128M --vm-keep",
            target,
        ]
    if anomaly_type == "NETWORK_LATENCY":
        return [
            "pumba", "netem", "--duration", f"{duration}s",
            "--tc-image", TC_IMAGE,
            "delay", "--time", "500",
            target,
        ]
    raise ValueError(anomaly_type)


class Injector:
    def __init__(self, shared_state, stop_event):
        self.shared_state = shared_state
        self.stop_event = stop_event
        self.docker_env = get_minikube_docker_env()
        os.makedirs(LOG_DIR, exist_ok=True)
        self._init_log()

    def _init_log(self):
        is_new = not os.path.exists(INJECTION_LOG_PATH) or os.path.getsize(INJECTION_LOG_PATH) == 0
        self._log_file = open(INJECTION_LOG_PATH, "a", newline="")
        self._log_writer = csv.writer(self._log_file)
        if is_new:
            self._log_writer.writerow(
                ["service", "anomaly_type", "label", "repeat", "duration_s", "start_iso", "end_iso", "status"]
            )
            self._log_file.flush()

    def _log_event(self, service, anomaly_type, label, repeat, duration, start_iso, end_iso, status):
        self._log_writer.writerow([service, anomaly_type, label, repeat, duration, start_iso, end_iso, status])
        self._log_file.flush()

    def _run_injection_command(self, cmd, duration):
        subprocess.run(
            cmd, env=self.docker_env, timeout=duration + 30,
            capture_output=True, text=True, check=True,
        )

    def _inject_once(self, service, anomaly_type, repeat):
        duration = random.randint(*ANOMALY_DURATION_RANGE)
        label = LABELS[anomaly_type]
        cmd = build_command(anomaly_type, service, duration)
        start_iso = datetime.now(timezone.utc).isoformat()
        logger.info(
            "[%s/5] injecting %s into %s for %ss", repeat + 1, anomaly_type, service, duration
        )
        self.shared_state[service] = label
        status = "ok"
        if anomaly_type == "NETWORK_LATENCY":
            clear_stale_qdisc(self.docker_env, service)
        try:
            try:
                self._run_injection_command(cmd, duration)
            except subprocess.CalledProcessError as exc:
                if anomaly_type == "NETWORK_LATENCY" and "exit code 2" in (exc.stderr or ""):
                    logger.warning(
                        "netem hit a stale qdisc on %s, clearing and retrying once", service
                    )
                    clear_stale_qdisc(self.docker_env, service)
                    self._run_injection_command(cmd, duration)
                else:
                    raise
        except subprocess.CalledProcessError as exc:
            status = f"failed: {exc.stderr[-300:] if exc.stderr else exc}"
            logger.error("injection failed for %s/%s: %s", service, anomaly_type, status)
        except subprocess.TimeoutExpired:
            status = "timeout"
            logger.error("injection timed out for %s/%s", service, anomaly_type)
        finally:
            # A failed/interrupted netem (e.g. the container restarted mid-injection)
            # can leave the delay in place; with the label already flipped back to
            # NORMAL those rows would be mislabelled. In the previous sweep this left
            # ~40% of user's NORMAL rows with a 500 ms delay. Always clear it.
            if anomaly_type == "NETWORK_LATENCY":
                clear_stale_qdisc(self.docker_env, service)
            self.shared_state[service] = LABELS["NORMAL"]
        end_iso = datetime.now(timezone.utc).isoformat()
        self._log_event(service, anomaly_type, label, repeat, duration, start_iso, end_iso, status)

    def run(self):
        combos = [(svc, at) for svc in SERVICES for at in ANOMALY_TYPES]
        total_events = len(combos) * REPEATS
        done = 0
        logger.info(
            "Starting full sweep: %d services x %d anomaly types x %d repeats = %d events",
            len(SERVICES), len(ANOMALY_TYPES), REPEATS, total_events,
        )
        for repeat in range(REPEATS):
            for service, anomaly_type in combos:
                if self.stop_event.is_set():
                    logger.info("stop requested, ending sweep early (%d/%d events done)", done, total_events)
                    return
                self._inject_once(service, anomaly_type, repeat)
                done += 1
                logger.info("progress: %d/%d events complete", done, total_events)
                self.stop_event.wait(NORMAL_GAP_SECONDS)
        logger.info("Full sweep complete: %d/%d events", done, total_events)
        self._log_file.close()
