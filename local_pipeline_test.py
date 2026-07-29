import sys
import os
import asyncio
import torch
import numpy as np

# Add project subdirectories to sys.path for direct imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "code"))
sys.path.append(os.path.join(PROJECT_ROOT, "HelmAndSaas", "Agent"))

try:
    import network_fed as net
    from agent.metrics_collector import MetricsCollector
except ImportError as e:
    print(f"[WARNING] Import error: {e}. Ensure virtual environment and dependencies are active.")

# Anomaly Class Mapping
ANOMALY_CLASSES = {
    0: "NORMAL",
    1: "CPU_HOG",
    2: "MEMORY_LEAK",
    3: "NETWORK_DELAY"
}

def load_global_model(model_path=None, num_features=36, num_classes=4):
    """Loads the trained PyTorch global model."""
    if model_path is None:
        model_path = os.path.join(PROJECT_ROOT, "SADMC-MT-FF-FL", "saved_models", "sadmc_global_model.pth")
        if not os.path.exists(model_path):
            model_path = os.path.join(PROJECT_ROOT, "saved_models", "sadmc_global_model.pth")

    # Create dummy initial parameters for MLSTM structure initialization
    dummy_params = [
        torch.zeros(128, 1, 7), torch.zeros(128),   # conv1 weight, bias
        torch.ones(128), torch.zeros(128),           # bn1 weight, bias
        torch.zeros(256, 128, 5), torch.zeros(256), # conv2 weight, bias
        torch.ones(256), torch.zeros(256),           # bn2 weight, bias
        torch.zeros(128, 256, 3), torch.zeros(128), # conv3 weight, bias
        torch.ones(128), torch.zeros(128)            # bn3 weight, bias
    ]
    
    model = net.MLSTM(ni=num_features, nf=num_classes, modelFCN=dummy_params)
    
    if os.path.exists(model_path):
        model.load_state_dict(torch.load(model_path, map_location="cpu"))
        print(f"[INFO] Successfully loaded model checkpoint from: {model_path}")
    else:
        print(f"[WARNING] Model checkpoint not found at '{model_path}'. Running with un-initialized weights for pipeline verification.")

    model.eval()
    return model

async def run_direct_pipeline():
    prometheus_url = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
    
    # Target microservices to monitor
    monitored_services = [
        {"name": "carts", "namespace": "sock-shop"},
        {"name": "orders", "namespace": "sock-shop"},
        {"name": "shipping", "namespace": "sock-shop"},
        {"name": "user", "namespace": "sock-shop"},
        {"name": "payment", "namespace": "sock-shop"}
    ]

    print("=" * 65)
    print("      SADMC SHIELD - DIRECT PIPELINE INFERENCE TESTER      ")
    print("=" * 65)
    print(f"[1] Connecting to Prometheus at: {prometheus_url}")
    
    collector = MetricsCollector(prometheus_url=prometheus_url)
    model = load_global_model()

    print(f"[2] Monitoring {len(monitored_services)} microservices. Press Ctrl+C to stop.\n")
    
    tick = 0
    while True:
        tick += 1
        print(f"\n--- [TICK #{tick}] Querying Cluster Telemetry ---")
        try:
            # Step 1: Collect 35 metrics from cluster
            collected_data = await collector.collect(monitored_services)

            if not collected_data:
                print("[WARNING] No metrics returned from Prometheus. Check cluster connection or port-forwarding.")

            for item in collected_data:
                svc_name = item["service_name"]
                raw_vector = item["feature_vector"]  # 35-feature vector from collector

                # Step 2: Pad to 36 features to match model training input dimension (ni=36)
                if len(raw_vector) < 36:
                    raw_vector = list(raw_vector) + [0.0] * (36 - len(raw_vector))

                # Skip inference if Prometheus returned no real data (all-zero vector)
                # All-zero inputs cause NaN in BatchNorm/ExternalAttention computations
                non_zero_count = sum(1 for v in raw_vector if abs(v) > 1e-9)
                if non_zero_count == 0:
                    print(f"  > Service: {svc_name:<12} | Anomaly Status: {'NO_DATA':<14} | Confidence:    N/A  (no Prometheus metrics)")
                    continue

                x_tensor = torch.tensor(raw_vector, dtype=torch.float32).reshape(1, 1, -1)
                x_tensor = torch.nan_to_num(x_tensor)

                # Step 3: Direct Model Inference
                with torch.no_grad():
                    logits = model(x_tensor)
                    logits = torch.nan_to_num(logits)  # Guard against NaN from degenerate inputs
                    probabilities = torch.softmax(logits, dim=1)
                    pred_class = torch.argmax(probabilities, dim=1).item()
                    confidence = probabilities[0][pred_class].item()

                status_label = ANOMALY_CLASSES.get(pred_class, "UNKNOWN")
                print(f"  > Service: {svc_name:<12} | Anomaly Status: {status_label:<14} | Confidence: {confidence*100:5.1f}%")

            await asyncio.sleep(5)  # Run every 5 seconds

        except KeyboardInterrupt:
            print("\n[INFO] Stopped local pipeline test.")
            break
        except Exception as e:
            print(f"[ERROR] Pipeline execution error: {e}")
            await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(run_direct_pipeline())
