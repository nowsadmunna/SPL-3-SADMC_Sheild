import express from "express";
import cors from "cors";
import { authRouter } from "./routes/auth.routes.js";
import { apiKeysRouter } from "./routes/apiKeys.routes.js";
import { agentRouter } from "./routes/agent.routes.js";
import { metricsRouter } from "./routes/metrics.routes.js";
import { remediationRouter } from "./routes/remediation.routes.js";
import { dashboardRouter } from "./routes/dashboard.routes.js";
import { errorHandler } from "./middleware/errorHandler.js";

export function createApp() {
  const app = express();

  app.use(cors());
  app.use(express.json());

  app.get("/healthz", (req, res) => res.json({ status: "ok" }));

  app.use("/auth", authRouter);
  app.use("/api-keys", apiKeysRouter);
  app.use("/v1/agent", agentRouter);
  app.use("/v1/metrics", metricsRouter);
  app.use("/v1/remediation", remediationRouter);
  app.use("/v1", dashboardRouter);

  app.use(errorHandler);
  return app;
}
