import { pool } from "../db/pool.js";
import { findClusterByUuid } from "./clusterService.js";
import { insertRemediationAction } from "./eventService.js";

export async function reportRemediation(tenantId, { cluster_uuid, event_id, status, error_message }) {
  const cluster = await findClusterByUuid(tenantId, cluster_uuid);
  if (!cluster) {
    const err = new Error("Unknown cluster_uuid for this tenant");
    err.status = 404;
    throw err;
  }

  // event_id is the anomaly_events.id the ingest response returned;
  // service_name/namespace for display come from that parent row.
  const parent = event_id ? await lookupEventTarget(event_id) : null;

  return insertRemediationAction({
    tenantId,
    eventId: event_id || null,
    clusterId: cluster.id,
    clusterUuid: cluster.cluster_uuid,
    serviceName: parent?.service_name || "unknown",
    namespace: parent?.namespace || "unknown",
    status,
    errorMessage: error_message,
  });
}

async function lookupEventTarget(eventId) {
  const result = await pool.query(
    `SELECT service_name, namespace FROM anomaly_events WHERE id = $1`,
    [eventId]
  );
  return result.rows[0] || null;
}
