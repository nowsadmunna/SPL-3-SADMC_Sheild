import bcrypt from "bcrypt";
import crypto from "node:crypto";
import { pool } from "../db/pool.js";
import { redis } from "../redis/client.js";
import { config } from "../config.js";

const CACHE_PREFIX = "apikey:";

export async function generateApiKey(tenantId, name) {
  const shortTenant = tenantId.replace(/-/g, "").slice(0, 8);
  const secret = crypto.randomBytes(32).toString("hex");
  const plaintextKey = `sadmc_sk_live_${shortTenant}_${secret}`;
  const keyPrefix = plaintextKey.slice(0, 24);
  const keyHash = await bcrypt.hash(plaintextKey, config.bcryptCost);

  const result = await pool.query(
    `INSERT INTO api_keys (tenant_id, key_hash, key_prefix, name)
     VALUES ($1, $2, $3, $4)
     RETURNING id, key_prefix, name, is_active, created_at`,
    [tenantId, keyHash, keyPrefix, name || null]
  );

  return { ...result.rows[0], api_key: plaintextKey };
}

export async function listApiKeys(tenantId) {
  const result = await pool.query(
    `SELECT id, key_prefix, name, is_active, created_at, last_used_at
     FROM api_keys WHERE tenant_id = $1 ORDER BY created_at DESC`,
    [tenantId]
  );
  return result.rows;
}

export async function revokeApiKey(tenantId, keyId) {
  const result = await pool.query(
    `UPDATE api_keys SET is_active = FALSE
     WHERE id = $1 AND tenant_id = $2
     RETURNING id`,
    [keyId, tenantId]
  );
  if (result.rows.length === 0) {
    const err = new Error("API key not found");
    err.status = 404;
    throw err;
  }
  // Note: the cache is keyed by sha256(raw key), which we no longer have
  // at revocation time (only the bcrypt hash is stored). A revoked key
  // already cached by resolveApiKey() stays valid until its TTL expires
  // (max API_KEY_CACHE_TTL_SECONDS, matching the doc's 5-min design).
}

/**
 * Resolves a raw API key (as sent by the agent) to its tenant, using a
 * Redis cache (5 min TTL) in front of a bcrypt-compare loop over active
 * keys, matching the architecture doc's §3.2.2 caching design.
 */
export async function resolveApiKey(rawKey) {
  const cacheKey = `${CACHE_PREFIX}${sha256(rawKey)}`;
  const cached = await redis.get(cacheKey);
  if (cached) {
    const parsed = JSON.parse(cached);
    touchLastUsed(parsed.api_key_id).catch(() => {});
    return parsed;
  }

  const { rows } = await pool.query(
    `SELECT id, tenant_id, key_hash FROM api_keys WHERE is_active = TRUE`
  );

  for (const row of rows) {
    if (await bcrypt.compare(rawKey, row.key_hash)) {
      const value = { tenant_id: row.tenant_id, api_key_id: row.id };
      await redis.set(cacheKey, JSON.stringify(value), "EX", config.apiKeyCacheTtlSeconds);
      touchLastUsed(row.id).catch(() => {});
      return value;
    }
  }
  return null;
}

function touchLastUsed(apiKeyId) {
  return pool.query("UPDATE api_keys SET last_used_at = NOW() WHERE id = $1", [apiKeyId]);
}

function sha256(value) {
  return crypto.createHash("sha256").update(value).digest("hex");
}
