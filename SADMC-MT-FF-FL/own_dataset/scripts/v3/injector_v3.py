"""
v3 injector: same tools as the paper (Pumba + stress-ng / netem), but every (service, fault) pair is hit with FIVE
DIFFERENT parameter levels instead of one fixed setting, and every event gets an event_id that the collector writes
into each row (so the dataset can be split by event, not by row).

Fault levels (index = which of the 5 repeats of a (service, fault) pair uses it; the assignment is rotated per pair
so every pair sees all five levels):
  CPU_HOG          stress-ng --cpu W --cpu-load L        (1,25) (1,50) (1,75) (1,100) (2,100)
  MEMORY_LEAK      stress-ng --vm 1 --vm-bytes B --vm-keep   steady 32M / 64M / 96M / 128M, and one RAMP:
                   four 32M stressors started at 0, D/4, D/2, 3D/4 (all end together) = gradual growth to 128M
  NETWORK_LATENCY  netem delay T ms, jitter T/10         20 / 50 / 100 / 200 / 500 ms
  (128M stays below the smallest memory limit in Sock-Shop, 200Mi, so a leak never turns into an OOM-kill)

Between faults: a random 4-6 min pause. After each full pass over the 21 pairs, 2 LOAD_SPIKE events (label NORMAL):
the load generator is scaled 2 -> 6 replicas for 3 min, so "busy but healthy" is in the data as a hard negative.

Label bookkeeping: state[service] = label int and event_ids[service] = id, set at the start of an event and reset at the
end (a failed injection is logged as such and its rows are still labelled by the time window the fault was active).
"""
import csv
import json
import logging
import os
import random
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone

from injector import TC_IMAGE, clear_stale_qdisc, get_minikube_docker_env, target_regex   # v2 helpers, unchanged
from feature_defs import SERVICES

logger = logging.getLogger("injector_v3")

TYPES = ["CPU_HOG", "MEMORY_LEAK", "NETWORK_LATENCY"]
LABELS = {"NORMAL": 0, "CPU_HOG": 1, "MEMORY_LEAK": 2, "NETWORK_LATENCY": 3}
CPU_LEVELS = [(1, 25), (1, 50), (1, 75), (1, 100), (2, 100)]
MEM_LEVELS = [("steady", "32M"), ("steady", "64M"), ("steady", "96M"), ("steady", "128M"), ("ramp", "32M")]
NET_LEVELS = [20, 50, 100, 200, 500]
REPEATS = int(os.getenv("V3_REPEATS", "5"))
DURATION_RANGE = (int(os.getenv("V3_DUR_MIN", "60")), int(os.getenv("V3_DUR_MAX", "300")))
GAP_RANGE = (int(os.getenv("V3_GAP_MIN", "240")), int(os.getenv("V3_GAP_MAX", "360")))
WARMUP_S = int(os.getenv("V3_WARMUP", "300"))
SPIKE_S, SPIKE_REPLICAS, BASE_REPLICAS = 180, 6, 2
LOADTEST = ("loadtest", "load-test")


def make_plan(seed=2027):
    """Deterministic list of events: dicts with service/type/repeat/level/duration (LOAD_SPIKE has service None)."""
    rng = random.Random(seed)
    offsets = {(s, t): rng.randrange(5) for s in SERVICES for t in TYPES}
    plan = []
    for rep in range(REPEATS):
        combos = [(s, t) for s in SERVICES for t in TYPES]
        rng.shuffle(combos)
        for s, t in combos:
            plan.append({"service": s, "type": t, "repeat": rep, "level": (rep + offsets[(s, t)]) % 5,
                         "duration": rng.randint(*DURATION_RANGE)})
        for _ in range(2):
            plan.append({"service": None, "type": "LOAD_SPIKE", "repeat": rep, "level": 0, "duration": SPIKE_S})
    return plan


def pilot_plan():
    """~15 min smoke test: one event of each kind, short, different levels."""
    d = int(os.getenv("V3_PILOT_DUR", "100"))
    return [{"service": "payment", "type": "CPU_HOG", "repeat": 0, "level": 0, "duration": d},
            {"service": "user", "type": "MEMORY_LEAK", "repeat": 0, "level": 4, "duration": d},
            {"service": "catalogue", "type": "NETWORK_LATENCY", "repeat": 0, "level": 0, "duration": d},
            {"service": "front-end", "type": "CPU_HOG", "repeat": 0, "level": 4, "duration": d},
            {"service": None, "type": "LOAD_SPIKE", "repeat": 0, "level": 0, "duration": 90}]


