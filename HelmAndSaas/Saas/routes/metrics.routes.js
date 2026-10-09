import { Router } from "express";
import { apiKeyAuth } from "../middleware/apiKeyAuth.js";
import { asyncRoute } from "../middleware/errorHandler.js";
import { findClusterByUuid, recordHeartbeat } from "../services/clusterService.js";
import { upsertService, insertMetricsRow } from "../services/metricsService.js";
import { predict } from "../services/inferenceService.js";
import { insertAnomalyEvent } from "../services/eventService.js";

export const metricsRouter = Router();
metricsRouter.use(apiKeyAuth);

metricsRouter.post(
  "/ingest",
  asyncRoute(async (req, res) => {
    const { cluster_uuid, services } = req.body || {};
    if (!cluster_uuid || !Array.isArray(services)) {
      return res.status(400).json({ error: "cluster_uuid and services[] are required" });
    }

    const cluster = await findClusterByUuid(req.tenantId, cluster_uuid);
    if (!cluster) {
      // Soft-fail: don't crash-loop the agent on an unknown/stale cluster_uuid.
      console.warn(`[ingest] unknown cluster_uuid=${cluster_uuid} for tenant=${req.tenantId}`);
      return res.json({ results: [] });
    }
    recordHeartbeat(req.tenantId, cluster_uuid).catch(() => {});

    const results = [];
    for (const svc of services) {
      const { service_name, namespace, metrics, feature_vector } = svc;
      if (!service_name || !namespace) continue;

      const serviceId = await upsertService(cluster.id, service_name, namespace);
      await insertMetricsRow(cluster.id, service_name, namespace, metrics, feature_vector);

      const inference = await predict(feature_vector, req.body?.feature_set);

      let eventId = null;
      if (inference.is_anomaly) {
        eventId = await insertAnomalyEvent({
          tenantId: req.tenantId,
          clusterId: cluster.id,
          clusterUuid: cluster.cluster_uuid,
          serviceId,
          serviceName: service_name,
          namespace,
          anomalyType: inference.anomaly_type,
          confidence: inference.confidence,
          metricsSnapshot: metrics,
        });
      }

      results.push({
        service_name,
        namespace,
        anomaly_type: inference.anomaly_type,
        confidence: inference.confidence,
        is_anomaly: inference.is_anomaly,
        event_id: eventId,
      });
    }

    res.json({ results });
  })
);
