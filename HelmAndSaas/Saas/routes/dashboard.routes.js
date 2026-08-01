import { Router } from "express";
import { jwtAuth } from "../middleware/jwtAuth.js";
import { asyncRoute } from "../middleware/errorHandler.js";
import * as dashboardService from "../services/dashboardService.js";

export const dashboardRouter = Router();
dashboardRouter.use(jwtAuth);

async function requireOwnedCluster(req, res, next) {
  const owned = await dashboardService.clusterBelongsToTenant(req.tenantId, req.params.id);
  if (!owned) {
    return res.status(404).json({ error: "Cluster not found" });
  }
  next();
}

dashboardRouter.get(
  "/clusters",
  asyncRoute(async (req, res) => {
    const clusters = await dashboardService.listClusters(req.tenantId);
    res.json({ clusters });
  })
);

dashboardRouter.get(
  "/clusters/:id/services",
  asyncRoute(requireOwnedCluster),
  asyncRoute(async (req, res) => {
    const services = await dashboardService.listServices(req.tenantId, req.params.id);
    res.json({ services });
  })
);

dashboardRouter.get(
  "/clusters/:id/anomalies",
  asyncRoute(requireOwnedCluster),
  asyncRoute(async (req, res) => {
    const { limit, offset } = req.query;
    const anomalies = await dashboardService.listAnomalies(req.tenantId, req.params.id, {
      limit: limit ? parseInt(limit, 10) : undefined,
      offset: offset ? parseInt(offset, 10) : undefined,
    });
    res.json({ anomalies });
  })
);

dashboardRouter.get(
  "/clusters/:id/remediations",
  asyncRoute(requireOwnedCluster),
  asyncRoute(async (req, res) => {
    const { limit, offset } = req.query;
    const { remediations, total } = await dashboardService.listRemediations(req.tenantId, req.params.id, {
      limit: limit ? parseInt(limit, 10) : undefined,
      offset: offset ? parseInt(offset, 10) : undefined,
    });
    res.json({ remediations, total });
  })
);

dashboardRouter.get(
  "/clusters/:id/metrics",
  asyncRoute(requireOwnedCluster),
  asyncRoute(async (req, res) => {
    const { start, end, service_name } = req.query;
    const metrics = await dashboardService.queryMetrics(req.tenantId, req.params.id, {
      start,
      end,
      serviceName: service_name,
    });
    res.json({ metrics });
  })
);
