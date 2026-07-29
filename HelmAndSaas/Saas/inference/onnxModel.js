import * as ort from "onnxruntime-node";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { config } from "../config.js";
import { ANOMALY_CLASSES, FEATURE_VECTOR_LENGTH, MODEL_INPUT_LENGTH } from "./classes.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

let sessionPromise = null;

function resolveModelPath() {
  return path.isAbsolute(config.onnxModelPath)
    ? config.onnxModelPath
    : path.join(path.dirname(__dirname), config.onnxModelPath.replace(/^\.\//, ""));
}

async function getSession() {
  if (!sessionPromise) {
    const modelPath = resolveModelPath();
    console.log(`[onnxModel] loading ${modelPath}`);
    sessionPromise = ort.InferenceSession.create(modelPath);
  }
  return sessionPromise;
}

/** Pads/guards a raw 35-length feature vector and returns {logits, probs}. */
export async function runRaw(featureVector) {
  if (featureVector.length !== FEATURE_VECTOR_LENGTH) {
    throw new Error(
      `runRaw expects a ${FEATURE_VECTOR_LENGTH}-length feature vector, got ${featureVector.length}`
    );
  }

  const padded = new Float32Array(MODEL_INPUT_LENGTH);
  for (let i = 0; i < featureVector.length; i++) {
    const v = featureVector[i];
    padded[i] = Number.isFinite(v) ? v : 0; // nan_to_num equivalent
  }
  // index [35] stays 0 — the single padding element.

  const session = await getSession();
  const tensor = new ort.Tensor("float32", padded, [1, 1, MODEL_INPUT_LENGTH]);
  const output = await session.run({ input: tensor });
  const logitsTensor = output[Object.keys(output)[0]];
  const logits = Array.from(logitsTensor.data).map((v) => (Number.isFinite(v) ? v : 0));

  const probs = softmax(logits);
  return { logits, probs };
}

function softmax(logits) {
  const max = Math.max(...logits);
  const exps = logits.map((v) => Math.exp(v - max));
  const sum = exps.reduce((a, b) => a + b, 0);
  return exps.map((v) => v / sum);
}

export function loadModel() {
  // Triggers session creation eagerly (used by inferenceService's singleton).
  getSession();
  return { predict };
}

export async function predict(featureVector) {
  const { probs } = await runRaw(featureVector);
  let predClass = 0;
  for (let i = 1; i < probs.length; i++) {
    if (probs[i] > probs[predClass]) predClass = i;
  }
  return {
    anomaly_type: ANOMALY_CLASSES[predClass],
    confidence: probs[predClass],
    is_anomaly: predClass !== 0,
  };
}
