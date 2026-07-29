# Paper-to-Code Traceability Matrix

This document maps the concepts, equations, and algorithms from the **AD.pdf** research paper to the corresponding files and lines in the codebase.

## 1. Algorithms

| Paper Element | Description | Code Implementation (File:Line) |
| :--- | :--- | :--- |
| **Algorithm 1** | SADMC-MT-FF-FL Main Loop | [sadmc-mt-ff-fl.py:L351-430](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L351-430) |
| **Algorithm 2** | LGF-PKT (Knowledge Transfer) | [network_fed.py:L586-614](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L586-614) |
| **Local Train** | Initial local model training | [sadmc-mt-ff-fl.py:L37-176](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L37-176) (`train_and_test`) |
| **Transfer Train** | Refinement using global weights | [sadmc-mt-ff-fl.py:L179-329](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L179-329) (`train_and_test_load`) |

## 2. Mathematical Formulas

| Concept | Paper Equation | Code Implementation (File) |
| :--- | :--- | :--- |
| **Cross Entropy Loss** | Equation (1) | [sadmc-mt-ff-fl.py:L53](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L53) |
| **External Attention** | Equation (6) | [network_fed.py:L118-131](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L118-131) |
| **Euclidean Distance** | Equation (16) | [network_fed.py:L277](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L277) (`np.linalg.norm`) |
| **Cosine Similarity** | Equation (17) | [network_fed.py:L278](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L278) |
| **Weight Distance ($d_{i,j}$)** | Equation (18) | [network_fed.py:L279](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L279) (`euclidean_dist / cosine_sim`) |

## 3. Model Architecture (EA-MRS)

| Component | Paper Section | Component in Code |
| :--- | :--- | :--- |
| **Local Model** | Section 3.3.1 | [network_fed.py:L14](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L14) (`BasicFCN`) |
| **Transfer Model** | Section 3.3.2 | [network_fed.py:L669](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L669) (`MLSTM`) |
| **External Attention** | Figure 4 | [network_fed.py:L118](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L118) (`ExternalAttention`) |
| **Residual branch** | Figure 4 | [network_fed.py:L713 & L726](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L713) (`conv4` and `x1 + x2`) |
| **Similarity Selection** | Figure 4 (c) | [network_fed.py:L586](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L586) (`StoreEW`) |

## 4. Dataset & Hyperparameters

| Component | Paper Specification | Code Constant / Value |
| :--- | :--- | :--- |
| **Dataset** | Sock-Shop | [sadmc-mt-ff-fl.py:L331](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L331) |
| **Fed Iterations** | 4 | [sadmc-mt-ff-fl.py:L335](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L335) (`Fed_iteration = 4`) |
| **Learning Rate** | 0.001 | [sadmc-mt-ff-fl.py:L39](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L39) (`lr = 0.001`) |
| **Batch Size** | 128 | [sadmc-mt-ff-fl.py:L366](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/sadmc-mt-ff-fl.py#L366) (`batch_size=128`) |
| **EA Attenuation** | 64 | [network_fed.py:L119](file:///home/mdnowsadhossenmunna/SPL-3/SADMC-MT-FF-FL/code/network_fed.py#L119) (`S=64`) |
