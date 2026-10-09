import { config } from "../config.js";
import { FEATURE_SETS, resolveSet } from "../inference/featureSets.js";
import { fixedNormalise } from "../inference/fixedScaler.js";

const onnxModels = new Map();

async function getOnnxModel(setName) {
  if (!onnxModels.has(setName)) {
    onnxModels.set(setName, import("../inference/onnxModel.js").then((m) => m.loadModel(setName)));
  }
  return onnxModels.get(setName);
}

/**
 * predict(featureVector, featureSet) -> { anomaly_type, confidence, is_anomaly }
 *
 * INFERENCE_MODE=stub  -> always NORMAL (used to build/verify the rest of the pipeline without the model).
 * INFERENCE_MODE=onnx  -> scales the vector with the fixed global scaler and runs the exported SADMC model.
 */
export async function predict(featureVector, featureSet) {
  const setName = resolveSet(featureSet);
  if (!setName) {
    console.warn(`[inference] unknown feature_set '${featureSet}'; defaulting to NORMAL`);
    return { anomaly_type: "NORMAL", confidence: 0, is_anomaly: false };
  }
  const expected = FEATURE_SETS[setName].length;
  if (!Array.isArray(featureVector) || featureVector.length !== expected) {
    console.warn(
      `[inference] malformed feature_vector for feature_set ${setName} (expected length ${expected}, got ${featureVector?.length}); defaulting to NORMAL`
    );
    return { anomaly_type: "NORMAL", confidence: 0, is_anomaly: false };
  }

  if (config.inferenceMode === "stub") {
    return { anomaly_type: "NORMAL", confidence: 1.0, is_anomaly: false };
  }

  return (await getOnnxModel(setName)).predict(fixedNormalise(featureVector, setName));
}
