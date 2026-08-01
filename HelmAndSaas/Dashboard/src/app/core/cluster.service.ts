import { Injectable, computed, signal } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { API_BASE_URL } from './api-config';
import { AnomalyEvent, Cluster, MetricPoint, RemediationAction, ServiceSummary } from './models';

@Injectable({ providedIn: 'root' })
export class ClusterService {
  private readonly clustersSignal = signal<Cluster[]>([]);
  private readonly selectedClusterIdSignal = signal<string | null>(null);

  readonly clusters = this.clustersSignal.asReadonly();
  readonly selectedClusterId = this.selectedClusterIdSignal.asReadonly();
  readonly selectedCluster = computed(
    () => this.clustersSignal().find((c) => c.id === this.selectedClusterIdSignal()) ?? null,
  );

  constructor(private readonly http: HttpClient) {}

  async loadClusters(): Promise<Cluster[]> {
    const res = await firstValueFrom(this.http.get<{ clusters: Cluster[] }>(`${API_BASE_URL}/v1/clusters`));
    this.clustersSignal.set(res.clusters);
    if (!this.selectedClusterIdSignal() && res.clusters.length > 0) {
      this.selectedClusterIdSignal.set(res.clusters[0].id);
    }
    return res.clusters;
  }

  selectCluster(clusterId: string): void {
    this.selectedClusterIdSignal.set(clusterId);
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

  async queryMetrics(clusterId: string, serviceName?: string): Promise<MetricPoint[]> {
    const params = serviceName ? `?service_name=${encodeURIComponent(serviceName)}` : '';
    const res = await firstValueFrom(
      this.http.get<{ metrics: MetricPoint[] }>(`${API_BASE_URL}/v1/clusters/${clusterId}/metrics${params}`),
    );
    return res.metrics;
  }
}
