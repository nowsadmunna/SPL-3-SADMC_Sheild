import { config } from "../config.js";
import { FEATURE_VECTOR_LENGTH } from "../inference/classes.js";

let onnxModelPromise = null;

async function getOnnxModel() {
  if (!onnxModelPromise) {
    onnxModelPromise = import("../inference/onnxModel.js").then((m) => m.loadModel());
  }
  return onnxModelPromise;
}

/**
 * predict(featureVector) -> { anomaly_type, confidence, is_anomaly }
 *
 * INFERENCE_MODE=stub  -> always NORMAL (used to build/verify the rest of
 *                         the pipeline before the real model is wired in).
 * INFERENCE_MODE=onnx  -> runs the exported SADMC MLSTM model.
 */
export async function predict(featureVector) {
  if (!Array.isArray(featureVector) || featureVector.length !== FEATURE_VECTOR_LENGTH) {
    console.warn(
      `[inference] malformed feature_vector (expected length ${FEATURE_VECTOR_LENGTH}, got ${featureVector?.length}); defaulting to NORMAL`
    );
    return { anomaly_type: "NORMAL", confidence: 0, is_anomaly: false };
  }

  if (config.inferenceMode === "stub") {
    return { anomaly_type: "NORMAL", confidence: 1.0, is_anomaly: false };
  }

  const model = await getOnnxModel();
  return model.predict(featureVector);
}
