"""
Offline export of the trained SADMC EA-MRS PyTorch model to ONNX, so that the Node.js backend can run inference with
onnxruntime-node without a Python runtime.

Run with the virtual environment that has torch and onnx installed:
    SADMC-MT-FF-FL/sadmc-venv/bin/python HelmAndSaas/Saas/inference/export_to_onnx.py

The model is the EA-MRS Transfer model trained centrally on all seven services (code/train_pooled_own.py) on features scaled
by ONE fixed global MinMax scaler (model/v3/global_scaler.json, the same one used at serving). 33 inputs, no padding.
Override the checkpoint with MODEL_PTH.

The export uses a FIXED batch size of 1 (no dynamic_axes). MLSTM.forward() does `x1 = self.conv4(x); x1 = self.aap(x1);
x1 = x1.squeeze()`, which collapses both the batch and the spatial size-1 dimensions to shape (128,) before adding to x2;
this only works for batch=1, so inference always runs one service at a time.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import torch  # noqa: E402
import onnx  # noqa: E402

from model_loader import PROJECT_ROOT, load_global_model  # noqa: E402

NUM_FEATURES = 33
DATASET = os.getenv("SADMC_DATASET", "ssh_bs-support_v3_globalscale")
MODEL_PTH = os.getenv("MODEL_PTH") or os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "saved_models", DATASET, "pooled_last", "sadmc_global_model_own.pth")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model", "v3", "sadmc_model.onnx")


def main():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    model = load_global_model(model_path=MODEL_PTH, num_features=NUM_FEATURES)
    model.eval()

    dummy_input = torch.zeros(1, 1, NUM_FEATURES, dtype=torch.float32)

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
