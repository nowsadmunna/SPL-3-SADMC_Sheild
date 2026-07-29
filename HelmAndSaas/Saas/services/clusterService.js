import { pool } from "../db/pool.js";

/**
 * Registers (or re-confirms) a cluster for the given tenant. The agent
 * sends a self-generated cluster_id; we try to use it verbatim as the
 * stored cluster_uuid, and only mint a fresh one on a collision (the
 * agent overwrites its cached uuid with whatever we return either way —
 * see HelmAndSaas/Agent/agent/inference_client.py::register()).
 */
export async function registerCluster(tenantId, clusterId) {
  const existing = await pool.query(
    `SELECT id, tenant_id, cluster_uuid FROM clusters WHERE cluster_uuid = $1`,
    [clusterId]
  );

  if (existing.rows.length > 0) {
    const cluster = existing.rows[0];
    if (cluster.tenant_id === tenantId) {
      await pool.query(
        `UPDATE clusters SET status = 'active', last_heartbeat = NOW() WHERE id = $1`,
        [cluster.id]
      );
      return cluster.cluster_uuid;
    }
    // Global UNIQUE collision across tenants (astronomically unlikely
    // since the agent generates a uuid4) — mint a fresh id instead.
    return insertCluster(tenantId, cryptoRandomUuid());
  }

  return insertCluster(tenantId, clusterId);
}

async function insertCluster(tenantId, clusterUuid) {
  const result = await pool.query(
    `INSERT INTO clusters (tenant_id, cluster_uuid, status, last_heartbeat)
     VALUES ($1, $2, 'active', NOW())
     RETURNING cluster_uuid`,
    [tenantId, clusterUuid]
  );
  return result.rows[0].cluster_uuid;
}

function cryptoRandomUuid() {
  return globalThis.crypto.randomUUID();
}

export async function findClusterByUuid(tenantId, clusterUuid) {
  const result = await pool.query(
    `SELECT id, tenant_id, cluster_uuid FROM clusters WHERE cluster_uuid = $1 AND tenant_id = $2`,
    [clusterUuid, tenantId]
  );
  return result.rows[0] || null;
}

export async function recordHeartbeat(tenantId, clusterUuid) {
  const result = await pool.query(
    `UPDATE clusters SET last_heartbeat = NOW(), status = 'active'
     WHERE cluster_uuid = $1 AND tenant_id = $2
     RETURNING id`,
    [clusterUuid, tenantId]
  );
  return result.rows.length > 0;
}
