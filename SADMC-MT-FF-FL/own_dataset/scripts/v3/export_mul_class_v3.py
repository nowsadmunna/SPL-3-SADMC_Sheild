"""
Built v3 dataset (build_v3_dataset.py output) -> the Mul_Class_Data .npy layout the existing training code reads.

  <out>/Mul_Class_Data/<service>.csv_{Xtrain,Ytrain,Xtest,Ytest}.npy      (Y one-hot, 4 classes)
  <out>/scalers/_global.json  (mode global)   or  scalers/<service>.json (mode per-service)

The scaler is fitted on TRAIN rows only (the earlier datasets fitted it on all rows, a small leak), transition rows are
excluded from train and test, and every value is clipped to [0, 1] after scaling - exactly what the SaaS does at
serving time. Constant columns (zero range in the training rows) are pinned to 0.

    python export_mul_class_v3.py <built_dir> <out_dir> [global|per-service]
"""
import csv
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from feature_defs import SERVICES

built, out = sys.argv[1], sys.argv[2]
mode = sys.argv[3] if len(sys.argv) > 3 else "global"
meta = json.load(open(f"{built}/split.json"))
feats = meta["features"]
os.makedirs(f"{out}/Mul_Class_Data", exist_ok=True)
os.makedirs(f"{out}/scalers", exist_ok=True)

D = {}
for s in SERVICES:
    rows = [r for r in csv.DictReader(open(f"{built}/{s}.csv")) if r["transition"] == "0"]
    X = np.array([[float(r[f]) for f in feats] for r in rows])
    D[s] = {"X": X, "y": np.array([int(r["label"]) for r in rows]), "split": np.array([r["split"] for r in rows])}


def fit(X):
    lo, hi = X.min(0), X.max(0)
    const = hi == lo
    with np.errstate(divide="ignore"):
        scale = np.where(const, 1.0, 1.0 / (hi - lo))
    return scale, -lo * scale, const


def apply(X, sc):
    scale, mn, const = sc
    Z = np.clip(X * scale + mn, 0.0, 1.0)
    Z[:, const] = 0.0
    return Z


if mode == "global":
    glob = fit(np.vstack([D[s]["X"][D[s]["split"] == "train"] for s in SERVICES]))
    json.dump({"feature_names": feats, "scale": glob[0].tolist(), "min": glob[1].tolist(), "constant": glob[2].tolist(),
               "fitted_on": "train rows of all services, transition rows excluded"}, open(f"{out}/scalers/_global.json", "w"))
for s in SERVICES:
    d = D[s]
    tr, te = d["split"] == "train", d["split"] == "test"
    sc = glob if mode == "global" else fit(d["X"][tr])
    if mode != "global":
        json.dump({"feature_names": feats, "scale": sc[0].tolist(), "min": sc[1].tolist(), "constant": sc[2].tolist()},
                  open(f"{out}/scalers/{s}.json", "w"))
    Z = apply(d["X"], sc)
    onehot = np.eye(4)[d["y"]]
    for part, m in (("train", tr), ("test", te)):
        np.save(f"{out}/Mul_Class_Data/{s}.csv_X{part}.npy", Z[m])
        np.save(f"{out}/Mul_Class_Data/{s}.csv_Y{part}.npy", onehot[m])
    print(f"{s:<10} train {int(tr.sum()):>5} {np.bincount(d['y'][tr], minlength=4).tolist()}   test {int(te.sum()):>5} {np.bincount(d['y'][te], minlength=4).tolist()}")
print(f"mode={mode}  features={len(feats)}  constant (pinned to 0): {int(sum(glob[2])) if mode == 'global' else 'per-service'}")
