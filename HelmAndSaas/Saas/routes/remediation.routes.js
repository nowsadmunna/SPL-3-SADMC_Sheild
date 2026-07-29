import { Router } from "express";
import { apiKeyAuth } from "../middleware/apiKeyAuth.js";
import { asyncRoute } from "../middleware/errorHandler.js";
import { reportRemediation } from "../services/remediationService.js";

export const remediationRouter = Router();
remediationRouter.use(apiKeyAuth);

remediationRouter.post(
  "/report",
  asyncRoute(async (req, res) => {
    const { cluster_uuid, event_id, status, error_message } = req.body || {};
    if (!cluster_uuid || !status) {
      return res.status(400).json({ error: "cluster_uuid and status are required" });
    }
    await reportRemediation(req.tenantId, { cluster_uuid, event_id, status, error_message });
    res.status(204).send();
  })
);
