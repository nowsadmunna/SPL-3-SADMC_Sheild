import { createServer } from "node:http";
import { createApp } from "./app.js";
import { attachWebSocketServer } from "./ws/wsServer.js";
import { config } from "./config.js";

const app = createApp();
const httpServer = createServer(app);
attachWebSocketServer(httpServer);

httpServer.listen(config.port, () => {
  console.log(`[server] SADMC Shield SaaS backend listening on :${config.port}`);
  console.log(`[server] WebSocket events available at ws://localhost:${config.port}/ws/events`);
});
