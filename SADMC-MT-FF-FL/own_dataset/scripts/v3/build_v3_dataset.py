"""
Turns a finished v3 run (raw/*.csv + logs/injection_log.csv) into training files.

  1. derive features from the raw counters (feature_defs.derive_features, one fixed rate window)
  2. drop the first RATE_WINDOW_S seconds (no full window yet) and rows with any NaN feature
  3. mark TRANSITION rows: within TRANSITION_S after a fault starts or ends the 1-minute rate still mixes
     the old and the new state, so the label is unreliable there (kept in the file, flag `transition`=1, excluded
     from training and from the headline score)
  4. split BY EVENT, not by row: neighbouring rows are almost identical, a random row split leaks.
     Every fault event goes entirely to train or entirely to test, stratified per (service, fault type): 3 of the 5
     events of each pair train, 2 test;
     NORMAL rows are split by contiguous time blocks of BLOCK_S seconds
  5. write per service  <out>/<service>.csv  (features + label + event_id + split + transition)
     and  <out>/split.json  (which event ids are in test)

    python build_v3_dataset.py <run_dir> <out_dir> [--model-features-only]
"""
import csv
import datetime as dt
import json
import os
import random
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_defs import (ARTIFACT_SUSPECTS, FEATURE_NAMES, LIMIT_RELATIVE, RAW_COLUMNS, RATE_WINDOW_S, SERVICES, derive_features,
                         RATIO_FEATURES, add_ratio_features, to_limit_relative)

TRANSITION_S = int(os.getenv("V3_TRANSITION", "60"))
BLOCK_S = int(os.getenv("V3_BLOCK", "600"))
TEST_FRACTION = 0.3
SEED = 123
ts = lambda s: dt.datetime.fromisoformat(s).timestamp()

run, out = sys.argv[1], sys.argv[2]
model_only = "--model-features-only" in sys.argv
ratio = "--ratio-features" in sys.argv
limit_rel = "--limit-relative" in sys.argv   # divide CPU/memory features by the service's limits (limits.json next to the run dir)
limits = json.load(open(f"{os.path.dirname(os.path.abspath(run))}/limits.json")) if limit_rel else None
os.makedirs(out, exist_ok=True)
events = list(csv.DictReader(open(f"{run}/logs/injection_log.csv")))
faults = [e for e in events if e["anomaly_type"] != "LOAD_SPIKE" and e["status"] == "ok"]
skipped = [e for e in events if e["anomaly_type"] != "LOAD_SPIKE" and e["status"] != "ok"]

# --- event-level split, stratified per (service, fault type): every service keeps all classes in both parts.
# Each pair has 5 events (5 repeats, 5 different parameter levels): 3 go to train, 2 to test.
rng = random.Random(SEED)
test_events = set()
for key in sorted({(e["service"], e["anomaly_type"]) for e in faults}):
    ids = sorted(e["event_id"] for e in faults if (e["service"], e["anomaly_type"]) == key)
    rng.shuffle(ids)
    test_events |= set(ids[: max(1, round(len(ids) * TEST_FRACTION))])

feature_cols = [f for f in FEATURE_NAMES if not (model_only and f in ARTIFACT_SUSPECTS)]
if limit_rel:
    feature_cols = [(f.replace('_pct', '').replace('_mb', '') + '_rel') if f in LIMIT_RELATIVE else f for f in feature_cols]
if ratio:
    feature_cols += RATIO_FEATURES
summary = {}
for s in SERVICES:
    rows = list(csv.DictReader(open(f"{run}/raw/{s}.csv")))
    t = np.array([float(r["t_unix"]) for r in rows])
    raw = {c: np.array([float(r[c]) if r[c] != "" else np.nan for r in rows]) for c in RAW_COLUMNS}
    feats = derive_features(t, raw)
    if ratio:
        feats = add_ratio_features(feats)
    if limit_rel:
        feats = to_limit_relative(feats, limits[s]["cpu_limit_cores"], limits[s]["mem_limit_mb"])
    label = np.array([int(r["label"]) for r in rows])
    eid = [r["event_id"] for r in rows]
    t0 = t[0]
    keep = (t - t0 >= RATE_WINDOW_S) & ~np.any(np.isnan(np.column_stack([feats[f] for f in feature_cols])), axis=1)
    # transition flag: near the start or end of any fault window of this service
    trans = np.zeros(len(t), dtype=int)
    for e in faults + skipped:
        if e["service"] == s:
            a, b = ts(e["start_iso"]), ts(e["end_iso"])
            trans[((t >= a) & (t <= a + TRANSITION_S)) | ((t >= b) & (t <= b + TRANSITION_S))] = 1
    # a failed injection leaves rows labelled as fault although nothing ran: drop them
    bad = np.zeros(len(t), dtype=bool)
    for e in skipped:
        if e["service"] == s:
            bad |= (t >= ts(e["start_iso"])) & (t <= ts(e["end_iso"]) + TRANSITION_S)
    keep &= ~bad
    split = []
    for i in range(len(t)):
        if label[i] != 0:
            split.append("test" if eid[i] in test_events else "train")
        else:
            blk = int((t[i] - t0) // BLOCK_S)
            split.append("test" if random.Random(SEED + blk * 7919 + SERVICES.index(s)).random() < TEST_FRACTION else "train")
    with open(f"{out}/{s}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["t_unix"] + feature_cols + ["label", "event_id", "split", "transition"])
        for i in np.where(keep)[0]:
            w.writerow([round(t[i], 3)] + [f"{feats[c][i]:.6g}" for c in feature_cols] + [label[i], eid[i], split[i], trans[i]])
    k = np.where(keep)[0]
    summary[s] = {"rows": int(len(k)), "label_counts": np.bincount(label[k], minlength=4).tolist(),
                  "train": int(sum(split[i] == "train" for i in k)), "test": int(sum(split[i] == "test" for i in k)),
                  "transition_rows": int(trans[k].sum())}

json.dump({"limit_relative": limit_rel, "ratio_features": ratio, "features": feature_cols, "excluded_artifact_suspects": sorted(ARTIFACT_SUSPECTS) if model_only else [],
          "test_event_ids": sorted(test_events), "failed_events_dropped": [e["event_id"] for e in skipped],
          "rate_window_s": RATE_WINDOW_S, "transition_s": TRANSITION_S, "block_s": BLOCK_S, "seed": SEED, "per_service": summary},
          open(f"{out}/split.json", "w"), indent=1)
print(f"{len(feature_cols)} features; {len(faults)} fault events ({len(test_events)} test), {len(skipped)} failed events dropped")
for s, v in summary.items():
    print(f"  {s:<10} rows={v['rows']:>5}  classes={v['label_counts']}  train={v['train']:>5} test={v['test']:>5}  transition rows={v['transition_rows']}")
