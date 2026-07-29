import jwt from "jsonwebtoken";
import { config } from "../config.js";

export function jwtAuth(req, res, next) {
  const header = req.headers.authorization || "";
  const [scheme, token] = header.split(" ");

  if (scheme !== "Bearer" || !token) {
    return res.status(401).json({ error: "Missing or malformed Authorization header" });
  }

  try {
    const payload = jwt.verify(token, config.jwtAccessSecret);
    req.tenantId = payload.tenant_id;
    next();
  } catch {
    return res.status(401).json({ error: "Invalid or expired access token" });
  }
}
