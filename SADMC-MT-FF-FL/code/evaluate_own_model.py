"""
Evaluate saved_models/sadmc_global_model_own.pth (produced by train_own_dataset.py)
against each service's held-out test set, reporting per-class precision/recall/F1 —
plain accuracy alone is misleading here since ~90% of rows are NORMAL.

Run after train_own_dataset.py finishes:
    ../sadmc-venv/bin/python evaluate_own_model.py
"""
import numpy as np
import torch
from sklearn.metrics import classification_report, confusion_matrix
import network_fed as net

DATA_DIR = "../Mul_Class_Data_own"
MODEL_PATH = "../saved_models/sadmc_global_model_own.pth"
SERVICES = ['carts.csv', 'catalogue.csv', 'front-end.csv', 'orders.csv', 'payment.csv', 'shipping.csv', 'user.csv']
CLASS_NAMES = ['NORMAL', 'CPU_HOG', 'MEMORY_LEAK', 'NETWORK_LATENCY']
NUM_CLASSES = 4

# MLSTM's constructor pulls initial conv1/conv2/conv3/bn1/bn2/bn3 weights from a
# parameter list (shape-compatible placeholder here); load_state_dict below then
# overwrites every weight, placeholder included, with the actual trained ones.
length = np.load(f"{DATA_DIR}/carts.csv_Xtrain.npy").shape[1]
placeholder_fcn = net.BasicFCN(1, NUM_CLASSES, length)
sp = net.StoreParameters()
sp.Appended(placeholder_fcn)
placeholder_params = sp.LoadParameters(0)

model = net.MLSTM(length, NUM_CLASSES, placeholder_params)
model.load_state_dict(torch.load(MODEL_PATH, map_location="cpu"))
model.eval()

all_y_true = []
all_y_pred = []

for service in SERVICES:
    x_test = np.load(f"{DATA_DIR}/{service}_Xtest.npy")
    y_test = np.load(f"{DATA_DIR}/{service}_Ytest.npy")
    y_test = np.argmax(y_test, axis=1)
    x_test = x_test.reshape((x_test.shape[0], 1, x_test.shape[1])).astype(np.float32)

    with torch.no_grad():
        output = model(torch.from_numpy(x_test))
        y_pred = torch.argmax(output, dim=1).numpy()

    print(f"\n=== {service} ===")
    labels_present = sorted(set(y_test) | set(y_pred))
    print(classification_report(
        y_test, y_pred,
        labels=labels_present,
        target_names=[CLASS_NAMES[i] for i in labels_present],
        digits=3, zero_division=0,
    ))
    print("Confusion matrix (rows=true, cols=pred), classes", [CLASS_NAMES[i] for i in labels_present])
    print(confusion_matrix(y_test, y_pred, labels=labels_present))

    all_y_true.append(y_test)
    all_y_pred.append(y_pred)

all_y_true = np.concatenate(all_y_true)
all_y_pred = np.concatenate(all_y_pred)
print("\n=== Overall (all services combined) ===")
labels_present = sorted(set(all_y_true) | set(all_y_pred))
print(classification_report(
    all_y_true, all_y_pred,
    labels=labels_present,
    target_names=[CLASS_NAMES[i] for i in labels_present],
    digits=3, zero_division=0,
))
