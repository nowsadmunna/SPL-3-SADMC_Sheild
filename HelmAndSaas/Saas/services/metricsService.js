import { pool } from "../db/pool.js";

export async function upsertService(clusterId, serviceName, namespace) {
  const result = await pool.query(
    `INSERT INTO services (cluster_id, service_name, namespace, last_seen)
     VALUES ($1, $2, $3, NOW())
     ON CONFLICT (cluster_id, service_name, namespace)
     DO UPDATE SET last_seen = NOW()
     RETURNING id`,
    [clusterId, serviceName, namespace]
  );
  return result.rows[0].id;
}

export async function insertMetricsRow(clusterId, serviceName, namespace, metrics, featureVector) {
  await pool.query(
    `INSERT INTO metrics (
       time, cluster_id, service_name, namespace,
       cpu_usage_percent, memory_usage_mb, network_latency_ms, request_rate, error_rate,
       raw_metrics
     ) VALUES (NOW(), $1, $2, $3, $4, $5, $6, $7, $8, $9)`,
    [
      clusterId,
      serviceName,
      namespace,
      metrics?.cpu_usage_percent ?? null,
      metrics?.memory_usage_mb ?? null,
      metrics?.network_latency_ms ?? null,
      metrics?.request_rate ?? null,
      metrics?.error_rate ?? null,
      JSON.stringify({ metrics, feature_vector: featureVector }),
    ]
  );
}
