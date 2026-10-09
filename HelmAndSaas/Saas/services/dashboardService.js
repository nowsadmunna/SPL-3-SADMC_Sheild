import { pool, withTenant } from "../db/pool.js";
import { NameTakenError } from "./clusterService.js";

export async function listClusters(tenantId) {
  return withTenant(tenantId, async (client) => {
    const result = await client.query(
      `SELECT id, cluster_uuid, name, k8s_version, node_count, agent_version, status, last_heartbeat, created_at,
              EXTRACT(EPOCH FROM (NOW() - last_heartbeat))::int AS heartbeat_age_seconds
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
      `SELECT r.id, r.service_name, r.namespace, r.action_type, r.action_params, r.status, r.executed_at, r.duration_ms, r.error_message,
              a.anomaly_type, a."timestamp" AS detected_at,
              -- seconds from the first detection of this problem (same service and type, up to 3 minutes earlier) to the action
              EXTRACT(EPOCH FROM (r.executed_at - (SELECT MIN(a2."timestamp") FROM anomaly_events a2
                 WHERE a2.cluster_id = r.cluster_id AND a2.service_name = r.service_name AND a2.anomaly_type = a.anomaly_type
                   AND a2."timestamp" BETWEEN r.executed_at - INTERVAL '3 minutes' AND r.executed_at)))::int AS reaction_seconds,
              COUNT(*) OVER() AS total_count
       FROM remediation_actions r
       JOIN clusters c ON c.id = r.cluster_id
       LEFT JOIN anomaly_events a ON a.id = r.anomaly_event_id
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

/** -> {id, name}, null when the cluster is not this tenant's, or throws NameTakenError when another cluster of the tenant has the name */
export async function renameCluster(tenantId, clusterId, name) {
  try {
    const result = await pool.query(
      `UPDATE clusters SET name = $3 WHERE id = $1 AND tenant_id = $2 RETURNING id, name`,
      [clusterId, tenantId, name]
    );
    return result.rows[0] || null;
  } catch (err) {
    if (err?.code === "23505") throw new NameTakenError(name);
    throw err;
  }
}

/**
 * One row per service for the Overview: the newest metrics, how old they are (server clock), and a 15-minute sparkline
 * (one point per minute). age_seconds = null when the service never reported.
 */
export async function overview(tenantId, clusterId) {
  return withTenant(tenantId, async (client) => {
    const latest = await client.query(
      `SELECT DISTINCT ON (m.service_name) m.service_name, m.namespace, m.time,
              EXTRACT(EPOCH FROM (NOW() - m.time))::int AS age_seconds,
              m.cpu_usage_percent, m.memory_usage_mb, m.network_latency_ms, m.request_rate, m.error_rate
       FROM metrics m JOIN clusters c ON c.id = m.cluster_id
       WHERE m.cluster_id = $1 AND c.tenant_id = $2 AND m.time > NOW() - INTERVAL '1 day'
       ORDER BY m.service_name, m.time DESC`,
      [clusterId, tenantId]
    );
    const spark = await client.query(
      `SELECT m.service_name, date_trunc('minute', m.time) AS minute,
              AVG(m.cpu_usage_percent) AS cpu, AVG(m.network_latency_ms) AS latency, AVG(m.request_rate) AS requests
       FROM metrics m JOIN clusters c ON c.id = m.cluster_id
       WHERE m.cluster_id = $1 AND c.tenant_id = $2 AND m.time > NOW() - INTERVAL '15 minutes'
       GROUP BY m.service_name, minute ORDER BY m.service_name, minute`,
      [clusterId, tenantId]
    );
    const byService = new Map();
    for (const r of spark.rows) {
      if (!byService.has(r.service_name)) byService.set(r.service_name, { times: [], cpu: [], latency: [], requests: [] });
      const o = byService.get(r.service_name);
      o.times.push(new Date(r.minute).toISOString()); o.cpu.push(Number(r.cpu)); o.latency.push(Number(r.latency)); o.requests.push(Number(r.requests));
    }
    const services = await client.query(
      `SELECT s.service_name, s.namespace FROM services s JOIN clusters c ON c.id = s.cluster_id
       WHERE s.cluster_id = $1 AND c.tenant_id = $2 ORDER BY s.service_name`,
      [clusterId, tenantId]
    );
    const latestBy = new Map(latest.rows.map((r) => [r.service_name, r]));
    return services.rows.map((s) => {
      const l = latestBy.get(s.service_name);
      return {
        service_name: s.service_name,
        namespace: s.namespace,
        age_seconds: l ? l.age_seconds : null,
        latest: l ? {
          cpu_usage_percent: l.cpu_usage_percent, memory_usage_mb: l.memory_usage_mb, network_latency_ms: l.network_latency_ms,
          request_rate: l.request_rate, error_rate: l.error_rate,
        } : null,
        spark: byService.get(s.service_name) || { times: [], cpu: [], latency: [], requests: [] },
      };
    });
  });
}

/**
 * Anomaly detections grouped into incidents: consecutive detections of the same fault type on the same service, with gaps of
 * at most gapSeconds, are ONE incident. ongoing = the last detection is newer than gapSeconds. Remediation actions taken on the
 * service during the incident (plus two minutes) are attached.
 */
export async function listIncidents(tenantId, clusterId, { limit = 50, offset = 0, service = null, type = null, gapSeconds = 60 } = {}) {
  return withTenant(tenantId, async (client) => {
    const result = await client.query(
      `WITH e AS (
         SELECT a.service_name, a.namespace, a.anomaly_type, a.confidence, a."timestamp",
                CASE WHEN LAG(a."timestamp") OVER w IS NULL OR a."timestamp" - LAG(a."timestamp") OVER w > make_interval(secs => $5) THEN 1 ELSE 0 END AS starts
         FROM anomaly_events a JOIN clusters c ON c.id = a.cluster_id
         WHERE a.cluster_id = $1 AND c.tenant_id = $2 AND a."timestamp" > NOW() - INTERVAL '30 days'
           AND ($6::text IS NULL OR a.service_name = $6) AND ($7::text IS NULL OR a.anomaly_type = $7)
         WINDOW w AS (PARTITION BY a.service_name, a.anomaly_type ORDER BY a."timestamp")
       ), g AS (
         SELECT *, SUM(starts) OVER (PARTITION BY service_name, anomaly_type ORDER BY "timestamp") AS grp FROM e
       ), inc AS (
         SELECT service_name, namespace, anomaly_type, MIN("timestamp") AS started_at, MAX("timestamp") AS last_seen_at,
                COUNT(*)::int AS detections, MAX(confidence) AS max_confidence
         FROM g GROUP BY service_name, namespace, anomaly_type, grp
       )
       SELECT i.*, (NOW() - i.last_seen_at) < make_interval(secs => $5) AS ongoing,
              COUNT(*) OVER()::int AS total_count,
              COALESCE((SELECT json_agg(json_build_object('action_type', r.action_type, 'status', r.status, 'executed_at', r.executed_at) ORDER BY r.executed_at)
                        FROM remediation_actions r
                        WHERE r.cluster_id = $1 AND r.service_name = i.service_name
                          AND r.executed_at BETWEEN i.started_at AND i.last_seen_at + INTERVAL '2 minutes'), '[]'::json) AS actions
       FROM inc i ORDER BY i.last_seen_at DESC LIMIT $3 OFFSET $4`,
      [clusterId, tenantId, limit, offset, gapSeconds, service, type]
    );
    const total = result.rows.length ? result.rows[0].total_count : 0;
    return { incidents: result.rows.map(({ total_count, ...row }) => row), total };
  });
}
