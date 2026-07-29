"""
Generates fixture feature vectors and runs them through the real PyTorch
model, dumping {input, logits, probs, pred_class} to fixtures/torch_reference.json.
verify_parity.js then runs the same vectors through the exported ONNX model
and asserts the two agree — the mandatory gate before flipping
INFERENCE_MODE=onnx in the Node backend.

Run with: SADMC-MT-FF-FL/sadmc-venv/bin/python HelmAndSaas/Saas/inference/verify_parity.py
"""
import json
import os
import random
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "code"))
sys.path.insert(0, PROJECT_ROOT)

import torch  # noqa: E402
from local_pipeline_test import load_global_model  # noqa: E402

FIXTURES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "torch_reference.json")


def build_fixtures():
    random.seed(1407)
    fixtures = []

    # All-zero edge case.
    fixtures.append([0.0] * 35)

    # All-ones (small, uniform) edge case.
    fixtures.append([1.0] * 35)

    # A handful of "plausible normal load" vectors: modest CPU/mem/latency.
    for _ in range(5):
        vec = [
            random.uniform(0, 30),   # cpu_user
            random.uniform(0, 20),   # cpu_system
            random.uniform(0, 40),   # cpu_total
            random.uniform(0, 1),    # cpu_throttled
            random.uniform(0, 5),    # cpu_cfs_periods
            random.uniform(50, 300),  # mem_rss
            random.uniform(10, 100),  # mem_cache
            random.uniform(0, 5),    # mem_swap
            random.uniform(0, 2),    # mem_failcnt
            random.uniform(100, 400),  # mem_usage
        ] + [random.uniform(0, 50) for _ in range(25)]
        fixtures.append(vec)

    # A handful of "CPU-spike-shaped" vectors: CPU-related indices (0-4)
    # pushed high, everything else modest.
    for _ in range(5):
        vec = [
            random.uniform(80, 100),  # cpu_user
            random.uniform(70, 100),  # cpu_system
            random.uniform(90, 100),  # cpu_total
            random.uniform(10, 40),   # cpu_throttled
            random.uniform(20, 60),   # cpu_cfs_periods
        ] + [random.uniform(0, 50) for _ in range(30)]
        fixtures.append(vec)

    # A handful of "memory-leak-shaped" vectors: memory indices (5-9) high.
    for _ in range(5):
        vec = (
            [random.uniform(0, 30) for _ in range(5)]
            + [
                random.uniform(2000, 8000),  # mem_rss
                random.uniform(500, 2000),  # mem_cache
                random.uniform(100, 500),   # mem_swap
                random.uniform(50, 200),    # mem_failcnt
                random.uniform(3000, 9000),  # mem_usage
            ]
            + [random.uniform(0, 50) for _ in range(25)]
        )
        fixtures.append(vec)

    # A couple of large/extreme values to probe numerical stability.
    fixtures.append([1e4] * 35)
    fixtures.append([-1.0] * 35)  # negative values shouldn't occur in practice, but guard anyway

    return fixtures


def main():
    model = load_global_model()
    model.eval()

    fixtures = build_fixtures()
    records = []

    for raw_vector in fixtures:
        padded = list(raw_vector) + [0.0] * (36 - len(raw_vector))
        x = torch.tensor(padded, dtype=torch.float32).reshape(1, 1, -1)
        x = torch.nan_to_num(x)

        with torch.no_grad():
            logits = torch.nan_to_num(model(x))
            probs = torch.softmax(logits, dim=1)
            pred_class = int(torch.argmax(probs, dim=1).item())

        records.append(
            {
                "input": raw_vector,
                "logits": logits[0].tolist(),
                "probs": probs[0].tolist(),
                "pred_class": pred_class,
            }
        )

    os.makedirs(os.path.dirname(FIXTURES_PATH), exist_ok=True)
    with open(FIXTURES_PATH, "w") as f:
        json.dump(records, f, indent=2)

    print(f"[verify_parity.py] wrote {len(records)} fixtures to {FIXTURES_PATH}")


if __name__ == "__main__":
    main()
