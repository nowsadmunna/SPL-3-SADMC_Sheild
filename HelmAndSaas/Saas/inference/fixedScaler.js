// Fixed global scaler: ONE MinMax scaler, fitted once on the training data of all services and
// frozen. Training and serving use the very same numbers, so there is no calibration phase and a
// verdict is available from the first sample.
//
//   z = clip(x * scale + min, 0, 1);  columns that never varied in training (constant) are pinned to 0
//
// Keep in lock-step with the scaler used to train the deployed model (model/v3/global_scaler.json, produced by
// SADMC-MT-FF-FL/own_dataset/scripts/v3/export_mul_class_v3.py) and with scale_fixed() in verify_parity.py.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
import { FEATURE_SET, FEATURE_SETS } from "./featureSets.js";

const scalers = new Map();
/** SCALER_PATH overrides the scaler of the default set only (experiments). */
export function loadScaler(setName = FEATURE_SET, file) {
  if (!scalers.has(setName)) {
    const set = FEATURE_SETS[setName];
    const f = file || (setName === FEATURE_SET && process.env.SCALER_PATH) || path.join(__dirname, set.scaler);
    const d = JSON.parse(readFileSync(f, "utf-8"));
    for (const k of ["scale", "min", "constant"]) {
      if (d[k]?.length !== set.length) throw new Error(`global scaler (${setName}): '${k}' must have ${set.length} entries`);
    }
    scalers.set(setName, d);
  }
  return scalers.get(setName);
}

/** raw vector of the given feature set -> Float32Array in [0, 1] */
export function fixedNormalise(vec, setName = FEATURE_SET) {
  const s = loadScaler(setName);
  const n = FEATURE_SETS[setName].length;
  const out = new Float32Array(n);
  for (let j = 0; j < n; j++) {
    if (s.constant[j]) continue;
    const v = Number.isFinite(vec[j]) ? vec[j] : 0;
    out[j] = Math.min(1, Math.max(0, v * s.scale[j] + s.min[j]));
  }
  return out;
}
