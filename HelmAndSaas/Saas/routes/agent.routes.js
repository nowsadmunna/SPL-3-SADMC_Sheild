import { Router } from "express";
import { apiKeyAuth } from "../middleware/apiKeyAuth.js";
import { asyncRoute } from "../middleware/errorHandler.js";
import * as clusterService from "../services/clusterService.js";

export const agentRouter = Router();
agentRouter.use(apiKeyAuth);

agentRouter.post(
  "/register",
  asyncRoute(async (req, res) => {
    const { cluster_id } = req.body || {};
    if (!cluster_id) {
      return res.status(400).json({ error: "cluster_id is required" });
    }
    const clusterUuid = await clusterService.registerCluster(req.tenantId, cluster_id);
    res.json({ cluster_uuid: clusterUuid });
  })
);

agentRouter.post(
  "/heartbeat",
  asyncRoute(async (req, res) => {
    const { cluster_uuid } = req.body || {};
    if (!cluster_uuid) {
      return res.status(400).json({ error: "cluster_uuid is required" });
    }
    const ok = await clusterService.recordHeartbeat(req.tenantId, cluster_uuid);
    if (!ok) {
      return res.status(404).json({ error: "Unknown cluster_uuid for this tenant" });
    }
    res.json({ status: "ok" });
  })
);
