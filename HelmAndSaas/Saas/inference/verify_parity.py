"""
Writes fixtures/torch_reference_v3.json for verify_parity.js, the gate before INFERENCE_MODE=onnx.

It checks the WHOLE serving path, not just the ONNX file:
  raw 33-vector --(fixed global MinMax scaler, model/v3/global_scaler.json)--> normalised --> model --> probs
verify_parity.js redoes the normalisation in JS (fixedScaler.js) and must land on the same numbers, then runs ONNX and must
reproduce torch's probabilities. An ONNX model that agrees perfectly with torch but is fed the wrong scaling is worthless,
hence the real-row accuracy printed at the end (this is a plumbing check, not a generalisation score).

Run: SADMC-MT-FF-FL/sadmc-venv/bin/python HelmAndSaas/Saas/inference/verify_parity.py
"""
import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np  # noqa: E402
import torch  # noqa: E402

from model_loader import PROJECT_ROOT, load_global_model  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
NUM_FEATURES = 33
FIXTURES_PATH = os.path.join(HERE, "fixtures", "torch_reference_v3.json")
MODEL_PTH = os.getenv("MODEL_PTH") or os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "saved_models", "ssh_bs-support_v3_globalscale", "pooled_last", "sadmc_global_model_own.pth")
SCALER = json.load(open(os.path.join(HERE, "model", "v3", "global_scaler.json")))
BUILT = os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "own_dataset", "datasets", "ssh_bs-support_v3", "built")   # derived (unscaled) features + labels
SERVICES = ["carts", "front-end", "user", "shipping"]


def load_rows(svc):
    feats = json.load(open(os.path.join(BUILT, "split.json")))["features"]
    with open(os.path.join(BUILT, f"{svc}.csv")) as f:
        rows = [r for r in csv.DictReader(f) if r["transition"] == "0"]
    return (np.array([[float(r[k]) for k in feats] for r in rows]), np.array([int(r["label"]) for r in rows]))


def scale_fixed(vec):
    z = np.asarray(vec, dtype=np.float64) * np.array(SCALER["scale"]) + np.array(SCALER["min"])
    z = np.clip(z, 0.0, 1.0)
    z[np.array(SCALER["constant"], dtype=bool)] = 0.0
    return z


def main():
    random.seed(1407)
    model = load_global_model(model_path=MODEL_PTH, num_features=NUM_FEATURES)
    model.eval()
    fixtures, hit, real = [], 0, 0
    for svc in SERVICES:
        X, y = load_rows(svc)
        picks = [([0.0] * NUM_FEATURES, None), ([1e9] * NUM_FEATURES, None), ([-5.0] * NUM_FEATURES, None)] if svc == SERVICES[0] else []
        for cls in range(4):   # real rows: 6 per class
            idx = [i for i in range(len(y)) if y[i] == cls]
            picks += [(X[i].tolist(), cls) for i in random.sample(idx, 6)]
        for raw, true_cls in picks:
            norm = scale_fixed(raw)
            with torch.no_grad():
                logits = model(torch.tensor(norm, dtype=torch.float32).reshape(1, 1, -1))
            probs = torch.softmax(logits, dim=1)[0]
            pred = int(torch.argmax(probs))
            fixtures.append({"service": svc, "input": raw, "normalised": norm.tolist(),
                             "true_class": true_cls, "probs": probs.tolist(), "pred_class": pred})
            if true_cls is not None:
                real += 1
                hit += int(pred == true_cls)
    os.makedirs(os.path.dirname(FIXTURES_PATH), exist_ok=True)
    with open(FIXTURES_PATH, "w") as f:
        json.dump({"fixtures": fixtures}, f)
    print(f"[parity] wrote {len(fixtures)} fixtures")
    print(f"[parity] sanity: torch gets {hit}/{real} REAL rows right ({100 * hit / real:.0f}%)")


if __name__ == "__main__":
    main()
