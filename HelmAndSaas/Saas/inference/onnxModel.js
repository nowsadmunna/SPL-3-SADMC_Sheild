import * as ort from "onnxruntime-node";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { config } from "../config.js";
import { ANOMALY_CLASSES } from "./classes.js";
import { FEATURE_SET, FEATURE_SETS } from "./featureSets.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// one ONNX session per feature set, created on first use
const sessions = new Map();

function resolveModelPath(setName) {
  // ONNX_MODEL_PATH (config.onnxModelPath) only overrides the default set
  const p = setName === FEATURE_SET ? config.onnxModelPath : FEATURE_SETS[setName].model;
  return path.isAbsolute(p) ? p : path.join(path.dirname(__dirname), p.replace(/^\.\//, ""));
}

async function getSession(setName) {
  if (!sessions.has(setName)) {
    const modelPath = resolveModelPath(setName);
    console.log(`[onnxModel] loading ${setName} model ${modelPath}`);
    sessions.set(setName, ort.InferenceSession.create(modelPath));
  }
  return sessions.get(setName);
}

/**
 * Runs the model of a feature set on an ALREADY SCALED input (see fixedScaler.js) and returns {logits, probs}.
 */
export async function runRaw(input, setName = FEATURE_SET) {
  const n = FEATURE_SETS[setName].length;
  if (input.length !== n) {
    throw new Error(`runRaw (${setName}) expects a ${n}-length input, got ${input.length}`);
  }
  const padded = Float32Array.from(input, (v) => (Number.isFinite(v) ? v : 0));

  const session = await getSession(setName);
  const tensor = new ort.Tensor("float32", padded, [1, 1, n]);
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

export function loadModel(setName = FEATURE_SET) {
  // Triggers session creation eagerly (used by inferenceService's singletons).
  getSession(setName);
  return { predict: (input) => predict(input, setName) };
}

export async function predict(input, setName = FEATURE_SET) {
  const { probs } = await runRaw(input, setName);
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
