import { pool } from "../db/pool.js";
import { redis } from "../redis/client.js";
import { REMEDIATION_RULES } from "../inference/classes.js";

export async function insertAnomalyEvent({
  tenantId,
  clusterId,
  clusterUuid,
  serviceId,
  serviceName,
  namespace,
  anomalyType,
  confidence,
  metricsSnapshot,
}) {
  const result = await pool.query(
    `INSERT INTO anomaly_events (
       cluster_id, service_id, service_name, namespace, anomaly_type, confidence, metrics_snapshot
     ) VALUES ($1, $2, $3, $4, $5, $6, $7)
     RETURNING id, "timestamp"`,
    [clusterId, serviceId, serviceName, namespace, anomalyType, confidence, metricsSnapshot || null]
  );
  const event = result.rows[0];

  await publishEvent(tenantId, {
    type: "ANOMALY_DETECTED",
    cluster_uuid: clusterUuid,
    service_name: serviceName,
    namespace,
    anomaly_type: anomalyType,
    confidence,
    timestamp: event.timestamp,
  });

  return event.id;
}

export async function insertRemediationAction({
  tenantId,
  eventId,
  clusterId,
  clusterUuid,
  serviceName,
  namespace,
  status,
  errorMessage,
}) {
  const anomalyType = await lookupAnomalyType(eventId);
  const rule = REMEDIATION_RULES[anomalyType] || REMEDIATION_RULES.NORMAL;

  const result = await pool.query(
    `INSERT INTO remediation_actions (
       anomaly_event_id, cluster_id, service_name, namespace,
       action_type, action_params, status, executed_at, error_message
     ) VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8)
     RETURNING id, action_type, status, executed_at`,
    [
      eventId || null,
      clusterId,
      serviceName,
      namespace,
      rule.action,
      JSON.stringify(rule),
      status,
      errorMessage || null,
    ]
  );
  const action = result.rows[0];

  await publishEvent(tenantId, {
    type: "REMEDIATION_EXECUTED",
    cluster_uuid: clusterUuid,
    service_name: serviceName,
    namespace,
    action: action.action_type,
    status: action.status,
    timestamp: action.executed_at,
  });

  return action.id;
}

async function lookupAnomalyType(eventId) {
  if (!eventId) return "NORMAL";
  const result = await pool.query(`SELECT anomaly_type FROM anomaly_events WHERE id = $1`, [
    eventId,
  ]);
  return result.rows[0]?.anomaly_type || "NORMAL";
}

async function publishEvent(tenantId, payload) {
  await redis.publish(`events:${tenantId}`, JSON.stringify(payload));
}
