import { Component, effect, signal } from '@angular/core';
import { ClusterService } from '../../core/cluster.service';
import { AnomalyType, ServiceSummary } from '../../core/models';
import { AnomalyBadge } from '../../shared/anomaly-badge/anomaly-badge';

interface ServiceHealth {
  service_name: string;
  namespace: string;
  status: AnomalyType;
}

@Component({
  selector: 'app-dashboard-overview',
  imports: [AnomalyBadge],
  templateUrl: './dashboard-overview.html',
})
export class DashboardOverview {
  readonly serviceHealth = signal<ServiceHealth[]>([]);
  readonly loading = signal(false);

  constructor(private readonly clusters: ClusterService) {
    effect(() => {
      const clusterId = this.clusters.selectedClusterId();
      if (clusterId) void this.load(clusterId);
    });
  }

  private async load(clusterId: string): Promise<void> {
    this.loading.set(true);
    try {
      const [services, anomalies] = await Promise.all([
        this.clusters.listServices(clusterId),
        this.clusters.listAnomalies(clusterId, 200),
      ]);

      const latestByService = new Map<string, AnomalyType>();
      // anomalies are ordered newest-first by the backend; first hit per
      // service_name wins as the "current" status.
      for (const anomaly of anomalies) {
        if (!latestByService.has(anomaly.service_name)) {
          latestByService.set(anomaly.service_name, anomaly.anomaly_type);
        }
      }

      this.serviceHealth.set(
        services.map((svc: ServiceSummary) => ({
          service_name: svc.service_name,
          namespace: svc.namespace,
          status: latestByService.get(svc.service_name) ?? 'NORMAL',
        })),
      );
    } finally {
      this.loading.set(false);
    }
  }
}