def build_commands(ev):
    """-> list of (start_offset_s, duration_s, argv) for Pumba, and a params dict for the log."""
    s, t, lv, d = ev["service"], ev["type"], ev["level"], ev["duration"]
    tgt = target_regex(s)
    stress = ["pumba", "stress", "--stress-image", "alexeiled/stress-ng", "--stressors"]
    if t == "CPU_HOG":
        w, load = CPU_LEVELS[lv]
        return [(0, d, stress[:2] + ["--duration", f"{d}s"] + stress[2:] + [f"--cpu {w} --cpu-load {load}", tgt])], \
            {"workers": w, "cpu_load": load}
    if t == "MEMORY_LEAK":
        mode, size = MEM_LEVELS[lv]
        if mode == "steady":
            return [(0, d, stress[:2] + ["--duration", f"{d}s"] + stress[2:] + [f"--vm 1 --vm-bytes {size} --vm-keep", tgt])], \
                {"mode": "steady", "vm_bytes": size}
        cmds = []
        for k in range(4):
            off = d * k // 4
            cmds.append((off, d - off, stress[:2] + ["--duration", f"{d - off}s"] + stress[2:] + [f"--vm 1 --vm-bytes {size} --vm-keep", tgt]))
        return cmds, {"mode": "ramp", "steps": 4, "step_bytes": size, "final": "128M"}
    if t == "NETWORK_LATENCY":
        ms = NET_LEVELS[lv]
        return [(0, d, ["pumba", "netem", "--duration", f"{d}s", "--tc-image", TC_IMAGE, "delay", "--time", str(ms),
                        "--jitter", str(max(1, ms // 10)), tgt])], {"delay_ms": ms, "jitter_ms": max(1, ms // 10)}
    raise ValueError(t)


class InjectorV3:
    def __init__(self, state, event_ids, stop_event, log_path):
        self.state, self.event_ids, self.stop = state, event_ids, stop_event
        self.env = get_minikube_docker_env()
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        new = not os.path.exists(log_path) or os.path.getsize(log_path) == 0
        self.f = open(log_path, "a", newline="")
        self.w = csv.writer(self.f)
        if new:
            self.w.writerow(["event_id", "service", "anomaly_type", "label", "repeat", "level", "duration_s", "params",
                             "start_iso", "end_iso", "status"])
            self.f.flush()

    def _log(self, *row):
        self.w.writerow(row)
        self.f.flush()

    def _set(self, services, label, event_id):
        for s in services:
            self.state[s] = label
            self.event_ids[s] = event_id

    def _fault(self, ev):
        eid = uuid.uuid4().hex[:10]
        s, t = ev["service"], ev["type"]
        cmds, params = build_commands(ev)
        logger.info("[%s] %s into %s level=%d dur=%ds %s", eid, t, s, ev["level"], ev["duration"], params)
        start = datetime.now(timezone.utc).isoformat()
        self._set([s], LABELS[t], eid)
        if t == "NETWORK_LATENCY":
            clear_stale_qdisc(self.env, s)
        status, procs, t0 = "ok", [], time.time()
        try:
            for off, dur, argv in cmds:
                wait = off - (time.time() - t0)
                if wait > 0 and self.stop.wait(wait):
                    break
                procs.append(subprocess.Popen(argv, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            for p in procs:
                try:
                    _, err = p.communicate(timeout=ev["duration"] + 60)
                except subprocess.TimeoutExpired:
                    p.kill()
                    status = "timeout"
                    continue
                if p.returncode != 0:
                    if t == "NETWORK_LATENCY" and "exit code 2" in (err or ""):
                        logger.warning("stale qdisc on %s; clearing and retrying once", s)
                        clear_stale_qdisc(self.env, s)
                        r = subprocess.run(p.args, env=self.env, capture_output=True, text=True, timeout=ev["duration"] + 60)
                        if r.returncode == 0:
                            continue
                        err = r.stderr
                    status = f"failed: {(err or '')[-200:]}"
        finally:
            for p in procs:
                if p.poll() is None:
                    p.kill()
            if t == "NETWORK_LATENCY":
                clear_stale_qdisc(self.env, s)
            self._set([s], 0, "")
        end = datetime.now(timezone.utc).isoformat()
        self._log(eid, s, t, LABELS[t], ev["repeat"], ev["level"], ev["duration"], json.dumps(params), start, end, status)

    def _spike(self, ev):
        eid = uuid.uuid4().hex[:10]
        logger.info("[%s] LOAD_SPIKE %d -> %d replicas for %ds (label NORMAL)", eid, BASE_REPLICAS, SPIKE_REPLICAS, ev["duration"])
        start = datetime.now(timezone.utc).isoformat()
        self._set(SERVICES, 0, eid)
        status = "ok"
        ns, dep = LOADTEST
        try:
            subprocess.run(["kubectl", "scale", "deploy", dep, "-n", ns, f"--replicas={SPIKE_REPLICAS}"], check=True, capture_output=True, timeout=30)
            self.stop.wait(ev["duration"])
        except Exception as exc:
            status = f"failed: {exc}"
        finally:
            subprocess.run(["kubectl", "scale", "deploy", dep, "-n", ns, f"--replicas={BASE_REPLICAS}"], capture_output=True, timeout=30)
            self._set(SERVICES, 0, "")
        end = datetime.now(timezone.utc).isoformat()
        self._log(eid, "ALL", "LOAD_SPIKE", 0, ev["repeat"], 0, ev["duration"], json.dumps({"replicas": SPIKE_REPLICAS}), start, end, status)

    def run(self, plan):
        logger.info("plan: %d events; warm-up %ds", len(plan), WARMUP_S)
        if self.stop.wait(WARMUP_S):
            return
        for i, ev in enumerate(plan, 1):
            if self.stop.is_set():
                logger.info("stop requested after %d/%d events", i - 1, len(plan))
                return
            (self._spike if ev["type"] == "LOAD_SPIKE" else self._fault)(ev)
            logger.info("progress %d/%d", i, len(plan))
            self.stop.wait(random.uniform(*GAP_RANGE))
        logger.info("plan complete")
