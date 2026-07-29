import bcrypt from "bcrypt";
import crypto from "node:crypto";
import jwt from "jsonwebtoken";
import { pool } from "../db/pool.js";
import { config } from "../config.js";

export async function registerTenant({ organizationName, email, password }) {
  const existing = await pool.query("SELECT id FROM tenants WHERE email = $1", [email]);
  if (existing.rows.length > 0) {
    const err = new Error("Email already registered");
    err.status = 409;
    throw err;
  }

  const passwordHash = await bcrypt.hash(password, config.bcryptCost);
  const result = await pool.query(
    `INSERT INTO tenants (organization_name, email, password_hash)
     VALUES ($1, $2, $3)
     RETURNING id, organization_name, email, subscription_plan, created_at`,
    [organizationName, email, passwordHash]
  );
  return result.rows[0];
}

export async function login({ email, password }) {
  const result = await pool.query("SELECT * FROM tenants WHERE email = $1", [email]);
  const tenant = result.rows[0];
  if (!tenant) {
    const err = new Error("Invalid credentials");
    err.status = 401;
    throw err;
  }

  const valid = await bcrypt.compare(password, tenant.password_hash);
  if (!valid) {
    const err = new Error("Invalid credentials");
    err.status = 401;
    throw err;
  }

  const accessToken = signAccessToken(tenant.id);
  const refreshToken = await issueRefreshToken(tenant.id);

  return {
    access_token: accessToken,
    refresh_token: refreshToken,
    tenant: {
      id: tenant.id,
      organization_name: tenant.organization_name,
      email: tenant.email,
    },
  };
}

export function signAccessToken(tenantId) {
  return jwt.sign({ tenant_id: tenantId }, config.jwtAccessSecret, {
    expiresIn: config.accessTokenExpiry,
  });
}

async function issueRefreshToken(tenantId) {
  const rawToken = crypto.randomBytes(32).toString("hex");
  const tokenHash = await bcrypt.hash(rawToken, config.bcryptCost);
  const expiresAt = new Date(Date.now() + config.refreshTokenExpiryDays * 24 * 60 * 60 * 1000);

  await pool.query(
    `INSERT INTO refresh_tokens (tenant_id, token_hash, expires_at)
     VALUES ($1, $2, $3)`,
    [tenantId, tokenHash, expiresAt]
  );

  // Encode tenantId + rawToken together so refresh/logout can find the
  // candidate rows without a plaintext-indexable column (bcrypt hashes
  // can't be looked up by equality).
  return Buffer.from(`${tenantId}:${rawToken}`).toString("base64url");
}

async function findRefreshTokenRow(refreshToken) {
  let tenantId, rawToken;
  try {
    const decoded = Buffer.from(refreshToken, "base64url").toString("utf-8");
    [tenantId, rawToken] = decoded.split(":");
  } catch {
    return null;
  }
  if (!tenantId || !rawToken) return null;

  const result = await pool.query(
    `SELECT * FROM refresh_tokens
     WHERE tenant_id = $1 AND revoked_at IS NULL AND expires_at > NOW()`,
    [tenantId]
  );

  for (const row of result.rows) {
    if (await bcrypt.compare(rawToken, row.token_hash)) {
      return row;
    }
  }
  return null;
}

export async function refreshAccessToken(refreshToken) {
  const row = await findRefreshTokenRow(refreshToken);
  if (!row) {
    const err = new Error("Invalid or expired refresh token");
    err.status = 401;
    throw err;
  }
  return { access_token: signAccessToken(row.tenant_id) };
}

export async function logout(refreshToken) {
  const row = await findRefreshTokenRow(refreshToken);
  if (!row) return;
  await pool.query("UPDATE refresh_tokens SET revoked_at = NOW() WHERE id = $1", [row.id]);
}
