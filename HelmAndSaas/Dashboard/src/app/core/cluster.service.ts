import { Injectable, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-config';
import { AnomalyEvent, Cluster, Incident, MetricPoint, RemediationAction, ServiceOverview, ServiceSummary } from './models';

@Injectable({ providedIn: 'root' })
export class ClusterService {
  private readonly clustersSignal = signal<Cluster[]>([]);
  private readonly selectedClusterIdSignal = signal<string | null>(null);

  /** when the cluster list was last fetched (ms); heartbeat_age_seconds is relative to this moment */
  readonly loadedAt = signal(Date.now());
  readonly clusters = this.clustersSignal.asReadonly();
  readonly selectedClusterId = this.selectedClusterIdSignal.asReadonly();
  readonly selectedCluster = computed(
    () => this.clustersSignal().find((c) => c.id === this.selectedClusterIdSignal()) ?? null,
  );

  constructor(private readonly http: HttpClient) {}

  async loadClusters(): Promise<Cluster[]> {
    const res = await firstValueFrom(this.http.get<{ clusters: Cluster[] }>(`${API_BASE_URL}/v1/clusters`));
    this.clustersSignal.set(res.clusters);
    this.loadedAt.set(Date.now());
    if (!this.selectedClusterIdSignal() && res.clusters.length > 0) {
      this.selectedClusterIdSignal.set(res.clusters[0].id);
    }
    return res.clusters;
  }

  /** seconds since the agent of this cluster last sent data (keeps counting between refreshes); null = never */
  dataAge(cluster: Cluster, nowMs = Date.now()): number | null {
    return cluster.heartbeat_age_seconds === null || cluster.heartbeat_age_seconds === undefined
      ? null
      : cluster.heartbeat_age_seconds + Math.max(0, nowMs - this.loadedAt()) / 1000;
  }

  /** What the UI shows for a cluster: its name; the short id only when it has no name or two clusters share a name. */
  label(cluster: Cluster): string {
    const short = cluster.cluster_uuid.slice(0, 8);
    if (!cluster.name) return `${short}…`;
    const clash = this.clustersSignal().some((c) => c.id !== cluster.id && c.name === cluster.name);
    return clash ? `${cluster.name} (${short}…)` : cluster.name;
  }

  /** true when another cluster of the account already has this name (case-insensitive) */
  nameTaken(name: string, exceptClusterId?: string): boolean {
    const n = name.trim().toLowerCase();
    return !!n && this.clustersSignal().some((c) => c.id !== exceptClusterId && (c.name ?? '').toLowerCase() === n);
  }

  /** throws an Error with the server's message when the name is already used (HTTP 409) */
  async renameCluster(clusterId: string, name: string): Promise<void> {
    try {
      await firstValueFrom(this.http.patch(`${API_BASE_URL}/v1/clusters/${clusterId}`, { name }));
    } catch (e) {
      const err = e as { status?: number; error?: { error?: string } };
      if (err.status === 409) throw new Error(err.error?.error ?? 'That cluster name is already used.');
      throw e;
    }
    this.clustersSignal.update((list) => list.map((c) => (c.id === clusterId ? { ...c, name } : c)));
  }

  selectCluster(clusterId: string): void {
    this.selectedClusterIdSignal.set(clusterId);
  }

  async overview(clusterId: string): Promise<ServiceOverview[]> {
    const res = await firstValueFrom(
      this.http.get<{ services: ServiceOverview[] }>(`${API_BASE_URL}/v1/clusters/${clusterId}/overview`),
    );
    return res.services;
  }

  async listIncidents(
    clusterId: string,
    opts: { limit?: number; offset?: number; service?: string | null; type?: string | null } = {},
  ): Promise<{ incidents: Incident[]; total: number }> {
    const q = new URLSearchParams({ limit: String(opts.limit ?? 50), offset: String(opts.offset ?? 0) });
    if (opts.service) q.set('service', opts.service);
    if (opts.type) q.set('type', opts.type);
    return firstValueFrom(
      this.http.get<{ incidents: Incident[]; total: number }>(`${API_BASE_URL}/v1/clusters/${clusterId}/incidents?${q}`),
    );
  }

  async listServices(clusterId: string): Promise<ServiceSummary[]> {
    const res = await firstValueFrom(
      this.http.get<{ services: ServiceSummary[] }>(`${API_BASE_URL}/v1/clusters/${clusterId}/services`),
    );
    return res.services;
  }

  async listAnomalies(clusterId: string, limit = 50): Promise<AnomalyEvent[]> {
    const res = await firstValueFrom(
      this.http.get<{ anomalies: AnomalyEvent[] }>(
        `${API_BASE_URL}/v1/clusters/${clusterId}/anomalies?limit=${limit}`,
      ),
    );
    return res.anomalies;
  }

  async listRemediations(
    clusterId: string,
    limit = 50,
    offset = 0,
  ): Promise<{ remediations: RemediationAction[]; total: number }> {
    return firstValueFrom(
      this.http.get<{ remediations: RemediationAction[]; total: number }>(
        `${API_BASE_URL}/v1/clusters/${clusterId}/remediations?limit=${limit}&offset=${offset}`,
      ),
    );
  }

  async queryMetrics(clusterId: string, serviceName?: string, startIso?: string): Promise<MetricPoint[]> {
    const q = new URLSearchParams();
    if (serviceName) q.set('service_name', serviceName);
    if (startIso) q.set('start', startIso);
    const res = await firstValueFrom(
      this.http.get<{ metrics: MetricPoint[] }>(`${API_BASE_URL}/v1/clusters/${clusterId}/metrics?${q}`),
    );
    return res.metrics;
  }
}
