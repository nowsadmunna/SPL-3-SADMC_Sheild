"""
Builds the EA-MRS network (MLSTM from SADMC-MT-FF-FL/code/network_fed.py) and loads a trained checkpoint.
Used by export_to_onnx.py and verify_parity.py, which run with the virtual environment that has torch installed.
"""
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.append(os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "code"))

import torch  # noqa: E402
import network_fed as net  # noqa: E402


def load_global_model(model_path, num_features=33, num_classes=4):
    """Returns the trained PyTorch model in eval mode. The checkpoint must match num_features."""
    # The constructor copies conv/batch-norm weights from a list; the real weights come from the checkpoint right after.
    dummy_params = [
        torch.zeros(128, 1, 7), torch.zeros(128),    # conv1 weight, bias
        torch.ones(128), torch.zeros(128),            # bn1 weight, bias
        torch.zeros(256, 128, 5), torch.zeros(256),  # conv2 weight, bias
        torch.ones(256), torch.zeros(256),            # bn2 weight, bias
        torch.zeros(128, 256, 3), torch.zeros(128),  # conv3 weight, bias
        torch.ones(128), torch.zeros(128),            # bn3 weight, bias
    ]
    model = net.MLSTM(ni=num_features, nf=num_classes, modelFCN=dummy_params)
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"model checkpoint not found: {model_path}")
    model.load_state_dict(torch.load(model_path, map_location="cpu"))
    print(f"[INFO] loaded model checkpoint from: {model_path}")
    model.eval()
    return model
