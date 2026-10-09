// The feature vector the deployed model expects: 33 features derived from cAdvisor, the apps' /metrics, the latency probe and the
// Kubernetes API (SADMC-MT-FF-FL/own_dataset/scripts/v3/feature_defs.py is the definition; the agent has a generated copy).
// The registry is keyed by name so that a second feature set can be added later without touching the callers: an agent sends
// `feature_set` in every ingest request and the backend applies the model and scaler of that set.
export const FEATURE_SETS = {
  v3: { length: 33, model: "./inference/model/v3/sadmc_model.onnx", scaler: "model/v3/global_scaler.json" },
};
// FEATURE_SET is only the DEFAULT, used for an agent that does not say which vector it sends.
export const FEATURE_SET = process.env.FEATURE_SET || "v3";
if (!FEATURE_SETS[FEATURE_SET]) throw new Error(`FEATURE_SET must be one of ${Object.keys(FEATURE_SETS).join(", ")}, got '${FEATURE_SET}'`);
export const ACTIVE = FEATURE_SETS[FEATURE_SET];

/** name sent by the agent (or undefined) -> a known set name; unknown names are rejected by the caller. */
export function resolveSet(name) {
  if (name === undefined || name === null || name === "") return FEATURE_SET;
  return FEATURE_SETS[name] ? name : null;
}
