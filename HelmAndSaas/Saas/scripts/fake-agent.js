/**
 * Simulates the real Python agent's request sequence (see
 * HelmAndSaas/Agent/agent/main.py + inference_client.py) against this
 * Node backend, without needing a Kubernetes cluster, Prometheus, or
 * Python at all. Exercises the exact same wire contract:
 *   register -> loop { ingest -> (if anomaly) remediation/report }
 *
 * If FAKE_AGENT_API_KEY is not set, auto-provisions a throwaway tenant +
 * API key against SAAS_ENDPOINT so this is runnable standalone.
 *
 * Usage:
 *   node scripts/fake-agent.js            # runs 5 ingest cycles then exits
 *   node scripts/fake-agent.js --loop      # runs forever, ~15s interval, like the real agent
 */
import crypto from "node:crypto";

const SAAS_ENDPOINT = process.env.SAAS_ENDPOINT || "http://localhost:8000";
const CHECK_INTERVAL_SECONDS = parseInt(process.env.CHECK_INTERVAL_SECONDS || "15", 10);
const LOOP_FOREVER = process.argv.includes("--loop");
const CYCLES = LOOP_FOREVER ? Infinity : 5;

const SERVICES = [
  { service_name: "payment", namespace: "sock-shop" },
  { service_name: "orders", namespace: "sock-shop" },
  { service_name: "carts", namespace: "sock-shop" },
];

async function main() {
  const apiKey = process.env.FAKE_AGENT_API_KEY || (await bootstrapTenantAndApiKey());
  const clusterId = crypto.randomUUID();

  console.log(`[fake-agent] registering cluster_id=${clusterId} against ${SAAS_ENDPOINT}`);
  const clusterUuid = await register(apiKey, clusterId);
  console.log(`[fake-agent] registered, cluster_uuid=${clusterUuid}`);

  for (let cycle = 0; cycle < CYCLES; cycle++) {
    await runCycle(apiKey, clusterUuid, cycle);
    if (cycle < CYCLES - 1) await sleep(CHECK_INTERVAL_SECONDS * 1000);
  }

  console.log("[fake-agent] done.");
}

async function runCycle(apiKey, clusterUuid, cycle) {
  const services = SERVICES.map((svc) => ({
    ...svc,
    metrics: syntheticMetricsDict(cycle),
    feature_vector: syntheticFeatureVector(cycle),
  }));

  const ingestResp = await postJson(`${SAAS_ENDPOINT}/v1/metrics/ingest`, apiKey, {
    timestamp: new Date().toISOString(),
    cluster_uuid: clusterUuid,
    services,
  });

  console.log(`[fake-agent] cycle ${cycle} ingest ->`, JSON.stringify(ingestResp.results));

  for (const result of ingestResp.results || []) {
    if (result.is_anomaly && result.event_id) {
      await postJson(`${SAAS_ENDPOINT}/v1/remediation/report`, apiKey, {
        cluster_uuid: clusterUuid,
        event_id: result.event_id,
        status: "success",
      });
      console.log(`[fake-agent] reported remediation for ${result.service_name} (${result.anomaly_type})`);
    }
  }
}

/** Every 3rd cycle, one service gets a "memory-leak-shaped" vector (all -1s,
 * per verify_parity.py's fixture that the real model classifies as
 * MEMORY_LEAK) so the loop periodically exercises the anomaly path;
 * otherwise sends a plausible "normal load" vector. */
function syntheticFeatureVector(cycle) {
  if (cycle % 3 === 0) {
    return Array(35).fill(-1.0);
  }
  return [
    rand(0, 30), rand(0, 20), rand(0, 40), rand(0, 1), rand(0, 5), // cpu
    rand(50, 300), rand(10, 100), rand(0, 5), rand(0, 2), rand(100, 400), // memory
    ...Array.from({ length: 25 }, () => rand(0, 50)),
  ];
}

function syntheticMetricsDict(cycle) {
  const anomalous = cycle % 3 === 0;
  return {
    cpu_usage_percent: anomalous ? 5 : rand(5, 40),
    memory_usage_mb: anomalous ? 9000 : rand(100, 400),
    network_latency_ms: rand(1, 50),
    request_rate: rand(1, 20),
    error_rate: rand(0, 0.05),
  };
}

function rand(min, max) {
  return Math.round((min + Math.random() * (max - min)) * 100) / 100;
}

async function register(apiKey, clusterId) {
  const resp = await postJson(`${SAAS_ENDPOINT}/v1/agent/register`, apiKey, { cluster_id: clusterId });
  return resp.cluster_uuid;
}

async function bootstrapTenantAndApiKey() {
  const email = `fake-agent-${crypto.randomUUID().slice(0, 8)}@example.com`;
  const password = crypto.randomBytes(12).toString("hex");

  await fetchJson(`${SAAS_ENDPOINT}/auth/register`, {
    method: "POST",
    body: { organization_name: "Fake Agent Tenant", email, password },
  });
  const login = await fetchJson(`${SAAS_ENDPOINT}/auth/login`, {
    method: "POST",
    body: { email, password },
  });

  const created = await fetchJson(`${SAAS_ENDPOINT}/api-keys`, {
    method: "POST",
    headers: { Authorization: `Bearer ${login.access_token}` },
    body: { name: "fake-agent" },
  });

  console.log(`[fake-agent] auto-provisioned tenant ${email} + API key`);
  return created.api_key;
}

async function postJson(url, apiKey, body) {
  return fetchJson(url, { method: "POST", headers: { "X-API-Key": apiKey }, body });
}

async function fetchJson(url, { method = "GET", headers = {}, body } = {}) {
  const resp = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json", ...headers },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  const json = text ? JSON.parse(text) : {};
  if (!resp.ok) {
    throw new Error(`${method} ${url} -> ${resp.status}: ${text}`);
  }
  return json;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

main().catch((err) => {
  console.error("[fake-agent] failed:", err);
  process.exit(1);
});
