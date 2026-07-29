# Project Navigation Guide: SADMC-MT-FF-FL

Welcome to the **SADMC-MT-FF-FL** repository. This project implements a federated multi-task learning framework for anomaly detection in microservices.

To understand this project efficiently, we recommend following the roadmap below.

## 1. Recommended Reading Order

1.  **`paper_implementation.md`**: (Previously generated) Start here for a high-level summary of the logic.
2.  **`TRACEABILITY.md`**: Refer to this to see how specific math/algorithms in the PDF map to actual lines of code.
3.  **`code/config.py`**: Understand the global constants, dataset paths, and hyperparameters.
4.  **`code/sadmc-mt-ff-fl.py`**: This is the main entry point. Analyze the `for e in range(1, Fed_iteration)` loop to see how the federated rounds progress.
5.  **`code/network_fed.py`**: This contains the "brain" of the project (Neural Networks and Weight Sharing logic).

---

## 2. Core Directory Structure

- `/code`: Contains all executable Python scripts and model definitions.
- `/Mul_Class_Data`: Contains the preprocessed `.npy` datasets for the Sock-Shop microservices.
- `/tSNE`: Contains visualization scripts to analyze the separation between normal and anomalous data.
- `AD.pdf`: The original research paper published in *Future Generation Computer Systems (2024)*.

---

## 3. High-Level execution Flow

The algorithm follows a three-stage pipeline for every federated round:

### Phase A: Local Feature Extraction
Each service (Node) trains a local model on its own data to identify service-specific patterns using the **Local model** (1D-CNN + External Attention).

### Phase B: Similarity-Based Aggregation
Weights are uploaded. The `StoreParameters` class calculates which microservices are "most similar" based on a hybrid Euclidean/Cosine distance metric.

### Phase C: Knowledge Transfer
Nodes fetch weights from their most similar neighbors and update their **Transfer model**. This allows a service to "learn" how an anomaly looks from other services that have experienced similar patterns.

---

## 4. Key Classes to Study

- **`LoadData`**: Custom PyTorch Dataset for loading the `.npy` files.
- **`MLSTM`**: the primary neural network class (found in `network_fed.py`).
- **`StoreParameters`**: The central coordinator for storing and comparing model weights across nodes.

---

## 5. Running the Project

Ensure you have PyTorch and NumPy installed. The main training script is executed via:
```bash
python code/sadmc-mt-ff-fl.py
```
*Note: Ensure the data paths in `config.py` or the main script match your local directory structure.*
