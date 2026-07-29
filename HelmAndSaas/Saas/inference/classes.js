// Mirrors ANOMALY_CLASSES in local_pipeline_test.py — must stay in sync
// with the class-index ordering the model was trained/exported with.
export const ANOMALY_CLASSES = {
  0: "NORMAL",
  1: "CPU_HOG",
  2: "MEMORY_LEAK",
  3: "NETWORK_DELAY",
};

export const FEATURE_VECTOR_LENGTH = 35; // as sent by the agent (metrics_collector.py)
export const MODEL_INPUT_LENGTH = 36; // padded length the MLSTM model expects (ni=36)

// Mirrors HelmAndSaas/Agent/agent/remediation/rules.py DEFAULT_RULES.
// The backend never decides remediation (the agent does) — this table
// is only used to label `action_type` on persisted remediation_actions
// rows for dashboard display.
export const REMEDIATION_RULES = {
  CPU_HOG: { action: "THROTTLE_CPU", cpu_limit: "200m", cooldown_seconds: 300 },
  MEMORY_LEAK: { action: "RESTART_POD", cooldown_seconds: 180 },
  NETWORK_DELAY: {
    action: "SCALE_UP",
    replica_increase: 1,
    max_replicas: 10,
    cooldown_seconds: 600,
  },
  NORMAL: { action: "NO_ACTION" },
};
