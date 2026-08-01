import { pool, withTenant } from "../db/pool.js";

export async function listClusters(tenantId) {
  return withTenant(tenantId, async (client) => {
    const result = await client.query(
      `SELECT id, cluster_uuid, k8s_version, node_count, agent_version, status, last_heartbeat, created_at
       FROM clusters WHERE tenant_id = $1 ORDER BY created_at DESC`,
      [tenantId]
    );
    return result.rows;
  });
}

export async function listServices(tenantId, clusterId) {
  return withTenant(tenantId, async (client) => {
    const result = await client.query(
      `SELECT s.id, s.service_name, s.namespace, s.last_seen
       FROM services s
       JOIN clusters c ON c.id = s.cluster_id
       WHERE s.cluster_id = $1 AND c.tenant_id = $2
       ORDER BY s.service_name`,
      [clusterId, tenantId]
    );
    return result.rows;
  });
}

export async function listAnomalies(tenantId, clusterId, { limit = 50, offset = 0 } = {}) {
  return withTenant(tenantId, async (client) => {
    const result = await client.query(
      `SELECT a.id, a.service_name, a.namespace, a.anomaly_type, a.confidence, a."timestamp"
       FROM anomaly_events a
       JOIN clusters c ON c.id = a.cluster_id
       WHERE a.cluster_id = $1 AND c.tenant_id = $2
       ORDER BY a."timestamp" DESC
       LIMIT $3 OFFSET $4`,
      [clusterId, tenantId, limit, offset]
    );
    return result.rows;
  });
}

export async function listRemediations(tenantId, clusterId, { limit = 50, offset = 0 } = {}) {
  return withTenant(tenantId, async (client) => {
    const result = await client.query(
      `SELECT r.id, r.service_name, r.namespace, r.action_type, r.status, r.executed_at, r.duration_ms, r.error_message,
              COUNT(*) OVER() AS total_count
       FROM remediation_actions r
       JOIN clusters c ON c.id = r.cluster_id
       WHERE r.cluster_id = $1 AND c.tenant_id = $2
       ORDER BY r.executed_at DESC NULLS LAST
       LIMIT $3 OFFSET $4`,
      [clusterId, tenantId, limit, offset]
    );
    const total = result.rows.length > 0 ? Number(result.rows[0].total_count) : 0;
    const remediations = result.rows.map(({ total_count, ...row }) => row);
    return { remediations, total };
  });
}

export async function queryMetrics(tenantId, clusterId, { start, end, serviceName }) {
  return withTenant(tenantId, async (client) => {
    const conditions = ["m.cluster_id = $1", "c.tenant_id = $2"];
    const params = [clusterId, tenantId];

    if (start) {
      params.push(start);
      conditions.push(`m.time >= $${params.length}`);
    }
    if (end) {
      params.push(end);
      conditions.push(`m.time <= $${params.length}`);
    }
    if (serviceName) {
      params.push(serviceName);
      conditions.push(`m.service_name = $${params.length}`);
    }

    const result = await client.query(
      `SELECT m.time, m.service_name, m.namespace,
              m.cpu_usage_percent, m.memory_usage_mb, m.network_latency_ms, m.request_rate, m.error_rate
       FROM metrics m
       JOIN clusters c ON c.id = m.cluster_id
       WHERE ${conditions.join(" AND ")}
       ORDER BY m.time ASC`,
      params
    );
    return result.rows;
  });
}

/** Used by routes to verify a :id path param actually belongs to the caller's tenant. */
export async function clusterBelongsToTenant(tenantId, clusterId) {
  const result = await pool.query(
    `SELECT 1 FROM clusters WHERE id = $1 AND tenant_id = $2`,
    [clusterId, tenantId]
  );
  return result.rows.length > 0;
}
