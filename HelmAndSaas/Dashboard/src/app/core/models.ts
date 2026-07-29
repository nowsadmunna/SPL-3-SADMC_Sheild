export type AnomalyType = 'NORMAL' | 'CPU_HOG' | 'MEMORY_LEAK' | 'NETWORK_DELAY';

export interface Tenant {
  id: string;
  organization_name: string;
  email: string;
  subscription_plan?: string;
  created_at?: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  tenant: Tenant;
}

export interface ApiKey {
  id: string;
  key_prefix: string;
  name: string | null;
  is_active: boolean;
  created_at: string;
  last_used_at: string | null;
}

export interface ApiKeyCreated extends ApiKey {
  api_key: string; // plaintext, only present on creation response
}

export interface Cluster {
  id: string;
  cluster_uuid: string;
  k8s_version: string | null;
  node_count: number | null;
  agent_version: string | null;
  status: string;
  last_heartbeat: string | null;
  created_at: string;
}

export interface ServiceSummary {
  id: string;
  service_name: string;
  namespace: string;
  last_seen: string;
}

export interface AnomalyEvent {
  id: string;
  service_name: string;
  namespace: string;
  anomaly_type: AnomalyType;
  confidence: number;
  timestamp: string;
}

export interface RemediationAction {
  id: string;
  service_name: string;
  namespace: string;
  action_type: string;
  status: 'pending' | 'success' | 'failed' | 'skipped';
  executed_at: string | null;
  duration_ms: number | null;
  error_message: string | null;
}

export interface MetricPoint {
  time: string;
  service_name: string;
  namespace: string;
  cpu_usage_percent: number | null;
  memory_usage_mb: number | null;
  network_latency_ms: number | null;
  request_rate: number | null;
  error_rate: number | null;
}

export interface AnomalyDetectedFrame {
  type: 'ANOMALY_DETECTED';
  cluster_uuid: string;
  service_name: string;
  namespace: string;
  anomaly_type: AnomalyType;
  confidence: number;
  timestamp: string;
}

export interface RemediationExecutedFrame {
  type: 'REMEDIATION_EXECUTED';
  cluster_uuid: string;
  service_name: string;
  namespace: string;
  action: string;
  status: string;
  timestamp: string;
}

export type EventFrame = AnomalyDetectedFrame | RemediationExecutedFrame;
