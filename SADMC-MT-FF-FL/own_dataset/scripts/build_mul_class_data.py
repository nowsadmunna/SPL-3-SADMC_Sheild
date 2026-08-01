"""
Convert own_dataset/raw/<service>.csv into the Mul_Class_Data_own/<service>.csv_{Xtrain,Ytrain,Xtest,Ytest}.npy
format expected by code/train_own_dataset.py (mirrors code/dataprocessing.py's original
MinMax-normalize + train/test split + one-hot conversion logic, adapted to the sock-shop schema).
"""
import csv
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import MinMaxScaler

RAW_DIR = "../raw"
OUT_DIR = "../../Mul_Class_Data_own"
SERVICES = ["carts", "catalogue", "front-end", "orders", "payment", "shipping", "user"]
NUM_CLASSES = 4  # NORMAL, CPU_HOG, MEMORY_LEAK, NETWORK_LATENCY
DROP_COLS = {"timestamp_unix", "timestamp_iso", "label", "label_name"}

import os
os.makedirs(OUT_DIR, exist_ok=True)

for service in SERVICES:
    path = f"{RAW_DIR}/{service}.csv"
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = list(reader)

    label_idx = header.index("label")
    feature_idx = [i for i, name in enumerate(header) if name not in DROP_COLS]

    X = np.array([[row[i] for i in feature_idx] for row in rows], dtype=np.float64)
    y = np.array([int(row[label_idx]) for row in rows], dtype=np.int64)

    scaler = MinMaxScaler()
    X = scaler.fit_transform(X)
    if np.isnan(X).any():
        X[np.isnan(X)] = np.nanmean(X)

    x_train, x_test, y_train, y_test = train_test_split(
        X, y, test_size=0.3, shuffle=True, random_state=123, stratify=y
    )

    Y_train = np.eye(NUM_CLASSES, dtype=np.float32)[y_train]
    Y_test = np.eye(NUM_CLASSES, dtype=np.float32)[y_test]

    class_name = f"{service}.csv"
    np.save(f"{OUT_DIR}/{class_name}_Xtrain.npy", x_train)
    np.save(f"{OUT_DIR}/{class_name}_Ytrain.npy", Y_train)
    np.save(f"{OUT_DIR}/{class_name}_Xtest.npy", x_test)
    np.save(f"{OUT_DIR}/{class_name}_Ytest.npy", Y_test)

    print(f"{service}: X_train {x_train.shape}, X_test {x_test.shape}, "
          f"train label counts {np.bincount(y_train, minlength=NUM_CLASSES)}, "
          f"test label counts {np.bincount(y_test, minlength=NUM_CLASSES)}")

print("Done.")
