# Implementation of SADMC-MT-FF-FL

This document outlines the technical implementation details of the **SADMC-MT-FF-FL** (Self-Adaptive Deep Multi-task Configuration - Multi-Task Feature Fusion - Federated Learning) framework for anomaly detection in microservices, as implemented in this repository.

## 1. Conceptual Overview

SADMC-MT-FF-FL is a distributed anomaly detection framework designed for microservice architectures. It addresses the challenges of data sparsity in individual services and the high overhead of centralized monitoring by leveraging **Multi-task Federated Learning** and **Advanced Feature Fusion**.

### Key Pillars:
- **Federated Learning (FL):** Enables collaborative training across distributed services without sharing raw metric data.
- **Multi-Task Learning (MTL):** Each microservice is treated as a separate task, allowing the model to learn common patterns while maintaining task-specific nuances.
- **Self-Adaptive Configuration:** Dynamically selects or fuses model parameters from the most relevant services based on a calculated similarity distance.
- **Feature Fusion (FF):** Utilizes Attention mechanisms (Squeeze-and-Excitation and External Attention) to capture complex interdependencies in telemetry metrics.

---

## 2. Neural Network Architecture

The implementation provides several model variants, primarily implemented in `code/network_fed.py`.

### A. Basic FCN (Fully Convolutional Network)
A 1D-CNN based architecture used as a baseline and core feature extractor.
- **Structure:** 3 Convolutional layers (128, 256, 128 channels).
- **Normalisation:** BatchNorm1d after each convolution.
- **Pooling:** AdaptiveAvgPool1d to reduce temporal dimensionality.

### B. SE-Attention & External Attention
To enhance feature extraction, the models incorporate two key attention mechanisms:
1. **SELayer (Squeeze-and-Excitation):**
   - Recalibrates channel-wise features by explicitly modeling inter-channel dependencies.
   - Helps the model focus on the most informative metrics in the telemetry stream.
2. **External Attention:**
   - Captures global dependencies with $O(N)$ linear complexity (instead of the $O(N^2)$ complexity of standard Self-Attention).
   - Essential for low-latency inference in microservice environments.

### C. MLSTM Model
A hybrid model that combines the strengths of 1D-CNNs for local feature extraction and attention mechanisms for global context.
- **Skip Connections:** Utilizes residual-like connections (adding `x1 + x2` in the final layer) to preserve raw feature information alongside processed features.

---

## 3. Federated Mechanism

The federated logic is managed by classes like `StoreParameters` and `BasicShared`.

### Model Parameter Storage
```python
class StoreParameters(object):
    def __init__(self):
        # Stores weights and biases for all 3 layers across all clients
        self.conv1_weight = []
        self.conv2_weight = []
        # ...
```

### Self-Adaptive Selection
Instead of simple FedAvg (Federated Averaging), the framework uses a similarity-based approach:
1. **Distance Metric (`SquareLossEW`):** Calculates a hybrid distance combining Euclidean distance and Cosine Similarity between model weight vectors.
   $$\text{Loss} = \frac{\text{EuclideanDist}}{\text{CosineSim}}$$
2. **Top-K Matching (`StoreEW`):** For a given service, the framework identifies the `top_k=2` most similar models from the parameter pool to perform update/fusion.

---

## 4. Training and Evaluation

### Dataset: Sock-Shop
The implementation is tailored for the **Sock-Shop** microservices benchmark.
- **Services:** `carts`, `catalogue`, `front-end`, `orders`, `payment`, `shipping`, `user`.
- **Labels:** Multi-class classification (Normal vs. different types of Anomalies).

### Execution Flow (`sadmc-mt-ff-fl.py`):
1. **Initial Local Training:** Each service trains a base model (`BasicFCN`).
2. **Federated Rounds:**
   - Local weights are uploaded to the shared pool.
   - For each service, the `top_k` most similar parameters are fetched.
   - The local model is re-initialized or fine-tuned using these shared parameters.
3. **Evaluation:** Detailed metrics including Precision, Recall, F1-Score, and Micro/Macro averages are calculated for each service.

---

## 5. Visualisation (t-SNE)
The framework includes a t-SNE module (`tSNE/`) to project high-dimensional model features into 2D space. This is used to qualitatively verify that the model successfully clusters normal and anomalous system states.
