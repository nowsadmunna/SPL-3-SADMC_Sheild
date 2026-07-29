import { resolveApiKey } from "../services/apiKeyService.js";

export async function apiKeyAuth(req, res, next) {
  const rawKey = req.headers["x-api-key"];
  if (!rawKey) {
    return res.status(401).json({ error: "Missing X-API-Key header" });
  }

  try {
    const resolved = await resolveApiKey(rawKey);
    if (!resolved) {
      return res.status(401).json({ error: "Invalid or revoked API key" });
    }
    req.tenantId = resolved.tenant_id;
    req.apiKeyId = resolved.api_key_id;
    next();
  } catch (err) {
    next(err);
  }
}
