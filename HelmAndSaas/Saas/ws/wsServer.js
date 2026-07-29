import { WebSocketServer } from "ws";
import jwt from "jsonwebtoken";
import { config } from "../config.js";
import { redisSub } from "../redis/client.js";

// tenant_id -> Set<ws>
const tenantSockets = new Map();

function addSocket(tenantId, ws) {
  if (!tenantSockets.has(tenantId)) {
    tenantSockets.set(tenantId, new Set());
  }
  tenantSockets.get(tenantId).add(ws);
}

function removeSocket(tenantId, ws) {
  const set = tenantSockets.get(tenantId);
  if (!set) return;
  set.delete(ws);
  if (set.size === 0) tenantSockets.delete(tenantId);
}

function extractToken(req) {
  // Preferred: Sec-WebSocket-Protocol: Bearer,<token>  (matches the
  // architecture doc's React `useWebSocket` example).
  const protocolHeader = req.headers["sec-websocket-protocol"];
  if (protocolHeader) {
    const parts = protocolHeader.split(",").map((p) => p.trim());
    if (parts[0] === "Bearer" && parts[1]) return parts[1];
  }
  // Fallback: ?token=<jwt> query param.
  const url = new URL(req.url, "http://localhost");
  return url.searchParams.get("token");
}

export function attachWebSocketServer(httpServer) {
  const wss = new WebSocketServer({ server: httpServer, path: "/ws/events" });

  wss.on("connection", (ws, req) => {
    const token = extractToken(req);
    let tenantId;
    try {
      const payload = jwt.verify(token, config.jwtAccessSecret);
      tenantId = payload.tenant_id;
    } catch {
      ws.close(4401, "Invalid or missing token");
      return;
    }

    addSocket(tenantId, ws);
    ws.on("close", () => removeSocket(tenantId, ws));
    ws.on("error", () => removeSocket(tenantId, ws));
  });

  startRedisBridge();
  return wss;
}

function startRedisBridge() {
  redisSub.psubscribe("events:*");
  redisSub.on("pmessage", (_pattern, channel, message) => {
    const tenantId = channel.slice("events:".length);
    const sockets = tenantSockets.get(tenantId);
    if (!sockets || sockets.size === 0) return;
    for (const ws of sockets) {
      if (ws.readyState === ws.OPEN) ws.send(message);
    }
  });
}
