"""
One-time offline export of the trained SADMC MLSTM PyTorch model to ONNX,
so the Node.js backend can run inference via onnxruntime-node without any
Python runtime dependency.

Run with the venv that already has torch installed:
    SADMC-MT-FF-FL/sadmc-venv/bin/python HelmAndSaas/Saas/inference/export_to_onnx.py

Reuses load_global_model() from local_pipeline_test.py verbatim (same
sys.path trick) so this export uses the exact same model construction /
state_dict loading path already verified to work.

Export uses a FIXED batch size of 1 (no dynamic_axes on the batch dim).
MLSTM.forward() does `x1 = self.conv4(x); x1 = self.aap(x1); x1 = x1.squeeze()`
which collapses both the batch and the spatial size-1 dims down to shape
(128,) before adding to x2 — this only works reliably for batch=1, so we
export accordingly and always run inference one service at a time.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "code"))

import torch  # noqa: E402
import onnx  # noqa: E402

sys.path.insert(0, PROJECT_ROOT)
from local_pipeline_test import load_global_model  # noqa: E402

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "sadmc_model.onnx")


def main():
    model = load_global_model()
    model.eval()

    dummy_input = torch.zeros(1, 1, 36, dtype=torch.float32)

    torch.onnx.export(
        model,
        dummy_input,
        OUTPUT_PATH,
        input_names=["input"],
        output_names=["logits"],
        opset_version=17,
        do_constant_folding=True,
        # No dynamic_axes: batch size is fixed at 1 (see module docstring).
    )
    print(f"[export] wrote {OUTPUT_PATH}")

    onnx_model = onnx.load(OUTPUT_PATH)
    onnx.checker.check_model(onnx_model)
    print("[export] onnx.checker.check_model passed")

    # Quick sanity check: onnxruntime output vs. torch output on the same
    # dummy input (real parity verification against varied fixtures happens
    # in verify_parity.py / verify_parity.js).
    import onnxruntime as ort
    import numpy as np

    session = ort.InferenceSession(OUTPUT_PATH, providers=["CPUExecutionProvider"])
    ort_out = session.run(None, {"input": dummy_input.numpy()})[0]

    with torch.no_grad():
        torch_out = model(dummy_input).numpy()

    max_diff = float(np.max(np.abs(ort_out - torch_out)))
    print(f"[export] sanity check max|onnx-torch| on zero input = {max_diff:.2e}")
    if max_diff > 1e-3:
        print("[export] WARNING: sanity check diff is larger than expected")


if __name__ == "__main__":
    main()
