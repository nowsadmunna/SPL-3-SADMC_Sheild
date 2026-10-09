import { pool } from "../db/pool.js";

/**
 * Registers (or re-confirms) a cluster for the given tenant. The agent
 * sends a self-generated cluster_id; we try to use it verbatim as the
 * stored cluster_uuid, and only mint a fresh one on a collision (the
 * agent overwrites its cached uuid with whatever we return either way —
 * see HelmAndSaas/Agent/agent/inference_client.py::register()).
 */
/** a cluster name from an agent: trimmed, at most 100 characters, empty -> null */
export function cleanName(name) {
  const n = typeof name === "string" ? name.trim().slice(0, 100) : "";
  return n || null;
}

export class NameTakenError extends Error {
  constructor(name) {
    super(`The cluster name '${name}' is already used by another cluster of this account. Choose a different one.`);
    this.name = "NameTakenError";
    this.status = 409;
  }
}
const isUniqueViolation = (err) => err?.code === "23505";

/**
 * name = what the agent asked for (helm sadmc.clusterName); it must be unique within the tenant (case-insensitive), otherwise
 * NameTakenError. fallbackName = the API key's name, used only when a NEW cluster is created without an explicit name; since
 * nobody chose it, a clash is resolved by appending -2, -3, ... instead of failing. A re-registering agent that sends no name
 * keeps the name already stored (it may have been renamed in the dashboard).
 */
export async function registerCluster(tenantId, clusterId, { name = null, fallbackName = null } = {}) {
  name = cleanName(name);
  const existing = await pool.query(
    `SELECT id, tenant_id, cluster_uuid FROM clusters WHERE cluster_uuid = $1`,
    [clusterId]
  );

  if (existing.rows.length > 0) {
    const cluster = existing.rows[0];
    if (cluster.tenant_id === tenantId) {
      try {
        await pool.query(
          `UPDATE clusters SET status = 'active', last_heartbeat = NOW(), name = COALESCE($2, name) WHERE id = $1`,
          [cluster.id, name]
        );
      } catch (err) {
        if (isUniqueViolation(err)) throw new NameTakenError(name);
        throw err;
      }
      return cluster.cluster_uuid;
    }
    // Global UNIQUE collision across tenants (astronomically unlikely
    // since the agent generates a uuid4) — mint a fresh id instead.
    return insertClusterNamed(tenantId, cryptoRandomUuid(), name, fallbackName);
  }

  return insertClusterNamed(tenantId, clusterId, name, fallbackName);
}

async function insertClusterNamed(tenantId, clusterUuid, name, fallbackName) {
  if (name) {
    try {
      return await insertCluster(tenantId, clusterUuid, name);
    } catch (err) {
      if (isUniqueViolation(err) && (await nameInUse(tenantId, name))) throw new NameTakenError(name);
      throw err;
    }
  }
  const base = cleanName(fallbackName);
  if (!base) return insertCluster(tenantId, clusterUuid, null);
  for (let n = 1; n <= 20; n++) {
    const candidate = n === 1 ? base : `${base.slice(0, 95)}-${n}`;
    try {
      return await insertCluster(tenantId, clusterUuid, candidate);
    } catch (err) {
      if (!(isUniqueViolation(err) && (await nameInUse(tenantId, candidate)))) throw err;
    }
  }
  return insertCluster(tenantId, clusterUuid, null);
}

async function nameInUse(tenantId, name) {
  const r = await pool.query(`SELECT 1 FROM clusters WHERE tenant_id = $1 AND lower(name) = lower($2)`, [tenantId, name]);
  return r.rows.length > 0;
}

async function insertCluster(tenantId, clusterUuid, name = null) {
  const result = await pool.query(
    `INSERT INTO clusters (tenant_id, cluster_uuid, name, status, last_heartbeat)
     VALUES ($1, $2, $3, 'active', NOW())
     RETURNING cluster_uuid`,
    [tenantId, clusterUuid, name]
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
