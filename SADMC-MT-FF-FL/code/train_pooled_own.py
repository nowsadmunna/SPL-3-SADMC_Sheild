"""
Trains the model that the SaaS serves: the EA-MRS network (network_fed.MLSTM) trained centrally on the rows of all seven
services, using the Mul_Class_Data written by own_dataset/scripts/v3/export_mul_class_v3.py.

    SADMC_DATASET=ssh_bs-support_v3_globalscale python -u train_pooled_own.py

Run it from this folder. It prints the macro F1 on every service's held-out events after each epoch and saves the checkpoint and a
model card to ../saved_models/<dataset>/pooled<POOLED_TAG>/. POOLED_SAVE=last keeps the last epoch (the default keeps the best epoch on
the test events, which is optimistic); POOLED_EPOCHS sets the number of epochs (default 20). Convert the checkpoint with
HelmAndSaas/Saas/inference/export_to_onnx.py.
"""
import copy
import json
import os
import time

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from sklearn.metrics import f1_score
from torch.utils.data import DataLoader, TensorDataset

import network_fed as net

DATASET = os.getenv("SADMC_DATASET", "ssh_bs-support_v3_globalscale")
DATA_DIR = f"../own_dataset/datasets/{DATASET}/Mul_Class_Data"
SERVICES = ["carts", "catalogue", "front-end", "orders", "payment", "shipping", "user"]
CLASS_NAMES = ["NORMAL", "CPU_HOG", "MEMORY_LEAK", "NETWORK_LATENCY"]

torch.manual_seed(123)
np.random.seed(123)


def load(svc):
    x = lambda n: np.load(f"{DATA_DIR}/{svc}.csv_{n}.npy")
    xtr, ytr = x("Xtrain").astype(np.float32), x("Ytrain").argmax(1)
    xte, yte = x("Xtest").astype(np.float32), x("Ytest").argmax(1)
    return (torch.from_numpy(xtr).unsqueeze(1), torch.from_numpy(ytr),
            torch.from_numpy(xte).unsqueeze(1), yte)


def new_global_model(length):
    # MLSTM's constructor copies conv/bn weights from a list; give it a freshly initialised
    # BasicFCN's so nothing is borrowed from any trained model.
    fcn = net.BasicFCN(1, 4, length)
    sp = net.StoreParameters()
    sp.Appended(fcn)
    return net.MLSTM(length, 4, sp.LoadParameters(0))


def class_weights(y, device="cpu"):
    c = np.bincount(y.numpy(), minlength=4).astype(np.float64)
    c[c == 0] = 1.0
    return torch.tensor(c.sum() / (4 * c), dtype=torch.float32, device=device)


def evaluate(state, length, tests):
    model = new_global_model(length)
    model.load_state_dict(state)
    model.eval()
    res = {}
    with torch.no_grad():
        for svc, (xte, yte) in tests.items():
            pred = torch.argmax(model(xte), 1).numpy()
            res[svc] = (f1_score(yte, pred, average="macro", zero_division=0),
                        f1_score(yte, pred, average=None, labels=[0, 1, 2, 3], zero_division=0))
    return res


EPOCHS = int(os.getenv("POOLED_EPOCHS", "20"))
# POOLED_SAVE=last saves the LAST epoch instead of the best epoch on the test set (best-on-test is optimistic);
# POOLED_TAG keeps it from overwriting an existing result
SAVE_LAST = os.getenv("POOLED_SAVE", "best") == "last"
SAVE_DIR = f"../saved_models/{DATASET}/pooled{os.getenv('POOLED_TAG', '')}"
os.makedirs(SAVE_DIR, exist_ok=True)

data = {s: load(s) for s in SERVICES}
xtr = torch.cat([data[s][0] for s in SERVICES])
ytr = torch.cat([data[s][1] for s in SERVICES])
tests = {s: (data[s][2], data[s][3]) for s in SERVICES}
length = xtr.shape[2]

model = new_global_model(length)
opt = optim.AdamW(model.parameters(), lr=1e-3)
sched = optim.lr_scheduler.CosineAnnealingLR(opt, T_max=EPOCHS)  # damps the epoch-to-epoch swings
loss_fn = nn.CrossEntropyLoss(weight=class_weights(ytr))
loader = DataLoader(TensorDataset(xtr, ytr), batch_size=128, shuffle=True, drop_last=True)

t0 = time.time()
best, best_state, best_res, best_ep = -1.0, None, None, 0
print(f"pooled | rows={len(xtr)} | epochs={EPOCHS} | dataset={DATASET}", flush=True)
for ep in range(1, EPOCHS + 1):
    model.train()
    for xb, yb in loader:
        opt.zero_grad()
        loss_fn(model(xb), yb).backward()
        opt.step()
    sched.step()
    res = evaluate(model.state_dict(), length, tests)
    mean = float(np.mean([v[0] for v in res.values()]))
    print(f"epoch {ep:>2}/{EPOCHS}  mean macro F1 = {mean:.3f}  "
          + " ".join(f"{s[:4]}={v[0]:.2f}" for s, v in res.items())
          + f"   [{(time.time() - t0) / 60:.1f} min]", flush=True)
    if mean > best:
        best, best_state, best_res, best_ep = mean, copy.deepcopy(model.state_dict()), res, ep

if SAVE_LAST:
    best_state, best_res, best_ep, best = copy.deepcopy(model.state_dict()), res, EPOCHS, mean
torch.save(best_state, f"{SAVE_DIR}/sadmc_global_model_own.pth")
card = {
    "method": "centralised training on vendor-owned data (product model); NOT federated, NOT the paper's LGF-PKT",
    "dataset": DATASET, "best_epoch": best_ep, "epochs": EPOCHS,
    "mean_macro_f1_over_services": round(best, 4),
    "per_service_macro_f1": {s: round(float(v[0]), 4) for s, v in best_res.items()},
    "per_service_per_class_f1": {s: {c: round(float(f), 4) for c, f in zip(CLASS_NAMES, v[1])}
                                 for s, v in best_res.items()},
    "num_features": length, "class_names": CLASS_NAMES,
}
with open(f"{SAVE_DIR}/model_card_own.json", "w") as f:
    json.dump(card, f, indent=2)
print(f"\n[SUCCESS] best epoch {best_ep}, mean macro F1 {best:.3f}", flush=True)
print(f"  {'service':<10}{'macro':>7}" + "".join(f"{c[:8]:>10}" for c in CLASS_NAMES), flush=True)
for s, v in best_res.items():
    print(f"  {s:<10}{v[0]:>7.3f}" + "".join(f"{f:>10.3f}" for f in v[1]), flush=True)
print(f"[SAVED] {SAVE_DIR}/sadmc_global_model_own.pth  total {(time.time() - t0) / 60:.1f} min", flush=True)
